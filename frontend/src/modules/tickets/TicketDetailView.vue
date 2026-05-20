<script setup lang="ts">
import { computed, ref } from "vue";
import type { Assignee, ManagedTicketListItem, QuickCreateDraft, StatusOption, TicketDetail, TrackerOption } from "../../shared/types";
import LoadingCircle from "../../shared/LoadingCircle.vue";
import QuickCreateTaskRow from "./QuickCreateTaskRow.vue";

const props = defineProps<{
  ticketSearch: string;
  managedScope: "following" | "all";
  managedTickets: ManagedTicketListItem[];
  loadingManaged: boolean;
  statusOptions: StatusOption[];
  assigneeOptions: Assignee[];
  ticketDetail: TicketDetail | null;
  loadingDetail: boolean;
  refreshingDetail?: boolean;
  ticketEdit: Record<number, { status: string; assignee: string }>;
  quickCreateForms: QuickCreateDraft[];
  trackerOptions: TrackerOption[];
  creatingChild: boolean;
  linkForm: { type: string; url: string };
  suggestSyncJpIssueId: number | null;
  showLinkForm: boolean;
  editingLinkId: number | null;
  isAdmin?: boolean;
  deletingManagedJpIssueId?: number | null;
  saving?: boolean;
  canPostToTeams?: boolean;
  postingTeams?: boolean;
}>();

const emit = defineEmits<{
  "update:ticketSearch": [value: string];
  "update:managedScope": [value: "following" | "all"];
  searchTicket: [];
  selectManaged: [jpIssueId: number];
  toggleFollow: [jpIssueId: number, currentlyFollowing: boolean];
  toggleLinkForm: [];
  createManagedTicket: [];
  deleteManagedTicket: [jpIssueId: number];
  refreshRedmineDetail: [];
  openQuickCreate: [issueId?: number];
  cancelQuickCreate: [draftId?: number];
  createChildTicket: [draftId?: number];
  saveAll: [];
  addLink: [];
  copyLink: [url: string];
  copyTeamsThread: [];
  postToTeams: [];
  editLink: [linkId: number, type: string, url: string];
  cancelEditLink: [];
  deleteLink: [linkId: number];
}>();

const linkTypes = ["spec", "thread", "client", "server", "pr"];
const showClosedIssues = ref(false);

const displayLinks = computed(() => {
  if (!props.ticketDetail) return [];

  return [
    { key: `jp-${props.ticketDetail.jp_info.issue_id}`, source: "JP", url: props.ticketDetail.jp_info.url, canManage: false, id: null, type: "jp" },
    { key: `vn-${props.ticketDetail.vn_issue.issue_id}`, source: "VN", url: props.ticketDetail.vn_issue.url, canManage: false, id: null, type: "vn" },
    ...props.ticketDetail.links.map((link) => ({
      key: `link-${link.id}`,
      source: link.type.toUpperCase(),
      url: link.url,
      canManage: true,
      id: link.id,
      type: link.type
    }))
  ];
});

const groupedLinks = computed(() => {
  const groups = new Map<string, typeof displayLinks.value>();
  for (const link of displayLinks.value) {
    const bucket = groups.get(link.source) ?? [];
    bucket.push(link);
    groups.set(link.source, bucket);
  }
  return Array.from(groups.entries()).map(([source, items]) => ({
    source,
    items,
    grouped: items.length > 1
  }));
});

const groupedRelatedIssues = computed(() => {
  if (!props.ticketDetail?.related?.length) return [];

  const groups = new Map<string, Array<(typeof props.ticketDetail.related)[number] & { isClosed: boolean; order: number }>>();
  props.ticketDetail.related.forEach((issue, idx) => {
    const key = issue.tracker || "Other";
    const bucket = groups.get(key) ?? [];
    bucket.push({ ...issue, isClosed: isClosedLike(issue.status), order: idx });
    groups.set(key, bucket);
  });

  return Array.from(groups.entries()).map(([tracker, items]) => ({
    tracker,
    items: items
      .filter((item) => showClosedIssues.value || !item.isClosed)
      .sort((a, b) => Number(a.isClosed) - Number(b.isClosed) || a.order - b.order)
  })).filter((group) => group.items.length > 0);
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

function trackerHeaderClass(tracker: string | null | undefined) {
  const value = (tracker || "").trim().toLowerCase();
  if (value === "story") return "bg-[#EAF1FF] text-[#2F56BA]";
  if (value.includes("sub")) return "bg-sky-50 text-sky-700";
  if (value.includes("bug")) return "bg-rose-50 text-rose-700";
  if (/q\W*a/.test(value) || value.includes("test")) return "bg-emerald-50 text-emerald-700";
  if (value.includes("task")) return "bg-amber-50 text-amber-700";
  return "bg-neutral-50 text-[#5C5E62]";
}

function isSubtaskTracker(tracker: string | null | undefined) {
  return (tracker || "").trim().toLowerCase().includes("sub");
}

function quickCreateFormsForParent(issueId: number) {
  return props.quickCreateForms.filter((draft) => draft.parent_issue_id === issueId);
}

const filteredManagedTickets = computed(() => {
  const rawQuery = props.ticketSearch.trim();
  if (!rawQuery) return props.managedTickets;

  const normalizedQuery = (() => {
    if (/^\d+$/.test(rawQuery)) return rawQuery;

    const issueMatch = rawQuery.match(/\/issues\/(\d+)/i);
    if (issueMatch) return issueMatch[1];

    const allNumbers = rawQuery.match(/\d+/g);
    return allNumbers?.length ? allNumbers[allNumbers.length - 1] : rawQuery;
  })();

  const query = normalizedQuery.trim();
  if (!query) return props.managedTickets;
  return props.managedTickets.filter((item) => String(item.jp_issue_id).startsWith(query));
});

const editableRows = computed(() => {
  if (!props.ticketDetail) return [];
  const rows: Array<{
    kind: "story" | "child";
    issue: { issue_id: number; subject: string; tracker: string; url: string; status: string; allowed_statuses: string[] };
    isClosed: boolean;
    order: number;
    last: boolean;
  }> = [
    {
      kind: "story",
      issue: props.ticketDetail.vn_issue,
      isClosed: isClosedLike(props.ticketDetail.vn_issue.status),
      order: 0,
      last: false
    }
  ];

  props.ticketDetail.children.forEach((child, idx) => {
    rows.push({
      kind: "child",
      issue: child,
      isClosed: isClosedLike(child.status),
      order: idx + 1,
      last: false
    });
  });

  const visibleRows = rows
    .filter((row) => showClosedIssues.value || !row.isClosed)
    .sort((a, b) => Number(a.isClosed) - Number(b.isClosed) || a.order - b.order);

  const childRows = visibleRows.filter((row) => row.kind === "child");
  const lastChildIssueId = childRows.length ? childRows[childRows.length - 1].issue.issue_id : null;

  return visibleRows.map((row) => ({
    ...row,
    last: row.kind === "child" && row.issue.issue_id === lastChildIssueId
  }));
});

function issueStatusOptions(issue: { status: string; allowed_statuses?: string[] }) {
  const names = [issue.status, ...(issue.allowed_statuses ?? [])].filter(Boolean);
  return Array.from(new Set(names)).map((name) => ({
    id: name,
    name
  }));
}

function isClosedLike(status: string | null | undefined) {
  const value = (status || "").trim().toLowerCase();
  return value.includes("close");
}
</script>

<template>
  <section class="grid gap-6">
    <div class="grid gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex items-center justify-between gap-3">
        <div>
          <h3 class="m-0 text-xl font-semibold text-[#171A20]">Managed tickets</h3>
          <p class="mt-1 text-xs text-[#5C5E62]">Type to filter managed tickets. Valid JP IDs load detail automatically. Search logic stays independent from list mode.</p>
        </div>
        <div class="inline-flex rounded-lg border border-neutral-200 bg-white p-1">
          <button
            type="button"
            class="rounded-md px-3 py-1.5 text-xs font-medium transition"
            :class="managedScope === 'following' ? 'bg-[#171A20] text-white' : 'text-[#5C5E62] hover:bg-neutral-100'"
            @click="emit('update:managedScope', 'following')"
          >
            Following
          </button>
          <button
            type="button"
            class="rounded-md px-3 py-1.5 text-xs font-medium transition"
            :class="managedScope === 'all' ? 'bg-[#171A20] text-white' : 'text-[#5C5E62] hover:bg-neutral-100'"
            @click="emit('update:managedScope', 'all')"
          >
            All
          </button>
        </div>
      </div>
      <div class="flex flex-wrap items-end gap-3">
        <div class="min-w-65 flex-1">
          <label class="mb-1 block text-xs font-medium uppercase tracking-wide text-[#5C5E62]">JP issue ID or URL</label>
          <div class="relative">
            <span class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-[#9CA0A6]">
              <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <circle cx="9" cy="9" r="5.5"></circle>
                <path d="m13 13 3.5 3.5"></path>
              </svg>
            </span>
            <input
              :value="ticketSearch"
              placeholder="12345 or https://.../issues/12345"
              class="w-full rounded-lg border border-[#D0D1D2] py-2 pr-3 pl-9 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
              @input="emit('update:ticketSearch', ($event.target as HTMLInputElement).value)"
            />
          </div>
        </div>
      </div>
      <div
        v-if="suggestSyncJpIssueId"
        class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3 text-sm text-amber-800"
      >
        <span>JP issue <span class="font-mono">#{{ suggestSyncJpIssueId }}</span> is not managed yet.</span>
        <button
          type="button"
          class="inline-flex items-center gap-1 rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-medium text-amber-800 transition hover:bg-amber-100"
          @click="emit('createManagedTicket')"
        >
          <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M10 4v12"></path>
            <path d="M4 10h12"></path>
          </svg>
          Sync JP issue
        </button>
      </div>
      <div v-if="loadingManaged" class="flex items-center justify-center gap-3 rounded-xl border border-neutral-200 px-4 py-6 text-sm text-[#5C5E62]">
        <LoadingCircle class="text-[#3E6AE1]" />
        Loading managed tickets...
      </div>
      <div v-else class="overflow-hidden rounded-lg border border-neutral-200">
        <div class="hidden grid-cols-[76px_76px_minmax(0,2.15fr)_104px_116px] gap-3 border-b border-neutral-200 bg-neutral-50 px-3 py-2 text-xs font-medium uppercase tracking-wide text-[#5C5E62] md:grid">
          <span>JP</span>
          <span>VN</span>
          <span>Subject</span>
          <span>Status</span>
          <span>Assignee</span>
        </div>
        <button
          v-for="item in filteredManagedTickets"
          :key="item.managed_ticket_id"
          type="button"
          class="grid w-full gap-3 border-b border-neutral-200 px-3 py-3 text-left transition hover:bg-neutral-50 last:border-b-0 md:grid-cols-[76px_76px_minmax(0,2.15fr)_104px_116px] md:items-center md:py-2"
          @click="emit('selectManaged', item.jp_issue_id)"
        >
          <div class="grid gap-1">
            <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">JP</span>
            <a :href="item.jp_url" target="_blank" rel="noreferrer" class="w-fit rounded bg-white px-1.5 py-0.5 text-xs font-mono text-[#3E6AE1] ring-1 ring-neutral-200 hover:bg-[#F5F8FF]" @click.stop>#{{ item.jp_issue_id }}</a>
          </div>
          <div class="grid gap-1">
            <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">VN</span>
            <a :href="item.vn_url" target="_blank" rel="noreferrer" class="w-fit rounded bg-white px-1.5 py-0.5 text-xs font-mono text-[#3E6AE1] ring-1 ring-neutral-200 hover:bg-[#F5F8FF]" @click.stop>#{{ item.vn_issue_id }}</a>
          </div>
          <div class="grid gap-1">
            <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Subject</span>
            <span class="wrap-break-word text-sm text-[#171A20]">{{ item.subject }}</span>
          </div>
          <div class="grid gap-1">
            <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Status</span>
            <span class="wrap-break-word text-sm text-[#5C5E62]">{{ item.status }}</span>
          </div>
          <div class="grid gap-1">
            <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Assignee</span>
            <div class="flex items-center justify-between gap-2">
              <span class="wrap-break-word text-sm text-[#5C5E62]">{{ item.assignee || "Unassigned" }}</span>
              <div class="flex items-center gap-2">
                <span
                  role="button"
                  tabindex="0"
                  class="flex size-7 shrink-0 items-center justify-center rounded-full border border-neutral-200 bg-white transition hover:bg-neutral-100"
                  :class="item.is_following ? 'text-amber-500' : 'text-[#9CA0A6]'"
                  :title="item.is_following ? 'Unfollow ticket' : 'Follow ticket'"
                  @click.stop="emit('toggleFollow', item.jp_issue_id, item.is_following)"
                  @keydown.enter.stop.prevent="emit('toggleFollow', item.jp_issue_id, item.is_following)"
                >
                  <svg viewBox="0 0 20 20" class="size-4" :fill="item.is_following ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="m10 2.8 2.16 4.37 4.82.7-3.49 3.4.82 4.8L10 13.78 5.69 16.07l.82-4.8-3.49-3.4 4.82-.7L10 2.8Z"></path>
                  </svg>
                </span>
              </div>
            </div>
          </div>
        </button>
        <div v-if="!filteredManagedTickets.length" class="px-3 py-6 text-center text-sm text-[#9CA0A6]">
          {{ managedTickets.length ? "No matching tickets." : managedScope === 'following' ? "No followed tickets yet." : "No managed tickets yet." }}
        </div>
      </div>
    </div>

    <div v-if="loadingDetail" class="flex items-center justify-center gap-3 rounded-2xl border border-neutral-200 bg-white px-6 py-10 text-sm text-[#5C5E62] shadow-sm">
      <LoadingCircle class="text-[#3E6AE1]" />
      Loading ticket detail...
    </div>

    <div v-else-if="ticketDetail" class="grid gap-6">
      <div class="grid gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <h3 class="m-0 text-xl font-semibold text-[#171A20]">Issues</h3>
            <button
              type="button"
              class="inline-flex items-center gap-3 rounded-full border px-3 py-1.5 text-xs font-medium transition"
              :class="showClosedIssues ? 'border-[#3E6AE1] bg-[#EAF1FF] text-[#2F56BA]' : 'border-neutral-200 bg-white text-[#5C5E62] hover:bg-neutral-50'"
              :aria-pressed="showClosedIssues"
              @click="showClosedIssues = !showClosedIssues"
            >
              <span
                class="relative h-5 w-9 rounded-full transition"
                :class="showClosedIssues ? 'bg-[#3E6AE1]' : 'bg-neutral-300'"
              >
                <span
                  class="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition"
                  :class="showClosedIssues ? 'translate-x-4' : 'translate-x-0'"
                ></span>
              </span>
              Show close/inclose
            </button>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="inline-flex size-8 shrink-0 items-center justify-center rounded-lg border border-neutral-200 bg-white text-[#5C5E62] transition hover:border-[#3E6AE1] hover:bg-[#F5F8FF] hover:text-[#3E6AE1] disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="refreshingDetail"
              title="Refresh from Redmine"
              @click="emit('refreshRedmineDetail')"
            >
              <LoadingCircle v-if="refreshingDetail" class="size-4" />
              <svg v-else viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M16 9a6 6 0 0 0-10.24-4.24L4 6.5"></path>
                <path d="M4 3.5v3h3"></path>
                <path d="M4 11a6 6 0 0 0 10.24 4.24L16 13.5"></path>
                <path d="M16 16.5v-3h-3"></path>
              </svg>
            </button>
            <button
              v-if="isAdmin"
              type="button"
              class="inline-flex items-center justify-center gap-1 rounded-lg border border-red-200 bg-red-50 px-3 py-1 text-sm font-medium text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="deletingManagedJpIssueId === ticketDetail.jp_issue_id"
              @click="emit('deleteManagedTicket', ticketDetail.jp_issue_id)"
            >
              <LoadingCircle v-if="deletingManagedJpIssueId === ticketDetail.jp_issue_id" class="size-4" />
              <svg v-else viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M6 6.5h8"></path>
                <path d="M7.5 10h5"></path>
                <path d="M4.5 10h1.5"></path>
                <path d="M14 10h1.5"></path>
              </svg>
              {{ deletingManagedJpIssueId === ticketDetail.jp_issue_id ? "Unlinking..." : "Unlink" }}
            </button>
            <span class="inline-flex rounded-full bg-[#F4F4F4] px-3 py-1 text-sm font-medium text-[#393C41]">#{{ ticketDetail.jp_issue_id }}</span>
          </div>
        </div>

        <div class="overflow-visible rounded-lg border border-neutral-200">
          <div class="hidden grid-cols-[140px_minmax(0,1fr)_120px_120px] gap-3 rounded-t-lg border-neutral-200 bg-neutral-50 px-3 py-2 text-xs font-medium uppercase tracking-wide text-[#5C5E62] md:grid pr-6">
            <span>Type / ID</span>
            <span>Subject</span>
            <span>Status</span>
            <span>Assignee</span>
          </div>

          <div
            v-if="ticketDetail.parent"
            class="relative grid gap-3 border-neutral-200 bg-amber-50/40 px-3 py-3 pr-6 md:grid-cols-[140px_minmax(0,1fr)_120px_120px] md:items-center md:py-2"
          >
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Type / ID</span>
              <span class="inline-flex w-fit rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">Parent</span>
              <span class="rounded bg-white px-1.5 py-0.5 text-xs font-mono text-amber-700 ring-1 ring-amber-200">#{{ ticketDetail.parent.issue_id }}</span>
            </div>
            <div class="grid gap-1">
              <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Subject</span>
              <a :href="ticketDetail.parent.url" target="_blank" rel="noreferrer" class="wrap-break-word text-sm text-[#171A20] hover:text-[#3E6AE1] hover:underline">
                {{ ticketDetail.parent.subject }}
              </a>
            </div>
            <div class="grid gap-1">
              <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Status</span>
              <span class="wrap-break-word text-sm text-[#5C5E62]">{{ ticketDetail.parent.status }}</span>
            </div>
            <div class="grid gap-1">
              <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Assignee</span>
              <span class="wrap-break-word text-sm text-[#5C5E62]">{{ ticketDetail.parent.assignee || "Unassigned" }}</span>
            </div>
            <div class="absolute top-1/2 right-0 z-10 translate-x-1/2 -translate-y-1/2">
              <button
                v-if="!isSubtaskTracker(ticketDetail.parent.tracker)"
                type="button"
                class="flex size-6 items-center justify-center rounded-full border border-neutral-200 bg-white text-[#5C5E62] shadow-sm transition hover:border-[#3E6AE1] hover:bg-[#F5F8FF] hover:text-[#3E6AE1]"
                title="Create subtask"
                @click="emit('openQuickCreate', ticketDetail.parent.issue_id)"
              >
                <svg viewBox="0 0 20 20" fill="none" class="size-3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M10 4v12"></path>
                  <path d="M4 10h12"></path>
                </svg>
              </button>
            </div>
          </div>
          <QuickCreateTaskRow
            v-for="draft in ticketDetail.parent ? quickCreateFormsForParent(ticketDetail.parent.issue_id) : []"
            :key="`quick-create-parent-${draft.id}`"
            from="detail"
            :draft="draft"
            :tracker-options="trackerOptions"
            :assignee-options="assigneeOptions"
            :creating-child="creatingChild"
            @create="emit('createChildTicket', $event)"
            @cancel="emit('cancelQuickCreate', $event)"
          />

          <template
            v-for="row in editableRows"
            :key="row.issue.issue_id"
          >
            <div
              class="relative grid gap-3 border-t border-neutral-200 px-3 py-3 pr-6 transition last:rounded-b-lg last:border-b-0 md:grid-cols-[140px_minmax(0,1fr)_120px_120px] md:items-center md:py-2"
              :class="row.isClosed ? 'bg-neutral-100 text-[#7A7D81]' : row.kind === 'story' ? 'bg-[#F5F8FF]' : 'hover:bg-neutral-50'"
            >
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Type / ID</span>
                <span
                  v-if="row.kind === 'story'"
                  :class="['inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold', trackerBadgeClass('Story')]"
                >Story</span>
                <span
                  v-else
                  :class="['inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', trackerBadgeClass(row.issue.tracker || 'Child')]"
                >{{ row.issue.tracker || "Child" }}</span>
                <span class="rounded bg-white px-1.5 py-0.5 text-xs font-mono text-[#3E6AE1] ring-1 ring-neutral-200">#{{ row.issue.issue_id }}</span>
              </div>
              <div class="grid gap-1">
                <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Subject</span>
                <a
                  :href="row.issue.url"
                  target="_blank"
                  rel="noreferrer"
                  class="flex items-start gap-2 wrap-break-word text-sm hover:text-[#3E6AE1] hover:underline"
                  :class="row.isClosed ? 'text-[#7A7D81]' : row.kind === 'story' ? 'font-medium text-[#171A20]' : 'text-[#171A20]'"
                >
                  <span v-if="row.kind === 'child'" class="select-none font-mono text-xs leading-5 text-[#9CA0A6]">{{ row.last ? "L-" : "|-" }}</span>
                  <span>{{ row.issue.subject }}</span>
                </a>
              </div>
              <div class="grid gap-1">
                <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Status</span>
                <select
                  v-model="ticketEdit[row.issue.issue_id].status"
                  class="w-full rounded-lg border border-[#D0D1D2] px-1 py-1 text-sm outline-none transition focus:border-[#3E6AE1]"
                  :class="row.isClosed ? 'bg-neutral-50 text-[#7A7D81]' : 'bg-white text-[#171A20]'"
                >
                  <option v-for="status in issueStatusOptions(row.issue)" :key="status.id" :value="status.name">{{ status.name }}</option>
                </select>
              </div>
              <div class="grid gap-1">
                <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Assignee</span>
                <select
                  v-model="ticketEdit[row.issue.issue_id].assignee"
                  class="w-full rounded-lg border border-[#D0D1D2] px-1 py-1 text-sm outline-none transition focus:border-[#3E6AE1]"
                  :class="row.isClosed ? 'bg-neutral-50 text-[#7A7D81]' : 'bg-white text-[#171A20]'"
                >
                  <option value="">Unassigned</option>
                  <option v-for="assignee in assigneeOptions" :key="assignee.id" :value="assignee.name">{{ assignee.name }}</option>
                </select>
              </div>
              <div class="absolute top-1/2 right-0 z-10 translate-x-1/2 -translate-y-1/2">
                <button
                  v-if="!isSubtaskTracker(row.issue.tracker)"
                  type="button"
                  class="flex size-6 items-center justify-center rounded-full border border-neutral-200 bg-white text-[#5C5E62] shadow-sm transition hover:border-[#3E6AE1] hover:bg-[#F5F8FF] hover:text-[#3E6AE1]"
                  title="Create subtask"
                  @click="emit('openQuickCreate', row.issue.issue_id)"
                >
                  <svg viewBox="0 0 20 20" fill="none" class="size-3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M10 4v12"></path>
                    <path d="M4 10h12"></path>
                  </svg>
                </button>
              </div>
            </div>

            <QuickCreateTaskRow
              v-for="draft in quickCreateFormsForParent(row.issue.issue_id)"
              :key="`quick-create-${draft.id}`"
              :draft="draft"
              from="detail"
              :tracker-options="trackerOptions"
              :assignee-options="assigneeOptions"
              :creating-child="creatingChild"
              @create="emit('createChildTicket', $event)"
              @cancel="emit('cancelQuickCreate', $event)"
            />
          </template>
        </div>

        <div class="flex flex-wrap items-center justify-end gap-3 pt-2">
          <button
            type="button"
            class="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-[#3E6AE1] px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="saving"
            @click="emit('saveAll')"
          >
            <LoadingCircle v-if="saving" />
            {{ saving ? "Saving..." : "Save changes" }}
          </button>
        </div>

        <div v-if="groupedRelatedIssues.length" class="grid gap-2 rounded-xl border border-neutral-200 bg-neutral-50/60 p-3">
          <p class="text-xs font-semibold uppercase tracking-[0.08em] text-[#5C5E62]">Related VN issues</p>
          <div class="grid gap-3">
            <div v-for="group in groupedRelatedIssues" :key="group.tracker" class="overflow-visible rounded-lg border border-neutral-200 bg-white">
              <div class="rounded-t-lg border-neutral-200 px-3 py-2 text-xs font-semibold uppercase tracking-[0.08em]" :class="trackerHeaderClass(group.tracker)">
                {{ group.tracker }}
              </div>
              <div class="hidden grid-cols-[104px_minmax(0,1fr)_80px_80px] gap-3 border-t border-neutral-200 bg-neutral-50 px-3 py-2 text-xs font-medium uppercase tracking-wide text-[#5C5E62] md:grid pr-6">
                <span>Issue</span>
                <span>Subject</span>
                <span>Status</span>
                <span>Assignee</span>
              </div>
              <template
                v-for="rel in group.items"
                :key="rel.issue_id"
              >
                <div
                  class="relative grid gap-3 border-t border-neutral-200 px-3 py-3 pr-6 text-sm transition last:rounded-b-lg last:border-b-0 md:grid-cols-[104px_minmax(0,1fr)_80px_80px] md:items-center md:py-2"
                  :class="rel.isClosed ? 'bg-neutral-100 text-[#7A7D81]' : 'text-[#171A20] hover:bg-neutral-50'"
                >
                  <div class="grid gap-1">
                    <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Issue</span>
                    <span class="w-fit rounded bg-white px-1.5 py-0.5 text-xs font-mono text-[#3E6AE1] ring-1 ring-neutral-200">#{{ rel.issue_id }}</span>
                  </div>
                  <div class="grid gap-1">
                    <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Subject</span>
                    <a :href="rel.url" target="_blank" rel="noreferrer" class="wrap-break-word hover:text-[#3E6AE1] hover:underline" :class="rel.isClosed ? 'text-[#7A7D81]' : 'text-[#171A20]'">{{ rel.subject }}</a>
                  </div>
                  <div class="grid gap-1">
                    <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Status</span>
                    <span :class="rel.isClosed ? 'text-[#7A7D81]' : 'text-[#5C5E62]'">{{ rel.status }}</span>
                  </div>
                  <div class="grid gap-1">
                    <span class="text-[11px] font-medium uppercase tracking-wide text-[#5C5E62] md:hidden">Assignee</span>
                    <span :class="rel.isClosed ? 'text-[#7A7D81]' : 'text-[#5C5E62]'">{{ rel.assignee || "Unassigned" }}</span>
                  </div>
                  <div class="absolute top-1/2 right-0 z-10 translate-x-1/2 -translate-y-1/2">
                    <button
                      v-if="!isSubtaskTracker(rel.tracker)"
                      type="button"
                      class="flex size-6 items-center justify-center rounded-full border border-neutral-200 bg-white text-[#5C5E62] shadow-sm transition hover:border-[#3E6AE1] hover:bg-[#F5F8FF] hover:text-[#3E6AE1]"
                      title="Create subtask"
                      @click="emit('openQuickCreate', rel.issue_id)"
                    >
                      <svg viewBox="0 0 20 20" fill="none" class="size-3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path d="M10 4v12"></path>
                        <path d="M4 10h12"></path>
                      </svg>
                    </button>
                  </div>
                </div>
                <QuickCreateTaskRow
                  v-for="draft in quickCreateFormsForParent(rel.issue_id)"
                  :key="`quick-create-related-${draft.id}`"
                  from="related"
                  :draft="draft"
                  :tracker-options="trackerOptions"
                  :assignee-options="assigneeOptions"
                  :creating-child="creatingChild"
                  @create="emit('createChildTicket', $event)"
                  @cancel="emit('cancelQuickCreate', $event)"
                />
              </template>
            </div>
          </div>
        </div>
      </div>

      <div class="grid gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
        <div class="flex items-center justify-between gap-3">
          <div>
            <h3 class="m-0 text-xl font-semibold text-[#171A20]">Links</h3>
            <p class="mt-1 text-xs text-[#5C5E62]">Spec / thread / build / PR.</p>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100"
              @click="emit('copyTeamsThread')"
            >
              <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <rect x="7" y="7" width="9" height="9" rx="2"></rect>
                <path d="M4 13V5a2 2 0 0 1 2-2h8"></path>
              </svg>
              Copy Teams Thread
            </button>
            <button
              v-if="canPostToTeams"
              type="button"
              class="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-[#3E6AE1] px-3 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="postingTeams"
              @click="emit('postToTeams')"
            >
              <LoadingCircle v-if="postingTeams" />
              <svg v-else viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M4 5.5h12"></path>
                <path d="M4 10h8"></path>
                <path d="M4 14.5h5"></path>
                <path d="m12.5 13.5 2 2 3-4"></path>
              </svg>
              {{ postingTeams ? "Posting..." : "Post to Teams" }}
            </button>
            <button
              type="button"
              class="flex size-9 items-center justify-center rounded-full border border-neutral-200 bg-white text-[#171A20] transition hover:bg-neutral-100"
              title="Add link"
              @click="emit('toggleLinkForm')"
            >
              <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M10 4v12"></path>
                <path d="M4 10h12"></path>
              </svg>
            </button>
          </div>
        </div>

        <div class="grid gap-3">
          <div v-for="group in groupedLinks" :key="group.source" class="grid gap-2">
            <div v-if="group.grouped" class="px-1 text-xs font-semibold uppercase tracking-[0.08em] text-[#5C5E62]">{{ group.source }}</div>
            <div
              v-for="link in group.items"
              :key="link.key"
              class="flex items-center gap-3 rounded-xl border border-neutral-200 p-2 text-sm text-[#171A20] transition hover:bg-neutral-50"
            >
              <span class="inline-flex min-w-16 justify-center rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium uppercase tracking-wide text-[#5C5E62]">{{ link.source }}</span>
              <template v-if="link.canManage && link.id && editingLinkId === link.id">
                <div class="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                  <div class="flex flex-wrap gap-2">
                    <button
                      v-for="type in linkTypes"
                      :key="`${link.key}-${type}`"
                      type="button"
                      class="rounded-full border px-2 py-1 text-xs transition"
                      :class="linkForm.type === type ? 'border-[#3E6AE1] bg-[#F5F8FF] text-[#3E6AE1]' : 'border-neutral-200 bg-white text-[#393C41] hover:bg-neutral-100'"
                      @click="linkForm.type = type"
                    >
                      {{ type }}
                    </button>
                  </div>
                  <input v-model="linkForm.url" placeholder="https://..." class="min-w-65 flex-1 rounded-lg border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
                  <button
                    type="button"
                    class="flex size-10 items-center justify-center rounded-lg bg-[#3E6AE1] text-white transition hover:brightness-95"
                    title="Update link"
                    @click="emit('addLink')"
                  >
                    <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path d="m4.5 10 3.5 3.5 7.5-8"></path>
                    </svg>
                  </button>
                  <button
                    type="button"
                    class="flex size-10 items-center justify-center rounded-lg border border-red-200 bg-red-50 text-red-700 transition hover:bg-red-100"
                    title="Delete link"
                    @click="emit('deleteLink', link.id)"
                  >
                    <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path d="M4.5 6.5h11"></path>
                      <path d="M8 6.5V5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1.5"></path>
                      <path d="M6.5 6.5 7 15a1 1 0 0 0 1 .94h4a1 1 0 0 0 1-.94l.5-8.5"></path>
                    </svg>
                  </button>
                  <button
                    type="button"
                    class="flex size-10 items-center justify-center rounded-lg border border-neutral-200 bg-white text-[#393C41] transition hover:bg-neutral-100"
                    title="Cancel edit"
                    @click="emit('cancelEditLink')"
                  >
                    <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path d="m5 5 10 10"></path>
                      <path d="M15 5 5 15"></path>
                    </svg>
                  </button>
                </div>
              </template>
              <a
                v-else
                :href="link.url"
                target="_blank"
                rel="noreferrer"
                class="min-w-0 flex-1 break-all text-[#3E6AE1]"
              >
                {{ link.url }}
              </a>
              <button
                v-if="link.canManage && link.id && editingLinkId !== link.id"
                type="button"
                class="flex size-8 shrink-0 items-center justify-center rounded-full border border-neutral-200 bg-white text-[#5C5E62] transition hover:bg-neutral-100 hover:text-[#171A20]"
                title="Edit link"
                @click.prevent="emit('editLink', link.id, link.type, link.url)"
              >
                <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M3 14.75V17h2.25L15.5 6.75 13.25 4.5 3 14.75Z"></path>
                  <path d="M12.5 5.25 14.75 7.5"></path>
                </svg>
              </button>
              <button
                type="button"
                class="flex size-8 shrink-0 items-center justify-center rounded-full border border-neutral-200 bg-white text-[#5C5E62] transition hover:bg-neutral-100 hover:text-[#171A20]"
                title="Copy link"
                @click.prevent="emit('copyLink', link.url)"
              >
                <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <rect x="7" y="7" width="9" height="9" rx="2"></rect>
                  <path d="M4 13V5a2 2 0 0 1 2-2h8"></path>
                </svg>
              </button>
            </div>
          </div>
          <div v-if="!displayLinks.length && !showLinkForm" class="rounded-xl border border-dashed border-neutral-300 px-4 py-6 text-center text-sm text-[#9CA0A6]">No links yet.</div>
        </div>

        <div v-if="showLinkForm" class="flex flex-wrap items-center gap-3 rounded-xl border border-neutral-200 p-2">
          <div class="flex flex-wrap gap-2">
            <button
              v-for="type in linkTypes"
              :key="type"
              type="button"
              class="rounded-full border px-3 py-1.5 text-sm transition"
              :class="linkForm.type === type ? 'border-[#3E6AE1] bg-[#F5F8FF] text-[#3E6AE1]' : 'border-neutral-200 bg-white text-[#393C41] hover:bg-neutral-100'"
              @click="linkForm.type = type"
            >
              {{ type }}
            </button>
          </div>
          <input v-model="linkForm.url" placeholder="https://..." class="min-w-[320px] flex-1 rounded-lg border border-[#D0D1D2] px-2 py-1.5 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
          <button
            type="button"
            class="flex size-8 items-center justify-center rounded-lg bg-[#3E6AE1] text-white transition hover:brightness-95"
            :title="editingLinkId ? 'Update link' : 'Save link'"
            @click="emit('addLink')"
          >
            <svg v-if="editingLinkId" viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="m4.5 10 3.5 3.5 7.5-8"></path>
            </svg>
            <svg v-else viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M10 4v12"></path>
              <path d="M4 10h12"></path>
            </svg>
          </button>
          <button
            type="button"
            class="flex size-8 items-center justify-center rounded-lg border border-neutral-200 bg-white text-[#393C41] transition hover:bg-neutral-100"
            title="Cancel link form"
            @click="emit('toggleLinkForm')"
          >
            <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="m5 5 10 10"></path>
              <path d="M15 5 5 15"></path>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
