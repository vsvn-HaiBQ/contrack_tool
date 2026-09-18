const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const http = require("node:http");
const { EventEmitter } = require("node:events");
const { PassThrough } = require("node:stream");
const { test } = require("node:test");
const childProcess = require("node:child_process");
const client = require("../lib/filehandler-client.cjs");

// Replace only the CLI process boundary; exercise the production orchestration,
// batching, HTTP multipart transport, cancellation and output writer together.
const cli = { prompts: [], translate: (text) => text.replaceAll("日本語", "Tiếng Việt"), wrongCount: false };
const originalSpawn = childProcess.spawn;
childProcess.spawn = (command, args) => {
  assert.equal(command, "test-codex");
  const child = new EventEmitter();
  child.stdin = new PassThrough();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.kill = () => { child.killed = true; child.emit("close", 1); };
  let prompt = "";
  child.stdin.on("data", (data) => { prompt += data; });
  child.stdin.on("finish", () => setImmediate(() => {
    if (args[0] === "exec") {
      cli.prompts.push(prompt);
      const input = prompt.split(/INPUT SEGMENTS \(\d+ total\):\n/)[1].split("\n\nOUTPUT REQUIREMENTS:")[0];
      const parts = input.split(/^\[\d+\] /m).slice(1);
      const translations = cli.wrongCount ? [] : parts.map((text, index) => cli.translate(index < parts.length - 1 ? text.slice(0, -1) : text));
      fs.writeFileSync(args[args.indexOf("--output-last-message") + 1], JSON.stringify({ translations }));
    } else child.stdout.write("test codex ready");
    child.emit("close", 0);
  }));
  return child;
};
const translation = require("../lib/codex-translation.cjs");
childProcess.spawn = originalSpawn;

async function fixture(t, handler) {
  cli.prompts = [];
  cli.wrongCount = false;
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ct-translation-test-"));
  t.after(() => {
    assert.equal(path.dirname(directory), path.resolve(os.tmpdir()));
    assert.ok(path.basename(directory).startsWith("ct-translation-test-"));
    fs.rmSync(directory, { recursive: true, force: true });
  });
  const requests = [];
  const server = http.createServer(async (req, res) => {
    try {
      const buffers = [];
      for await (const chunk of req) buffers.push(chunk);
      const form = req.method === "POST" ? await new Request("http://localhost", {
        method: "POST", headers: req.headers, body: Buffer.concat(buffers),
      }).formData() : null;
      const request = { route: req.url, form, res };
      requests.push(request);
      if (req.url === "/health") return res.end(JSON.stringify({ status: "ok" }));
      await handler(request);
    } catch (error) {
      res.statusCode = 500;
      res.end(String(error));
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => { server.closeAllConnections(); server.close(resolve); }));
  const baseUrl = `http://127.0.0.1:${server.address().port}`;
  return { directory, requests, baseUrl, options: { filehandler_base_url: baseUrl, codexCommand: "test-codex", model: "test-model", direction: "ja_to_vi" } };
}

for (const extension of [".txt", ".md", ".docx", ".xlsx", ".pptx", ".DOCX"]) {
  test(`FileHandler translates ${extension} with one source snapshot and ordered multipart JSON`, async (t) => {
    const source = Buffer.from("source 日本語\r\n");
    const structured = "<ox:r0>日本語 \\\\ \\<literal</ox:r0><ox:k0/><ox:r1>日本語</ox:r1>";
    const segments = [extension === ".txt" ? "  日本語\r\n日本語\t " : structured, " 123\t", "日本語"];
    let filePath;
    const f = await fixture(t, async ({ route, form, res }) => {
      assert.deepEqual(Buffer.from(await form.get("file").arrayBuffer()), source);
      assert.equal(form.get("file").name, `source${extension}`);
      if (route === "/import") {
        fs.writeFileSync(filePath, "Changed while translating");
        res.end(JSON.stringify(segments));
      } else {
        assert.equal(route, "/export");
        assert.deepEqual([...form.keys()], ["file", "translatedTexts"]);
        assert.deepEqual(JSON.parse(form.get("translatedTexts")), segments.map(cli.translate));
        res.setHeader("Content-Disposition", `attachment; filename=source${extension}`);
        res.end("translated file bytes");
      }
    });
    filePath = path.join(f.directory, `source${extension}`);
    fs.writeFileSync(filePath, source);
    const result = await translation.translateDocument({ ...f.options, filePath, instructions: "Custom glossary instructions", batchSize: 1 });
    assert.equal(result.file_processor, "filehandler");
    assert.equal(result.total_segments, 3);
    assert.equal(result.translatable_segments, 2);
    assert.equal(fs.readFileSync(result.output_path, "utf8"), "translated file bytes");
    assert.equal(fs.readFileSync(filePath, "utf8"), "Changed while translating");
    assert.notEqual(result.output_path, filePath);
    assert.match(path.basename(result.output_path), /^Source_VN\./);
    assert.ok(cli.prompts.every((prompt) => prompt.includes("Custom glossary instructions")));
    assert.ok(cli.prompts.every((prompt) => prompt.includes(extension === ".txt" ? "any token-like text is literal" : "MANDATORY FILE FORMAT RULES")));
    assert.equal(f.requests.filter((req) => req.route === "/export").length, 1);
  });
}

test("selection defaults, invalid values and unsupported sheet selection", async () => {
  assert.equal(translation.defaultTranslationConfig().file_processor, "filehandler");
  assert.throws(() => translation.startDocumentTranslationJob({ file_processor: "unknown" }), /file_processor/);
  assert.throws(() => translation.startDocumentTranslationJob({ sheets: ["Sheet1"] }), /sheet selection/);
  await assert.rejects(translation.judgeDocumentSheets({ file_processor: "filehandler" }), /sheet selection/);
});

test("health uses only FileHandler when OpenXML is unavailable", async (t) => {
  const f = await fixture(t, () => assert.fail("Unexpected request"));
  const result = await translation.documentTranslationHealth({ ...f.options, openxml_base_url: "http://127.0.0.1:1" });
  assert.equal(result.ok, true);
  assert.equal(result.file_processor, "filehandler");
  assert.equal(result.processor.base_url, f.baseUrl);
});

test("API errors include code, segment index, source line and marker", async (t) => {
  const f = await fixture(t, ({ res }) => {
    res.statusCode = 422;
    res.end(JSON.stringify([{ code: "invalid_marker_syntax", message: "Invalid token", index: 0, line: { start: 1, end: 2 }, marker: "r0" }]));
  });
  const snapshot = { bytes: Buffer.from("source"), fileName: "source.md", mimeType: "text/markdown" };
  await assert.rejects(client.exportFileHandler(snapshot, ["text"], { fileHandlerBaseUrl: f.baseUrl }), /invalid_marker_syntax.*index=0.*line=1-2.*marker=r0/);
});

test("import rejects non-string arrays and leaves whitespace unchanged", async (t) => {
  let segments = [null];
  const f = await fixture(t, ({ res }) => res.end(JSON.stringify(segments)));
  const filePath = path.join(f.directory, "source.txt");
  fs.writeFileSync(filePath, "original");
  await assert.rejects(translation.extractDocumentText({ ...f.options, filePath }), /array of strings/);
  segments = ["  日本語\r\n\t "];
  assert.deepEqual((await translation.extractDocumentText({ ...f.options, filePath })).segments, segments);
});

for (const scenario of ["empty", "wrong-count", "export-error", "collision", "source-output"]) {
  test(`FileHandler handles ${scenario} without overwriting the source`, async (t) => {
    const f = await fixture(t, ({ route, res }) => {
      if (route === "/import") res.end(JSON.stringify(scenario === "empty" ? [] : ["日本語"]));
      else if (scenario === "export-error") { res.statusCode = 422; res.end('[{"code":"empty_translation","message":"Empty run"}]'); }
      else res.end("result");
    });
    const filePath = path.join(f.directory, "source.txt");
    fs.writeFileSync(filePath, "source");
    const outputPath = path.join(f.directory, "Source_VN.txt");
    if (scenario === "collision") fs.writeFileSync(outputPath, "existing");
    if (scenario === "wrong-count") cli.wrongCount = true;
    const promise = translation.translateDocument({ ...f.options, filePath, ...(scenario === "source-output" ? { outputPath: filePath } : {}) });
    if (scenario === "collision") {
      const result = await promise;
      assert.notEqual(result.output_path, outputPath);
      assert.equal(fs.readFileSync(outputPath, "utf8"), "existing");
    } else {
      await assert.rejects(promise, scenario === "empty" ? /no text segments/ : scenario === "wrong-count" ? /expected 1/ : scenario === "source-output" ? /overwrite the source/ : /empty_translation/);
      assert.equal(fs.existsSync(outputPath), false);
    }
    assert.equal(fs.readFileSync(filePath, "utf8"), "source");
  });
}

test("HTTP timeout and disconnected API produce clear errors", async (t) => {
  const f = await fixture(t, () => {});
  const snapshot = { bytes: Buffer.from("source"), fileName: "source.txt", mimeType: "text/plain" };
  await assert.rejects(client.importFileHandler(snapshot, { fileHandlerBaseUrl: f.baseUrl, timeoutMs: 50 }), /timed out/);
  const health = await client.checkFileHandler({ fileHandlerBaseUrl: "http://127.0.0.1:1" });
  assert.equal(health.ok, false);
  assert.match(health.message, /FileHandler/);
});

for (const stage of ["import", "export"]) {
  test(`cancel during FileHandler ${stage} aborts the request and creates no output`, async (t) => {
    let started;
    const reachedStage = new Promise((resolve) => { started = resolve; });
    const f = await fixture(t, ({ route, res }) => {
      if (route === `/${stage}`) started();
      else res.end(JSON.stringify(["日本語"]));
    });
    const filePath = path.join(f.directory, "source.txt");
    fs.writeFileSync(filePath, "source");
    const job = translation.startDocumentTranslationJob({ ...f.options, filePath });
    await reachedStage;
    translation.cancelDocumentTranslationJob(job.job_id);
    // Wait for the worker's finally block, rather than just the synchronous cancel response.
    await new Promise((resolve, reject) => {
      const deadline = Date.now() + 3000;
      const poll = () => {
        const current = translation.getDocumentTranslationJob(job.job_id);
        if (current.logs.some((entry) => entry.message === "Document translation stopped")) return resolve();
        if (Date.now() > deadline) return reject(new Error("Cancellation did not settle"));
        setTimeout(poll, 10);
      };
      poll();
    });
    assert.equal(translation.getDocumentTranslationJob(job.job_id).status, "canceled");
    assert.deepEqual(fs.readdirSync(f.directory), ["source.txt"]);
  });
}

test("OpenXML / Local keeps TXT and Markdown processing local", async (t) => {
  const f = await fixture(t, () => assert.fail("Legacy text must not call FileHandler"));
  for (const extension of [".txt", ".md"]) {
    const filePath = path.join(f.directory, `legacy${extension}`);
    fs.writeFileSync(filePath, extension === ".md" ? "# 日本語\n" : "日本語\r\n");
    const result = await translation.translateDocument({ ...f.options, filePath, file_processor: "openxml" });
    assert.equal(result.file_processor, "openxml");
    assert.match(fs.readFileSync(result.output_path, "utf8"), /Tiếng Việt/);
  }
  assert.equal(f.requests.length, 0);
});

test("OpenXML Office export retains repeated data multipart fields", async (t) => {
  const f = await fixture(t, ({ route, form, res }) => {
    if (route === "/import") res.end(JSON.stringify(["日本語", "123"]));
    else {
      assert.equal(route, "/export");
      assert.deepEqual(form.getAll("data"), ["Tiếng Việt", "123"]);
      assert.equal(form.has("translatedTexts"), false);
      res.end("legacy office bytes");
    }
  });
  const filePath = path.join(f.directory, "legacy.docx");
  fs.writeFileSync(filePath, "source");
  const result = await translation.translateDocument({ ...f.options, file_processor: "openxml", openxml_base_url: f.baseUrl, filePath });
  assert.equal(result.file_processor, "openxml");
  assert.equal(fs.readFileSync(result.output_path, "utf8"), "legacy office bytes");
});

test("formatting tokens alone do not trigger English translation", async (t) => {
  const segments = ["<ox:r0>123</ox:r0><ox:k0/>"];
  const f = await fixture(t, ({ route, form, res }) => {
    if (route === "/import") res.end(JSON.stringify(segments));
    else { assert.deepEqual(JSON.parse(form.get("translatedTexts")), segments); res.end("result"); }
  });
  const filePath = path.join(f.directory, "123.docx");
  fs.writeFileSync(filePath, "source");
  const result = await translation.translateDocument({ ...f.options, direction: "en_to_vi", filePath });
  assert.equal(result.translatable_segments, 0);
  assert.equal(cli.prompts.length, 0);
});
