const fs = require("node:fs/promises");
const path = require("node:path");

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

function fileForm(snapshot) {
  const form = new FormData();
  form.append("file", new Blob([snapshot.bytes], { type: snapshot.mimeType }), snapshot.fileName);
  return form;
}

function errorDetails(text, response) {
  try {
    const errors = JSON.parse(text);
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

async function requestFileHandler(route, { fileHandlerBaseUrl, signal, timeoutMs = 120000, form, binary = false } = {}) {
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
    const result = binary ? Buffer.from(await response.arrayBuffer()) : await response.json();
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
  const segments = await requestFileHandler("import", { ...options, form: fileForm(snapshot) });
  if (!Array.isArray(segments) || segments.some((item) => typeof item !== "string")) {
    throw new Error("FileHandler import returned an invalid response: expected an array of strings");
  }
  return segments;
}

async function exportFileHandler(snapshot, translations, options = {}) {
  if (!Array.isArray(translations) || translations.some((item) => typeof item !== "string")) {
    throw new Error("FileHandler translations must be an array of strings");
  }
  const form = fileForm(snapshot);
  form.append("translatedTexts", JSON.stringify(translations));
  return requestFileHandler("export", { ...options, form, binary: true });
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

module.exports = { defaultFileHandlerBaseUrl, snapshotFile, importFileHandler, exportFileHandler, checkFileHandler };
