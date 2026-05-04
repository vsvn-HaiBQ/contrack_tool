<script setup lang="ts">
import type { User } from "../../shared/types";

defineProps<{
  me: User;
  tabs: Array<{ key: string; label: string }>;
  currentTab: string;
  userMenuOpen: boolean;
}>();

const emit = defineEmits<{
  select: [value: string];
  toggleUserMenu: [];
  settings: [];
  checkUpdate: [];
  logout: [];
}>();

function isActiveTab(currentTab: string, tabKey: string) {
  return currentTab === tabKey || currentTab.startsWith(`${tabKey}/`);
}
</script>

<template>
  <header class="sticky top-0 z-20 border-b border-neutral-200 bg-white/95 backdrop-blur">
    <div class="mx-auto flex w-full max-w-none items-center justify-between gap-3 px-4 py-2 sm:px-6">
      <nav class="flex min-w-0 flex-1 flex-wrap gap-2">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="rounded-lg px-4 py-2 text-sm font-medium transition-colors duration-200"
          :class="isActiveTab(currentTab, tab.key) ? 'bg-[#3E6AE1] text-white' : 'bg-neutral-100 text-[#393C41] hover:bg-neutral-200'"
          @click="emit('select', tab.key)"
        >
          {{ tab.label }}
        </button>
      </nav>
      <div class="relative shrink-0">
        <button class="rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-2 text-left" @click="emit('toggleUserMenu')">
          <p class="text-sm font-medium text-[#171A20]">{{ me.username }}</p>
        </button>
        <div v-if="userMenuOpen" class="absolute right-0 z-30 mt-2 w-40 overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-lg">
          <button class="block w-full px-4 py-2 text-left text-sm text-[#171A20] transition hover:bg-neutral-50" @click="emit('settings')">Settings</button>
          <button class="block w-full px-4 py-2 text-left text-sm text-[#171A20] transition hover:bg-neutral-50" @click="emit('checkUpdate')">Check Update</button>
          <button class="block w-full px-4 py-2 text-left text-sm text-[#171A20] transition hover:bg-neutral-50" @click="emit('logout')">Logout</button>
        </div>
      </div>
    </div>
  </header>
</template>
