const fs = require("node:fs/promises");
const path = require("node:path");
const { parseMultipart } = require("./filehandler-multipart.cjs");

const FORMATS = { ".txt": "plaintext", ".md": "markdown", ".docx": "word", ".xlsx": "excel", ".pptx": "powerpoint" };

const MIME_TYPES = {
  ".txt": "text/plain",
  ".md": "text/markdown",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
};

function defaultFileHandlerBaseUrl() {
  return (process.env.CONTRACK_FILEHANDLER_BASE_URL || "http://127.0.0.1:5001").replace(/\/+$/, "");
}

function canceledError() {
  return Object.assign(new Error("Stopped by user"), { name: "CanceledError" });
}

function assertActive(signal) {
  if (signal?.aborted) throw canceledError();
}

async function snapshotFile(filePath, signal) {
  assertActive(signal);
  const resolved = path.resolve(filePath);
  const extension = path.extname(resolved).toLowerCase();
  const mimeType = MIME_TYPES[extension];
  if (!mimeType) throw new Error("Only .txt, .md, .docx, .xlsx, and .pptx files are supported");
  const bytes = await fs.readFile(resolved, { signal });
  assertActive(signal);
  return { bytes, fileName: path.basename(resolved), mimeType };
}

function formatOf(snapshot) {
  const format = FORMATS[path.extname(snapshot.fileName).toLowerCase()];
  if (!format) throw new Error("Unsupported FileHandler file extension");
  return format;
}

function fileForm(snapshot, options = {}) {
  const form = new FormData();
  form.append("file", new Blob([snapshot.bytes], { type: snapshot.mimeType }), snapshot.fileName);
  for (const [key, format] of [["sheetIds", "excel"], ["slideIds", "powerpoint"]]) {
    const ids = options[key];
    if (ids == null) continue;
    if (formatOf(snapshot) !== format) throw new Error(`${key} requires a ${format} file`);
    if (!Array.isArray(ids) || ids.some((id) => typeof id !== "string" || !id.trim())) {
      throw new Error(`${key} must be an array of non-empty source ID strings`);
    }
    form.append(key, JSON.stringify(ids));
  }
  return form;
}

function errorDetails(text, response) {
  try {
    const payload = JSON.parse(text);
    const errors = Array.isArray(payload) ? payload : payload?.errors;
    if (Array.isArray(errors) && errors.length) {
      return errors.map((error) => {
        const location = [
          error.index != null ? `index=${error.index}` : "",
          error.line ? `line=${error.line.start}-${error.line.end}` : "",
          error.marker ? `marker=${error.marker}` : "",
        ].filter(Boolean).join(", ");
        return `${error.code || "error"}: ${error.message || "Request failed"}${location ? ` (${location})` : ""}`;
      }).join("; ");
    }
  } catch { /* A proxy may return a non-JSON error. */ }
  return text.trim() || `${response.status} ${response.statusText}`.trim();
}

async function requestFileHandler(route, { fileHandlerBaseUrl, signal, timeoutMs = 120000, form, attachment } = {}) {
  assertActive(signal);
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, timeoutMs);
  const baseUrl = (fileHandlerBaseUrl || defaultFileHandlerBaseUrl()).replace(/\/+$/, "");
  try {
    const response = await fetch(`${baseUrl}/${route}`, {
      method: form ? "POST" : "GET",
      body: form,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`FileHandler ${route} failed (HTTP ${response.status}): ${errorDetails(await response.text(), response)}`);
    }
    let result;
    if (attachment) {
      const parts = parseMultipart(Buffer.from(await response.arrayBuffer()), response.headers.get("content-type"));
      if (parts.length !== 2 || parts[0].id !== "<metadata>" || parts[1].id !== `<${attachment}>`
          || !/^application\/json(?:\s*;|$)/i.test(parts[0].contentType)) {
        throw new Error("Invalid FileHandler multipart response parts");
      }
      const envelope = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(parts[0].bytes));
      result = { ...envelope, attachment: parts[1].bytes };
    } else {
      result = await response.json();
    }
    if (form && (!result?.metadata || !Array.isArray(result.errors))) {
      throw new Error("Invalid FileHandler response envelope");
    }
    if (result?.errors?.length || result?.metadata?.status === "failed") {
      throw new Error(errorDetails(JSON.stringify(result), response));
    }
    assertActive(signal);
    return result;
  } catch (error) {
    if (signal?.aborted) throw canceledError();
    if (controller.signal.aborted) throw new Error(`FileHandler ${route} timed out after ${timeoutMs / 1000}s`);
    throw new Error(`FileHandler ${route} at ${baseUrl}: ${error.message}`);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

async function importFileHandler(snapshot, options = {}) {
  const form = fileForm(snapshot, options);
  if (options.debug) form.append("debug", "true");
  const result = await requestFileHandler(`api/${formatOf(snapshot)}/import`, {
    ...options, form, attachment: options.debug ? "units" : undefined,
  });
  if (!Array.isArray(result.texts) || result.texts.some((item) => typeof item !== "string")) {
    throw new Error("FileHandler import returned invalid texts: expected an array of strings");
  }
  if (options.debug) {
    const mapping = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(result.attachment));
    if (!Array.isArray(mapping.units)) throw new Error("FileHandler import returned invalid units");
    result.units = mapping.units;
    delete result.attachment;
  }
  return result;
}

async function exportFileHandler(snapshot, translations, options = {}) {
  if (!Array.isArray(translations) || translations.some((item) => typeof item !== "string")) {
    throw new Error("FileHandler translations must be an array of strings");
  }
  const form = fileForm(snapshot, options);
  form.append("texts", JSON.stringify(translations));
  const result = await requestFileHandler(`api/${formatOf(snapshot)}/export`, { ...options, form, attachment: "file" });
  return { bytes: result.attachment, metadata: result.metadata, errors: result.errors };
}

async function discoverFileHandler(snapshot, options = {}) {
  const format = formatOf(snapshot);
  const collection = format === "excel" ? "sheets" : format === "powerpoint" ? "slides" : null;
  if (!collection) throw new Error("FileHandler discovery requires an Excel or PowerPoint file");
  const result = await requestFileHandler(`api/${format}/${collection}`, { ...options, form: fileForm(snapshot) });
  if (!Array.isArray(result[collection])) throw new Error(`FileHandler returned invalid ${collection}`);
  return result;
}

async function checkFileHandler(options = {}) {
  const baseUrl = (options.fileHandlerBaseUrl || defaultFileHandlerBaseUrl()).replace(/\/+$/, "");
  try {
    const result = await requestFileHandler("health", { ...options, timeoutMs: 3000 });
    if (result?.status !== "ok") throw new Error("Invalid FileHandler health response");
    return { ok: true, base_url: baseUrl, message: "FileHandler API is reachable" };
  } catch (error) {
    if (error.name === "CanceledError") throw error;
    return { ok: false, base_url: baseUrl, message: error.message };
  }
}

module.exports = { defaultFileHandlerBaseUrl, snapshotFile, importFileHandler, exportFileHandler, discoverFileHandler, checkFileHandler };
