const fs = require("node:fs");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "..", "..");
const outputRoot = path.resolve(process.env.CONTRACK_BUILD_OUTPUT || path.join(repoRoot, "build_output"));
const localServerOut = path.join(outputRoot, "local-server");
const expectedRoot = path.join(repoRoot, "build_output");
const staleLocalServerWebOut = path.join(localServerOut, "web");
const staleTrayLauncher = path.join(localServerOut, "tray-launcher.ps1");
const webOut = path.join(outputRoot, "web");

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

assertInsideOutput(localServerOut);
assertInsideOutput(webOut);
assertInsideOutput(staleLocalServerWebOut);
assertInsideOutput(staleTrayLauncher);
fs.mkdirSync(localServerOut, { recursive: true });
fs.rmSync(staleLocalServerWebOut, { recursive: true, force: true });
fs.rmSync(staleTrayLauncher, { force: true });

copyFile(path.join(repoRoot, "local-server", "server.cjs"), path.join(localServerOut, "server.cjs"));

const libOut = path.join(localServerOut, "lib");
for (const file of ["build-source.cjs", "git-eol-local.cjs", "settings.cjs"]) {
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
    "title Contrack Node processing server",
    "echo Contrack Node processing server",
    "echo Host: %CONTRACK_LOCAL_SERVER_HOST%",
    "echo Port: %CONTRACK_LOCAL_SERVER_PORT%",
    "echo.",
    "echo Press Ctrl+C to stop the server.",
    "echo.",
    "node server.cjs",
    "set \"EXIT_CODE=%ERRORLEVEL%\"",
    "echo.",
    "echo Node processing server stopped with exit code %EXIT_CODE%.",
    "pause",
    "exit /b %EXIT_CODE%",
    "",
  ].join("\r\n"),
  "utf8"
);

console.log(`Local server build written to ${localServerOut}`);
if (webSource) {
  console.log(`Web build copied to ${webOut}`);
}
