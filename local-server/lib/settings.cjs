const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

let cachedSettings = null;

function settingsFile() {
  const dataDir = process.env.CONTRACK_LOCAL_DATA_DIR || path.join(os.homedir(), ".contrack-client");
  return path.join(dataDir, "settings.json");
}

function appRoot() {
  if (process.pkg) {
    return path.dirname(process.execPath);
  }
  return path.resolve(__dirname, "..");
}

function defaultPaths() {
  const root = appRoot();
  return {
    sourceFolder: path.join(root, "source"),
    buildFolder: path.join(root, "build"),
  };
}

function defaults() {
  const paths = defaultPaths();
  return {
    paths: {
      gitEolSourceFolder: "",
      gitEolBranchSourceFolder: "",
      buildSourceFolder: paths.sourceFolder,
      buildOutputFolder: paths.buildFolder,
    },
    cookies: {},
  };
}

function mergeDefaults(value) {
  const base = defaults();
  const { apiBaseUrl: _ignoredApiBaseUrl, ...stored } = value || {};
  return {
    ...base,
    ...stored,
    paths: {
      ...base.paths,
      ...((stored && stored.paths) || {}),
    },
    cookies: {
      ...base.cookies,
      ...((stored && stored.cookies) || {}),
    },
  };
}

function readSettings() {
  if (cachedSettings) {
    return cachedSettings;
  }
  try {
    const raw = fs.readFileSync(settingsFile(), "utf8");
    cachedSettings = mergeDefaults(JSON.parse(raw));
  } catch {
    cachedSettings = defaults();
  }
  return cachedSettings;
}

function writeSettings(next) {
  cachedSettings = mergeDefaults(next);
  fs.mkdirSync(path.dirname(settingsFile()), { recursive: true });
  fs.writeFileSync(settingsFile(), JSON.stringify(cachedSettings, null, 2), "utf8");
  return cachedSettings;
}

function getByPath(object, key) {
  return key.split(".").reduce((current, part) => {
    if (!current || typeof current !== "object") {
      return undefined;
    }
    return current[part];
  }, object);
}

function setByPath(object, key, value) {
  const parts = key.split(".");
  let current = object;
  for (const part of parts.slice(0, -1)) {
    if (!current[part] || typeof current[part] !== "object") {
      current[part] = {};
    }
    current = current[part];
  }
  current[parts[parts.length - 1]] = value;
}

function getSetting(key) {
  return getByPath(readSettings(), key);
}

function setSetting(key, value) {
  const next = readSettings();
  setByPath(next, key, value);
  writeSettings(next);
  return value;
}

function getBuildToolDir() {
  if (process.env.CONTRACK_BUILD_TOOL_DIR) {
    return path.resolve(process.env.CONTRACK_BUILD_TOOL_DIR);
  }
  if (process.pkg) {
    return path.join(path.dirname(process.execPath), "build");
  }
  const candidates = [
    path.resolve(__dirname, "..", "build"),
    path.resolve(__dirname, "..", "..", "build"),
    path.resolve(process.cwd(), "build"),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) || candidates[1];
}

module.exports = {
  appRoot,
  defaultPaths,
  getBuildToolDir,
  getSetting,
  readSettings,
  setSetting,
  writeSettings,
};
