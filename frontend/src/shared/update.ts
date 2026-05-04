import { ref } from "vue";
import { updatesApi } from "../modules/updates/api";
import type { ClientUpdateInfo } from "./types";
import { electronApi } from "./electron";

export const updateInfo = ref<ClientUpdateInfo | null>(null);
export const checkingUpdate = ref(false);

export async function currentClientVersion() {
  const api = electronApi();
  if (api) {
    return api.getVersion();
  }
  return import.meta.env.VITE_APP_VERSION || "0.1.0";
}

export async function checkClientUpdate() {
  checkingUpdate.value = true;
  try {
    const version = await currentClientVersion();
    updateInfo.value = await updatesApi.check(version);
    return updateInfo.value;
  } finally {
    checkingUpdate.value = false;
  }
}
