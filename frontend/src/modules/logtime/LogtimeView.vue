<script setup lang="ts">
import { computed } from "vue";
import type { Assignee, LogtimeRow, LogtimeSaveResult, StatusOption } from "../../shared/types";
import LoadingCircle from "../../shared/LoadingCircle.vue";

const props = defineProps<{
  logtimeDate: string;
  rows: LogtimeRow[];
  activities: string[];
  statusOptions: StatusOption[];
  assigneeOptions: Assignee[];
  totalHours: number;
  results: LogtimeSaveResult[];
  loading: boolean;
  saving: boolean;
}>();

const emit = defineEmits<{
  "update:logtimeDate": [value: string];
  shiftDate: [delta: number];
  goToday: [];
  save: [];
}>();

type GroupedRow = {
  row: LogtimeRow;
  isLast: boolean;
};

type RowGroup = {
  root: LogtimeRow;
  children: GroupedRow[];
};

const groupedRows = computed<RowGroup[]>(() => {
  const list = props.rows;
  const idSet = new Set(list.map((r) => r.issue_id));
  const roots = list.filter((r) => !r.parent_issue_id || !idSet.has(r.parent_issue_id));
  const childrenOf = new Map<number, LogtimeRow[]>();

  for (const r of list) {
    if (r.parent_issue_id && idSet.has(r.parent_issue_id)) {
      const bucket = childrenOf.get(r.parent_issue_id) ?? [];
      bucket.push(r);
      childrenOf.set(r.parent_issue_id, bucket);
    }
  }

  return roots.map((root) => ({
    root,
    children: (childrenOf.get(root.issue_id) ?? []).map((row, idx, items) => ({
      row,
      isLast: idx === items.length - 1
    }))
  }));
});

function issueStatusOptions(row: LogtimeRow) {
  const names = [row.status, ...(row.allowed_statuses ?? [])].filter(Boolean);
  return Array.from(new Set(names)).map((name) => ({
    id: name,
    name
  }));
}

function trackerBadgeClass(tracker?: string | null) {
  const t = (tracker || "").toLowerCase();
  if (t === "story") return "bg-[#3E6AE1] text-white";
  if (t.includes("bug")) return "bg-rose-100 text-rose-700 ring-1 ring-rose-200";
  if (/q\W*a/.test(t) || t.includes("test")) return "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200";
  if (t.includes("sub")) return "bg-sky-100 text-sky-700 ring-1 ring-sky-200";
  if (t.includes("task")) return "bg-amber-100 text-amber-700 ring-1 ring-amber-200";
  return "bg-neutral-100 text-[#5C5E62] ring-1 ring-neutral-200";
}

function isStory(row: LogtimeRow) {
  return (row.tracker || "").trim().toLowerCase() === "story";
}

const formattedHeaderDate = computed(() => {
  const parsed = new Date(`${props.logtimeDate}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return props.logtimeDate;
  }

  return new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric"
  }).format(parsed);
});
</script>

<template>
  <section class="grid gap-6">
    <div class="grid gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.08em] text-[#5C5E62]">Daily Tracker</p>
          <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Logtime</h3>
          <p class="mt-1 text-sm text-[#5C5E62]">{{ formattedHeaderDate }}</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button
            type="button"
            class="flex size-10 items-center justify-center rounded-lg border border-neutral-200 bg-white text-[#393C41] transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
            title="Previous day"
            :disabled="loading || saving"
            @click="emit('shiftDate', -1)"
          >
            <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="m12.5 4.5-5 5 5 5"></path>
            </svg>
          </button>
          <input class="rounded-lg border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1] disabled:cursor-not-allowed disabled:opacity-60" :value="logtimeDate" type="date" :disabled="loading || saving" @input="emit('update:logtimeDate', ($event.target as HTMLInputElement).value)" />
          <button
            type="button"
            class="flex size-10 items-center justify-center rounded-lg border border-neutral-200 bg-white text-[#393C41] transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
            title="Next day"
            :disabled="loading || saving"
            @click="emit('shiftDate', 1)"
          >
            <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="m7.5 4.5 5 5-5 5"></path>
            </svg>
          </button>
          <button class="inline-flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60" :disabled="loading || saving" @click="emit('goToday')">
            <LoadingCircle v-if="loading" class="text-[#3E6AE1]" />
            Today
          </button>
        </div>
      </div>

      <div v-if="loading" class="flex items-center justify-center gap-3 rounded-xl border border-neutral-200 px-4 py-8 text-sm text-[#5C5E62]">
        <LoadingCircle class="text-[#3E6AE1]" />
        Loading logtime...
      </div>
      <div v-else-if="groupedRows.length" class="grid gap-3">
        <div class="hidden grid-cols-[minmax(132px,0.68fr)_minmax(0,3.2fr)_minmax(115px,0.62fr)_minmax(115px,0.62fr)_minmax(115px,0.58fr)_60px] gap-2 rounded-xl border border-neutral-200 bg-neutral-50 px-2 py-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#5C5E62] md:grid">
          <span>Issue</span>
          <span>Subject</span>
          <span>Status</span>
          <span>Assignee</span>
          <span>Activity</span>
          <span class="text-right">Hours</span>
        </div>
        <article
          v-for="group in groupedRows"
          :key="group.root.issue_id"
          class="overflow-hidden rounded-xl border border-neutral-200"
        >
          <div class="grid gap-2 bg-[#F5F8FF] px-2 py-2 md:grid-cols-[minmax(132px,0.68fr)_minmax(0,3.2fr)_minmax(115px,0.62fr)_minmax(115px,0.62fr)_minmax(115px,0.58fr)_60px] md:items-center">
            <div class="flex min-w-0 flex-wrap items-center gap-2">
              <span class="inline-flex w-fit items-center rounded-full px-2 py-0.5 text-xs font-semibold" :class="trackerBadgeClass(group.root.tracker)">
                {{ group.root.tracker || "Issue" }}
              </span>
              <span class="rounded bg-white px-1.5 py-0.5 text-xs font-mono text-[#3E6AE1] ring-1 ring-neutral-200">#{{ group.root.issue_id }}</span>
            </div>
            <div class="grid min-w-0 gap-1">
              <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Subject</span>
              <a :href="group.root.url" target="_blank" rel="noreferrer" class="block min-w-0 truncate text-sm font-medium text-[#171A20] hover:text-[#3E6AE1] hover:underline" :title="group.root.subject">
                {{ group.root.subject }}
              </a>
            </div>
            <div class="grid gap-1">
              <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Status</span>
              <select v-model="group.root.status" class="w-full rounded-lg border border-[#D0D1D2] bg-white px-1 py-1 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
                <option v-for="status in issueStatusOptions(group.root)" :key="status.id" :value="status.name">{{ status.name }}</option>
              </select>
            </div>
            <div class="grid gap-1">
              <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Assignee</span>
              <select v-model="group.root.assignee" class="w-full rounded-lg border border-[#D0D1D2] bg-white px-1 py-1 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
                <option value="">Unassigned</option>
                <option v-for="assignee in assigneeOptions" :key="assignee.id" :value="assignee.name">{{ assignee.name }}</option>
              </select>
            </div>
            <div class="grid gap-1">
              <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Activity</span>
              <select v-if="!isStory(group.root)" v-model="group.root.activity" class="w-full rounded-lg border border-[#D0D1D2] bg-white px-1 py-1 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
                <option v-for="activity in activities" :key="activity">{{ activity }}</option>
              </select>
            </div>
            <div class="grid gap-1">
              <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Spent time</span>
              <input v-if="!isStory(group.root)" v-model.number="group.root.hours" type="number" min="0" step="0.25" class="w-full rounded-lg border border-[#D0D1D2] bg-white px-1 py-1 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
              <div v-else class="hidden min-h-10 w-full rounded-lg border border-transparent md:block"></div>
            </div>
          </div>

          <div v-if="group.children.length" class="border-t border-neutral-200 bg-neutral-50/70">
            <div class="grid gap-0">
              <div
                v-for="item in group.children"
                :key="item.row.issue_id"
                class="grid gap-2 border-b border-neutral-200 px-1 py-1 last:border-b-0 md:grid-cols-[minmax(132px,0.68fr)_minmax(0,3.2fr)_minmax(115px,0.62fr)_minmax(115px,0.62fr)_minmax(115px,0.58fr)_60px] md:items-center"
              >
                <div class="flex min-w-0 flex-wrap items-center gap-2">
                  <span class="inline-flex w-fit items-center rounded-full px-2 py-0.5 text-xs font-semibold" :class="trackerBadgeClass(item.row.tracker)">
                    {{ item.row.tracker || "Sub" }}
                  </span>
                  <span class="rounded bg-white px-1.5 py-0.5 text-xs font-mono text-[#3E6AE1] ring-1 ring-neutral-200">#{{ item.row.issue_id }}</span>
                </div>
                <div class="grid min-w-0 gap-1">
                  <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Subject</span>
                  <div class="relative min-w-0 pl-4">
                    <span class="absolute top-0.5 left-0 h-2.5 w-3 border-l border-b border-neutral-300"></span>
                    <span v-if="!item.isLast" class="absolute top-3 left-0 h-[calc(100%-0.75rem)] border-l border-neutral-300"></span>
                    <a :href="item.row.url" target="_blank" rel="noreferrer" class="block min-w-0 truncate text-sm text-[#171A20] hover:text-[#3E6AE1] hover:underline" :title="item.row.subject">
                      {{ item.row.subject }}
                    </a>
                  </div>
                </div>
                <div class="grid gap-1">
                  <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Status</span>
                  <select v-model="item.row.status" class="w-full rounded-lg border border-[#D0D1D2] bg-white px-1 py-1 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
                    <option v-for="status in issueStatusOptions(item.row)" :key="status.id" :value="status.name">{{ status.name }}</option>
                  </select>
                </div>
                <div class="grid gap-1">
                  <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Assignee</span>
                  <select v-model="item.row.assignee" class="w-full rounded-lg border border-[#D0D1D2] bg-white px-1 py-1 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
                    <option value="">Unassigned</option>
                    <option v-for="assignee in assigneeOptions" :key="assignee.id" :value="assignee.name">{{ assignee.name }}</option>
                  </select>
                </div>
                <div class="grid gap-1">
                  <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Activity</span>
                  <select v-model="item.row.activity" class="w-full rounded-lg border border-[#D0D1D2] bg-white px-1 py-1 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
                    <option v-for="activity in activities" :key="activity">{{ activity }}</option>
                  </select>
                </div>
                <div class="grid gap-1">
                  <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Spent time</span>
                  <input v-model.number="item.row.hours" type="number" min="0" step="0.25" class="w-full rounded-lg border border-[#D0D1D2] bg-white px-1 py-1 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
                </div>
              </div>
            </div>
          </div>
        </article>
      </div>
      <div v-else class="rounded-xl border border-dashed border-neutral-300 px-4 py-6 text-center text-sm text-[#5C5E62]">
        No tickets for this date.
      </div>

      <div class="flex items-center justify-between gap-3">
        <p class="text-sm text-[#5C5E62]">Total: <span class="font-semibold text-[#171A20]">{{ totalHours }}h</span> <span v-if="totalHours > 8" class="ml-2 inline-flex items-center rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 ring-1 ring-amber-200">Over 8h</span></p>
        <button class="inline-flex min-h-10 min-w-[200px] items-center justify-center gap-2 rounded-lg bg-[#3E6AE1] px-5 py-2 text-sm font-medium text-white shadow-sm transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60" :disabled="loading || saving" @click="emit('save')">
          <LoadingCircle v-if="saving" />
          {{ saving ? "Saving..." : "Save Logtime" }}
        </button>
      </div>

      <div v-if="results.length" class="overflow-hidden rounded-lg border border-neutral-200">
        <div class="grid grid-cols-[120px_minmax(0,1fr)_120px] gap-3 border-b border-neutral-200 bg-neutral-50 px-3 py-2 text-xs font-medium uppercase tracking-wide text-[#5C5E62]">
          <span>Issue</span>
          <span>Result</span>
          <span class="text-right">Status</span>
        </div>
        <div v-for="result in results" :key="result.issue_id" class="grid grid-cols-[120px_minmax(0,1fr)_120px] gap-3 border-b border-neutral-200 px-3 py-2 last:border-b-0">
          <span class="font-mono text-sm text-[#3E6AE1]">#{{ result.issue_id }}</span>
          <span class="text-sm text-[#393C41]">{{ result.message }}</span>
          <span class="text-right text-xs font-medium" :class="result.success ? 'text-emerald-700' : 'text-rose-700'">{{ result.success ? "OK" : "Failed" }}</span>
        </div>
      </div>
    </div>
  </section>
</template>
