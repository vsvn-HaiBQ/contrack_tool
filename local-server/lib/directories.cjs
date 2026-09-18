const fs = require("node:fs");
const path = require("node:path");

function ensureDirectory(directory) {
  // Windows can reject mkdir('C:\\', { recursive: true }) even though it exists.
  // Cloning into C:\repo needs that existing parent, not a mkdir on the drive.
  try {
    if (!fs.statSync(directory).isDirectory()) {
      throw new Error(`Path is not a directory: ${directory}`);
    }
    return;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  fs.mkdirSync(directory, { recursive: true });
}

function resolveWorkDirectory(value, label) {
  const raw = String(value || "").trim();
  if (!raw) throw new Error(`${label} is required`);
  const resolved = path.resolve(raw);
  if (resolved === path.parse(resolved).root || /^[A-Za-z]:$/.test(raw)) {
    throw new Error(`${label} must be a folder below the drive or share root`);
  }
  return resolved;
}

module.exports = { ensureDirectory, resolveWorkDirectory };
