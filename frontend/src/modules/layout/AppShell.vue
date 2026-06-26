<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterView, useRouter } from "vue-router";
import SidebarNav from "./SidebarNav.vue";
import { authApi } from "../auth/api";
import { clearSession, hasRequiredRedmineKeys, pinVersion, sessionState } from "../../shared/session";
import { localServerApi, localServerBase } from "../../shared/localServer";
import { absoluteBackendUrl, localServerReleaseApi } from "../../shared/localServerRelease";
import { showToast } from "../../shared/toast";
import type { LocalServerReleaseManifest } from "../../shared/types";

const router = useRouter();
const userMenuOpen = ref(false);
const nodeServerOnline = ref(false);
const nodeServerChecked = ref(false);
const nodeServerVersion = ref<string | null>(null);
const latestLocalServerRelease = ref<LocalServerReleaseManifest | null>(null);
const localServerUpdateAvailable = ref(false);
const localServerUpdaterUnavailable = ref(false);
const installingNodeUpdate = ref(false);
const downloadingNodeServer = ref(false);
let nodeHealthTimer: number | null = null;
let lastReleaseCheckAt = 0;

const tabs = [
  { key: "/tickets/detail", label: "Ticket Detail" },
  { key: "/tickets/sync", label: "Sync Ticket" },
  { key: "/pull-requests", label: "Create PR", hiddenForRoles: ["qa"] },
  { key: "/git-eol", label: "Fix EOL", requiresNode: true, hiddenForRoles: ["qa"] },
  { key: "/build-source", label: "Build Source", requiresNode: true, hiddenForRoles: ["qa"] },
  { key: "/confluence-preview", label: "Confluence Preview" },
  { key: "/document-translation", label: "Translate Docs", requiresNode: true },
  { key: "/logtime", label: "Logtime" },
  { key: "/notes", label: "Notes" },
  { key: "/audit", label: "Audit Logs", adminOnly: true },
];

const nodeOnlyRoutes = new Set(["/git-eol", "/build-source", "/document-translation"]);
function normalizedRole() {
  return String(sessionState.me?.role ?? "").trim().toLowerCase();
}

const visibleTabs = computed(() =>
  tabs.filter(
    (tab) =>
      (!tab.requiresNode || nodeServerOnline.value) &&
      (!tab.adminOnly || sessionState.me?.role === "admin") &&
      !(tab.hiddenForRoles ?? []).includes(normalizedRole())
  )
);
const nodeServerWarning = computed(() => {
  if (nodeServerChecked.value && !nodeServerOnline.value) {
    return `Node server offline: ${localServerBase}. Local tools hidden.`;
  }
  if (nodeServerOnline.value && localServerUpdaterUnavailable.value && latestLocalServerRelease.value) {
    return `Node updater unavailable. Install local server ${latestLocalServerRelease.value.version} manually once.`;
  }
  return null;
});
const nodeServerUpdate = computed(() =>
  nodeServerOnline.value && localServerUpdateAvailable.value && latestLocalServerRelease.value
    ? {
        currentVersion: nodeServerVersion.value,
        latestVersion: latestLocalServerRelease.value.version,
        installing: installingNodeUpdate.value
      }
    : null
);
const nodeServerDownload = computed(() =>
  nodeServerChecked.value && !nodeServerOnline.value && latestLocalServerRelease.value
    ? {
        latestVersion: latestLocalServerRelease.value.version,
        downloading: downloadingNodeServer.value
      }
    : null
);

function fallbackRoute() {
  return hasRequiredRedmineKeys() ? { name: "detail" } : { name: "settings" };
}

async function refreshNodeServerStatus() {
  try {
    const health = await localServerApi.health();
    nodeServerOnline.value = Boolean(health.ok);
    nodeServerVersion.value = health.version || null;
  } catch {
    nodeServerOnline.value = false;
    nodeServerVersion.value = null;
    localServerUpdateAvailable.value = false;
    localServerUpdaterUnavailable.value = false;
  } finally {
    nodeServerChecked.value = true;
  }

  await refreshLocalServerRelease();

  if (!nodeServerOnline.value && nodeOnlyRoutes.has(router.currentRoute.value.path)) {
    await router.replace(fallbackRoute());
  }
}

async function refreshLocalServerRelease(force = false) {
  const now = Date.now();
  if (!force && now - lastReleaseCheckAt < 60000) return;
  lastReleaseCheckAt = now;
  let latest: LocalServerReleaseManifest;
  try {
    latest = await localServerReleaseApi.latest();
  } catch {
    latestLocalServerRelease.value = null;
    localServerUpdateAvailable.value = false;
    localServerUpdaterUnavailable.value = false;
    return;
  }
  latestLocalServerRelease.value = latest;
  try {
    const check = await localServerApi.updates.check({ manifest: latest });
    nodeServerVersion.value = check.current_version || nodeServerVersion.value;
    localServerUpdateAvailable.value = Boolean(check.update_available);
    localServerUpdaterUnavailable.value = false;
  } catch {
    localServerUpdateAvailable.value = false;
    localServerUpdaterUnavailable.value = true;
  }
}

async function installNodeUpdate() {
  if (!latestLocalServerRelease.value || installingNodeUpdate.value) return;
  installingNodeUpdate.value = true;
  try {
    const manifest = latestLocalServerRelease.value;
    const ticket = await localServerReleaseApi.createDownloadTicket(manifest.version);
    const result = await localServerApi.updates.install({
      manifest,
      downloadUrl: absoluteBackendUrl(ticket.download_url),
      restart: true
    });
    showToast(result.message || "Node server update is restarting", "success");
    localServerUpdateAvailable.value = false;
    nodeServerOnline.value = false;
    window.setTimeout(() => void refreshNodeServerStatus(), 4000);
    window.setTimeout(() => void refreshNodeServerStatus(), 9000);
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    installingNodeUpdate.value = false;
  }
}

async function downloadNodeServerPackage() {
  if (!latestLocalServerRelease.value || downloadingNodeServer.value) return;
  downloadingNodeServer.value = true;
  try {
    const ticket = await localServerReleaseApi.createDownloadTicket(latestLocalServerRelease.value.version);
    const downloadUrl = ticket.zip_download_url || ticket.download_url;
    window.location.href = absoluteBackendUrl(downloadUrl);
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    downloadingNodeServer.value = false;
  }
}

async function logout() {
  await authApi.logout();
  clearSession();
  showToast("Logged out", "success");
  await router.replace({ name: "login" });
}

function goSettings() {
  userMenuOpen.value = false;
  router.push({ name: "settings" });
}

async function handlePinVersion(versionId: number | null) {
  try {
    await pinVersion(versionId);
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

onMounted(() => {
  void refreshNodeServerStatus();
  nodeHealthTimer = window.setInterval(() => void refreshNodeServerStatus(), 5000);
});

onBeforeUnmount(() => {
  if (nodeHealthTimer !== null) {
    window.clearInterval(nodeHealthTimer);
  }
});
</script>

<template>
  <div v-if="sessionState.me" class="min-h-screen bg-neutral-50">
    <SidebarNav
      :me="sessionState.me"
      :tabs="visibleTabs"
      :current-tab="$route.path"
      :user-menu-open="userMenuOpen"
      :node-server-warning="nodeServerWarning"
      :node-server-update="nodeServerUpdate"
      :node-server-download="nodeServerDownload"
      :versions="sessionState.versions"
      :pinned-version-id="sessionState.pinnedVersionId"
      @select="$router.push($event)"
      @toggle-user-menu="userMenuOpen = !userMenuOpen"
      @close-user-menu="userMenuOpen = false"
      @settings="goSettings"
      @logout="logout"
      @install-node-update="installNodeUpdate"
      @download-node-server="downloadNodeServerPackage"
      @pin-version="handlePinVersion"
    />
    <main
      class="mx-auto grid w-full max-w-7xl gap-8 px-4 py-6 sm:px-6 lg:px-8"
    >
      <RouterView v-slot="{ Component, route }">
        <KeepAlive>
          <component :is="Component" v-if="route.meta.keepAlive" :key="route.name ?? route.fullPath" />
        </KeepAlive>
        <component :is="Component" v-if="!route.meta.keepAlive" :key="route.fullPath" />
      </RouterView>
    </main>
  </div>
</template>
