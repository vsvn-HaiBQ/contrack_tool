const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const zlib = require("node:zlib");
const { execFileSync } = require("node:child_process");

const repoRoot = path.resolve(__dirname, "..", "..");
const outputRoot = path.resolve(process.env.CONTRACK_BUILD_OUTPUT || path.join(repoRoot, "build_output"));
const localServerOut = path.join(outputRoot, "local-server");
const releaseOut = path.join(outputRoot, "releases", "local-server");
const expectedRoot = outputRoot;
const staleLocalServerWebOut = path.join(localServerOut, "web");
const staleTrayLauncher = path.join(localServerOut, "tray-launcher.ps1");
const webOut = path.join(outputRoot, "web");
const bundleFormat = "contrack-local-server-bundle-v1";

function assertInsideOutput(target) {
  const relative = path.relative(expectedRoot, target);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`Refusing to write outside build_output: ${target}`);
  }
}

function copyFile(from, to) {
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.copyFileSync(from, to);
}

function copyDirectory(from, to) {
  fs.mkdirSync(to, { recursive: true });
  for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
    const source = path.join(from, entry.name);
    const target = path.join(to, entry.name);
    if (entry.isDirectory()) {
      copyDirectory(source, target);
    } else if (entry.isFile()) {
      copyFile(source, target);
    }
  }
}

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return {};
  }
}

function safeVersion(value) {
  const version = String(value || "").trim().replace(/[^0-9A-Za-z._-]/g, "-");
  return version || "0.1.0-dev";
}

function localServerVersion() {
  return safeVersion(
    process.env.CONTRACK_LOCAL_SERVER_VERSION ||
      readJson(path.join(repoRoot, "package.json")).version ||
      readJson(path.join(repoRoot, "frontend", "package.json")).version ||
      "0.1.0-dev"
  );
}

function gitCommitSha() {
  try {
    return execFileSync("git", ["rev-parse", "--short=12", "HEAD"], {
      cwd: repoRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return "";
  }
}

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function listFiles(root, current = root) {
  const files = [];
  for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
    const source = path.join(current, entry.name);
    if (entry.isDirectory()) {
      files.push(...listFiles(root, source));
    } else if (entry.isFile()) {
      files.push(path.relative(root, source).replace(/\\/g, "/"));
    }
  }
  return files.sort((a, b) => a.localeCompare(b));
}

function createReleaseBundle(version, createdAt, commitSha) {
  fs.mkdirSync(releaseOut, { recursive: true });
  const files = listFiles(localServerOut).map((relativePath) => {
    const content = fs.readFileSync(path.join(localServerOut, ...relativePath.split("/")));
    return {
      path: relativePath,
      sha256: sha256(content),
      size_bytes: content.length,
      content_base64: content.toString("base64"),
    };
  });
  const bundle = {
    format: bundleFormat,
    version,
    created_at: createdAt,
    commit_sha: commitSha,
    files,
  };
  const bundleBuffer = zlib.gzipSync(Buffer.from(JSON.stringify(bundle), "utf8"), { level: 9 });
  const packageFile = `contrack-local-server-${version}.bundle.json.gz`;
  const packagePath = path.join(releaseOut, packageFile);
  fs.writeFileSync(packagePath, bundleBuffer);

  const manifest = {
    service: "contrack-local-node",
    format: bundleFormat,
    version,
    created_at: createdAt,
    commit_sha: commitSha,
    package_file: packageFile,
    package_size_bytes: bundleBuffer.length,
    package_sha256: sha256(bundleBuffer),
    download_url: `/api/local-server/releases/${encodeURIComponent(version)}/download`,
  };
  fs.writeFileSync(path.join(releaseOut, "latest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  return manifest;
}

assertInsideOutput(localServerOut);
assertInsideOutput(webOut);
assertInsideOutput(staleLocalServerWebOut);
assertInsideOutput(staleTrayLauncher);
assertInsideOutput(releaseOut);
fs.mkdirSync(localServerOut, { recursive: true });
fs.rmSync(staleLocalServerWebOut, { recursive: true, force: true });
fs.rmSync(staleTrayLauncher, { force: true });

copyFile(path.join(repoRoot, "local-server", "server.cjs"), path.join(localServerOut, "server.cjs"));

const libOut = path.join(localServerOut, "lib");
for (const file of ["build-source.cjs", "codex-translation.cjs", "git-eol-local.cjs", "openxml-client.cjs", "settings.cjs", "updater.cjs", "version.cjs"]) {
  copyFile(path.join(repoRoot, "local-server", "lib", file), path.join(libOut, file));
}

copyDirectory(path.join(repoRoot, "build"), path.join(localServerOut, "build"));

const frontendDist = path.join(repoRoot, "frontend", "dist");
const webSource = [
  frontendDist,
  webOut,
].find((candidate) => fs.existsSync(path.join(candidate, "index.html")));

if (webSource) {
  if (path.resolve(webSource) !== path.resolve(webOut)) {
    copyDirectory(webSource, webOut);
  }
}

fs.writeFileSync(
  path.join(localServerOut, "start-local-server.bat"),
  [
    "@echo off",
    "cd /d \"%~dp0\"",
    "if \"%CONTRACK_LOCAL_SERVER_HOST%\"==\"\" set CONTRACK_LOCAL_SERVER_HOST=127.0.0.1",
    "if \"%CONTRACK_LOCAL_SERVER_PORT%\"==\"\" set CONTRACK_LOCAL_SERVER_PORT=3219",
    "for /f \"usebackq delims=\" %%v in (`node -p \"try{require('./version.json').version}catch(e){'dev'}\"`) do set \"CONTRACK_LOCAL_SERVER_VERSION_DISPLAY=%%v\"",
    "title Contrack Node processing server",
    "echo Contrack Node processing server",
    "echo Version: %CONTRACK_LOCAL_SERVER_VERSION_DISPLAY%",
    "echo Host: %CONTRACK_LOCAL_SERVER_HOST%",
    "echo Port: %CONTRACK_LOCAL_SERVER_PORT%",
    "echo.",
    "echo Press Ctrl+C to stop the server.",
    "echo.",
    ":run",
    "set CONTRACK_RESTART_HANDLED_BY_LAUNCHER=1",
    "node server.cjs",
    "set \"EXIT_CODE=%ERRORLEVEL%\"",
    "if \"%EXIT_CODE%\"==\"75\" (",
    "  echo.",
    "  echo Applying local server update and restarting...",
    "  timeout /t 8 /nobreak >nul",
    "  goto run",
    ")",
    "echo.",
    "echo Node processing server stopped with exit code %EXIT_CODE%.",
    "pause",
    "exit /b %EXIT_CODE%",
    "",
  ].join("\r\n"),
  "utf8"
);

const version = localServerVersion();
const createdAt = new Date().toISOString();
const commitSha = gitCommitSha();
fs.writeFileSync(
  path.join(localServerOut, "version.json"),
  `${JSON.stringify(
    {
      service: "contrack-local-node",
      version,
      created_at: createdAt,
      commit_sha: commitSha,
    },
    null,
    2
  )}\n`,
  "utf8"
);

const releaseManifest = createReleaseBundle(version, createdAt, commitSha);

console.log(`Local server build written to ${localServerOut}`);
console.log(`Local server release written to ${path.join(releaseOut, releaseManifest.package_file)}`);
if (webSource) {
  console.log(`Web build copied to ${webOut}`);
}
