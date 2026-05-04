const path = require("node:path");
const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { apiFetch } = require("./api-proxy.cjs");
const { getBuildJob, startBuildJob } = require("./build-source.cjs");
const {
  commitWorkingTree,
  fixWorkingTree,
  previewWorkingTree,
  pushWorkingTree,
  structuredDiff,
} = require("./git-eol-local.cjs");
const { defaultPaths, getSetting, readSettings, setSetting } = require("./settings.cjs");

let mainWindow = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1100,
    minHeight: 720,
    title: "Contrack",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });

  const devUrl = process.env.ELECTRON_RENDERER_URL;
  if (devUrl) {
    mainWindow.loadURL(devUrl);
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

function registerIpc() {
  ipcMain.handle("app:get-version", () => app.getVersion());
  ipcMain.handle("settings:all", () => readSettings());
  ipcMain.handle("settings:get", (_event, key) => getSetting(key));
  ipcMain.handle("settings:set", (_event, key, value) => setSetting(key, value));
  ipcMain.handle("settings:default-paths", () => defaultPaths());
  ipcMain.handle("dialog:select-directory", async (_event, currentPath) => {
    const result = await dialog.showOpenDialog(mainWindow, {
      title: "Select folder",
      defaultPath: currentPath || undefined,
      properties: ["openDirectory", "createDirectory"],
    });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("shell:open-path", async (_event, targetPath) => {
    if (!targetPath) return;
    if (/^https?:\/\//i.test(String(targetPath))) {
      await shell.openExternal(String(targetPath));
      return;
    }
    const normalized = path.resolve(String(targetPath));
    const fs = require("node:fs");
    if (fs.existsSync(normalized) && fs.statSync(normalized).isFile()) {
      shell.showItemInFolder(normalized);
      return;
    }
    await shell.openPath(normalized);
  });
  ipcMain.handle("api:fetch", (_event, request) => apiFetch(request));
  ipcMain.handle("build:start", (_event, payload) => startBuildJob(payload));
  ipcMain.handle("build:get-job", (_event, jobId) => getBuildJob(jobId));
  ipcMain.handle("git-eol:preview-working-tree", (_event, payload) => previewWorkingTree(payload));
  ipcMain.handle("git-eol:structured-diff", (_event, payload) => structuredDiff(payload));
  ipcMain.handle("git-eol:fix-working-tree", (_event, payload) => fixWorkingTree(payload));
  ipcMain.handle("git-eol:commit-working-tree", (_event, payload) => commitWorkingTree(payload));
  ipcMain.handle("git-eol:push-working-tree", (_event, payload) => pushWorkingTree(payload));
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });
  app.whenReady().then(() => {
    registerIpc();
    createWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      }
    });
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
