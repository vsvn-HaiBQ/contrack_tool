export function electronApi() {
  return window.contrackElectron ?? null;
}

export function isElectronClient() {
  return Boolean(window.contrackElectron?.isElectron);
}
