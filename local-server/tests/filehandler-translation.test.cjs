const assert = require("node:assert/strict");
const { test } = require("node:test");
const { EventEmitter } = require("node:events");
const { PassThrough, Writable } = require("node:stream");
const Module = require("node:module");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

// Exercise the production orchestration and file writes with deterministic model
// responses. The optional live tests use the real FileHandler HTTP API.
function translatorWithModel(translate, prompts = []) {
  const filename = require.resolve("../lib/codex-translation.cjs");
  const loaded = new Module(filename, module);
  loaded.filename = filename;
  loaded.paths = Module._nodeModulePaths(path.dirname(filename));
  const realRequire = loaded.require.bind(loaded);
  loaded.require = (id) => id === "node:child_process" ? {
    ...require(id),
    spawn(_command, args) {
      const child = new EventEmitter();
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      let prompt = "";
      child.stdin = new Writable({ write(chunk, _encoding, done) { prompt += chunk; done(); } });
      child.stdin.on("finish", () => setImmediate(() => {
        try {
          if (args[0] === "exec") {
            prompts.push(prompt);
            const text = /INPUT SEGMENTS \(\d+ total\):\n([\s\S]*?)\n\nOUTPUT REQUIREMENTS:/.exec(prompt)[1];
            const starts = [...text.matchAll(/(?:^|\n)\[\d+\] /g)];
            const segments = starts.map((match, i) => text.slice(match.index + match[0].length, starts[i + 1]?.index ?? text.length));
            fs.writeFileSync(args[args.indexOf("--output-last-message") + 1], JSON.stringify({ translations: translate(segments) }));
          } else child.stdout.write("test CLI ready");
          child.emit("close", 0);
        } catch (error) { child.emit("error", error); }
      }));
      return child;
    },
  } : realRequire(id);
  loaded._compile(fs.readFileSync(filename, "utf8"), filename);
  return loaded.exports;
}

function document(t, source = "# Hello\n\nWorld\n") {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ct-translation-flow-"));
  const filePath = path.join(directory, "source.md");
  const outputPath = path.join(directory, "translated.md");
  fs.writeFileSync(filePath, source);
  t.after(() => {
    for (const file of fs.readdirSync(directory)) fs.unlinkSync(path.join(directory, file));
    fs.rmdirSync(directory);
  });
  return { file_processor: "filehandler", filePath, outputPath, model: "test-model", codexCommand: "test-translator", direction: "ja_to_vi", batchSize: 100 };
}

function stubApi(t, input, { texts = ["Hello", "World"], unchanged = false, partial = false } = {}) {
  const source = fs.readFileSync(input.filePath);
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, request) => {
    calls.push({ url, form: request.body });
    if (url.endsWith("/health")) return Response.json({ status: "ok" });
    assert.deepEqual(Buffer.from(await request.body.get("file").arrayBuffer()), source);
    const metadata = { format: "markdown", status: partial ? "partial" : "success", unitCount: texts.length,
      skipped: partial ? [{ severity: "warning", stage: "translation", code: "invalid_marker_syntax", message: "Source retained", count: 1, unitIndex: 1 }] : [],
      skipCount: { warning: partial ? 1 : 0, info: 0 } };
    if (url.endsWith("/import")) return Response.json({ texts, metadata, errors: [] });
    const translated = JSON.parse(request.body.get("texts"));
    const output = unchanged ? source : Buffer.from(`# ${translated[0]}\n\n${partial ? texts[1] : translated[1]}\n`);
    return new Response(Buffer.concat([
      Buffer.from(`--boundary\r\nContent-ID: <metadata>\r\nContent-Type: application/json\r\n\r\n${JSON.stringify({ metadata, errors: [] })}\r\n--boundary\r\nContent-ID: <file>\r\nContent-Type: text/markdown\r\n\r\n`),
      output, Buffer.from("\r\n--boundary--\r\n"),
    ]), { headers: { "content-type": "multipart/mixed; boundary=boundary" } });
  });
  return calls;
}

test("Markdown sends English text despite Japanese source setting and saves actual translations", async (t) => {
  const input = document(t);
  const calls = stubApi(t, input);
  const prompts = [];
  const { translateDocument } = translatorWithModel(texts => texts.map(text => ({ Hello: "Xin chào", World: "Thế giới" })[text]), prompts);
  const result = await translateDocument(input);
  assert.equal(fs.readFileSync(input.outputPath, "utf8"), "# Xin chào\n\nThế giới\n");
  assert.equal(result.translatable_segments, 2);
  assert.equal(result.changed_segments, 2);
  assert.equal(prompts.length, 1);
  assert.match(prompts[0], /translate their entire text/);
  assert.equal(calls.filter(call => call.url.endsWith("/export")).length, 1);
  assert.equal(fs.readFileSync(input.filePath, "utf8"), "# Hello\n\nWorld\n");
});

test("unchanged model output fails without publishing a misleading translated file", async (t) => {
  const input = document(t);
  const calls = stubApi(t, input);
  const { translateDocument } = translatorWithModel(texts => texts);
  await assert.rejects(translateDocument(input), /all source text unchanged/);
  assert.equal(fs.existsSync(input.outputPath), false);
  assert.equal(calls.some(call => call.url.endsWith("/export")), false);
});

test("export retaining all source fails without publishing a file", async (t) => {
  const input = document(t);
  stubApi(t, input, { unchanged: true, partial: true });
  const logs = [];
  const { translateDocument } = translatorWithModel(texts => texts.map(() => "Bản dịch"));
  await assert.rejects(translateDocument(input, { log: (...args) => logs.push(args) }), /retained the entire source/);
  assert.equal(fs.existsSync(input.outputPath), false);
  assert.ok(logs.some(log => log[0] === "warn" && log[2].includes("invalid_marker_syntax")));
});

test("numeric-only documents fail instead of being copied as translated", async (t) => {
  const input = document(t);
  stubApi(t, input, { texts: ["123", "456"] });
  const prompts = [];
  const { translateDocument } = translatorWithModel(texts => texts, prompts);
  await assert.rejects(translateDocument(input), /No text to translate/);
  assert.equal(prompts.length, 0);
  assert.equal(fs.existsSync(input.outputPath), false);
});

test("live Markdown flow applies model translations and preserves code, URLs and formatting", { skip: !process.env.CT_FILEHANDLER_TEST_URL }, async (t) => {
  const source = "# Hello\n\nHello **World** and [Guide](https://example.com).\n\nこんにちは\n\n```js\nconst greeting = 'Hello';\n```\n";
  const input = { ...document(t, source), filehandler_base_url: process.env.CT_FILEHANDLER_TEST_URL, debug: true };
  const prompts = [];
  const { translateDocument } = translatorWithModel(texts => texts.map(text => text
    .replaceAll("Hello", "Xin chào").replaceAll("World", "Thế giới").replaceAll("Guide", "Hướng dẫn").replaceAll(" and ", " và ").replaceAll("こんにちは", "Xin chào")), prompts);
  const result = await translateDocument(input);
  const output = fs.readFileSync(input.outputPath, "utf8");
  assert.match(output, /# Xin chào/);
  assert.match(output, /\*\*Thế giới\*\*/);
  assert.match(output, /\[Hướng dẫn\]\(https:\/\/example.com\)/);
  assert.match(output, /const greeting = 'Hello';/);
  assert.doesNotMatch(output, /こんにちは/);
  assert.equal(result.metadata.status, "success");
  assert.ok(prompts.some(prompt => prompt.includes("<ox:r")));
  assert.equal(fs.readFileSync(input.filePath, "utf8"), source);
});

test("live Markdown invalid tokens cannot produce a successful unchanged output", { skip: !process.env.CT_FILEHANDLER_TEST_URL }, async (t) => {
  const input = { ...document(t, "Hello **World**\n"), filehandler_base_url: process.env.CT_FILEHANDLER_TEST_URL };
  const { translateDocument } = translatorWithModel(texts => texts.map(() => "Xin chào thế giới"));
  await assert.rejects(translateDocument(input), /retained the entire source/);
  assert.equal(fs.existsSync(input.outputPath), false);
});
