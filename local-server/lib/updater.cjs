const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const path = require("node:path");
const zlib = require("node:zlib");

const { localServerVersion, updaterVersion } = require("./version.cjs");

const bundleFormat = "contrack-local-server-bundle-v1";
const maxPackageBytes = 256 * 1024 * 1024;

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function parseVersion(value) {
  const match = String(value || "").trim().match(/^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?(.+))?$/);
  if (!match) {
    return null;
  }
  return {
    major: Number(match[1] || 0),
    minor: Number(match[2] || 0),
    patch: Number(match[3] || 0),
    prerelease: match[4] || "",
  };
}

function compareVersions(left, right) {
  if (left === right) return 0;
  const a = parseVersion(left);
  const b = parseVersion(right);
  if (!a || !b) {
    return String(left || "").localeCompare(String(right || ""));
  }
  for (const key of ["major", "minor", "patch"]) {
    if (a[key] !== b[key]) {
      return a[key] > b[key] ? 1 : -1;
    }
  }
  if (a.prerelease === b.prerelease) return 0;
  if (!a.prerelease) return 1;
  if (!b.prerelease) return -1;
  return a.prerelease.localeCompare(b.prerelease);
}

function updateStatus(manifest) {
  const current = localServerVersion();
  const latestVersion = manifest && typeof manifest.version === "string" ? manifest.version : "";
  const canCompare = Boolean(latestVersion && current.version);
  return {
    service: current.service,
    current_version: current.version,
    latest_version: latestVersion || null,
    update_available: canCompare ? compareVersions(latestVersion, current.version) > 0 : false,
    updater_version: updaterVersion,
    manifest: manifest || null,
  };
}

function safeRelativePath(input) {
  const raw = String(input || "").replace(/\\/g, "/");
  if (!raw || raw.includes("\0") || path.posix.isAbsolute(raw)) {
    throw new Error(`Invalid bundle path: ${input}`);
  }
  const normalized = path.posix.normalize(raw);
  if (normalized === "." || normalized.startsWith("../") || normalized.includes("/../")) {
    throw new Error(`Invalid bundle path: ${input}`);
  }
  return normalized;
}

function resolveInside(root, relativePath) {
  const clean = safeRelativePath(relativePath);
  const rootPath = path.resolve(root);
  const target = path.resolve(rootPath, ...clean.split("/"));
  const relative = path.relative(rootPath, target);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`Refusing path outside update root: ${relativePath}`);
  }
  return target;
}

function downloadBuffer(url, redirectCount = 0) {
  return new Promise((resolve, reject) => {
    if (redirectCount > 5) {
      reject(new Error("Too many redirects while downloading update"));
      return;
    }
    let parsed;
    try {
      parsed = new URL(url);
    } catch (error) {
      reject(new Error(`Update download URL is invalid: ${error.message}`));
      return;
    }
    if (!["http:", "https:"].includes(parsed.protocol)) {
      reject(new Error("Update download URL must use HTTP or HTTPS"));
      return;
    }
    const client = parsed.protocol === "https:" ? https : http;
    const request = client.get(
      parsed,
      {
        headers: {
          Accept: "application/gzip, application/octet-stream",
        },
      },
      (response) => {
        const status = response.statusCode || 0;
        if (status >= 300 && status < 400 && response.headers.location) {
          response.resume();
          const nextUrl = new URL(response.headers.location, parsed).toString();
          downloadBuffer(nextUrl, redirectCount + 1).then(resolve, reject);
          return;
        }
        if (status !== 200) {
          response.resume();
          reject(new Error(`Update download failed with HTTP ${status}`));
          return;
        }
        const chunks = [];
        let total = 0;
        response.on("data", (chunk) => {
          total += chunk.length;
          if (total > maxPackageBytes) {
            request.destroy(new Error("Update package is too large"));
            return;
          }
          chunks.push(chunk);
        });
        response.on("end", () => resolve(Buffer.concat(chunks)));
      }
    );
    request.setTimeout(120000, () => request.destroy(new Error("Update download timed out")));
    request.on("error", reject);
  });
}

function decodeBundle(buffer) {
  let payload;
  try {
    payload = zlib.gunzipSync(buffer);
  } catch (error) {
    throw new Error(`Update package is not a valid gzip bundle: ${error.message}`);
  }
  let bundle;
  try {
    bundle = JSON.parse(payload.toString("utf8"));
  } catch (error) {
    throw new Error(`Update bundle JSON is invalid: ${error.message}`);
  }
  if (!bundle || bundle.format !== bundleFormat || !Array.isArray(bundle.files)) {
    throw new Error("Update bundle format is not supported");
  }
  return bundle;
}

function stageBundle(bundle) {
  const appRoot = path.resolve(__dirname, "..");
  const stamp = `${Date.now()}-${String(bundle.version || "unknown").replace(/[^0-9A-Za-z._-]/g, "-")}`;
  const stageRoot = path.join(appRoot, ".updates", stamp);
  const stagedFilesRoot = path.join(stageRoot, "files");
  const relativeFiles = [];
  fs.mkdirSync(stagedFilesRoot, { recursive: true });

  for (const file of bundle.files) {
    const relativePath = safeRelativePath(file.path);
    const content = Buffer.from(String(file.content_base64 || ""), "base64");
    if (file.sha256 && sha256(content) !== file.sha256) {
      throw new Error(`Checksum mismatch inside update bundle: ${relativePath}`);
    }
    const target = resolveInside(stagedFilesRoot, relativePath);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content);
    relativeFiles.push(relativePath);
  }

  return {
    appRoot,
    stageRoot,
    stagedFilesRoot,
    relativeFiles,
  };
}

function updaterScript(options) {
  return `
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

const appRoot = ${JSON.stringify(options.appRoot)};
const stagedFilesRoot = ${JSON.stringify(options.stagedFilesRoot)};
const files = ${JSON.stringify(options.relativeFiles)};
const version = ${JSON.stringify(options.version)};
const logPath = path.join(appRoot, ".updates", "last-update.log");
const restartHandledByLauncher = process.env.CONTRACK_RESTART_HANDLED_BY_LAUNCHER === "1";

function log(message) {
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  fs.appendFileSync(logPath, \`[\${new Date().toISOString()}] \${message}\\n\`, "utf8");
}

function safeRelativePath(input) {
  const raw = String(input || "").replace(/\\\\/g, "/");
  if (!raw || raw.includes("\\0") || path.posix.isAbsolute(raw)) {
    throw new Error(\`Invalid update path: \${input}\`);
  }
  const normalized = path.posix.normalize(raw);
  if (normalized === "." || normalized.startsWith("../") || normalized.includes("/../")) {
    throw new Error(\`Invalid update path: \${input}\`);
  }
  return normalized;
}

function resolveInside(root, relativePath) {
  const clean = safeRelativePath(relativePath);
  const rootPath = path.resolve(root);
  const target = path.resolve(rootPath, ...clean.split("/"));
  const relative = path.relative(rootPath, target);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(\`Refusing path outside update root: \${relativePath}\`);
  }
  return target;
}

function isPidRunning(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForParent(pid) {
  const deadline = Date.now() + 30000;
  while (isPidRunning(pid) && Date.now() < deadline) {
    await sleep(250);
  }
}

function copyFile(from, to) {
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.copyFileSync(from, to);
}

function restoreBackup(backupRoot, copied) {
  for (const relativePath of copied.reverse()) {
    const backup = resolveInside(backupRoot, relativePath);
    const target = resolveInside(appRoot, relativePath);
    if (fs.existsSync(backup)) {
      copyFile(backup, target);
    }
  }
}

function startLocalServer() {
  if (restartHandledByLauncher) {
    log("Restart delegated to start-local-server.bat launcher");
    return;
  }

  const restartLogPath = path.join(appRoot, ".updates", "server-restart.log");
  fs.mkdirSync(path.dirname(restartLogPath), { recursive: true });
  const restartLog = fs.openSync(restartLogPath, "a");
  const child = spawn(process.execPath, ["server.cjs"], {
    cwd: appRoot,
    detached: true,
    stdio: ["ignore", restartLog, restartLog],
    windowsHide: false,
  });
  child.unref();
  log("Restart launched with direct node fallback");
}

async function main() {
  const parentPid = Number(process.argv[2] || 0);
  await waitForParent(parentPid);
  const backupRoot = path.join(appRoot, ".update-backups", \`\${Date.now()}-pre-\${version}\`);
  const copied = [];
  fs.mkdirSync(backupRoot, { recursive: true });
  log(\`Applying local server update \${version}\`);
  try {
    for (const relativePath of files) {
      const source = resolveInside(stagedFilesRoot, relativePath);
      const target = resolveInside(appRoot, relativePath);
      if (fs.existsSync(target)) {
        copyFile(target, resolveInside(backupRoot, relativePath));
      }
      copyFile(source, target);
      copied.push(relativePath);
    }
  } catch (error) {
    log(\`Update failed, restoring backup: \${error.message}\`);
    restoreBackup(backupRoot, copied);
    throw error;
  }
  startLocalServer();
  log(\`Local server updated to \${version} and restarted\`);
}

main().catch((error) => {
  log(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
`.trimStart();
}

async function prepareUpdate(input) {
  const manifest = input && typeof input.manifest === "object" ? input.manifest : null;
  if (!manifest || manifest.format !== bundleFormat || !manifest.version) {
    throw new Error("Update manifest is missing or unsupported");
  }
  const downloadUrl = String(input.downloadUrl || input.download_url || "").trim();
  if (!downloadUrl) {
    throw new Error("Update download URL is required");
  }
  const current = localServerVersion();
  const packageBuffer = await downloadBuffer(downloadUrl);
  if (manifest.package_sha256 && sha256(packageBuffer) !== manifest.package_sha256) {
    throw new Error("Update package checksum does not match the release manifest");
  }
  const bundle = decodeBundle(packageBuffer);
  if (bundle.version !== manifest.version) {
    throw new Error(`Update bundle version ${bundle.version} does not match manifest version ${manifest.version}`);
  }
  const staged = stageBundle(bundle);
  const applyScript = path.join(staged.stageRoot, "apply-update.cjs");
  fs.writeFileSync(
    applyScript,
    updaterScript({
      appRoot: staged.appRoot,
      stagedFilesRoot: staged.stagedFilesRoot,
      relativeFiles: staged.relativeFiles,
      version: manifest.version,
    }),
    "utf8"
  );
  return {
    status: "staged",
    service: current.service,
    current_version: current.version,
    version: manifest.version,
    staged_path: staged.stageRoot,
    apply_script: applyScript,
    restart_required: input.restart !== false,
    message: "Update package staged; local server will restart to apply it.",
  };
}

module.exports = {
  bundleFormat,
  compareVersions,
  prepareUpdate,
  updateStatus,
  updaterVersion,
};
