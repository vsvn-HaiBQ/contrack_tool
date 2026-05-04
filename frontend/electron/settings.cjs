const fs = require("node:fs");
const path = require("node:path");
const { app } = require("electron");

let cachedSettings = null;

function settingsFile() {
  return path.join(app.getPath("userData"), "settings.json");
}

function appRoot() {
  if (app.isPackaged) {
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

function getApiBaseUrl() {
  return process.env.CONTRACK_API_BASE || process.env.VITE_API_BASE || "http://localhost:8009/api";
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
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "build");
  }
  return path.resolve(__dirname, "..", "..", "build");
}

module.exports = {
  appRoot,
  defaultPaths,
  getApiBaseUrl,
  getBuildToolDir,
  getSetting,
  readSettings,
  setSetting,
  writeSettings,
};
