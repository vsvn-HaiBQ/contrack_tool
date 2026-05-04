<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterView, useRouter } from "vue-router";
import SidebarNav from "./SidebarNav.vue";
import { authApi } from "../auth/api";
import { clearSession, hasRequiredRedmineKeys, sessionState } from "../../shared/session";
import { localServerApi, localServerBase } from "../../shared/localServer";
import { showToast } from "../../shared/toast";

const router = useRouter();
const userMenuOpen = ref(false);
const nodeServerOnline = ref(false);
const nodeServerChecked = ref(false);
let nodeHealthTimer: number | null = null;

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
const nodeServerWarning = computed(() =>
  nodeServerChecked.value && !nodeServerOnline.value
    ? `Node server offline: ${localServerBase}. Local tools hidden.`
    : null
);

function fallbackRoute() {
  return hasRequiredRedmineKeys() ? { name: "detail" } : { name: "settings" };
}

async function refreshNodeServerStatus() {
  try {
    const health = await localServerApi.health();
    nodeServerOnline.value = Boolean(health.ok);
  } catch {
    nodeServerOnline.value = false;
  } finally {
    nodeServerChecked.value = true;
  }

  if (!nodeServerOnline.value && nodeOnlyRoutes.has(router.currentRoute.value.path)) {
    await router.replace(fallbackRoute());
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
      @select="$router.push($event)"
      @toggle-user-menu="userMenuOpen = !userMenuOpen"
      @close-user-menu="userMenuOpen = false"
      @settings="goSettings"
      @logout="logout"
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
