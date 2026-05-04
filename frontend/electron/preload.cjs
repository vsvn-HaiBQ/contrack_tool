const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("contrackElectron", {
  isElectron: true,
  getVersion: () => ipcRenderer.invoke("app:get-version"),
  getAllSettings: () => ipcRenderer.invoke("settings:all"),
  getSetting: (key) => ipcRenderer.invoke("settings:get", key),
  setSetting: (key, value) => ipcRenderer.invoke("settings:set", key, value),
  getDefaultPaths: () => ipcRenderer.invoke("settings:default-paths"),
  selectDirectory: (currentPath) => ipcRenderer.invoke("dialog:select-directory", currentPath),
  openPath: (targetPath) => ipcRenderer.invoke("shell:open-path", targetPath),
  apiFetch: (path, init) => ipcRenderer.invoke("api:fetch", { path, init }),
  build: {
    start: (payload) => ipcRenderer.invoke("build:start", payload),
    getJob: (jobId) => ipcRenderer.invoke("build:get-job", jobId),
  },
  gitEol: {
    previewWorkingTree: (payload) => ipcRenderer.invoke("git-eol:preview-working-tree", payload),
    structuredDiff: (payload) => ipcRenderer.invoke("git-eol:structured-diff", payload),
    fixWorkingTree: (payload) => ipcRenderer.invoke("git-eol:fix-working-tree", payload),
    commitWorkingTree: (payload) => ipcRenderer.invoke("git-eol:commit-working-tree", payload),
    pushWorkingTree: (payload) => ipcRenderer.invoke("git-eol:push-working-tree", payload),
  },
});
