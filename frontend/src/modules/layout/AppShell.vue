<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterView, useRouter } from "vue-router";
import SidebarNav from "./SidebarNav.vue";
import { authApi } from "../auth/api";
import { clearSession, hasRequiredRedmineKeys, sessionState } from "../../shared/session";
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
let nodeHealthTimer: number | null = null;
let lastReleaseCheckAt = 0;

const tabs = [
  { key: "/tickets/detail", label: "Ticket Detail" },
  { key: "/tickets/sync", label: "Sync Ticket" },
  { key: "/pull-requests", label: "Create PR" },
  { key: "/git-eol", label: "Fix EOL", requiresNode: true },
  { key: "/build-source", label: "Build Source", requiresNode: true },
  { key: "/document-translation", label: "Translate Docs", requiresNode: true },
  { key: "/logtime", label: "Logtime" },
];

const nodeOnlyRoutes = new Set(["/git-eol", "/build-source", "/document-translation"]);
const visibleTabs = computed(() => tabs.filter((tab) => !tab.requiresNode || nodeServerOnline.value));
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
    latestLocalServerRelease.value = null;
  } finally {
    nodeServerChecked.value = true;
  }

  if (nodeServerOnline.value) {
    await refreshLocalServerRelease();
  }

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
      @select="$router.push($event)"
      @toggle-user-menu="userMenuOpen = !userMenuOpen"
      @close-user-menu="userMenuOpen = false"
      @settings="goSettings"
      @logout="logout"
      @install-node-update="installNodeUpdate"
    />
    <main
      class="mx-auto grid w-full gap-8 px-4 py-6 sm:px-6 lg:px-8"
      :class="$route.path.startsWith('/git-eol') ? 'max-w-none' : 'max-w-7xl'"
    >
      <RouterView v-slot="{ Component }">
        <KeepAlive>
          <component :is="Component" />
        </KeepAlive>
      </RouterView>
    </main>
  </div>
</template>
