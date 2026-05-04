const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { spawn } = require("node:child_process");

function requireLocalModule(fileName) {
  const candidates = [
    path.join(__dirname, "lib", fileName),
  ];
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) {
    throw new Error(`Cannot find local module ${fileName}. Checked: ${candidates.join(", ")}`);
  }
  return require(found);
}

const { getBuildJob, startBuildJob } = requireLocalModule("build-source.cjs");
const {
  bootstrapCodexCli,
  defaultTranslationConfig,
  documentTranslationHealth,
  extractDocumentText,
  getDocumentTranslationJob,
  judgeDocumentSheets,
  listCodexModels,
  startDocumentTranslationJob,
} = requireLocalModule("codex-translation.cjs");
const {
  commitWorkingTree,
  fixWorkingTree,
  previewWorkingTree,
  pushWorkingTree,
  structuredDiff,
} = requireLocalModule("git-eol-local.cjs");
const { defaultPaths, getSetting, setSetting } = requireLocalModule("settings.cjs");
const { prepareUpdate, updateStatus } = requireLocalModule("updater.cjs");
const { localServerVersion } = requireLocalModule("version.cjs");

const host = process.env.CONTRACK_LOCAL_SERVER_HOST || "127.0.0.1";
const port = Number(process.env.CONTRACK_LOCAL_SERVER_PORT || 3219);
const maxBodyBytes = 1024 * 1024 * 5;
const allowedOrigins = (process.env.CONTRACK_ALLOWED_ORIGINS || process.env.CONTRACK_CORS_ORIGINS || "")
  .split(",")
  .map((origin) => origin.trim().replace(/\/$/, ""))
  .filter(Boolean);
let server;
let updateApplyScheduled = false;

function isLoopbackHost(value) {
  const hostName = String(value || "").replace(/^\[/, "").replace(/\]$/, "").toLowerCase();
  return hostName === "localhost" || hostName === "127.0.0.1" || hostName === "::1";
}

function hostNameFromHeader(value) {
  const text = String(value || "");
  if (text.startsWith("[")) {
    return text.slice(1, text.indexOf("]"));
  }
  return text.split(":")[0];
}

function isAllowedOrigin(origin, hostHeader) {
  if (!origin) return true;
  if (/^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/i.test(origin)) return true;
  if (allowedOrigins.includes("*")) return true;
  if (allowedOrigins.includes(origin.replace(/\/$/, ""))) return true;
  try {
    const originUrl = new URL(origin);
    const hostName = hostNameFromHeader(hostHeader);
    return Boolean(
      hostName &&
        (isLoopbackHost(hostName) || originUrl.hostname.toLowerCase() === hostName.toLowerCase())
    );
  } catch {
    return false;
  }
}

function applyCors(req, res) {
  const origin = req.headers.origin;
  if (isAllowedOrigin(origin, req.headers.host)) {
    res.setHeader("Access-Control-Allow-Origin", origin || "*");
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,PUT,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Access-Control-Allow-Private-Network", "true");
}

function sendJson(req, res, status, payload) {
  applyCors(req, res);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(payload));
}

function sendError(req, res, status, error) {
  const message = error && error.message ? error.message : String(error);
  sendJson(req, res, status, { message });
}

function scheduleUpdateApply(applyScript) {
  if (updateApplyScheduled) return;
  updateApplyScheduled = true;
  const exitCode = process.env.CONTRACK_RESTART_HANDLED_BY_LAUNCHER === "1" ? 75 : 0;
  const timer = setTimeout(() => {
    try {
      const child = spawn(process.execPath, [applyScript, String(process.pid)], {
        cwd: path.dirname(applyScript),
        detached: true,
        stdio: "ignore",
        windowsHide: false,
      });
      child.unref();
      const forceExit = setTimeout(() => process.exit(exitCode), 2500);
      forceExit.unref?.();
      if (server) {
        server.close(() => process.exit(exitCode));
      } else {
        process.exit(exitCode);
      }
    } catch (error) {
      updateApplyScheduled = false;
      console.error(`Failed to start update apply script: ${error && error.message ? error.message : String(error)}`);
    }
  }, 500);
  timer.unref?.();
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let total = 0;
    req.on("data", (chunk) => {
      total += chunk.length;
      if (total > maxBodyBytes) {
        reject(new Error("Request body is too large"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      const text = Buffer.concat(chunks).toString("utf8").trim();
      if (!text) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(text));
      } catch {
        reject(new Error("Request body must be valid JSON"));
      }
    });
    req.on("error", reject);
  });
}

function runProcess(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env || process.env,
      windowsHide: Boolean(options.windowsHide),
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve(stdout);
        return;
      }
      reject(new Error((stderr || stdout || `${command} exited with code ${code}`).trim()));
    });
  });
}

function encodedPowerShell(script) {
  return Buffer.from(script, "utf16le").toString("base64");
}

function openWindowsExplorer(args) {
  return new Promise((resolve, reject) => {
    const child = spawn("explorer.exe", args, {
      detached: true,
      stdio: "ignore",
      windowsHide: false,
    });
    child.on("error", reject);
    child.on("spawn", () => {
      child.unref();
      resolve();
    });
  });
}

async function selectDirectory(currentPath) {
  if (process.platform !== "win32") {
    throw new Error("Folder picker is only supported on Windows local server");
  }
  const script = [
    "$ErrorActionPreference = 'Stop'",
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
    "$initial = $env:CONTRACK_INITIAL_PATH",
    "$selected = $null",
    "try {",
    "  Add-Type -AssemblyName System.Windows.Forms",
    "  Add-Type -AssemblyName System.Drawing",
    "  [System.Windows.Forms.Application]::EnableVisualStyles()",
    "  $owner = New-Object System.Windows.Forms.Form",
    "  $owner.StartPosition = 'CenterScreen'",
    "  $owner.Size = [System.Drawing.Size]::new(1, 1)",
    "  $owner.ShowInTaskbar = $false",
    "  $owner.TopMost = $true",
    "  $owner.Opacity = 0",
    "  $owner.Show()",
    "  $owner.Activate()",
    "  $dialog = New-Object System.Windows.Forms.FolderBrowserDialog",
    "  $dialog.Description = 'Select folder'",
    "  $dialog.ShowNewFolderButton = $true",
    "  if (![string]::IsNullOrWhiteSpace($initial) -and (Test-Path -LiteralPath $initial -PathType Container)) { $dialog.SelectedPath = $initial }",
    "  if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { $selected = $dialog.SelectedPath }",
    "  $owner.Close()",
    "  $owner.Dispose()",
    "} catch {",
    "  $shell = New-Object -ComObject Shell.Application",
    "  $root = 0",
    "  if (![string]::IsNullOrWhiteSpace($initial) -and (Test-Path -LiteralPath $initial -PathType Container)) { $root = $initial }",
    "  $folder = $shell.BrowseForFolder(0, 'Select folder', 0, $root)",
    "  if ($folder) { $selected = $folder.Self.Path }",
    "}",
    "if (![string]::IsNullOrWhiteSpace($selected)) { [Console]::Out.WriteLine($selected) }",
  ].join("\r\n");
  const output = await runProcess(
    "powershell.exe",
    ["-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encodedPowerShell(script)],
    {
      env: {
        ...process.env,
        CONTRACK_INITIAL_PATH: currentPath || "",
      },
      windowsHide: true,
    }
  );
  return output.trim() || null;
}

async function selectFile(currentPath) {
  if (process.platform !== "win32") {
    throw new Error("File picker is only supported on Windows local server");
  }
  const script = [
    "$ErrorActionPreference = 'Stop'",
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
    "$initial = $env:CONTRACK_INITIAL_FILE_PATH",
    "$selected = $null",
    "Add-Type -AssemblyName System.Windows.Forms",
    "Add-Type -AssemblyName System.Drawing",
    "[System.Windows.Forms.Application]::EnableVisualStyles()",
    "$owner = New-Object System.Windows.Forms.Form",
    "$owner.StartPosition = 'CenterScreen'",
    "$owner.Size = [System.Drawing.Size]::new(1, 1)",
    "$owner.ShowInTaskbar = $false",
    "$owner.TopMost = $true",
    "$owner.Opacity = 0",
    "$owner.Show()",
    "$owner.Activate()",
    "$dialog = New-Object System.Windows.Forms.OpenFileDialog",
    "$dialog.Title = 'Select document'",
    "$dialog.Filter = 'Supported documents (*.txt;*.md;*.docx;*.xlsx;*.pptx)|*.txt;*.md;*.docx;*.xlsx;*.pptx|Text documents (*.txt;*.md)|*.txt;*.md|Office documents (*.docx;*.xlsx;*.pptx)|*.docx;*.xlsx;*.pptx|All files (*.*)|*.*'",
    "$dialog.Multiselect = $false",
    "if (![string]::IsNullOrWhiteSpace($initial)) {",
    "  if (Test-Path -LiteralPath $initial -PathType Leaf) {",
    "    $dialog.InitialDirectory = [System.IO.Path]::GetDirectoryName($initial)",
    "    $dialog.FileName = [System.IO.Path]::GetFileName($initial)",
    "  } elseif (Test-Path -LiteralPath $initial -PathType Container) {",
    "    $dialog.InitialDirectory = $initial",
    "  }",
    "}",
    "if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { $selected = $dialog.FileName }",
    "$owner.Close()",
    "$owner.Dispose()",
    "if (![string]::IsNullOrWhiteSpace($selected)) { [Console]::Out.WriteLine($selected) }",
  ].join("\r\n");
  const output = await runProcess(
    "powershell.exe",
    ["-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encodedPowerShell(script)],
    {
      env: {
        ...process.env,
        CONTRACK_INITIAL_FILE_PATH: currentPath || "",
      },
      windowsHide: true,
    }
  );
  return output.trim() || null;
}

async function openPath(targetPath) {
  const target = String(targetPath || "").trim();
  if (!target) {
    throw new Error("path is required");
  }
  if (process.platform === "win32") {
    const script = [
      "$target = $env:CONTRACK_OPEN_TARGET",
      "if ($target -match '^https?://') { Start-Process $target; exit 0 }",
      "if (Test-Path -LiteralPath $target -PathType Leaf) { explorer.exe /select, $target; exit 0 }",
      "Start-Process -LiteralPath $target",
    ].join("\r\n");
    await runProcess("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encodedPowerShell(script)], {
      env: {
        ...process.env,
        CONTRACK_OPEN_TARGET: target,
      },
      windowsHide: true,
    });
    return;
  }
  const opener = process.platform === "darwin" ? "open" : "xdg-open";
  const child = spawn(opener, [target], { detached: true, stdio: "ignore" });
  child.unref();
}

async function openContainingFolder(targetPath) {
  const target = String(targetPath || "").trim();
  if (!target) {
    throw new Error("path is required");
  }
  const resolvedTarget = path.resolve(target);
  const folder = fs.existsSync(resolvedTarget) && fs.statSync(resolvedTarget).isDirectory()
    ? resolvedTarget
    : path.dirname(resolvedTarget);
  if (!fs.existsSync(folder) || !fs.statSync(folder).isDirectory()) {
    throw new Error(`Output folder not found: ${folder}`);
  }
  if (process.platform === "win32") {
    await openWindowsExplorer(["/n,", folder]);
    return;
  }
  const opener = process.platform === "darwin" ? "open" : "xdg-open";
  const child = spawn(opener, [folder], { detached: true, stdio: "ignore" });
  child.unref();
}

function validatePath(input) {
  const target = String(input && input.path ? input.path : "").trim();
  const mustBeDirectory = input && input.mustBeDirectory !== false;
  if (!target) {
    return {
      path: "",
      exists: false,
      is_directory: false,
      is_file: false,
      valid: false,
      message: "path is required",
    };
  }
  let resolved;
  try {
    resolved = path.resolve(target);
  } catch (error) {
    return {
      path: target,
      exists: false,
      is_directory: false,
      is_file: false,
      valid: false,
      message: error && error.message ? error.message : "Path is invalid",
    };
  }
  let stat;
  try {
    stat = fs.existsSync(resolved) ? fs.statSync(resolved) : null;
  } catch (error) {
    return {
      path: resolved,
      exists: true,
      is_directory: false,
      is_file: false,
      valid: false,
      message: error && error.message ? error.message : `Cannot access path: ${resolved}`,
    };
  }
  if (!stat) {
    return {
      path: resolved,
      exists: false,
      is_directory: false,
      is_file: false,
      valid: false,
      message: `Path does not exist: ${resolved}`,
    };
  }
  const isDirectory = stat.isDirectory();
  const isFile = stat.isFile();
  const valid = mustBeDirectory ? isDirectory : true;
  return {
    path: resolved,
    exists: true,
    is_directory: isDirectory,
    is_file: isFile,
    valid,
    message: valid ? "Path is valid" : `Path is not a folder: ${resolved}`,
  };
}

async function route(req, res) {
  applyCors(req, res);
  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }
  if (req.headers.origin && !isAllowedOrigin(req.headers.origin, req.headers.host)) {
    sendJson(req, res, 403, { message: "Origin is not allowed" });
    return;
  }

  const url = new URL(req.url || "/", `http://${req.headers.host || `${host}:${port}`}`);
  const pathname = url.pathname.replace(/\/+$/, "") || "/";

  if (req.method === "GET" && pathname === "/health") {
    const versionInfo = localServerVersion();
    sendJson(req, res, 200, {
      ok: true,
      service: "contrack-local-node",
      version: versionInfo.version,
      created_at: versionInfo.created_at,
      commit_sha: versionInfo.commit_sha,
      updater_version: versionInfo.updater_version,
      port,
      default_paths: defaultPaths(),
      document_translation: defaultTranslationConfig(),
    });
    return;
  }
  if (req.method === "GET" && pathname === "/updates/status") {
    sendJson(req, res, 200, updateStatus(null));
    return;
  }
  if (req.method === "POST" && pathname === "/updates/check") {
    const body = await readJson(req);
    sendJson(req, res, 200, updateStatus(body.manifest || null));
    return;
  }
  if (req.method === "POST" && pathname === "/updates/install") {
    const result = await prepareUpdate(await readJson(req));
    sendJson(req, res, 200, result);
    if (result.restart_required && result.apply_script) {
      scheduleUpdateApply(result.apply_script);
    }
    return;
  }
  if (req.method === "GET" && pathname === "/settings/default-paths") {
    sendJson(req, res, 200, defaultPaths());
    return;
  }
  if (req.method === "GET" && pathname.startsWith("/settings/")) {
    const key = decodeURIComponent(pathname.slice("/settings/".length));
    sendJson(req, res, 200, { key, value: getSetting(key) ?? null });
    return;
  }
  if (req.method === "PUT" && pathname.startsWith("/settings/")) {
    const key = decodeURIComponent(pathname.slice("/settings/".length));
    const body = await readJson(req);
    sendJson(req, res, 200, { key, value: setSetting(key, body.value) });
    return;
  }
  if (req.method === "POST" && pathname === "/dialog/select-directory") {
    const body = await readJson(req);
    sendJson(req, res, 200, { path: await selectDirectory(body.currentPath) });
    return;
  }
  if (req.method === "POST" && pathname === "/dialog/select-file") {
    const body = await readJson(req);
    sendJson(req, res, 200, { path: await selectFile(body.currentPath) });
    return;
  }
  if (req.method === "POST" && pathname === "/shell/open-path") {
    const body = await readJson(req);
    await openPath(body.path);
    sendJson(req, res, 200, { ok: true });
    return;
  }
  if (req.method === "POST" && pathname === "/shell/open-containing-folder") {
    const body = await readJson(req);
    await openContainingFolder(body.path);
    sendJson(req, res, 200, { ok: true });
    return;
  }
  if (req.method === "POST" && pathname === "/filesystem/validate-path") {
    sendJson(req, res, 200, validatePath(await readJson(req)));
    return;
  }
  if (req.method === "GET" && pathname === "/document-translation/health") {
    sendJson(req, res, 200, await documentTranslationHealth());
    return;
  }
  if (req.method === "GET" && pathname === "/document-translation/models") {
    sendJson(req, res, 200, { models: listCodexModels() });
    return;
  }
  if (req.method === "POST" && pathname === "/document-translation/sheets") {
    const body = await readJson(req);
    sendJson(req, res, 200, {
      sheets: await judgeDocumentSheets({
        filePath: body.filePath ?? body.file_path,
        openXmlBaseUrl: body.openXmlBaseUrl ?? body.openxml_base_url,
      }),
    });
    return;
  }
  if (req.method === "POST" && pathname === "/document-translation/extract") {
    sendJson(req, res, 200, await extractDocumentText(await readJson(req)));
    return;
  }
  if (req.method === "POST" && pathname === "/document-translation/translate") {
    sendJson(req, res, 200, startDocumentTranslationJob(await readJson(req)));
    return;
  }
  if (req.method === "GET" && pathname.startsWith("/document-translation/jobs/")) {
    const jobId = decodeURIComponent(pathname.slice("/document-translation/jobs/".length));
    const job = getDocumentTranslationJob(jobId);
    if (!job) {
      sendJson(req, res, 404, { message: "Document translation job not found" });
      return;
    }
    sendJson(req, res, 200, job);
    return;
  }
  if (req.method === "POST" && pathname === "/build/start") {
    sendJson(req, res, 200, startBuildJob(await readJson(req)));
    return;
  }
  if (req.method === "GET" && pathname.startsWith("/build/jobs/")) {
    const jobId = decodeURIComponent(pathname.slice("/build/jobs/".length));
    const job = getBuildJob(jobId);
    if (!job) {
      sendJson(req, res, 404, { message: "Build job not found" });
      return;
    }
    sendJson(req, res, 200, job);
    return;
  }
  if (req.method === "POST" && pathname === "/git-eol/working-tree/preview") {
    sendJson(req, res, 200, previewWorkingTree(await readJson(req)));
    return;
  }
  if (req.method === "POST" && pathname === "/git-eol/working-tree/structured-diff") {
    sendJson(req, res, 200, structuredDiff(await readJson(req)));
    return;
  }
  if (req.method === "POST" && pathname === "/git-eol/working-tree/fix") {
    sendJson(req, res, 200, fixWorkingTree(await readJson(req)));
    return;
  }
  if (req.method === "POST" && pathname === "/git-eol/working-tree/commit") {
    sendJson(req, res, 200, commitWorkingTree(await readJson(req)));
    return;
  }
  if (req.method === "POST" && pathname === "/git-eol/working-tree/push") {
    sendJson(req, res, 200, pushWorkingTree(await readJson(req)));
    return;
  }

  sendJson(req, res, 404, { message: "Endpoint not found" });
}

server = http.createServer((req, res) => {
  route(req, res).catch((error) => sendError(req, res, error.message === "Request body is too large" ? 413 : 500, error));
});

server.listen(port, host, () => {
  const versionInfo = localServerVersion();
  console.log(`Contrack Node processing server ${versionInfo.version} listening at http://${host}:${port}`);
  if (versionInfo.commit_sha) {
    console.log(`Build commit: ${versionInfo.commit_sha}`);
  }
  void bootstrapCodexCli({ logger: console }).catch((error) => {
    console.warn(`Codex CLI bootstrap failed: ${error && error.message ? error.message : String(error)}`);
  });
});
