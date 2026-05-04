const fs = require("node:fs");
const path = require("node:path");

const updaterVersion = "1";

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return {};
  }
}

function cleanVersion(value) {
  const version = String(value || "").trim();
  return version || "0.1.0-dev";
}

function localServerVersion() {
  const packaged = readJson(path.join(__dirname, "..", "version.json"));
  const rootPackage = readJson(path.join(__dirname, "..", "..", "package.json"));
  const frontendPackage = readJson(path.join(__dirname, "..", "..", "frontend", "package.json"));
  return {
    service: "contrack-local-node",
    version: cleanVersion(process.env.CONTRACK_LOCAL_SERVER_VERSION || packaged.version || rootPackage.version || frontendPackage.version),
    created_at: packaged.created_at || null,
    commit_sha: packaged.commit_sha || null,
    updater_version: updaterVersion,
  };
}

module.exports = {
  localServerVersion,
  updaterVersion,
};
