<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import TicketDetailView from "./TicketDetailView.vue";
import { ticketsApi } from "./api";
import { showToast } from "../../shared/toast";
import type { Assignee, ManagedTicketListItem, QuickCreateDraft, StatusOption, TicketDetail } from "../../shared/types";
import { usersApi } from "../users/api";
import { sessionState } from "../../shared/session";
import { copyClipboard, copyText, escapeHtml } from "../../shared/clipboard";

const router = useRouter();
const route = useRoute();
const ticketSearch = ref("");
const managedScope = ref<"following" | "all">("following");
const ticketDetail = ref<TicketDetail | null>(null);
const managedTickets = ref<ManagedTicketListItem[]>([]);
const loadingManaged = ref(false);
const statusOptions = ref<StatusOption[]>([]);
const assigneeOptions = ref<Assignee[]>([]);
const ticketEdit = reactive<Record<number, { status: string; assignee: string }>>({});
const ticketEditOriginal = reactive<Record<number, { status: string; assignee: string }>>({});
const linkForm = reactive({ type: "spec", url: "" });
const showLinkForm = ref(false);
const editingLinkId = ref<number | null>(null);
const loadingDetail = ref(false);
const refreshingDetail = ref(false);
const saving = ref(false);
const deletingManagedJpIssueId = ref<number | null>(null);
const suggestSyncJpIssueId = ref<number | null>(null);
const creatingChild = ref(false);
const postingTeams = ref(false);
const quickCreateForms = reactive<QuickCreateDraft[]>([]);
let quickCreateDraftId = 0;
const defaultQuickCreateAssigneeId = () => sessionState.userSettings.default_assignee_id ?? sessionState.assignees[0]?.id ?? null;
const AUTO_SEARCH_DELAY_MS = 500;
let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null;
let skipNextAutoSearch = false;

async function loadManaged() {
  loadingManaged.value = true;
  try {
    managedTickets.value = await ticketsApi.managed(managedScope.value);
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    loadingManaged.value = false;
  }
}

async function loadOptions() {
  try {
    statusOptions.value = await usersApi.statuses();
  } catch (error) {
    showToast((error as Error).message, "error");
  }
  assigneeOptions.value = sessionState.assignees;
}

function parseJpIssueInput(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (/^\d+$/.test(trimmed)) return Number(trimmed);

  const issueMatch = trimmed.match(/\/issues\/(\d+)/i);
  if (issueMatch) return Number(issueMatch[1]);

  const allNumbers = trimmed.match(/\d+/g);
  if (!allNumbers?.length) return null;
  return Number(allNumbers[allNumbers.length - 1]);
}

function snapshotEdit(issueId: number, status: string, assignee: string) {
  ticketEdit[issueId] = { status, assignee };
  ticketEditOriginal[issueId] = { status, assignee };
}

function applyTicketDetail(detail: TicketDetail, preserveQuickCreate = false) {
  ticketDetail.value = detail;
  ticketSearch.value = String(detail.jp_issue_id);
  if (!preserveQuickCreate) {
    quickCreateForms.splice(0);
  }
  suggestSyncJpIssueId.value = null;
  snapshotEdit(detail.vn_issue.issue_id, detail.vn_issue.status, detail.vn_issue.assignee ?? "");
  for (const child of detail.children) {
    snapshotEdit(child.issue_id, child.status, child.assignee ?? "");
  }
}

async function loadByJpIssueId(
  jpIssueId: number,
  options?: { notifyLoaded?: boolean; notifyMissing?: boolean; preserveQuickCreate?: boolean }
): Promise<boolean> {
  const notifyLoaded = options?.notifyLoaded ?? true;
  const notifyMissing = options?.notifyMissing ?? true;
  const preserveQuickCreate = options?.preserveQuickCreate ?? false;
  loadingDetail.value = true;
  try {
    const searchResult = await ticketsApi.search(jpIssueId);
    if (!searchResult.exists) {
      ticketDetail.value = null;
      suggestSyncJpIssueId.value = jpIssueId;
      if (notifyMissing) {
        showToast("JP issue is not managed yet. Sync it first.", "warning");
      }
      return false;
    }

    applyTicketDetail(await ticketsApi.detail(jpIssueId), preserveQuickCreate);
    if (notifyLoaded) {
      showToast("Ticket loaded", "success");
    }
    return true;
  } catch (error) {
    ticketDetail.value = null;
    showToast((error as Error).message, "error");
    return false;
  } finally {
    loadingDetail.value = false;
  }
}

async function refreshRedmineDetail() {
  if (!ticketDetail.value) {
    return;
  }

  refreshingDetail.value = true;
  try {
    const detail = await ticketsApi.detail(ticketDetail.value.jp_issue_id, true);
    applyTicketDetail(detail, true);
    showToast("Redmine detail refreshed", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    refreshingDetail.value = false;
  }
}

function currentRouteJpIssueId() {
  const raw = route.params.jpIssueId;
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

async function syncDetailRoute(jpIssueId: number | null, mode: "push" | "replace" = "replace") {
  const currentJpIssueId = currentRouteJpIssueId();
  if (jpIssueId == null) {
    if (currentJpIssueId != null) {
      await router.replace({ name: "detail" });
    }
    return;
  }
  if (currentJpIssueId === jpIssueId) {
    return;
  }
  await router[mode]({ name: "detail", params: { jpIssueId: String(jpIssueId) } });
}

async function load(options?: { notifyInvalid?: boolean; notifyLoaded?: boolean; notifyMissing?: boolean }) {
  const notifyInvalid = options?.notifyInvalid ?? true;
  const jpIssueId = parseJpIssueInput(ticketSearch.value);
  if (!jpIssueId) {
    suggestSyncJpIssueId.value = null;
    if (notifyInvalid) {
      showToast("Enter a JP issue ID or URL", "warning");
    }
    return;
  }

  skipNextAutoSearch = ticketSearch.value !== String(jpIssueId);
  ticketSearch.value = String(jpIssueId);
  const loaded = await loadByJpIssueId(jpIssueId, options);
  if (loaded) {
    await syncDetailRoute(jpIssueId, "replace");
  }
}

async function selectManaged(jpIssueId: number) {
  if (currentRouteJpIssueId() === jpIssueId) {
    await loadByJpIssueId(jpIssueId);
    return;
  }
  await syncDetailRoute(jpIssueId, "push");
}

async function saveAll() {
  if (!ticketDetail.value) return;
  const dirty = Object.keys(ticketEdit)
    .map((id) => Number(id))
    .filter((id) => {
      const cur = ticketEdit[id];
      const orig = ticketEditOriginal[id];
      return !orig || cur.status !== orig.status || cur.assignee !== orig.assignee;
    });
  if (!dirty.length) {
    showToast("Nothing to save", "warning");
    return;
  }
  saving.value = true;
  try {
    const results = await Promise.allSettled(
      dirty.map((id) => ticketsApi.updateIssue(id, ticketEdit[id]))
    );
    const failed = results.filter((r) => r.status === "rejected");
    if (failed.length) {
      showToast(`Saved ${results.length - failed.length}/${results.length}; ${failed.length} failed`, "warning");
    } else {
      showToast(`Saved ${results.length} ticket${results.length > 1 ? "s" : ""}`, "success");
    }
    await load();
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    saving.value = false;
  }
}

async function addLink() {
  try {
    if (editingLinkId.value) {
      await ticketsApi.updateLink(editingLinkId.value, linkForm);
      showToast("Link updated", "success");
    } else {
      if (!ticketDetail.value) {
        showToast("Load a managed ticket first", "warning");
        return;
      }
      await ticketsApi.upsertLink(ticketDetail.value.jp_issue_id, linkForm);
      showToast("Link saved", "success");
    }
    linkForm.url = "";
    linkForm.type = "spec";
    editingLinkId.value = null;
    showLinkForm.value = false;
    await load();
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

function startEditLink(linkId: number, type: string, url: string) {
  editingLinkId.value = linkId;
  linkForm.type = type;
  linkForm.url = url;
  showLinkForm.value = false;
}

function cancelEditLink() {
  editingLinkId.value = null;
  linkForm.type = "spec";
  linkForm.url = "";
}

async function deleteLink(linkId: number) {
  try {
    await ticketsApi.deleteLink(linkId);
    if (editingLinkId.value === linkId) {
      editingLinkId.value = null;
      linkForm.type = "spec";
      linkForm.url = "";
      showLinkForm.value = false;
    }
    showToast("Link deleted", "success");
    await load();
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function copyLink(url: string) {
  try {
    await copyText(url);
    showToast("Link copied", "success");
  } catch {
    showToast("Cannot copy link", "error");
  }
}

async function copyTeamThread() {
  if (!ticketDetail.value) {
    showToast("Load a managed ticket first", "warning");
    return;
  }

  const findLink = (type: string) => ticketDetail.value?.links.find((link) => link.type === type)?.url;
  const lines = [
    `#${ticketDetail.value.jp_issue_id}: ${ticketDetail.value.jp_info.subject}`,
    "",
    "Ticket JP:",
    ticketDetail.value.jp_info.url,
    "",
    "Ticket VN:",
    ticketDetail.value.vn_issue.url
  ];

  const optionalSections = [
    { label: "Spec:", url: findLink("spec") },
    { label: "Pull request:", url: findLink("pr") },
    { label: "Client build:", url: findLink("client") },
    { label: "Server build:", url: findLink("server") }
  ].filter((item) => item.url);

  for (const section of optionalSections) {
    lines.push("", section.label, section.url as string);
  }

  const htmlParts = [
    `<div>#${ticketDetail.value.jp_issue_id}: ${escapeHtml(ticketDetail.value.jp_info.subject)}</div>`,
    "<br>",
    "<div><b>Ticket JP:</b></div>",
    `<div>${escapeHtml(ticketDetail.value.jp_info.url)}</div>`,
    "<br>",
    "<div><b>Ticket VN:</b></div>",
    `<div>${escapeHtml(ticketDetail.value.vn_issue.url)}</div>`
  ];

  for (const section of optionalSections) {
    htmlParts.push(
      "<br>",
      `<div><b>${escapeHtml(section.label)}</b></div>`,
      `<div>${escapeHtml(section.url as string)}</div>`
    );
  }

  try {
    await copyClipboard({
      text: lines.join("\n"),
      html: htmlParts.join("")
    });
    showToast("Team thread format copied", "success");
  } catch {
    showToast("Cannot copy team thread format", "error");
  }
}

async function postToTeams() {
  if (!ticketDetail.value) {
    showToast("Load a managed ticket first", "warning");
    return;
  }
  if (!sessionState.userSettings.team_automate_url?.trim()) {
    showToast("Team Automate URL is not configured", "warning");
    return;
  }
  if (!window.confirm(`Post JP #${ticketDetail.value.jp_issue_id} to Teams?`)) {
    return;
  }

  postingTeams.value = true;
  try {
    const result = await ticketsApi.postTeamThread(ticketDetail.value.jp_issue_id);
    ticketDetail.value.links = result.links;
    showToast("Posted to Teams and saved thread link", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    postingTeams.value = false;
  }
}

function openQuickCreate(issueId?: number) {
  if (!ticketDetail.value) {
    showToast("Load a managed ticket first", "warning");
    return;
  }

  quickCreateForms.push({
    id: ++quickCreateDraftId,
    tracker: "Sub-task",
    parent_issue_id: issueId ?? ticketDetail.value.vn_issue.issue_id,
    subject: "",
    description: "",
    assignee_id: defaultQuickCreateAssigneeId()
  });
}

function cancelQuickCreate(draftId?: number) {
  if (draftId != null) {
    const draftIndex = quickCreateForms.findIndex((draft) => draft.id === draftId);
    if (draftIndex >= 0) {
      quickCreateForms.splice(draftIndex, 1);
    }
    return;
  }
  quickCreateForms.splice(0);
}

async function createChildTicket(draftId?: number) {
  const draft = draftId != null ? quickCreateForms.find((item) => item.id === draftId) : null;
  if (!draft) {
    showToast("Task row is no longer available", "warning");
    return;
  }
  if (!ticketDetail.value || !draft.parent_issue_id) {
    showToast("Select a parent issue first", "warning");
    return;
  }
  if (!draft.subject.trim()) {
    showToast("Enter a task subject", "warning");
    return;
  }

  creatingChild.value = true;
  try {
    const created = await ticketsApi.createChild(ticketDetail.value.jp_issue_id, {
      parent_issue_id: draft.parent_issue_id,
      subject: draft.subject.trim(),
      description: draft.description.trim() || null,
      assignee_id: draft.assignee_id,
      tracker: draft.tracker
    });
    showToast(`Created ${created.tracker} #${created.issue_id}`, "success");
    cancelQuickCreate(draftId);
    await loadByJpIssueId(ticketDetail.value.jp_issue_id, { notifyLoaded: false, preserveQuickCreate: true });
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    creatingChild.value = false;
  }
}

async function createManagedTicket() {
  const jpIssueId = suggestSyncJpIssueId.value ?? parseJpIssueInput(ticketSearch.value);
  if (!jpIssueId) {
    showToast("Enter a JP issue ID or URL first", "warning");
    return;
  }

  await router.push({ name: "sync", query: { jpIssueId: String(jpIssueId) } });
}

loadOptions();

async function deleteManagedTicket(jpIssueId: number) {
  if (!window.confirm(`Unlink managed ticket for JP #${jpIssueId}? This only removes the mapping in ct_tool.`)) {
    return;
  }

  deletingManagedJpIssueId.value = jpIssueId;
  try {
    await ticketsApi.deleteManaged(jpIssueId);
    if (ticketDetail.value?.jp_issue_id === jpIssueId) {
      ticketDetail.value = null;
      ticketSearch.value = "";
      quickCreateForms.splice(0);
      await syncDetailRoute(null);
    }
    suggestSyncJpIssueId.value = jpIssueId;
    await loadManaged();
    showToast("Managed ticket unlinked", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    deletingManagedJpIssueId.value = null;
  }
}

async function toggleFollow(jpIssueId: number, currentlyFollowing: boolean) {
  try {
    if (currentlyFollowing) {
      await ticketsApi.unfollow(jpIssueId);
    } else {
      await ticketsApi.follow(jpIssueId);
    }

    if (ticketDetail.value?.jp_issue_id === jpIssueId) {
      ticketDetail.value.is_following = !currentlyFollowing;
    }

    await loadManaged();
    showToast(currentlyFollowing ? "Ticket unfollowed" : "Ticket followed", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

watch(
  managedScope,
  async () => {
    await loadManaged();
  },
  { immediate: true }
);

watch(
  () => route.params.jpIssueId,
  async () => {
    const jpIssueId = currentRouteJpIssueId();
    if (jpIssueId == null) {
      return;
    }
    if (ticketDetail.value?.jp_issue_id === jpIssueId && ticketSearch.value === String(jpIssueId)) {
      return;
    }
    skipNextAutoSearch = true;
    ticketSearch.value = String(jpIssueId);
    await loadByJpIssueId(jpIssueId, { notifyLoaded: false, notifyMissing: true });
  },
  { immediate: true }
);

watch(ticketSearch, (value) => {
  if (skipNextAutoSearch) {
    skipNextAutoSearch = false;
    return;
  }

  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = null;
  }

  const jpIssueId = parseJpIssueInput(value);
  if (!jpIssueId) {
    suggestSyncJpIssueId.value = null;
    return;
  }

  if (ticketDetail.value?.jp_issue_id === jpIssueId && !suggestSyncJpIssueId.value) {
    return;
  }

  if (suggestSyncJpIssueId.value === jpIssueId) {
    return;
  }

  searchDebounceTimer = setTimeout(() => {
    void load({ notifyInvalid: false, notifyLoaded: false, notifyMissing: false });
  }, AUTO_SEARCH_DELAY_MS);
});

onBeforeUnmount(() => {
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer);
  }
});
</script>

<template>
  <TicketDetailView
    :ticket-search="ticketSearch"
    :managed-scope="managedScope"
    :managed-tickets="managedTickets"
    :loading-managed="loadingManaged"
    :status-options="statusOptions"
    :assignee-options="assigneeOptions"
    :ticket-detail="ticketDetail"
    :loading-detail="loadingDetail"
    :refreshing-detail="refreshingDetail"
    :ticket-edit="ticketEdit"
    :quick-create-forms="quickCreateForms"
    :tracker-options="sessionState.trackers"
    :creating-child="creatingChild"
    :link-form="linkForm"
    :suggest-sync-jp-issue-id="suggestSyncJpIssueId"
    :show-link-form="showLinkForm"
    :editing-link-id="editingLinkId"
    :is-admin="sessionState.me?.role === 'admin'"
    :deleting-managed-jp-issue-id="deletingManagedJpIssueId"
    :saving="saving"
    :can-post-to-teams="Boolean(sessionState.userSettings.team_automate_url?.trim())"
    :posting-teams="postingTeams"
    @update:ticket-search="ticketSearch = $event"
    @update:managed-scope="managedScope = $event"
    @search-ticket="load"
    @select-managed="selectManaged"
    @toggle-follow="toggleFollow"
    @create-managed-ticket="createManagedTicket"
    @delete-managed-ticket="deleteManagedTicket"
    @refresh-redmine-detail="refreshRedmineDetail"
    @open-quick-create="openQuickCreate"
    @cancel-quick-create="cancelQuickCreate"
    @toggle-link-form="showLinkForm = !showLinkForm; if (!showLinkForm) { editingLinkId = null; linkForm.type = 'spec'; linkForm.url = ''; }"
    @save-all="saveAll"
    @add-link="addLink"
    @copy-link="copyLink"
    @copy-team-thread="copyTeamThread"
    @post-to-teams="postToTeams"
    @edit-link="startEditLink"
    @cancel-edit-link="cancelEditLink"
    @delete-link="deleteLink"
    @create-child-ticket="createChildTicket"
  />
</template>
