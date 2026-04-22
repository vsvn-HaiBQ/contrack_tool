<script setup lang="ts">
import { ref } from "vue";
import { RouterView, useRouter } from "vue-router";
import SidebarNav from "./SidebarNav.vue";
import { authApi } from "../auth/api";
import { clearSession, sessionState } from "../../shared/session";
import { showToast } from "../../shared/toast";

const router = useRouter();
const userMenuOpen = ref(false);

const tabs = [
  { key: "/tickets/detail", label: "Ticket Detail" },
  { key: "/tickets/sync", label: "Sync Ticket" },
  { key: "/pull-requests", label: "Create PR" },
  { key: "/logtime", label: "Logtime" },
];

function visibleTabs() {
  return tabs;
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
</script>

<template>
  <div v-if="sessionState.me" class="min-h-screen bg-neutral-50">
    <SidebarNav
      :me="sessionState.me"
      :tabs="visibleTabs()"
      :current-tab="$route.path"
      :user-menu-open="userMenuOpen"
      @select="$router.push($event)"
      @toggle-user-menu="userMenuOpen = !userMenuOpen"
      @settings="goSettings"
      @logout="logout"
    />
    <main class="mx-auto grid w-full max-w-7xl gap-8 px-4 py-6 sm:px-6 lg:px-8">
      <RouterView />
    </main>
  </div>
</template>
