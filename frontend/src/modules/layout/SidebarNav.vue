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
  logout: [];
}>();

function isActiveTab(currentTab: string, tabKey: string) {
  return currentTab === tabKey || currentTab.startsWith(`${tabKey}/`);
}
</script>

<template>
  <header class="border-b border-neutral-200 bg-white">
    <div class="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-4 sm:px-6 lg:px-8">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div class="flex items-center justify-between gap-4">
          <div>
            <p class="m-0 text-lg font-semibold tracking-[0.06em] text-[#171A20] uppercase">Contrack</p>
          </div>
          <button
            class="rounded-lg border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100 lg:hidden"
            @click="emit('logout')"
          >
            Logout
          </button>
        </div>
        <div class="flex items-center gap-3">
          <div class="relative">
            <button class="rounded-xl border border-neutral-200 bg-neutral-50 px-4 py-2 text-left" @click="emit('toggleUserMenu')">
              <p class="text-sm font-medium text-[#171A20]">{{ me.username }}</p>
            </button>
            <div v-if="userMenuOpen" class="absolute right-0 z-10 mt-2 w-40 overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-lg">
              <button class="block w-full px-4 py-2 text-left text-sm text-[#171A20] transition hover:bg-neutral-50" @click="emit('settings')">Settings</button>
              <button class="block w-full px-4 py-2 text-left text-sm text-[#171A20] transition hover:bg-neutral-50" @click="emit('logout')">Logout</button>
            </div>
          </div>
        </div>
      </div>
      <nav class="flex flex-wrap gap-2">
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
    </div>
  </header>
</template>
