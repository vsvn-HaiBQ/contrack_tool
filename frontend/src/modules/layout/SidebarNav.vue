<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import type { User, Version } from "../../shared/types";

const props = defineProps<{
  me: User;
  tabs: Array<{ key: string; label: string }>;
  currentTab: string;
  userMenuOpen: boolean;
  nodeServerWarning?: string | null;
  nodeServerUpdate?: { currentVersion?: string | null; latestVersion: string; installing: boolean } | null;
  nodeServerDownload?: { latestVersion: string; downloading: boolean } | null;
  versions?: Version[];
  pinnedVersionId?: number | null;
}>();

const emit = defineEmits<{
  select: [value: string];
  toggleUserMenu: [];
  closeUserMenu: [];
  settings: [];
  logout: [];
  installNodeUpdate: [];
  downloadNodeServer: [];
  pinVersion: [versionId: number | null];
}>();

const userMenuRef = ref<HTMLElement | null>(null);

function isActiveTab(currentTab: string, tabKey: string) {
  return currentTab === tabKey || currentTab.startsWith(`${tabKey}/`);
}

function closeUserMenuOnClickOutside(event: PointerEvent) {
  if (!props.userMenuOpen || !userMenuRef.value) return;
  const target = event.target;
  if (target instanceof Node && !userMenuRef.value.contains(target)) {
    emit("closeUserMenu");
  }
}

onMounted(() => {
  document.addEventListener("pointerdown", closeUserMenuOnClickOutside);
});

onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", closeUserMenuOnClickOutside);
});
</script>

<template>
  <header class="sticky top-0 z-20 border-b border-neutral-200 bg-white/95 backdrop-blur">
    <div class="mx-auto grid w-full max-w-none gap-2 px-4 py-2 sm:px-6">
      <div class="flex items-center justify-between gap-3">
        <button
          class="shrink-0 rounded-lg px-2 py-1 text-lg font-semibold text-[#171A20] transition hover:bg-neutral-100"
          @click="emit('select', '/tickets/detail')"
        >
          ConTrack
        </button>
        <div class="flex min-w-0 flex-1 items-center justify-end gap-3">
          <div v-if="(versions ?? []).length" class="flex items-center gap-2">
            <label class="whitespace-nowrap text-xs font-medium text-[#5C5E62]">Version</label>
            <select
              class="rounded-lg border border-neutral-200 bg-white px-2 py-1.5 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
              :value="pinnedVersionId ?? (versions && versions[0] ? versions[0].id : '')"
              @change="emit('pinVersion', Number(($event.target as HTMLSelectElement).value))"
            >
              <option v-for="version in versions" :key="version.id" :value="version.id">{{ version.name }}</option>
            </select>
          </div>
          <div ref="userMenuRef" class="relative shrink-0">
            <button class="rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-2 text-left" @click="emit('toggleUserMenu')">
              <p class="text-sm font-medium text-[#171A20]">{{ me.username }}</p>
            </button>
            <div v-if="userMenuOpen" class="absolute right-0 z-30 mt-2 w-40 overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-lg">
              <button class="block w-full px-4 py-2 text-left text-sm text-[#171A20] transition hover:bg-neutral-50" @click="emit('settings')">Settings</button>
              <button class="block w-full px-4 py-2 text-left text-sm text-[#171A20] transition hover:bg-neutral-50" @click="emit('logout')">Logout</button>
            </div>
          </div>
        </div>
      </div>
      <div class="flex min-w-0 items-center gap-2">
        <nav class="flex min-w-0 flex-1 gap-2 overflow-x-auto pb-1">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="shrink-0 rounded-lg px-4 py-2 text-sm font-medium transition-colors duration-200"
            :class="isActiveTab(currentTab, tab.key) ? 'bg-[#3E6AE1] text-white' : 'bg-neutral-100 text-[#393C41] hover:bg-neutral-200'"
            @click="emit('select', tab.key)"
          >
            {{ tab.label }}
          </button>
        </nav>
        <div v-if="nodeServerWarning" class="shrink-0 whitespace-nowrap rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900">
          {{ nodeServerWarning }}
        </div>
        <div v-if="nodeServerDownload" class="flex shrink-0 items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-900">
          <span class="whitespace-nowrap">Local server {{ nodeServerDownload.latestVersion }}</span>
          <button
            type="button"
            class="rounded bg-amber-700 px-2 py-1 text-white transition hover:bg-amber-800 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="nodeServerDownload.downloading"
            @click="emit('downloadNodeServer')"
          >
            {{ nodeServerDownload.downloading ? "Preparing" : "Download" }}
          </button>
        </div>
        <div v-if="nodeServerUpdate" class="flex shrink-0 items-center gap-2 rounded-md border border-sky-300 bg-sky-50 px-3 py-1.5 text-xs font-medium text-sky-900">
          <span class="whitespace-nowrap">
            Node {{ nodeServerUpdate.currentVersion || "unknown" }} -> {{ nodeServerUpdate.latestVersion }}
          </span>
          <button
            type="button"
            class="rounded bg-sky-700 px-2 py-1 text-white transition hover:bg-sky-800 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="nodeServerUpdate.installing"
            @click="emit('installNodeUpdate')"
          >
            {{ nodeServerUpdate.installing ? "Updating" : "Update" }}
          </button>
        </div>
      </div>
    </div>
  </header>
</template>
