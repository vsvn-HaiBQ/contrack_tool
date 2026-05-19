<script setup lang="ts">
import { computed } from "vue";
import type { Assignee, QuickCreateDraft, TrackerOption } from "../../shared/types";
import LoadingCircle from "../../shared/LoadingCircle.vue";

const props = defineProps<{
  draft: QuickCreateDraft;
  trackerOptions: TrackerOption[];
  assigneeOptions: Assignee[];
  creatingChild: boolean;
  from: "detail" | "related" | "logtime";
}>();

const emit = defineEmits<{
  create: [draftId: number];
  cancel: [draftId: number];
}>();

const quickCreateTrackerOptions = computed(() => {
  if (props.trackerOptions.length) {
    return props.trackerOptions;
  }
  return [
    { id: -1, name: "Story" },
    { id: -2, name: "Sub-task" },
    { id: -3, name: "QA" },
    { id: -4, name: "Bug" }
  ];
});

function trackerBadgeClass(tracker: string | null | undefined) {
  const value = (tracker || "").trim().toLowerCase();
  if (value === "story") return "bg-[#3E6AE1] text-white";
  if (value.includes("sub")) return "bg-sky-100 text-sky-700 ring-1 ring-sky-200";
  if (value.includes("bug")) return "bg-rose-100 text-rose-700 ring-1 ring-rose-200";
  if (/q\W*a/.test(value) || value.includes("test")) return "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200";
  if (value.includes("task")) return "bg-amber-100 text-amber-700 ring-1 ring-amber-200";
  return "bg-neutral-100 text-[#5C5E62] ring-1 ring-neutral-200";
}
</script>

<template>
  <div :class="`grid bg-[#F8FAFF] px-2 py-2 pr-6 last:rounded-xl border-t border-neutral-200 ${from === 'detail' ? 'md:grid-cols-[160px_minmax(0,1fr)]' : from === 'logtime' ? 'md:grid-cols-[140px_minmax(0,1fr)]' : 'md:grid-cols-[120px_minmax(0,1fr)]'}`">
    <div class="flex flex-wrap items-start gap-2">
      <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Type / ID</span>
      <span :class="['inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', trackerBadgeClass(draft.tracker || 'Task')]">{{ draft.tracker || "Task" }}</span>
      <span class="rounded bg-white px-1.5 py-0.5 text-xs font-mono text-[#9CA0A6] ring-1 ring-neutral-200">New</span>
    </div>
    <div class="grid gap-3">
      <div class="grid gap-1">
        <label class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62]">Subject</label>
        <div class="relative">
          <span class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-[#9CA0A6]">
            <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M4 5.5h12"></path>
              <path d="M4 10h12"></path>
              <path d="M4 14.5h8"></path>
            </svg>
          </span>
          <input
            v-model="draft.subject"
            placeholder="Enter task subject"
            class="w-full rounded-lg border border-[#D0D1D2] bg-white py-1 pr-3 pl-9 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
            @keydown.enter="emit('create', draft.id)"
          />
        </div>
      </div>
      <div class="grid gap-1">
        <label class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62]">Description</label>
        <div class="relative">
          <span class="pointer-events-none absolute top-3 left-3 text-[#9CA0A6]">
            <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M5 4.5h10"></path>
              <path d="M5 8.5h10"></path>
              <path d="M5 12.5h7"></path>
            </svg>
          </span>
          <textarea
            v-model="draft.description"
            rows="2"
            placeholder="Description (optional)"
            class="w-full rounded-lg border border-[#D0D1D2] bg-white py-1 pr-3 pl-9 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
          ></textarea>
        </div>
      </div>
      <div class="grid gap-3 md:grid-cols-[120px_120px_120px_auto] md:items-end">
        <div class="grid gap-1">
          <label class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62]">Type</label>
          <div class="relative">
            <span class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-[#9CA0A6]">
              <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <rect x="4" y="4" width="12" height="12" rx="2"></rect>
                <path d="M7 8h6"></path>
                <path d="M7 12h4"></path>
              </svg>
            </span>
            <select
              v-model="draft.tracker"
              class="w-full rounded-lg border border-[#D0D1D2] bg-white py-1 pr-3 pl-9 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
            >
              <option v-for="tracker in quickCreateTrackerOptions" :key="tracker.id" :value="tracker.name">{{ tracker.name }}</option>
            </select>
          </div>
        </div>
        <div class="grid gap-1">
          <label class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62]">Assignee</label>
          <div class="relative">
            <span class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-[#9CA0A6]">
              <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <circle cx="10" cy="7" r="3"></circle>
                <path d="M4.5 16a5.5 5.5 0 0 1 11 0"></path>
              </svg>
            </span>
            <select
              v-model="draft.assignee_id"
              class="w-full rounded-lg border border-[#D0D1D2] bg-white py-1 pr-3 pl-9 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
            >
              <option :value="null">Unassigned</option>
              <option v-for="assignee in assigneeOptions" :key="assignee.id" :value="assignee.id">{{ assignee.name }}</option>
            </select>
          </div>
        </div>
        <div class="grid gap-1">
          <label class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62]">Parent ID</label>
          <input
            v-model.number="draft.parent_issue_id"
            type="number"
            min="1"
            class="w-full rounded-lg border border-[#D0D1D2] bg-white px-2 py-1 text-sm font-mono text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
          />
        </div>
        <div class="flex flex-wrap items-center gap-2 md:justify-end">
          <button
            type="button"
            class="inline-flex min-h-7.5 items-center justify-center gap-1 rounded-lg bg-[#3E6AE1] px-3 py-1 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60 md:w-7.5 md:px-0"
            :disabled="creatingChild"
            :title="creatingChild ? 'Creating task' : 'Create task'"
            @click="emit('create', draft.id)"
          >
            <LoadingCircle v-if="creatingChild" class="md:size-4" />
            <svg v-else viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="m4.5 10 3.5 3.5 7.5-8"></path>
            </svg>
            <span class="md:hidden">{{ creatingChild ? "Creating..." : "Create" }}</span>
          </button>
          <button
            type="button"
            class="inline-flex min-h-7.5 items-center justify-center gap-1 rounded-lg border border-neutral-200 bg-white px-3 py-1 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100 md:w-7.5 md:px-0"
            :disabled="creatingChild"
            title="Cancel task form"
            @click="emit('cancel', draft.id)"
          >
            <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="m5 5 10 10"></path>
              <path d="M15 5 5 15"></path>
            </svg>
            <span class="md:hidden">Cancel</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
