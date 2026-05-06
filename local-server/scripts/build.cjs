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

const crcTable = (() => {
  const table = new Uint32Array(256);
  for (let index = 0; index < 256; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) {
      value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[index] = value >>> 0;
  }
  return table;
})();

function crc32(buffer) {
  let value = 0xffffffff;
  for (const byte of buffer) {
    value = crcTable[(value ^ byte) & 0xff] ^ (value >>> 8);
  }
  return (value ^ 0xffffffff) >>> 0;
}

function dosDateTime(date) {
  const year = Math.max(1980, date.getFullYear());
  const dosTime = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
  const dosDate = ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { dosDate, dosTime };
}

function writeUInt16(value) {
  const buffer = Buffer.allocUnsafe(2);
  buffer.writeUInt16LE(value);
  return buffer;
}

function writeUInt32(value) {
  const buffer = Buffer.allocUnsafe(4);
  buffer.writeUInt32LE(value >>> 0);
  return buffer;
}

function createZipArchive(entries, date = new Date()) {
  const localParts = [];
  const centralParts = [];
  const { dosDate, dosTime } = dosDateTime(date);
  let offset = 0;

  for (const entry of entries) {
    const nameBuffer = Buffer.from(entry.path.replace(/\\/g, "/"), "utf8");
    const content = entry.content;
    const checksum = crc32(content);
    const localHeader = Buffer.concat([
      writeUInt32(0x04034b50),
      writeUInt16(20),
      writeUInt16(0),
      writeUInt16(0),
      writeUInt16(dosTime),
      writeUInt16(dosDate),
      writeUInt32(checksum),
      writeUInt32(content.length),
      writeUInt32(content.length),
      writeUInt16(nameBuffer.length),
      writeUInt16(0),
      nameBuffer,
    ]);
    localParts.push(localHeader, content);
    centralParts.push(Buffer.concat([
      writeUInt32(0x02014b50),
      writeUInt16(20),
      writeUInt16(20),
      writeUInt16(0),
      writeUInt16(0),
      writeUInt16(dosTime),
      writeUInt16(dosDate),
      writeUInt32(checksum),
      writeUInt32(content.length),
      writeUInt32(content.length),
      writeUInt16(nameBuffer.length),
      writeUInt16(0),
      writeUInt16(0),
      writeUInt16(0),
      writeUInt16(0),
      writeUInt32(0),
      writeUInt32(offset),
      nameBuffer,
    ]));
    offset += localHeader.length + content.length;
  }

  const centralOffset = offset;
  const centralDirectory = Buffer.concat(centralParts);
  const endOfCentralDirectory = Buffer.concat([
    writeUInt32(0x06054b50),
    writeUInt16(0),
    writeUInt16(0),
    writeUInt16(entries.length),
    writeUInt16(entries.length),
    writeUInt32(centralDirectory.length),
    writeUInt32(centralOffset),
    writeUInt16(0),
  ]);
  return Buffer.concat([...localParts, centralDirectory, endOfCentralDirectory]);
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
  const packageRoot = `contrack-local-server-${version}`;
  const files = listFiles(localServerOut).map((relativePath) => {
    const content = fs.readFileSync(path.join(localServerOut, ...relativePath.split("/")));
    return {
      path: relativePath,
      content,
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
    files: files.map((file) => ({
      path: file.path,
      sha256: file.sha256,
      size_bytes: file.size_bytes,
      content_base64: file.content_base64,
    })),
  };
  const bundleBuffer = zlib.gzipSync(Buffer.from(JSON.stringify(bundle), "utf8"), { level: 9 });
  const packageFile = `contrack-local-server-${version}.bundle.json.gz`;
  const packagePath = path.join(releaseOut, packageFile);
  fs.writeFileSync(packagePath, bundleBuffer);

  const zipBuffer = createZipArchive(
    files.map((file) => ({
      path: `${packageRoot}/${file.path}`,
      content: file.content,
    })),
    new Date(createdAt)
  );
  const zipFile = `contrack-local-server-${version}.zip`;
  const zipPath = path.join(releaseOut, zipFile);
  fs.writeFileSync(zipPath, zipBuffer);

  const manifest = {
    service: "contrack-local-node",
    format: bundleFormat,
    version,
    created_at: createdAt,
    commit_sha: commitSha,
    package_file: packageFile,
    package_size_bytes: bundleBuffer.length,
    package_sha256: sha256(bundleBuffer),
    zip_file: zipFile,
    zip_size_bytes: zipBuffer.length,
    zip_sha256: sha256(zipBuffer),
    download_url: `/api/local-server/releases/${encodeURIComponent(version)}/download`,
    zip_download_url: `/api/local-server/releases/${encodeURIComponent(version)}/download-zip`,
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
for (const file of ["box-upload.cjs", "build-source.cjs", "codex-translation.cjs", "git-eol-local.cjs", "openxml-client.cjs", "settings.cjs", "updater.cjs", "version.cjs"]) {
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
console.log(`Local server zip written to ${path.join(releaseOut, releaseManifest.zip_file)}`);
if (webSource) {
  console.log(`Web build copied to ${webOut}`);
}
