const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { importFileHandler, exportFileHandler, discoverFileHandler, checkFileHandler } = require("../lib/filehandler-client.cjs");
const { extractDocumentText, judgeDocumentSheets, judgeDocumentSlides, translateDocument } = require("../lib/codex-translation.cjs");

const formats = { txt: "plaintext", md: "markdown", docx: "word", xlsx: "excel", pptx: "powerpoint" };
const snapshot = (extension = "txt") => ({ fileName: `source.${extension}`, mimeType: "application/octet-stream", bytes: Buffer.from([0, 255, 80, 75, 13, 10]) });
const envelope = (format = "plaintext", extra = {}) => ({ metadata: { format, status: "success", unitCount: 2, skipped: [], skipCount: { warning: 0, info: 0 } }, errors: [], ...extra });
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });

function mockFetch(t, handler) {
  t.mock.restoreAll();
  t.mock.method(globalThis, "fetch", handler);
}

function multipart(value, bytes, id = "file", boundary = "test_boundary", tail = "--\r\n") {
  return new Response(Buffer.concat([
    Buffer.from(`--${boundary}\r\nContent-Type: application/json; charset=utf-8\r\nContent-ID: <metadata>\r\n\r\n${JSON.stringify(value)}\r\n`),
    Buffer.from(`--${boundary}\r\nContent-Type: ${id === "units" ? "application/json" : "application/octet-stream"}\r\nContent-ID: <${id}>\r\nContent-Disposition: attachment; filename="output"\r\n\r\n`),
    bytes,
    Buffer.from(`\r\n--${boundary}${tail}`),
  ]), { headers: { "content-type": `multipart/mixed; boundary="${boundary}"` } });
}

for (const [extension, format] of Object.entries(formats)) {
  test(`${extension}: maps import/export, preserves text order and binary output`, async (t) => {
    const source = snapshot(extension.toUpperCase());
    const texts = ["  日本語\r\n", "<ox:r0>Hello</ox:r0><ox:k0/>", ""];
    const bytes = Buffer.concat([source.bytes, Buffer.from("\r\n--test_boundaryX\r\n--test_boundary--X\r\n")]);
    const calls = [];
    mockFetch(t, async (url, request) => {
      calls.push(url);
      assert.equal(request.method, "POST");
      assert.deepEqual(Buffer.from(await request.body.get("file").arrayBuffer()), source.bytes);
      if (url.endsWith("/import")) {
        assert.deepEqual([...request.body.keys()], ["file"]);
        return json(envelope(format, { texts }));
      }
      assert.equal(request.body.get("translatedTexts"), null);
      assert.deepEqual(JSON.parse(request.body.get("texts")), texts);
      return multipart(envelope(format), bytes);
    });
    const options = { fileHandlerBaseUrl: "http://processor.test/base/" };
    const imported = await importFileHandler(source, options);
    assert.deepEqual(imported.texts, texts);
    const exported = await exportFileHandler(source, imported.texts, options);
    assert.deepEqual(exported.bytes, bytes);
    assert.equal(exported.metadata.format, format);
    assert.deepEqual(calls, [`http://processor.test/base/api/${format}/import`, `http://processor.test/base/api/${format}/export`]);
  });
}

test("debug import reads units attachment and explicit empty selection survives import/export", async (t) => {
  const units = [{ index: 0, kind: "sheetName", location: { sheetId: "42" } }];
  for (const [extension, key, ids] of [["xlsx", "sheetIds", []], ["pptx", "slideIds", ["900"]]]) {
    mockFetch(t, async (url, request) => {
      assert.equal(request.body.get(key), JSON.stringify(ids));
      if (url.endsWith("/import")) {
        assert.equal(request.body.get("debug"), "true");
        return multipart(envelope(formats[extension], { texts: ["Sales"] }), Buffer.from(JSON.stringify({ units })), "units");
      }
      assert.equal(request.body.get("debug"), null);
      return multipart(envelope(formats[extension]), Buffer.alloc(0));
    });
    const options = { [key]: ids, debug: true };
    const imported = await importFileHandler(snapshot(extension), options);
    assert.deepEqual(imported.units, units);
    assert.equal(imported.attachment, undefined);
    assert.deepEqual((await exportFileHandler(snapshot(extension), imported.texts, options)).bytes, Buffer.alloc(0));
  }
});

test("discovery returns native sheet/slide IDs and visibility", async (t) => {
  const sheets = [{ sheetId: "42", index: 1, name: "Internal", state: "veryHidden", kind: "worksheet", canImport: true }];
  const slides = [{ slideId: "900", index: 1, title: null, hidden: true }];
  mockFetch(t, async (url, request) => {
    assert.deepEqual([...request.body.keys()], ["file"]);
    if (url.endsWith("/api/excel/sheets")) return json(envelope("excel", { sheets }));
    assert.ok(url.endsWith("/api/powerpoint/slides"));
    return json(envelope("powerpoint", { slides }));
  });
  assert.deepEqual((await discoverFileHandler(snapshot("xlsx"))).sheets, sheets);
  assert.deepEqual((await discoverFileHandler(snapshot("pptx"))).slides, slides);
});

test("reports fatal envelope code/index/line/marker and retains partial metadata", async (t) => {
  const error = { code: "count_mismatch", message: "Wrong count", index: 0, line: { start: 2, end: 4 }, marker: "ox:r0" };
  mockFetch(t, async () => json(envelope("plaintext", { errors: [error] }), 422));
  await assert.rejects(importFileHandler(snapshot()), /count_mismatch: Wrong count.*index=0, line=2-4, marker=ox:r0/);
  mockFetch(t, async () => new Response("proxy unavailable", { status: 502 }));
  await assert.rejects(importFileHandler(snapshot()), /HTTP 502.*proxy unavailable/);
  const partial = envelope();
  partial.metadata.status = "partial";
  partial.metadata.skipped = [{ code: "empty_translation", severity: "warning", count: 1, message: "Source retained" }];
  mockFetch(t, async () => multipart(partial, Buffer.from("source")));
  const result = await exportFileHandler(snapshot(), [""]);
  assert.deepEqual(result.metadata, partial.metadata);
  assert.equal(result.bytes.toString(), "source");
});

test("rejects old, malformed, failed, truncated, or incorrectly identified responses", async (t) => {
  for (const payload of [["old contract"], envelope("plaintext", { texts: [null] }), envelope("plaintext", { texts: [1] })]) {
    mockFetch(t, async () => json(payload));
    await assert.rejects(importFileHandler(snapshot()), /invalid/i);
  }
  for (const response of [
    new Response("raw legacy bytes"),
    multipart(envelope(), Buffer.from("payload"), "units"),
    multipart(envelope(), Buffer.from("payload"), "file", "test_boundary", ""),
    multipart(envelope("plaintext", { errors: [{ code: "invalid_translation", message: "Invalid" }] }), Buffer.from("payload")),
  ]) {
    mockFetch(t, async () => response);
    await assert.rejects(exportFileHandler(snapshot(), ["translation"]));
  }
});

test("validates selection IDs without silently selecting all", async () => {
  for (const sheetIds of ["42", [42], [null], [" "]]) {
    await assert.rejects(importFileHandler(snapshot("xlsx"), { sheetIds }), /array of non-empty source ID strings/);
  }
  await assert.rejects(importFileHandler(snapshot("txt"), { sheetIds: [] }), /requires a excel file/);
});

test("abort and timeout cover response body reads", async (t) => {
  mockFetch(t, async (_url, { signal }) => ({
    ok: true,
    json: () => new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    }),
  }));
  const controller = new AbortController();
  const pending = importFileHandler(snapshot(), { signal: controller.signal });
  setImmediate(() => controller.abort());
  await assert.rejects(pending, { name: "CanceledError" });
  await assert.rejects(importFileHandler(snapshot(), { timeoutMs: 10 }), /timed out/);
  await assert.rejects(importFileHandler(snapshot(), { signal: controller.signal }), { name: "CanceledError" });
});

test("local extraction and discovery forward URLs, aliases, metadata and debug mapping", async (t) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "ct-filehandler-test-"));
  const files = ["xlsx", "pptx"].map((ext) => path.join(directory, `source.${ext}`));
  t.after(async () => {
    for (const file of files) await fs.unlink(file);
    await fs.rmdir(directory);
  });
  for (const file of files) await fs.writeFile(file, "source");
  const units = [{ index: 0, kind: "sheetName", location: { sheetId: "42" } }];
  mockFetch(t, async (url, request) => {
    assert.ok(url.startsWith("http://selected-processor.test/"));
    if (url.endsWith("/sheets")) return json(envelope("excel", { sheets: [{ sheetId: "42" }] }));
    if (url.endsWith("/slides")) return json(envelope("powerpoint", { slides: [{ slideId: "900" }] }));
    assert.equal(request.body.get("sheetIds"), "[]");
    assert.equal(request.body.get("debug"), "true");
    return multipart(envelope("excel", { texts: ["Sales"] }), Buffer.from(JSON.stringify({ units })), "units");
  });
  const input = { file_processor: "filehandler", filehandler_base_url: "http://selected-processor.test", file_path: files[0] };
  const extracted = await extractDocumentText({ ...input, sheet_ids: [], debug: true });
  assert.deepEqual(extracted.segments, ["Sales"]);
  assert.equal(extracted.metadata.format, "excel");
  assert.deepEqual(extracted.units, units);
  assert.deepEqual(await judgeDocumentSheets(input), [{ sheetId: "42" }]);
  assert.deepEqual(await judgeDocumentSlides({ ...input, file_path: files[1] }), [{ slideId: "900" }]);
  await assert.rejects(extractDocumentText({ ...input, sheets: ["Sales"] }), /selection uses sheetIds/);
  await assert.rejects(extractDocumentText({ ...input, sheet_ids: [42] }), /non-empty source ID/);
});

test("empty import stops before translation or output publication", async (t) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "ct-filehandler-test-"));
  const file = path.join(directory, "source.txt");
  t.after(async () => { await fs.unlink(file); await fs.rmdir(directory); });
  await fs.writeFile(file, "source");
  mockFetch(t, async (url) => url.endsWith("/health") ? json({ status: "ok" }) : json(envelope("plaintext", { texts: [] })));
  await assert.rejects(translateDocument({ file_processor: "filehandler", file_path: file }), /extracted no text/);
  assert.deepEqual(await fs.readdir(directory), ["source.txt"]);
});

test("health keeps its dedicated route", async (t) => {
  mockFetch(t, async (url) => {
    assert.equal(url, "http://processor.test/health");
    return json({ status: "ok" });
  });
  assert.equal((await checkFileHandler({ fileHandlerBaseUrl: "http://processor.test/" })).ok, true);
});

test("live FileHandler TXT/Markdown round trip", { skip: !process.env.CT_FILEHANDLER_TEST_URL }, async () => {
  const options = { fileHandlerBaseUrl: process.env.CT_FILEHANDLER_TEST_URL };
  const health = await checkFileHandler(options);
  assert.equal(health.ok, true, health.message);
  for (const [extension, content] of [["txt", "Hello\r\n\r\nWorld\r\n"], ["md", "# Hello\n\nWorld\n"]]) {
    const source = { fileName: `source.${extension}`, mimeType: extension === "txt" ? "text/plain" : "text/markdown", bytes: Buffer.from(content) };
    const imported = await importFileHandler(source, { ...options, debug: true });
    assert.equal(imported.metadata.format, formats[extension]);
    assert.equal(imported.units.length, imported.texts.length);
    const result = await exportFileHandler(source, imported.texts, options);
    assert.deepEqual(result.bytes, source.bytes);
    const translated = await exportFileHandler(source, imported.texts.map((text) => text.replace("Hello", "Xin chào")), options);
    assert.ok(translated.bytes.toString("utf8").includes("Xin chào"));
    const partial = await exportFileHandler(source, imported.texts.map(() => ""), options);
    assert.equal(partial.metadata.status, "partial");
    assert.deepEqual(partial.bytes, source.bytes);
  }
});
