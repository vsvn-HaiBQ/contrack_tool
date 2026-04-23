<script setup lang="ts">
import { computed } from "vue";
import type { Assignee, SyncResult, TicketCandidate, TrackerOption } from "../../shared/types";
import LoadingCircle from "../../shared/LoadingCircle.vue";

const props = defineProps<{
  syncState: {
    jp_issue_input: string;
    jp_issue_id: number | null;
    jp_subject: string;
    jp_issue_url: string;
    verified: boolean;
    verifying: boolean;
    candidates: TicketCandidate[];
    subject: string;
    subject_prefix: "Bug" | "CR" | "";
    description: string;
    assignee_id: number | null;
    parent_issue_id: number | null;
    related_ticket_id: number | null;
    existing_vn_issue_id: number | null;
    selected_subtasks: string[];
    subtask_titles: Record<string, string>;
    extra_tracker: string;
    force_create: boolean;
  };
  syncResult: SyncResult;
  assignees: Assignee[];
  trackers: TrackerOption[];
}>();

const emit = defineEmits<{
  verify: [];
  runSync: [payload?: { mode: "create_new" | "link"; existingVnIssueId?: number | null }];
  forceCreate: [];
}>();

type ReferenceRow = {
  candidate: TicketCandidate;
  isStory: boolean;
  isLast: boolean;
};

const referenceRows = computed<ReferenceRow[]>(() => {
  const stories = props.syncState.candidates.filter((item) => item.tracker?.toLowerCase() === "story");
  const children = props.syncState.candidates.filter((item) => item.tracker?.toLowerCase() !== "story");
  const childMap = new Map<number, TicketCandidate[]>();

  for (const child of children) {
    const parentId = child.parent_issue_id ?? -1;
    const bucket = childMap.get(parentId) ?? [];
    bucket.push(child);
    childMap.set(parentId, bucket);
  }

  const rows: ReferenceRow[] = [];
  for (const story of stories) {
    rows.push({ candidate: story, isStory: true, isLast: false });
    const kids = childMap.get(story.issue_id) ?? [];
    kids.forEach((child, idx) => {
      rows.push({ candidate: child, isStory: false, isLast: idx === kids.length - 1 });
    });
  }

  const orphans = children.filter((child) => !stories.some((story) => story.issue_id === child.parent_issue_id));
  orphans.forEach((child, idx) => {
    rows.push({ candidate: child, isStory: false, isLast: idx === orphans.length - 1 });
  });

  return rows;
});

const subtaskPreview = computed(() =>
  props.syncState.selected_subtasks.map((key) => ({
    key,
    label: props.syncState.subtask_titles[key] ?? key,
    fullSubject: props.syncState.jp_issue_id
      ? `#${props.syncState.jp_issue_id}: ${props.syncState.subtask_titles[key] ?? key}`
      : props.syncState.subtask_titles[key] ?? key
  }))
);

const editorTitle = computed(() => `Create ${props.syncState.extra_tracker}`);
const hasReferenceCandidates = computed(() => props.syncState.candidates.length > 0);
const trackerOptions = computed(() => {
  if (props.trackers.length) return props.trackers;
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
  <section class="grid gap-5 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="mt-1 text-2xl font-semibold text-[#171A20]">Verify a JP issue, then create or link a VN Story.</h1>
      </div>
      <span v-if="syncState.verified" class="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200">
        Verified
      </span>
    </div>

    <div class="flex flex-wrap items-end gap-3">
      <div class="min-w-[220px]">
        <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-[#5C5E62]">JP issue ID or URL</label>
        <input
          v-model="syncState.jp_issue_input"
          type="text"
          placeholder="12345 or https://.../issues/12345"
          class="w-full max-w-md rounded-lg border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1] focus:ring-2 focus:ring-[#3E6AE1]/20"
        />
      </div>
      <button
        class="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[#3E6AE1] px-5 py-2 text-sm font-medium text-white shadow-sm transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="syncState.verifying"
        @click="emit('verify')"
      >
        <LoadingCircle v-if="syncState.verifying" />
        {{ syncState.verifying ? "Verifying..." : "Verify" }}
      </button>
    </div>

    <div v-if="syncState.jp_subject" class="rounded-xl border border-neutral-200 bg-neutral-50 px-4 py-3">
      <div class="flex items-center gap-2">
        <span class="break-words text-sm font-medium text-[#171A20]">#{{ syncState.jp_issue_id }}: {{ syncState.jp_subject }}</span>
      </div>
      <a v-if="syncState.jp_issue_url" :href="syncState.jp_issue_url" target="_blank" rel="noreferrer" class="mt-1 block break-all text-xs text-[#3E6AE1]">
        {{ syncState.jp_issue_url }}
      </a>
    </div>
  </section>

  <section v-if="syncState.verified" class="grid gap-6">
    <div class="grid content-start gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex items-center justify-between gap-3">
        <div>
          <h3 class="m-0 text-xl font-semibold text-[#171A20]">VN Reference</h3>
          <p class="mt-1 text-xs text-[#5C5E62]">VN tickets whose subject contains the JP code.</p>
        </div>
        <span class="inline-flex rounded-full bg-[#F4F4F4] px-3 py-1 text-xs font-medium text-[#393C41]">#{{ syncState.jp_issue_id }}</span>
      </div>

      <div v-if="referenceRows.length" class="overflow-hidden rounded-lg border border-neutral-200">
        <div class="grid grid-cols-[140px_minmax(0,1fr)_80px_80px_80px] gap-3 border-b border-neutral-200 bg-neutral-50 px-3 py-2 text-xs font-medium uppercase tracking-wide text-[#5C5E62]">
          <span>Type / ID</span>
          <span>Subject</span>
          <span>Assignee</span>
          <span>Status</span>
          <span class="text-right">Action</span>
        </div>
        <div
          v-for="row in referenceRows"
          :key="row.candidate.issue_id"
          class="grid grid-cols-[140px_minmax(0,1fr)_80px_80px_80px] items-center gap-3 border-b border-neutral-200 px-3 py-2 last:border-b-0 transition"
          :class="row.isStory ? 'bg-[#F5F8FF]' : 'hover:bg-neutral-50'"
        >
          <div class="flex items-center gap-2">
            <span
              v-if="row.isStory"
              :class="['inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold', trackerBadgeClass('Story')]"
            >Story</span>
            <span
              v-else
              :class="['inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', trackerBadgeClass(row.candidate.tracker || 'Child')]"
            >{{ row.candidate.tracker || "Child" }}</span>
            <span class="rounded bg-white px-1.5 py-0.5 text-xs font-mono text-[#3E6AE1] ring-1 ring-neutral-200">#{{ row.candidate.issue_id }}</span>
          </div>
          <a
            v-if="row.candidate.url"
            :href="row.candidate.url"
            target="_blank"
            rel="noreferrer"
            class="flex items-center gap-2 break-words text-sm text-[#171A20] hover:text-[#3E6AE1] hover:underline"
          >
            <span v-if="!row.isStory" class="select-none font-mono text-xs text-[#9CA0A6]">{{ row.isLast ? "L-" : "|-" }}</span>
            <span :class="row.isStory ? 'font-medium' : ''">{{ row.candidate.subject }}</span>
          </a>
          <span v-else class="break-words text-sm text-[#171A20]">{{ row.candidate.subject }}</span>
          <span class="text-sm text-[#5C5E62]">{{ row.candidate.assignee || "-" }}</span>
          <span class="text-sm text-[#5C5E62]">{{ row.candidate.status || "-" }}</span>
          <div class="flex items-center justify-end">
            <button
              v-if="row.isStory && syncState.existing_vn_issue_id === row.candidate.issue_id"
              type="button"
              disabled
              class="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-700"
              title="Linked story"
            >
              <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="m4.5 10 3.5 3.5 7.5-8"></path>
              </svg>
              Linked
            </button>
            <button
              v-else-if="row.isStory"
              type="button"
              class="inline-flex items-center gap-1 rounded-lg border border-[#3E6AE1] px-3 py-2 text-xs font-medium text-[#3E6AE1] transition hover:bg-[#F5F8FF]"
              @click="emit('runSync', { mode: 'link', existingVnIssueId: row.candidate.issue_id })"
            >
              <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M8 12 12 8"></path>
                <path d="M7 6.5H5.75A2.75 2.75 0 0 0 3 9.25v5A2.75 2.75 0 0 0 5.75 17h5a2.75 2.75 0 0 0 2.75-2.75V13"></path>
                <path d="M11 3h6v6"></path>
              </svg>
              Link
            </button>
          </div>
        </div>
      </div>
      <div v-else class="rounded-xl border border-dashed border-neutral-300 px-4 py-6 text-center text-sm text-[#5C5E62]">
        No VN reference tickets found yet.
      </div>

      <div
        v-if="hasReferenceCandidates && !syncState.force_create"
        class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-900"
      >
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p class="m-0 font-semibold">VN reference already exists.</p>
            <p class="mt-1 text-amber-800">Create form is hidden to avoid duplicate Story creation. Link an existing Story, or continue only if you need to force create.</p>
          </div>
          <button
            type="button"
            class="inline-flex min-h-10 items-center justify-center rounded-lg border border-amber-300 bg-white px-4 py-2 text-sm font-medium text-amber-900 transition hover:bg-amber-100"
            @click="emit('forceCreate')"
          >
            Force Create
          </button>
        </div>
      </div>
    </div>

    <div v-if="!hasReferenceCandidates || syncState.force_create" class="grid content-start gap-5 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex items-center gap-3">
        <h3 class="m-0 text-xl font-semibold text-[#171A20]">{{ editorTitle }}</h3>
      </div>

      <div class="grid gap-3">
        <p class="text-xs font-semibold uppercase tracking-[0.08em] text-[#5C5E62]">Story info</p>
        <div class="flex flex-wrap items-center gap-4 text-sm text-[#393C41]">
          <span class="text-xs uppercase tracking-wide text-[#9CA0A6]">prefix</span>
          <label class="flex items-center gap-2"><input v-model="syncState.subject_prefix" :value="'Bug'" type="radio" class="size-4" /> Bug</label>
          <label class="flex items-center gap-2"><input v-model="syncState.subject_prefix" :value="'CR'" type="radio" class="size-4" /> CR</label>
          <label class="flex items-center gap-2"><input v-model="syncState.subject_prefix" :value="''" type="radio" class="size-4" /> None</label>
        </div>
        <label class="text-xs font-medium uppercase tracking-wide text-[#5C5E62]">Story subject</label>
        <input v-model="syncState.subject" class="w-full rounded-lg border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1] focus:ring-2 focus:ring-[#3E6AE1]/20" />
        <label class="text-xs font-medium uppercase tracking-wide text-[#5C5E62]">Description</label>
        <textarea v-model="syncState.description" rows="7" class="w-full rounded-lg border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1] focus:ring-2 focus:ring-[#3E6AE1]/20"></textarea>
        <p class="-mt-2 text-xs text-[#9CA0A6]">Description template comes from System Settings. Available placeholders: <code>{jp_issue_id}</code>, <code>{jp_issue_url}</code>, <code>{jp_subject}</code>.</p>
        <div class="grid gap-3 md:grid-cols-2">
          <div>
            <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-[#5C5E62]">Assignee</label>
            <select v-model="syncState.assignee_id" class="w-full rounded-lg border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
              <option v-for="assignee in assignees" :key="assignee.id" :value="assignee.id">
                {{ assignee.name }}
              </option>
            </select>
          </div>
          <div>
            <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-[#5C5E62]">Tracker</label>
            <select
              v-model="syncState.extra_tracker"
              class="w-full rounded-lg border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
            >
              <option v-for="tracker in trackerOptions" :key="tracker.id" :value="tracker.name">{{ tracker.name }}</option>
            </select>
          </div>
        </div>
      </div>

      <div class="grid gap-3 rounded-xl border border-neutral-200 bg-neutral-50/60 p-4">
        <div class="grid gap-3 md:grid-cols-2">
          <div>
            <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-[#5C5E62]">Parent issue ID</label>
            <input v-model="syncState.parent_issue_id" type="number" placeholder="VN epic / story id" class="w-full rounded-lg border border-[#D0D1D2] bg-white px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-[#5C5E62]">Related VN ticket</label>
            <input v-model="syncState.related_ticket_id" type="number" placeholder="VN ticket id (relates)" class="w-full rounded-lg border border-[#D0D1D2] bg-white px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
          </div>
        </div>
      </div>

      <div class="grid gap-3 rounded-xl border border-neutral-200 bg-neutral-50/60 p-4">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.08em] text-[#5C5E62]">Subtasks to create</p>
        </div>
        <div class="flex flex-wrap gap-3 text-sm text-[#393C41]">
          <label class="flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-2 py-2"><input v-model="syncState.selected_subtasks" value="fix_bug" type="checkbox" class="size-4" /> Fix bug</label>
          <label class="flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-2 py-2"><input v-model="syncState.selected_subtasks" value="dev" type="checkbox" class="size-4" /> Dev</label>
          <label class="flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-2 py-2"><input v-model="syncState.selected_subtasks" value="estimate" type="checkbox" class="size-4" /> Estimate</label>
          <label class="flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-2 py-2"><input v-model="syncState.selected_subtasks" value="test" type="checkbox" class="size-4" /> Test</label>
        </div>
        <div v-if="subtaskPreview.length" class="grid gap-2">
          <div
            v-for="item in subtaskPreview"
            :key="item.key"
            class="rounded-lg border border-neutral-200 bg-white px-3 py-2"
          >
            <input
              v-model="syncState.subtask_titles[item.key]"
              class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
            />
          </div>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-3 border-t border-neutral-100 pt-4">
        <button
          class="min-h-10 min-w-[200px] rounded-lg bg-[#3E6AE1] px-5 py-2 text-sm font-medium text-white shadow-sm transition hover:brightness-95"
          @click="emit('runSync', { mode: 'create_new' })"
        >
          {{ editorTitle }}
        </button>
      </div>
    </div>

    <div v-if="syncResult.story" class="grid content-start gap-3 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div>
        <h3 class="m-0 text-xl font-semibold text-[#171A20]">Sync result</h3>
        <p class="mt-1 text-sm text-[#5C5E62]">{{ syncResult.message }}</p>
      </div>
      <div class="grid gap-2 rounded-xl border border-neutral-200 p-4">
        <p class="text-xs font-semibold uppercase tracking-wide text-[#5C5E62]">Story</p>
        <a :href="syncResult.story.url" target="_blank" rel="noreferrer" class="flex flex-wrap items-center gap-2 text-sm hover:underline">
          <span class="rounded bg-[#3E6AE1] px-2 py-0.5 text-xs font-semibold text-white">#{{ syncResult.story.issue_id }}</span>
          <span class="break-all text-[#171A20]">{{ syncResult.story.subject }}</span>
        </a>
      </div>
      <div v-if="syncResult.subtasks.length" class="grid gap-2 rounded-xl border border-neutral-200 p-4">
        <p class="text-xs font-semibold uppercase tracking-wide text-[#5C5E62]">Subtasks</p>
        <a
          v-for="subtask in syncResult.subtasks"
          :key="subtask.issue_id"
          :href="subtask.url"
          target="_blank"
          rel="noreferrer"
          class="flex flex-wrap items-center gap-2 text-sm hover:underline"
        >
          <span class="rounded bg-neutral-100 px-2 py-0.5 text-xs font-mono text-[#3E6AE1] ring-1 ring-neutral-200">#{{ subtask.issue_id }}</span>
          <span class="break-all text-[#171A20]">{{ subtask.subject }}</span>
        </a>
      </div>
    </div>
  </section>
</template>
