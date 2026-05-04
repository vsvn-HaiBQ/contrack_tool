const fs = require("node:fs");
const path = require("node:path");

const OFFICE_MIME_TYPES = {
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

function defaultOpenXmlBaseUrl() {
  return (process.env.CONTRACK_OPENXML_BASE_URL || process.env.OPEN_XML_HOST || "http://127.0.0.1:5000").replace(/\/+$/, "");
}

function assertFormDataSupport() {
  if (typeof fetch !== "function" || typeof FormData !== "function" || typeof Blob !== "function") {
    throw new Error("Node 18+ is required for OpenXML multipart requests");
  }
}

function normalizeStringArray(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item ?? "").trim()).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  return [];
}

function ensureOfficeFile(filePath) {
  const rawPath = String(filePath || "").trim();
  if (!rawPath) {
    throw new Error("filePath is required");
  }

  const resolved = path.resolve(rawPath);
  if (!fs.existsSync(resolved)) {
    throw new Error(`File not found: ${resolved}`);
  }

  const stat = fs.statSync(resolved);
  if (!stat.isFile()) {
    throw new Error(`Path is not a file: ${resolved}`);
  }

  const extension = path.extname(resolved).toLowerCase();
  const mimeType = OFFICE_MIME_TYPES[extension];
  if (!mimeType) {
    throw new Error("Only .docx, .pptx, and .xlsx files are supported");
  }

  return {
    path: resolved,
    extension,
    fileName: path.basename(resolved),
    mimeType,
    size: stat.size,
  };
}

async function officeForm(filePath, fields = {}) {
  assertFormDataSupport();
  const file = ensureOfficeFile(filePath);
  const form = new FormData();
  const buffer = await fs.promises.readFile(file.path);
  form.append("file", new Blob([buffer], { type: file.mimeType }), file.fileName);

  for (const [key, value] of Object.entries(fields)) {
    const values = Array.isArray(value) ? value : [value];
    for (const item of values) {
      if (item === undefined || item === null) continue;
      form.append(key, String(item));
    }
  }

  return { form, file };
}

async function readOpenXmlError(response) {
  const text = await response.text().catch(() => "");
  return text.trim() || `${response.status} ${response.statusText}`.trim();
}

async function postOpenXml(route, form, responseType, openXmlBaseUrl) {
  const baseUrl = (openXmlBaseUrl || defaultOpenXmlBaseUrl()).replace(/\/+$/, "");
  const response = await fetch(`${baseUrl}/${route.replace(/^\/+/, "")}`, {
    method: "POST",
    body: form,
  });

  if (!response.ok) {
    throw new Error(`OpenXML ${route} failed: ${await readOpenXmlError(response)}`);
  }

  if (responseType === "buffer") {
    return Buffer.from(await response.arrayBuffer());
  }
  return response.json();
}

async function importOfficeFile({ filePath, sheets, openXmlBaseUrl } = {}) {
  const { form } = await officeForm(filePath, { sheets: normalizeStringArray(sheets) });
  const data = await postOpenXml("import", form, "json", openXmlBaseUrl);
  if (!Array.isArray(data)) {
    throw new Error("OpenXML import returned an invalid response");
  }
  return data.map((item) => String(item ?? ""));
}

async function judgeOfficeSheets({ filePath, openXmlBaseUrl } = {}) {
  const file = ensureOfficeFile(filePath);
  if (file.extension !== ".xlsx") {
    return [];
  }
  const { form } = await officeForm(file.path);
  const data = await postOpenXml("judge", form, "json", openXmlBaseUrl);
  if (!Array.isArray(data)) {
    throw new Error("OpenXML judge returned an invalid response");
  }
  return data.map((item) => String(item ?? ""));
}

function safeTimestamp() {
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\..+$/, "").replace("T", "-");
}

function defaultOutputPath(inputPath, outputDirectory, outputBaseName) {
  const resolvedInput = path.resolve(inputPath);
  const directory = outputDirectory ? path.resolve(outputDirectory) : path.dirname(resolvedInput);
  const extension = path.extname(resolvedInput);
  const baseName = String(outputBaseName || "").trim() || `${path.basename(resolvedInput, extension)}.translated`;
  let candidate = path.join(directory, `${baseName}${extension}`);
  if (!fs.existsSync(candidate)) {
    return candidate;
  }
  candidate = path.join(directory, `${baseName}.${safeTimestamp()}${extension}`);
  return candidate;
}

async function exportOfficeFile({ filePath, data, sheets, outputPath, outputDirectory, outputBaseName, openXmlBaseUrl } = {}) {
  if (!Array.isArray(data)) {
    throw new Error("data must be an array of translated strings");
  }
  const file = ensureOfficeFile(filePath);
  const { form } = await officeForm(file.path, {
    data: data.map((item) => String(item ?? "")),
    sheets: normalizeStringArray(sheets),
  });
  const buffer = await postOpenXml("export", form, "buffer", openXmlBaseUrl);
  const targetPath = outputPath ? path.resolve(outputPath) : defaultOutputPath(file.path, outputDirectory, outputBaseName);
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  await fs.promises.writeFile(targetPath, buffer);
  return targetPath;
}

async function checkOpenXml({ openXmlBaseUrl, timeoutMs = 3000 } = {}) {
  const baseUrl = (openXmlBaseUrl || defaultOpenXmlBaseUrl()).replace(/\/+$/, "");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${baseUrl}/health`, { signal: controller.signal });
    if (!response.ok) {
      return { ok: false, base_url: baseUrl, message: `${response.status} ${response.statusText}`.trim() };
    }
    return { ok: true, base_url: baseUrl, message: "OpenXML API is reachable" };
  } catch (error) {
    const message = error && error.name === "AbortError" ? "OpenXML API health check timed out" : error.message;
    return { ok: false, base_url: baseUrl, message };
  } finally {
    clearTimeout(timeout);
  }
}

module.exports = {
  checkOpenXml,
  defaultOpenXmlBaseUrl,
  ensureOfficeFile,
  exportOfficeFile,
  importOfficeFile,
  judgeOfficeSheets,
  normalizeStringArray,
};
