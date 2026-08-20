const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const {
  checkOpenXml,
  defaultOpenXmlBaseUrl,
  ensureOfficeFile,
  exportOfficeFile,
  importOfficeFile,
  judgeOfficeSheets,
  normalizeStringArray,
} = require("./openxml-client.cjs");

const jobs = new Map();
const maxLogsPerJob = 500;
const officeFileExtensions = new Set([".docx", ".pptx", ".xlsx"]);
const textFileExtensions = new Set([".txt", ".md"]);

const DEFAULT_INSTRUCTIONS = [
  "Use glossary translations exactly when a matching source term appears.",
  "Translate terms not present in the glossary naturally for the target language.",
  "Preserve whitespace, punctuation, placeholders, numbers, URLs, code-like tokens, and product names unless translation is clearly required.",
  "Use surrounding context only to choose the right wording; do not translate surrounding context lines.",
  "Return exactly one translated string for each input segment.",
].join("\n");

const PROMPT_TEMPLATE = `You are a professional document translator.

TRANSLATION DIRECTION:
{direction}

GLOSSARY:
{glossary}

DOCUMENT CONTEXT:
{documentSummary}

INSTRUCTIONS:
{instructions}

SURROUNDING CONTEXT FOR REFERENCE ONLY:
[BEFORE]
{contextBefore}
[AFTER]
{contextAfter}

INPUT SEGMENTS ({segmentCount} total):
{segments}

OUTPUT REQUIREMENTS:
- Return a JSON object with this shape: {"translations":[...]}.
- The translations array must contain exactly {segmentCount} strings.
- translations[0] translates segment [1], translations[1] translates segment [2], and so on.
- Do not merge, split, skip, repeat, or reorder segments.
- Do not include markdown, explanations, or any text outside the JSON object.
`;

function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

function defaultTranslationConfig() {
  const configuredCodexCommand = process.env.CONTRACK_CODEX_COMMAND || "codex";
  return {
    openxml_base_url: defaultOpenXmlBaseUrl(),
    codex_command: resolveCodexCommand(configuredCodexCommand),
    model: normalizeText(process.env.CODEX_DEFAULT_MODEL || process.env.CONTRACK_CODEX_MODEL),
    reasoning_effort: normalizeText(process.env.CODEX_DEFAULT_REASONING_EFFORT || process.env.CONTRACK_CODEX_REASONING_EFFORT),
    timeout_seconds: positiveInt(process.env.CONTRACK_CODEX_TIMEOUT_SECONDS || process.env.CODEX_TIMEOUT, 120, 5, 3600),
    context_window: positiveInt(process.env.CONTRACK_CODEX_CONTEXT_WINDOW || process.env.CODEX_CONTEXT_WINDOW, 20, 0, 200),
    batch_size: positiveInt(process.env.CONTRACK_CODEX_BATCH_SIZE || process.env.CODEX_MAX_BATCH_SIZE, 100, 1, 200),
    concurrency: positiveInt(process.env.CONTRACK_CODEX_CONCURRENCY, 2, 1, 4),
    fast_mode: parseBoolean(process.env.CONTRACK_CODEX_FAST_MODE, false),
  };
}

function codexHomePath() {
  return process.env.CODEX_HOME || path.join(os.homedir(), ".codex");
}

function normalizeModelOption(model) {
  return {
    slug: normalizeText(model?.slug),
    display_name: normalizeText(model?.display_name, normalizeText(model?.slug)),
    description: normalizeText(model?.description),
    default_reasoning_level: normalizeText(model?.default_reasoning_level),
    supported_reasoning_levels: Array.isArray(model?.supported_reasoning_levels)
      ? model.supported_reasoning_levels
        .filter((level) => level && normalizeText(level.effort))
        .map((level) => ({ effort: normalizeText(level.effort), description: normalizeText(level.description) }))
      : [],
    additional_speed_tiers: Array.isArray(model?.additional_speed_tiers) ? model.additional_speed_tiers.map((item) => String(item)) : [],
  };
}

async function listCodexModels() {
  const configuredCodexCommand = process.env.CONTRACK_CODEX_COMMAND || "codex";
  const command = resolveCodexCommand(configuredCodexCommand);
  const result = await runProcess(command, ["debug", "models"], { timeoutMs: 10000 });
  let catalog;
  try {
    catalog = JSON.parse(result.stdout);
  } catch (error) {
    throw new Error(`Codex CLI returned an invalid model catalog: ${error.message}`);
  }
  const models = Array.isArray(catalog?.models) ? catalog.models : [];
  return models
    .filter((model) => model && model.visibility !== "hide" && normalizeText(model.slug))
    .sort((left, right) => {
      const leftPriority = Number.isFinite(Number(left.priority)) ? Number(left.priority) : Number.MAX_SAFE_INTEGER;
      const rightPriority = Number.isFinite(Number(right.priority)) ? Number(right.priority) : Number.MAX_SAFE_INTEGER;
      return leftPriority - rightPriority || String(left.slug).localeCompare(String(right.slug));
    })
    .map(normalizeModelOption);
}

function resolveCodexCommand(command) {
  const rawCommand = normalizeText(command, "codex");
  if (process.platform !== "win32" || rawCommand.toLowerCase() !== "codex") {
    return rawCommand;
  }

  const candidates = [
    process.env.APPDATA ? path.join(process.env.APPDATA, "npm", "codex.cmd") : null,
    process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "Programs", "codex", "codex.cmd") : null,
  ].filter(Boolean);

  return candidates.find((candidate) => fs.existsSync(candidate)) || findCommandOnPath(["codex"]) || rawCommand;
}

function positiveInt(value, fallback, min, max) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  const rounded = Math.floor(parsed);
  return Math.min(Math.max(rounded, min), max);
}

function parseBoolean(value, fallback = false) {
  if (typeof value === "boolean") return value;
  if (value === undefined || value === null || value === "") return fallback;
  return ["1", "true", "yes", "on"].includes(String(value).trim().toLowerCase());
}

function createCanceledError() {
  const error = new Error("Stopped by user");
  error.name = "CanceledError";
  return error;
}

function isCanceledError(error) {
  return Boolean(error && (error.name === "CanceledError" || error.code === "ERR_CANCELED"));
}

function throwIfCanceled(callbacks = {}) {
  if (callbacks.isCanceled?.()) {
    throw createCanceledError();
  }
}

function isTerminalStatus(status) {
  return status === "succeeded" || status === "failed" || status === "canceled";
}

function terminateChild(child) {
  if (!child || child.killed) {
    return;
  }
  if (process.platform === "win32" && child.pid) {
    spawnSync("taskkill.exe", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
    return;
  }
  child.kill("SIGTERM");
}

function normalizeDirection(input) {
  const value = input && (input.direction ?? input.langType ?? input.lang_type ?? input.language_direction);
  const text = String(value ?? "ja_to_vi").trim().toLowerCase();

  if (value === 0 || text === "0" || text === "ja_to_vi" || text === "jp_to_vi" || text === "japanese_to_vietnamese") {
    return { key: "ja_to_vi", label: "Japanese to Vietnamese", source: "Japanese", target: "Vietnamese" };
  }
  if (value === 1 || text === "1" || text === "vi_to_ja" || text === "vi_to_jp" || text === "vietnamese_to_japanese") {
    return { key: "vi_to_ja", label: "Vietnamese to Japanese", source: "Vietnamese", target: "Japanese" };
  }
  if (text === "ja_to_en" || text === "jp_to_en" || text === "japanese_to_english") {
    return { key: "ja_to_en", label: "Japanese to English", source: "Japanese", target: "English" };
  }
  if (text === "en_to_ja" || text === "en_to_jp" || text === "english_to_japanese") {
    return { key: "en_to_ja", label: "English to Japanese", source: "English", target: "Japanese" };
  }
  if (text === "vi_to_en" || text === "vietnamese_to_english") {
    return { key: "vi_to_en", label: "Vietnamese to English", source: "Vietnamese", target: "English" };
  }
  if (text === "en_to_vi" || text === "english_to_vietnamese") {
    return { key: "en_to_vi", label: "English to Vietnamese", source: "English", target: "Vietnamese" };
  }

  // Generic free-form: "french_to_spanish", "chinese to japanese", etc.
  const separator = text.includes("_to_") ? "_to_" : text.includes(" to ") ? " to " : null;
  if (separator) {
    const idx = text.indexOf(separator);
    const rawSource = text.slice(0, idx).trim().replace(/_/g, " ");
    const rawTarget = text.slice(idx + separator.length).trim().replace(/_/g, " ");
    const source = rawSource.slice(0, 1).toUpperCase() + rawSource.slice(1);
    const target = rawTarget.slice(0, 1).toUpperCase() + rawTarget.slice(1);
    if (source && target) {
      const key = `${rawSource.replace(/\s+/g, "_")}_to_${rawTarget.replace(/\s+/g, "_")}`;
      return { key, label: `${source} to ${target}`, source, target };
    }
  }

  throw new Error(`Invalid direction: "${value}". Expected format: "SourceLanguage to TargetLanguage" (e.g. "Japanese to Vietnamese")`);
}

function normalizeGlossary(value) {
  if (!value) return "(no glossary defined)";
  if (typeof value === "string") return value.trim() || "(no glossary defined)";
  if (Array.isArray(value)) {
    const lines = value
      .map((item) => {
        if (typeof item === "string") return item.trim();
        if (!item || typeof item !== "object") return "";
        const source = item.source ?? item.from ?? item.ja ?? item.vi ?? item.term;
        const target = item.target ?? item.to ?? item.translation;
        return source && target ? `${source} => ${target}` : "";
      })
      .filter(Boolean);
    return lines.length ? lines.join("\n") : "(no glossary defined)";
  }
  if (typeof value === "object") {
    const lines = Object.entries(value)
      .map(([source, target]) => `${source} => ${target}`)
      .filter(Boolean);
    return lines.length ? lines.join("\n") : "(no glossary defined)";
  }
  return "(no glossary defined)";
}

function normalizeText(value, fallback = "") {
  return String(value ?? "").trim() || fallback;
}

function ensureTranslationFile(filePath) {
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
  if (officeFileExtensions.has(extension)) {
    return { path: resolved, extension, fileName: path.basename(resolved), kind: "office", size: stat.size };
  }
  if (textFileExtensions.has(extension)) {
    return { path: resolved, extension, fileName: path.basename(resolved), kind: extension === ".md" ? "markdown" : "text", size: stat.size };
  }

  throw new Error("Only .txt, .md, .docx, .pptx, and .xlsx files are supported");
}

function translationOptions(input = {}) {
  const defaults = defaultTranslationConfig();
  return {
    direction: normalizeDirection(input),
    openXmlBaseUrl: normalizeText(input.openXmlBaseUrl ?? input.openxml_base_url, defaults.openxml_base_url),
    codexCommand: resolveCodexCommand(normalizeText(input.codexCommand ?? input.codex_command, defaults.codex_command)),
    model: normalizeText(input.model, defaults.model),
    reasoningEffort: normalizeText(input.reasoningEffort ?? input.reasoning_effort, defaults.reasoning_effort),
    timeoutSeconds: positiveInt(input.timeoutSeconds ?? input.timeout_seconds, defaults.timeout_seconds, 5, 3600),
    contextWindow: positiveInt(input.contextWindow ?? input.context_window, defaults.context_window, 0, 200),
    batchSize: positiveInt(input.batchSize ?? input.batch_size, defaults.batch_size, 1, 200),
    concurrency: positiveInt(input.concurrency, defaults.concurrency, 1, 4),
    fastMode: parseBoolean(input.fastMode ?? input.fast_mode, defaults.fast_mode),
    glossary: normalizeGlossary(input.glossary),
    instructions: normalizeText(input.instructions, DEFAULT_INSTRUCTIONS),
    documentSummary: normalizeText(input.documentSummary ?? input.document_summary, "(no summary provided)"),
    sheets: normalizeStringArray(input.sheets),
    outputPath: normalizeText(input.outputPath ?? input.output_path),
    outputDirectory: normalizeText(input.outputDirectory ?? input.output_directory),
  };
}

function containsJapanese(text) {
  return /[\u3040-\u309f\u30a0-\u30ff\u3400-\u9fff\uff66-\uff9f]/u.test(text);
}

function containsVietnamese(text) {
  return /[A-Za-z\u00c0-\u1ef9]{2,}/u.test(text);
}

function containsEnglish(text) {
  return /[A-Za-z]{2,}/.test(text);
}

function shouldTranslate(text, direction) {
  const trimmed = String(text ?? "").trim();
  if (!trimmed) return false;
  const src = direction.source;
  if (src === "Japanese") return containsJapanese(trimmed);
  if (src === "Vietnamese") return containsVietnamese(trimmed);
  if (src === "English") return containsEnglish(trimmed);
  return containsJapanese(trimmed);
}

function stripVietnameseDiacritics(input) {
  return String(input ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\u0111/g, "d")
    .replace(/\u0110/g, "D")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D");
}

function cleanFileBaseName(input, fallback = "translated") {
  const text = String(input ?? "")
    .replace(/[\\/:*"<>|]/g, "")
    .replace(/[\u0000-\u001f]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[. ]+$/g, "");
  return text || fallback;
}

function normalizeVietnameseFileName(input) {
  const withoutSuffix = cleanFileBaseName(input).replace(/_JA$/i, "");
  const ascii = stripVietnameseDiacritics(withoutSuffix);
  const compact = ascii
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.slice(0, 1).toUpperCase() + word.slice(1))
    .join("");
  return `${cleanFileBaseName(compact)}_VN`;
}

function normalizeJapaneseFileName(input) {
  const withoutSuffix = cleanFileBaseName(input).replace(/_VN$/i, "");
  return `${cleanFileBaseName(withoutSuffix.replace(/\s+/g, ""))}_JP`;
}

function normalizeEnglishFileName(input) {
  const withoutSuffix = cleanFileBaseName(input).replace(/_(VN|JP)$/i, "");
  const clean = withoutSuffix.replace(/\s+/g, "_");
  return `${cleanFileBaseName(clean)}_EN`;
}

function normalizeTargetFileName(translatedBaseName, direction) {
  if (direction.target === "Vietnamese") return normalizeVietnameseFileName(translatedBaseName);
  if (direction.target === "Japanese") return normalizeJapaneseFileName(translatedBaseName);
  if (direction.target === "English") return normalizeEnglishFileName(translatedBaseName);
  return normalizeVietnameseFileName(translatedBaseName);
}

async function translateFileBaseName(file, options, callbacks = {}) {
  const originalBaseName = path.basename(file.path, file.extension);
  let translatedBaseName = originalBaseName;
  if (shouldTranslate(originalBaseName, options.direction)) {
    callbacks.log?.("info", "codex", `Translating file name: ${originalBaseName}`);
    [translatedBaseName] = await translateBatch(
      [{ index: 0, text: originalBaseName }],
      [originalBaseName],
      { ...options, contextWindow: 0, documentSummary: "Document file name" },
      callbacks
    );
  }
  return normalizeTargetFileName(translatedBaseName, options.direction);
}

function preserveOuterWhitespace(original, translated) {
  const text = String(original ?? "");
  const leading = text.match(/^\s*/u)?.[0] ?? "";
  const trailing = text.match(/\s*$/u)?.[0] ?? "";
  return `${leading}${String(translated ?? "").trim()}${trailing}`;
}

function chunks(items, size) {
  const result = [];
  for (let i = 0; i < items.length; i += size) {
    result.push(items.slice(i, i + size));
  }
  return result;
}

function splitTextRecords(content) {
  const records = [];
  const text = String(content ?? "");
  const linePattern = /([^\r\n]*)(\r\n|\n|\r|$)/g;
  let match;
  while ((match = linePattern.exec(text)) !== null) {
    if (match[0] === "" && match[2] === "") break;
    records.push({ text: match[1], eol: match[2] });
    if (match[2] === "") break;
  }
  return records;
}

function readTextFileSegments(filePath) {
  return splitTextRecords(fs.readFileSync(filePath, "utf8")).map((record) => record.text);
}

function markdownTextCandidate(value) {
  return String(value ?? "")
    .trim()
    .replace(/^#{1,6}\s+/u, "")
    .replace(/^>\s*/u, "")
    .replace(/^[-+*]\s+/u, "")
    .replace(/^\d+[.)]\s+/u, "")
    .replace(/^\[[ xX]\]\s+/u, "")
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/<\/?[^>]+>/g, "")
    .replace(/[*_~]/g, "")
    .trim();
}

function markdownLineSegments(line) {
  const trimmed = String(line ?? "").trim();
  if (!trimmed || /^[-*_]{3,}$/u.test(trimmed)) return [];
  if (/^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/u.test(trimmed)) return [];

  const cells = trimmed.includes("|")
    ? trimmed.split("|").map((cell) => cell.trim()).filter(Boolean)
    : [trimmed];
  return cells.map(markdownTextCandidate).filter(Boolean);
}

function readMarkdownFileSegments(filePath) {
  const content = fs.readFileSync(filePath, "utf8").replace(/<br\s*\/?>/gi, "\n");
  const segments = [];
  let fenced = false;
  for (const line of content.split(/\r\n|\n|\r/)) {
    if (/^\s*(```|~~~)/u.test(line)) {
      fenced = !fenced;
      continue;
    }
    if (fenced) continue;
    segments.push(...markdownLineSegments(line));
  }
  return segments;
}

function safeTimestamp() {
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\..+$/u, "").replace("T", "-");
}

function defaultDocumentOutputPath(inputPath, outputDirectory, outputBaseName) {
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

function writeTranslatedTextFile({ file, translatedSegments, outputPath, outputDirectory, outputBaseName }) {
  const records = splitTextRecords(fs.readFileSync(file.path, "utf8"));
  if (records.length !== translatedSegments.length) {
    throw new Error(`Text file changed while translating: expected ${translatedSegments.length} lines, found ${records.length}`);
  }
  const targetPath = outputPath ? path.resolve(outputPath) : defaultDocumentOutputPath(file.path, outputDirectory, outputBaseName);
  const content = records.map((record, index) => `${String(translatedSegments[index] ?? "")}${record.eol}`).join("");
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.writeFileSync(targetPath, content, "utf8");
  return targetPath;
}

function writeTranslatedMarkdownFile({ file, sourceSegments, translatedSegments, outputPath, outputDirectory, outputBaseName }) {
  const targetPath = outputPath ? path.resolve(outputPath) : defaultDocumentOutputPath(file.path, outputDirectory, outputBaseName);
  const replacements = new Map();
  for (let index = 0; index < sourceSegments.length; index += 1) {
    const source = String(sourceSegments[index] ?? "").trim();
    const translated = String(translatedSegments[index] ?? "").trim();
    if (source && source !== translated) {
      replacements.set(source, translated);
    }
  }

  let content = fs.readFileSync(file.path, "utf8").replace(/<br>/gi, "<br/>");
  for (const [source, translated] of Array.from(replacements.entries()).sort((left, right) => right[0].length - left[0].length)) {
    content = content.split(source).join(translated);
  }

  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.writeFileSync(targetPath, content, "utf8");
  return targetPath;
}

function buildPrompt({ batch, allSegments, firstIndex, options }) {
  const start = Math.max(0, firstIndex - options.contextWindow);
  const lastIndex = batch[batch.length - 1].index;
  const end = Math.min(allSegments.length, lastIndex + 1 + options.contextWindow);
  const contextBefore = allSegments.slice(start, firstIndex).join("\n") || "(none)";
  const contextAfter = allSegments.slice(lastIndex + 1, end).join("\n") || "(none)";
  const segments = batch.map((item, index) => `[${index + 1}] ${item.text}`).join("\n");

  return PROMPT_TEMPLATE
    .replaceAll("{direction}", options.direction.label)
    .replaceAll("{glossary}", options.glossary)
    .replaceAll("{documentSummary}", options.documentSummary)
    .replaceAll("{instructions}", options.instructions)
    .replaceAll("{contextBefore}", contextBefore)
    .replaceAll("{contextAfter}", contextAfter)
    .replaceAll("{segmentCount}", String(batch.length))
    .replaceAll("{segments}", segments);
}

function codexTempRoot(kind) {
  const configured = process.env.CONTRACK_CODEX_TEMP_DIR;
  return path.join(configured ? path.resolve(configured) : path.join(os.tmpdir(), "contrack-codex"), kind);
}

function writeSchema(schemaPath, expectedCount) {
  fs.writeFileSync(
    schemaPath,
    JSON.stringify(
      {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        type: "object",
        additionalProperties: false,
        required: ["translations"],
        properties: {
          translations: {
            type: "array",
            minItems: expectedCount,
            maxItems: expectedCount,
            items: { type: "string" },
          },
        },
      },
      null,
      2
    ),
    "utf8"
  );
}

function isWindowsCommandScript(command) {
  return process.platform === "win32" && /\.(cmd|bat)$/i.test(String(command || ""));
}

function quoteCmdArg(value) {
  const text = String(value ?? "").replace(/%/g, "%%").replace(/"/g, '""');
  return `"${text}"`;
}

function spawnTarget(command, args) {
  if (!isWindowsCommandScript(command)) {
    return {
      command,
      args,
      windowsVerbatimArguments: false,
    };
  }

  const commandLine = [quoteCmdArg(command), ...args.map(quoteCmdArg)].join(" ");
  return {
    command: process.env.ComSpec || "cmd.exe",
    args: ["/d", "/s", "/c", `"${commandLine}"`],
    windowsVerbatimArguments: true,
  };
}

function findCommandOnPath(names) {
  const pathDirs = String(process.env.PATH || "")
    .split(path.delimiter)
    .map((dir) => dir.trim().replace(/^"|"$/g, ""))
    .filter(Boolean);
  const expandedNames = [];
  for (const name of names) {
    if (path.isAbsolute(name)) {
      expandedNames.push(name);
      continue;
    }
    if (process.platform === "win32" && !path.extname(name)) {
      expandedNames.push(`${name}.cmd`, `${name}.exe`, `${name}.bat`, name);
    } else {
      expandedNames.push(name);
    }
  }

  for (const dir of pathDirs) {
    for (const name of expandedNames) {
      const candidate = path.isAbsolute(name) ? name : path.join(dir, name);
      if (fs.existsSync(candidate)) {
        return candidate;
      }
    }
  }
  return null;
}

function resolveNpmCommand() {
  const configured = normalizeText(process.env.CONTRACK_NPM_COMMAND || process.env.NPM_COMMAND);
  if (configured) {
    return configured;
  }
  return findCommandOnPath(["npm"]) || (process.platform === "win32" ? "npm.cmd" : "npm");
}

function runInteractiveProcess(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const target = spawnTarget(command, args);
    const child = spawn(target.command, target.args, {
      cwd: options.cwd,
      env: options.env || process.env,
      stdio: "inherit",
      windowsHide: false,
      windowsVerbatimArguments: target.windowsVerbatimArguments,
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${command} exited with code ${code}`));
      }
    });
  });
}

function runProcess(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    if (options.isCanceled?.()) {
      reject(createCanceledError());
      return;
    }
    const target = spawnTarget(command, args);
    const child = spawn(target.command, target.args, {
      cwd: options.cwd,
      env: options.env || process.env,
      windowsHide: true,
      windowsVerbatimArguments: target.windowsVerbatimArguments,
    });
    options.trackChild?.(child);
    if (options.isCanceled?.()) {
      terminateChild(child);
    }
    let stdout = "";
    let stderr = "";
    let settled = false;

    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      options.untrackChild?.(child);
      if (error) reject(error);
      else resolve(value);
    };

    const timeoutMs = Math.max(Number(options.timeoutMs || 0), 0);
    const timer = timeoutMs
      ? setTimeout(() => {
          terminateChild(child);
          finish(new Error(`${command} timed out after ${Math.ceil(timeoutMs / 1000)}s`));
        }, timeoutMs)
      : null;

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", finish);
    child.on("close", (code) => {
      if (options.isCanceled?.()) {
        finish(createCanceledError());
        return;
      }
      if (code === 0) {
        finish(null, { stdout, stderr });
      } else {
        finish(new Error((stderr || stdout || `${command} exited with code ${code}`).trim()));
      }
    });

    child.stdin.on("error", () => {
      // The process may have been killed by a user stop request before stdin flushes.
    });
    if (options.input) {
      child.stdin.write(options.input);
    }
    child.stdin.end();
  });
}

function cleanupTempFiles(files) {
  for (const file of files) {
    if (!file) continue;
    try {
      fs.rmSync(file, { force: true });
    } catch {
      // Best-effort cleanup only.
    }
  }
}

async function runCodex(prompt, expectedCount, options, callbacks = {}) {
  throwIfCanceled(callbacks);
  if (!options.model) {
    throw new Error("Select a model from the Codex CLI catalog before starting translation");
  }
  const runId = crypto.randomUUID();
  const keepFiles = parseBoolean(process.env.CONTRACK_CODEX_KEEP_FILES, false);
  const promptDir = keepFiles ? codexTempRoot("prompts") : null;
  const outputDir = codexTempRoot("outputs");
  if (promptDir) {
    fs.mkdirSync(promptDir, { recursive: true });
  }
  fs.mkdirSync(outputDir, { recursive: true });

  const promptPath = promptDir ? path.join(promptDir, `${runId}.txt`) : null;
  const outputPath = path.join(outputDir, `${runId}.txt`);
  const schemaPath = path.join(outputDir, `${runId}.schema.json`);
  if (promptPath) {
    fs.writeFileSync(promptPath, prompt, "utf8");
  }
  writeSchema(schemaPath, expectedCount);
  const tempFiles = [promptPath, outputPath, schemaPath];

  const args = [
    "exec",
    "--sandbox",
    "read-only",
    "--skip-git-repo-check",
    "--ephemeral",
    "--ignore-rules",
    "-m",
    options.model,
    "--output-schema",
    schemaPath,
    "--output-last-message",
    outputPath,
  ];
  if (options.reasoningEffort) {
    args.push("-c", `model_reasoning_effort='${options.reasoningEffort}'`);
  }
  if (options.fastMode) {
    args.push("-c", "features.fast=true");
  }

  try {
    const result = await runProcess(options.codexCommand, args, {
      input: prompt,
      timeoutMs: options.timeoutSeconds * 1000,
      cwd: process.cwd(),
      isCanceled: callbacks.isCanceled,
      trackChild: callbacks.trackChild,
      untrackChild: callbacks.untrackChild,
    });
    throwIfCanceled(callbacks);
    const output = fs.existsSync(outputPath) ? fs.readFileSync(outputPath, "utf8") : result.stdout;
    return output.trim();
  } catch (error) {
    if (keepFiles) {
      error.message = `${error.message}\nCodex temp files kept at: ${tempFiles.filter(Boolean).join(", ")}`;
    }
    throw error;
  } finally {
    if (!keepFiles) {
      cleanupTempFiles(tempFiles);
    }
  }
}

function parseCodexOutput(output, expectedCount) {
  let text = String(output || "").trim();
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  if (fenced) {
    text = fenced[1].trim();
  }

  const candidates = [text];
  const firstBrace = text.indexOf("{");
  const lastBrace = text.lastIndexOf("}");
  if (firstBrace >= 0 && lastBrace > firstBrace) {
    candidates.push(text.slice(firstBrace, lastBrace + 1));
  }
  const firstBracket = text.indexOf("[");
  const lastBracket = text.lastIndexOf("]");
  if (firstBracket >= 0 && lastBracket > firstBracket) {
    candidates.push(text.slice(firstBracket, lastBracket + 1));
  }

  let parsed;
  let parseError;
  for (const candidate of candidates) {
    try {
      parsed = JSON.parse(candidate);
      break;
    } catch (error) {
      parseError = error;
    }
  }

  const translations = Array.isArray(parsed) ? parsed : parsed && parsed.translations;
  if (!Array.isArray(translations)) {
    throw new Error(`Codex output does not contain a translations array: ${parseError ? parseError.message : "invalid JSON"}`);
  }
  if (translations.length !== expectedCount) {
    throw new Error(`Codex returned ${translations.length} translations, expected ${expectedCount}`);
  }
  return translations.map((item) => String(item ?? ""));
}

async function translateBatch(batch, allSegments, options, callbacks = {}) {
  throwIfCanceled(callbacks);
  const prompt = buildPrompt({
    batch,
    allSegments,
    firstIndex: batch[0].index,
    options,
  });
  const output = await runCodex(prompt, batch.length, options, callbacks);
  throwIfCanceled(callbacks);
  return parseCodexOutput(output, batch.length);
}

async function translateSegments(segments, options, callbacks = {}) {
  const allSegments = segments.map((item) => String(item ?? "").trim());
  const translatedSegments = segments.map((item) => String(item ?? ""));
  const candidates = translatedSegments
    .map((text, index) => ({ index, text: text.trim() }))
    .filter((item) => shouldTranslate(item.text, options.direction));
  const batches = chunks(candidates, options.batchSize);

  callbacks.progress?.({
    total_segments: translatedSegments.length,
    translatable_segments: candidates.length,
    translated_segments: 0,
    batches_done: 0,
    batches_total: batches.length,
  });

  let translatedCount = 0;
  let completedBatches = 0;
  let nextBatchIndex = 0;
  let firstError = null;
  const workerCount = Math.min(Math.max(options.concurrency || 1, 1), Math.max(batches.length, 1));

  if (batches.length > 1) {
    callbacks.log?.("info", "codex", `Using ${workerCount} Codex workers`);
  }

  async function translateBatchAt(batchIndex, workerNumber) {
    throwIfCanceled(callbacks);
    const batch = batches[batchIndex];
    const workerLabel = workerCount > 1 ? ` worker ${workerNumber}` : "";
    callbacks.log?.("info", "codex", `Translating batch ${batchIndex + 1}/${batches.length}${workerLabel} (${batch.length} segments)`);
    const translations = await translateBatch(batch, allSegments, options, callbacks);
    throwIfCanceled(callbacks);
    for (let i = 0; i < batch.length; i += 1) {
      const item = batch[i];
      translatedSegments[item.index] = preserveOuterWhitespace(segments[item.index], translations[i]);
      translatedCount += 1;
    }
    completedBatches += 1;
    callbacks.progress?.({
      total_segments: translatedSegments.length,
      translatable_segments: candidates.length,
      translated_segments: translatedCount,
      batches_done: completedBatches,
      batches_total: batches.length,
    });
  }

  async function worker(workerNumber) {
    while (!firstError && !callbacks.isCanceled?.()) {
      const batchIndex = nextBatchIndex;
      nextBatchIndex += 1;
      if (batchIndex >= batches.length) return;
      try {
        await translateBatchAt(batchIndex, workerNumber);
      } catch (error) {
        firstError = error;
      }
    }
  }

  await Promise.all(Array.from({ length: workerCount }, (_, index) => worker(index + 1)));
  throwIfCanceled(callbacks);
  if (firstError) {
    throw firstError;
  }

  return {
    translatedSegments,
    total_segments: translatedSegments.length,
    translatable_segments: candidates.length,
  };
}

async function codexLoginStatus(command) {
  try {
    const result = await runProcess(command, ["login", "status"], { timeoutMs: 10000 });
    return {
      ok: true,
      message: result.stdout.trim() || "Codex CLI is authenticated",
    };
  } catch (error) {
    return {
      ok: false,
      message: error && error.message ? error.message : String(error),
    };
  }
}

function shouldBootstrapCodex() {
  return parseBoolean(process.env.CONTRACK_CODEX_AUTO_BOOTSTRAP ?? process.env.CONTRACK_CODEX_BOOTSTRAP, true);
}

function isDefaultCodexCommand(command) {
  const value = normalizeText(command, "codex").toLowerCase();
  return value === "codex" || /[\\/]codex(\.cmd|\.exe)?$/i.test(value);
}

async function bootstrapCodexCli({ logger = console } = {}) {
  if (!shouldBootstrapCodex()) {
    logger.log?.("Codex CLI bootstrap is disabled");
    return { ok: false, skipped: true, message: "Codex CLI bootstrap is disabled" };
  }

  const rawCommand = process.env.CONTRACK_CODEX_COMMAND || "codex";
  let command = resolveCodexCommand(rawCommand);
  let version = "";

  try {
    const result = await runProcess(command, ["--version"], { timeoutMs: 10000 });
    version = result.stdout.trim();
  } catch (error) {
    if (!isDefaultCodexCommand(rawCommand)) {
      const message = `Configured Codex command is not available: ${command}`;
      logger.warn?.(`${message}. ${error.message}`);
      return { ok: false, command, message };
    }

    const npmCommand = resolveNpmCommand();
    logger.warn?.("Codex CLI was not found. Installing @openai/codex globally...");
    await runInteractiveProcess(npmCommand, ["install", "-g", "@openai/codex"], { cwd: process.cwd() });
    command = resolveCodexCommand("codex");
    const result = await runProcess(command, ["--version"], { timeoutMs: 10000 });
    version = result.stdout.trim();
  }

  logger.log?.(`Codex CLI ready: ${version || command}`);
  let auth = await codexLoginStatus(command);
  if (!auth.ok) {
    logger.warn?.("Codex CLI authentication is required. Starting `codex login` in this server console...");
    await runInteractiveProcess(command, ["login"], { cwd: process.cwd() });
    auth = await codexLoginStatus(command);
  }

  if (!auth.ok) {
    logger.warn?.(`Codex CLI is still not authenticated: ${auth.message}`);
    return { ok: false, command, version, message: auth.message };
  }

  logger.log?.(`Codex CLI auth ready: ${auth.message}`);
  return { ok: true, command, version, message: auth.message };
}

async function checkCodexAvailability(input = {}) {
  const defaults = defaultTranslationConfig();
  const command = resolveCodexCommand(normalizeText(input.codexCommand ?? input.codex_command, defaults.codex_command));
  try {
    const result = await runProcess(command, ["--version"], { timeoutMs: 10000 });
    const codexHome = codexHomePath();
    const auth = await codexLoginStatus(command);
    if (!auth.ok) {
      return {
        ok: false,
        command,
        codex_home: codexHome,
        message: `Codex CLI is installed, but authentication is not ready. Run codex login. ${auth.message}`.trim(),
        version: result.stdout.trim(),
      };
    }
    return {
      ok: true,
      command,
      codex_home: codexHome,
      message: "Codex CLI is available",
      version: result.stdout.trim(),
    };
  } catch (error) {
    return {
      ok: false,
      command,
      message: error && error.code === "ENOENT" ? "Codex CLI is not installed or not on PATH" : error.message,
    };
  }
}

async function documentTranslationHealth(input = {}) {
  const options = translationOptions(input);
  const defaults = defaultTranslationConfig();
  const [openxml, codex] = await Promise.all([
    checkOpenXml({ openXmlBaseUrl: options.openXmlBaseUrl }),
    checkCodexAvailability({ codexCommand: options.codexCommand }),
  ]);
  return {
    ok: Boolean(openxml.ok && codex.ok),
    openxml,
    codex,
    defaults: {
      ...defaults,
      openxml_base_url: options.openXmlBaseUrl,
    },
  };
}

async function judgeDocumentSheets(input = {}) {
  const file = ensureTranslationFile(input.filePath ?? input.file_path);
  if (file.extension !== ".xlsx") {
    return [];
  }
  const options = translationOptions(input);
  return judgeOfficeSheets({
    filePath: file.path,
    openXmlBaseUrl: options.openXmlBaseUrl,
  });
}

async function extractDocumentText(input = {}) {
  const options = translationOptions(input);
  const file = ensureTranslationFile(input.filePath ?? input.file_path);
  const segments = file.kind === "office"
    ? await importOfficeFile({
        filePath: file.path,
        sheets: options.sheets,
        openXmlBaseUrl: options.openXmlBaseUrl,
      })
    : file.kind === "markdown"
      ? readMarkdownFileSegments(file.path)
      : readTextFileSegments(file.path);
  return {
    file_path: file.path,
    extension: file.extension,
    file_type: file.kind,
    sheets: options.sheets,
    segment_count: segments.length,
    segments,
  };
}

async function translateOfficeDocument(input = {}, callbacks = {}) {
  const file = ensureOfficeFile(input.filePath ?? input.file_path);
  const options = translationOptions(input);

  throwIfCanceled(callbacks);
  callbacks.log?.("info", "openxml", `Extracting ${file.fileName}`);
  const openxml = await checkOpenXml({ openXmlBaseUrl: options.openXmlBaseUrl });
  if (!openxml.ok) {
    throw new Error(`OpenXML API is not ready: ${openxml.message}`);
  }

  const codex = await checkCodexAvailability({ codexCommand: options.codexCommand });
  if (!codex.ok) {
    throw new Error(`Codex CLI is not ready: ${codex.message}`);
  }

  const segments = await importOfficeFile({
    filePath: file.path,
    sheets: options.sheets,
    openXmlBaseUrl: options.openXmlBaseUrl,
  });
  if (!segments.length) {
    throw new Error("OpenXML extracted no text segments from the document");
  }

  throwIfCanceled(callbacks);
  callbacks.log?.("info", "openxml", `Extracted ${segments.length} segments`);
  const translated = await translateSegments(segments, options, callbacks);
  throwIfCanceled(callbacks);
  const outputBaseName = options.outputPath ? "" : await translateFileBaseName(file, options, callbacks);

  throwIfCanceled(callbacks);
  callbacks.log?.("info", "openxml", "Writing translated document");
  const outputPath = await exportOfficeFile({
    filePath: file.path,
    data: translated.translatedSegments,
    sheets: options.sheets,
    outputPath: options.outputPath,
    outputDirectory: options.outputDirectory,
    outputBaseName,
    openXmlBaseUrl: options.openXmlBaseUrl,
  });

  return {
    file_path: file.path,
    output_path: outputPath,
    output_file_name: path.basename(outputPath),
    file_type: "office",
    direction: options.direction.key,
    model: options.model,
    reasoning_effort: options.reasoningEffort,
    fast_mode: options.fastMode,
    total_segments: translated.total_segments,
    translatable_segments: translated.translatable_segments,
    openxml_base_url: options.openXmlBaseUrl,
  };
}

async function translateTextDocument(input = {}, callbacks = {}) {
  const file = ensureTranslationFile(input.filePath ?? input.file_path);
  if (file.kind === "office") {
    return translateOfficeDocument(input, callbacks);
  }
  const options = translationOptions(input);

  throwIfCanceled(callbacks);
  callbacks.log?.("info", "file", `Reading ${file.fileName}`);
  const codex = await checkCodexAvailability({ codexCommand: options.codexCommand });
  if (!codex.ok) {
    throw new Error(`Codex CLI is not ready: ${codex.message}`);
  }

  const segments = file.kind === "markdown" ? readMarkdownFileSegments(file.path) : readTextFileSegments(file.path);
  if (!segments.length) {
    throw new Error(`${file.extension} file contains no text segments`);
  }

  throwIfCanceled(callbacks);
  callbacks.log?.("info", "file", `Extracted ${segments.length} segments`);
  const translated = await translateSegments(segments, options, callbacks);
  throwIfCanceled(callbacks);
  const outputBaseName = options.outputPath ? "" : await translateFileBaseName(file, options, callbacks);

  throwIfCanceled(callbacks);
  callbacks.log?.("info", "file", "Writing translated document");
  const outputPath = file.kind === "markdown"
    ? writeTranslatedMarkdownFile({
        file,
        sourceSegments: segments,
        translatedSegments: translated.translatedSegments,
        outputPath: options.outputPath,
        outputDirectory: options.outputDirectory,
        outputBaseName,
      })
    : writeTranslatedTextFile({
        file,
        translatedSegments: translated.translatedSegments,
        outputPath: options.outputPath,
        outputDirectory: options.outputDirectory,
        outputBaseName,
      });

  return {
    file_path: file.path,
    output_path: outputPath,
    output_file_name: path.basename(outputPath),
    file_type: file.kind,
    direction: options.direction.key,
    model: options.model,
    reasoning_effort: options.reasoningEffort,
    fast_mode: options.fastMode,
    total_segments: translated.total_segments,
    translatable_segments: translated.translatable_segments,
    openxml_base_url: options.openXmlBaseUrl,
  };
}

async function translateDocument(input = {}, callbacks = {}) {
  const file = ensureTranslationFile(input.filePath ?? input.file_path);
  return file.kind === "office" ? translateOfficeDocument(input, callbacks) : translateTextDocument(input, callbacks);
}

function appendLog(job, level, source, message) {
  job.logs.push({
    seq: job.logs.length + 1,
    ts: nowSeconds(),
    level,
    source,
    message,
  });
  if (job.logs.length > maxLogsPerJob) {
    job.logs.splice(0, job.logs.length - maxLogsPerJob);
  }
  job.updated_at = nowSeconds();
}

function publicJob(job) {
  return {
    job_id: job.job_id,
    kind: job.kind,
    status: job.status,
    error: job.error,
    logs: job.logs,
    progress: job.progress,
    result: job.result,
    cancel_requested: Boolean(job.cancel_requested),
    created_at: job.created_at,
    updated_at: job.updated_at,
  };
}

function startDocumentTranslationJob(input = {}) {
  const now = nowSeconds();
  const job = {
    job_id: crypto.randomUUID(),
    kind: "document-translation",
    status: "queued",
    error: null,
    logs: [],
    cancel_requested: false,
    children: new Set(),
    progress: {
      total_segments: 0,
      translatable_segments: 0,
      translated_segments: 0,
      batches_done: 0,
      batches_total: 0,
    },
    result: null,
    created_at: now,
    updated_at: now,
  };
  jobs.set(job.job_id, job);

  setImmediate(async () => {
    try {
      throwIfCanceled({ isCanceled: () => job.cancel_requested });
      job.status = "running";
      appendLog(job, "info", "job", "Document translation started");
      job.result = await translateDocument(input, {
        log: (level, source, message) => appendLog(job, level, source, message),
        isCanceled: () => job.cancel_requested,
        trackChild: (child) => job.children.add(child),
        untrackChild: (child) => job.children.delete(child),
        progress: (progress) => {
          job.progress = { ...job.progress, ...progress };
          job.updated_at = nowSeconds();
        },
      });
      throwIfCanceled({ isCanceled: () => job.cancel_requested });
      job.status = "succeeded";
      appendLog(job, "info", "job", `Document translation completed: ${job.result.output_path}`);
    } catch (error) {
      if (isCanceledError(error) || job.cancel_requested) {
        job.cancel_requested = true;
        job.status = "canceled";
        job.error = "Stopped by user";
        appendLog(job, "warn", "job", "Document translation stopped");
      } else {
        job.status = "failed";
        job.error = error && error.message ? error.message : String(error);
        appendLog(job, "error", "job", job.error);
      }
    } finally {
      job.updated_at = nowSeconds();
    }
  });

  return publicJob(job);
}

function getDocumentTranslationJob(jobId) {
  const job = jobs.get(jobId);
  return job ? publicJob(job) : null;
}

function cancelDocumentTranslationJob(jobId) {
  const job = jobs.get(jobId);
  if (!job) {
    return null;
  }
  if (!isTerminalStatus(job.status)) {
    job.cancel_requested = true;
    job.status = "canceled";
    job.error = "Stopped by user";
    appendLog(job, "warn", "job", "Stop requested by user");
    for (const child of Array.from(job.children || [])) {
      terminateChild(child);
    }
  }
  job.updated_at = nowSeconds();
  return publicJob(job);
}

module.exports = {
  bootstrapCodexCli,
  cancelDocumentTranslationJob,
  checkCodexAvailability,
  defaultTranslationConfig,
  documentTranslationHealth,
  extractDocumentText,
  getDocumentTranslationJob,
  judgeDocumentSheets,
  judgeOfficeSheets,
  listCodexModels,
  startDocumentTranslationJob,
  translateDocument,
  translateOfficeDocument,
};
