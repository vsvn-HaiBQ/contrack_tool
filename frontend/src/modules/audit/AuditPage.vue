<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { auditApi, type AuditFilters } from "./api";
import LoadingCircle from "../../shared/LoadingCircle.vue";
import { showToast } from "../../shared/toast";
import type { AuditLog } from "../../shared/types";

const loading = ref(false);
const deleting = ref(false);
const rows = ref<AuditLog[]>([]);
const total = ref(0);
const payloadModal = ref<{ title: string; payload: string } | null>(null);
const options = reactive({
  actions: [] as string[],
  actor_usernames: [] as string[],
  target_types: [] as string[]
});
const selectedIds = reactive<Record<number, boolean>>({});
const filters = reactive({
  action: "",
  actor_username: "",
  target_type: "",
  date_from: "",
  date_to: "",
  limit: 100,
  offset: 0
});

const selectedCount = computed(() => Object.values(selectedIds).filter(Boolean).length);
const allVisibleSelected = computed(() => rows.value.length > 0 && rows.value.every((row) => selectedIds[row.id]));
const currentFrom = computed(() => (total.value === 0 ? 0 : filters.offset + 1));
const currentTo = computed(() => Math.min(filters.offset + rows.value.length, total.value));

function toApiDateStart(value: string) {
  return value ? `${value}T00:00:00` : undefined;
}

function toApiDateEnd(value: string) {
  return value ? `${value}T23:59:59` : undefined;
}

function apiFilters(): AuditFilters {
  return {
    action: filters.action.trim() || undefined,
    actor_username: filters.actor_username.trim() || undefined,
    target_type: filters.target_type.trim() || undefined,
    date_from: toApiDateStart(filters.date_from),
    date_to: toApiDateEnd(filters.date_to),
    limit: filters.limit,
    offset: filters.offset
  };
}

function formatDate(value: string) {
  return new Date(value).toLocaleString();
}

function payloadPreview(value: Record<string, unknown> | null) {
  if (!value) return "";
  return JSON.stringify(value, null, 2);
}

function openPayload(row: AuditLog) {
  payloadModal.value = {
    title: `${row.action} / ${row.target_type}${row.target_id ? `:${row.target_id}` : ""}`,
    payload: payloadPreview(row.payload_after || row.payload_before) || "{}"
  };
}

function clearSelection() {
  for (const key of Object.keys(selectedIds)) {
    delete selectedIds[Number(key)];
  }
}

async function load(resetOffset = false) {
  if (resetOffset) filters.offset = 0;
  loading.value = true;
  try {
    const response = await auditApi.list(apiFilters());
    rows.value = response.items;
    total.value = response.total;
    clearSelection();
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    loading.value = false;
  }
}

async function loadOptions() {
  try {
    const response = await auditApi.options();
    options.actions = response.actions;
    options.actor_usernames = response.actor_usernames;
    options.target_types = response.target_types;
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

function toggleAllVisible() {
  const next = !allVisibleSelected.value;
  for (const row of rows.value) {
    selectedIds[row.id] = next;
  }
}

async function deleteSelected() {
  const ids = Object.entries(selectedIds)
    .filter(([, selected]) => selected)
    .map(([id]) => Number(id));
  if (!ids.length) {
    showToast("Select audit logs to delete", "warning");
    return;
  }
  if (!window.confirm(`Delete ${ids.length} selected audit log(s)?`)) return;
  deleting.value = true;
  try {
    const response = await auditApi.delete({ ids });
    showToast(response.message, "success");
    await load();
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    deleting.value = false;
  }
}

function nextPage() {
  if (filters.offset + filters.limit >= total.value) return;
  filters.offset += filters.limit;
  void load();
}

function prevPage() {
  filters.offset = Math.max(0, filters.offset - filters.limit);
  void load();
}

watch(
  () => [filters.action, filters.actor_username, filters.target_type, filters.date_from, filters.date_to],
  () => {
    void load(true);
  }
);

onMounted(async () => {
  await loadOptions();
  await load();
});
</script>

<template>
  <section class="grid gap-5">
    <div class="grid gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 class="text-2xl font-semibold text-[#171A20]">Audit Logs</h1>
          <p class="mt-1 text-sm text-[#5C5E62]">Admin view for tracked system actions.</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button
            class="inline-flex size-10 items-center justify-center rounded-lg border border-neutral-200 bg-white text-[#393C41] transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="loading"
            title="Refresh"
            @click="load(true)"
          >
            <LoadingCircle v-if="loading" class="text-current" />
            <svg v-else viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M16.5 7.5a6.5 6.5 0 1 0 1 3.5"></path>
              <path d="M16.5 3.5v4h-4"></path>
            </svg>
          </button>
          <button
            class="inline-flex size-10 items-center justify-center rounded-lg border border-red-200 bg-red-50 text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="deleting || selectedCount === 0"
            :title="`Delete selected (${selectedCount})`"
            @click="deleteSelected"
          >
            <LoadingCircle v-if="deleting" class="text-current" />
            <svg v-else viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M3 5h14"></path>
              <path d="M8 5V3.75A1.25 1.25 0 0 1 9.25 2.5h1.5A1.25 1.25 0 0 1 12 3.75V5"></path>
              <path d="M6 8v7.25A1.75 1.75 0 0 0 7.75 17h4.5A1.75 1.75 0 0 0 14 15.25V8"></path>
              <path d="M8.5 9.5v4"></path>
              <path d="M11.5 9.5v4"></path>
            </svg>
          </button>
        </div>
      </div>

      <div class="grid gap-3 md:grid-cols-[minmax(150px,1fr)_minmax(150px,1fr)_minmax(150px,1fr)_minmax(140px,180px)_minmax(140px,180px)]">
        <select v-model="filters.action" class="rounded border border-[#D0D1D2] bg-white px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
          <option value="">All actions</option>
          <option v-for="action in options.actions" :key="action" :value="action">{{ action }}</option>
        </select>
        <select v-model="filters.actor_username" class="rounded border border-[#D0D1D2] bg-white px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
          <option value="">All users</option>
          <option v-for="username in options.actor_usernames" :key="username" :value="username">{{ username }}</option>
        </select>
        <select v-model="filters.target_type" class="rounded border border-[#D0D1D2] bg-white px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
          <option value="">All target types</option>
          <option v-for="targetType in options.target_types" :key="targetType" :value="targetType">{{ targetType }}</option>
        </select>
        <input v-model="filters.date_from" type="date" class="rounded border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
        <input v-model="filters.date_to" type="date" class="rounded border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
      </div>
    </div>

    <div class="overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm">
      <div class="max-h-[510px] overflow-auto">
        <div class="sticky top-0 z-10 grid min-w-[940px] grid-cols-[40px_170px_84px_minmax(150px,0.9fr)_minmax(280px,1.6fr)_72px] items-center gap-4 border-b border-neutral-200 bg-neutral-50 px-4 py-2 text-xs font-medium uppercase tracking-wide text-[#5C5E62]">
          <div class="flex items-center justify-center">
            <input
              type="checkbox"
              class="size-4 rounded border-neutral-300 accent-[#3E6AE1]"
              :checked="allVisibleSelected"
              @change="toggleAllVisible"
            />
          </div>
          <span>Time</span>
          <span>User</span>
          <span>Action</span>
          <span>Target</span>
          <span>Payload</span>
        </div>
        <div v-if="loading" class="flex min-w-[940px] items-center gap-2 px-4 py-8 text-sm text-[#5C5E62]">
          <LoadingCircle class="text-[#3E6AE1]" />
          Loading audit logs...
        </div>
        <div v-else-if="!rows.length" class="min-w-[940px] px-4 py-8 text-sm text-[#5C5E62]">No audit logs found.</div>
        <div
          v-else
          v-for="row in rows"
          :key="row.id"
          class="grid min-w-[940px] grid-cols-[40px_170px_84px_minmax(150px,0.9fr)_minmax(280px,1.6fr)_72px] items-start gap-4 border-b border-neutral-200 px-4 py-3 text-sm last:border-b-0"
        >
          <div class="flex items-center justify-center pt-0.5">
            <input v-model="selectedIds[row.id]" type="checkbox" class="size-4 rounded border-neutral-300 accent-[#3E6AE1]" />
          </div>
          <span class="text-xs leading-5 text-[#5C5E62]">{{ formatDate(row.created_at) }}</span>
          <span class="min-w-0 truncate font-medium leading-5 text-[#171A20]" :title="row.actor_username">{{ row.actor_username }}</span>
          <span class="min-w-0 wrap-break-word leading-5 text-[#171A20]">{{ row.action }}</span>
          <span class="min-w-0 wrap-break-word leading-5 text-[#393C41]">{{ row.target_type }}<template v-if="row.target_id">: {{ row.target_id }}</template></span>
          <button
            type="button"
            class="inline-flex min-h-7 items-center justify-center rounded border border-neutral-200 bg-white px-2 text-xs font-medium text-[#3E6AE1] transition hover:bg-neutral-50"
            @click="openPayload(row)"
          >
            View
          </button>
        </div>
      </div>
      <div class="flex flex-wrap items-center justify-between gap-3 border-t border-neutral-200 bg-neutral-50 px-4 py-3 text-sm text-[#5C5E62]">
        <span>{{ currentFrom }}-{{ currentTo }} / {{ total }}</span>
        <div class="flex items-center gap-2">
          <button class="rounded border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60" :disabled="filters.offset === 0" @click="prevPage">Prev</button>
          <button class="rounded border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60" :disabled="filters.offset + filters.limit >= total" @click="nextPage">Next</button>
        </div>
      </div>
    </div>

    <div v-if="payloadModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6" @click.self="payloadModal = null">
      <div class="grid max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-xl">
        <div class="flex items-center justify-between gap-3 border-b border-neutral-200 px-4 py-3">
          <h2 class="min-w-0 truncate text-base font-semibold text-[#171A20]">{{ payloadModal.title }}</h2>
          <button
            type="button"
            class="inline-flex size-8 items-center justify-center rounded-lg border border-neutral-200 bg-white text-[#393C41] transition hover:bg-neutral-100"
            title="Close"
            @click="payloadModal = null"
          >
            <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
              <path d="M5 5l10 10"></path>
              <path d="M15 5 5 15"></path>
            </svg>
          </button>
        </div>
        <pre class="max-h-[70vh] overflow-auto p-4 text-xs leading-5">{{ payloadModal.payload }}</pre>
      </div>
    </div>
  </section>
</template>
