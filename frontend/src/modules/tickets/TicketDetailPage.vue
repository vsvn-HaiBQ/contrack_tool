<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import TicketDetailView from "./TicketDetailView.vue";
import { ticketsApi } from "./api";
import { showToast } from "../../shared/toast";
import type { Assignee, ManagedTicketListItem, StatusOption, TicketDetail } from "../../shared/types";
import { usersApi } from "../users/api";
import { sessionState } from "../../shared/session";

const router = useRouter();
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
const saving = ref(false);
const deletingManagedJpIssueId = ref<number | null>(null);
const suggestSyncJpIssueId = ref<number | null>(null);
const creatingChild = ref(false);
const quickCreateOpenIssueId = ref<number | null>(null);
const quickCreateForm = reactive({
  tracker: "Sub-task",
  parent_issue_id: null as number | null,
  subject: "",
  description: "",
  assignee_id: sessionState.userSettings.default_assignee_id as number | null
});
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
  if (!quickCreateForm.assignee_id) {
    quickCreateForm.assignee_id = sessionState.userSettings.default_assignee_id ?? sessionState.assignees[0]?.id ?? null;
  }
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

async function loadByJpIssueId(
  jpIssueId: number,
  options?: { notifyLoaded?: boolean; notifyMissing?: boolean }
) {
  const notifyLoaded = options?.notifyLoaded ?? true;
  const notifyMissing = options?.notifyMissing ?? true;
  loadingDetail.value = true;
  try {
    const searchResult = await ticketsApi.search(jpIssueId);
    if (!searchResult.exists) {
      ticketDetail.value = null;
      suggestSyncJpIssueId.value = jpIssueId;
      if (notifyMissing) {
        showToast("JP issue is not managed yet. Sync it first.", "warning");
      }
      return;
    }

    ticketDetail.value = await ticketsApi.detail(jpIssueId);
    quickCreateOpenIssueId.value = null;
    quickCreateForm.subject = "";
    quickCreateForm.description = "";
    quickCreateForm.parent_issue_id = null;
    suggestSyncJpIssueId.value = null;
    snapshotEdit(
      ticketDetail.value.vn_issue.issue_id,
      ticketDetail.value.vn_issue.status,
      ticketDetail.value.vn_issue.assignee ?? ""
    );
    for (const child of ticketDetail.value.children) {
      snapshotEdit(child.issue_id, child.status, child.assignee ?? "");
    }
    if (notifyLoaded) {
      showToast("Ticket loaded", "success");
    }
  } catch (error) {
    ticketDetail.value = null;
    showToast((error as Error).message, "error");
  } finally {
    loadingDetail.value = false;
  }
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
  await loadByJpIssueId(jpIssueId, options);
}

async function selectManaged(jpIssueId: number) {
  await loadByJpIssueId(jpIssueId);
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
    await navigator.clipboard.writeText(url);
    showToast("Link copied", "success");
  } catch {
    showToast("Cannot copy link", "error");
  }
}

function openQuickCreate(issueId?: number) {
  if (!ticketDetail.value) {
    showToast("Load a managed ticket first", "warning");
    return;
  }

  quickCreateOpenIssueId.value = issueId ?? ticketDetail.value.vn_issue.issue_id;
  quickCreateForm.tracker = "Sub-task";
  quickCreateForm.parent_issue_id = quickCreateOpenIssueId.value;
  quickCreateForm.subject = "";
  quickCreateForm.description = "";
  quickCreateForm.assignee_id = sessionState.userSettings.default_assignee_id ?? sessionState.assignees[0]?.id ?? null;
}

function cancelQuickCreate() {
  quickCreateOpenIssueId.value = null;
  quickCreateForm.parent_issue_id = null;
  quickCreateForm.subject = "";
  quickCreateForm.description = "";
}

async function createChildTicket() {
  if (!ticketDetail.value || !quickCreateForm.parent_issue_id) {
    showToast("Select a parent issue first", "warning");
    return;
  }
  if (!quickCreateForm.subject.trim()) {
    showToast("Enter a task subject", "warning");
    return;
  }

  creatingChild.value = true;
  try {
    const created = await ticketsApi.createChild(ticketDetail.value.jp_issue_id, {
      parent_issue_id: quickCreateForm.parent_issue_id,
      subject: quickCreateForm.subject.trim(),
      description: quickCreateForm.description.trim() || null,
      assignee_id: quickCreateForm.assignee_id,
      tracker: quickCreateForm.tracker
    });
    showToast(`Created ${created.tracker} #${created.issue_id}`, "success");
    cancelQuickCreate();
    await load();
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
  if (!window.confirm(`Delete managed ticket for JP #${jpIssueId}?`)) {
    return;
  }

  deletingManagedJpIssueId.value = jpIssueId;
  try {
    await ticketsApi.deleteManaged(jpIssueId);
    if (ticketDetail.value?.jp_issue_id === jpIssueId) {
      ticketDetail.value = null;
      quickCreateOpenIssueId.value = null;
      quickCreateForm.parent_issue_id = null;
      quickCreateForm.subject = "";
      quickCreateForm.description = "";
    }
    suggestSyncJpIssueId.value = jpIssueId;
    await loadManaged();
    showToast("Managed ticket deleted", "success");
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
    :ticket-edit="ticketEdit"
    :quick-create-open-issue-id="quickCreateOpenIssueId"
    :quick-create-form="quickCreateForm"
    :tracker-options="sessionState.trackers"
    :creating-child="creatingChild"
    :link-form="linkForm"
    :suggest-sync-jp-issue-id="suggestSyncJpIssueId"
    :show-link-form="showLinkForm"
    :editing-link-id="editingLinkId"
    :is-admin="sessionState.me?.role === 'admin'"
    :deleting-managed-jp-issue-id="deletingManagedJpIssueId"
    :saving="saving"
    @update:ticket-search="ticketSearch = $event"
    @update:managed-scope="managedScope = $event"
    @search-ticket="load"
    @select-managed="selectManaged"
    @toggle-follow="toggleFollow"
    @create-managed-ticket="createManagedTicket"
    @delete-managed-ticket="deleteManagedTicket"
    @open-quick-create="openQuickCreate"
    @cancel-quick-create="cancelQuickCreate"
    @toggle-link-form="showLinkForm = !showLinkForm; if (!showLinkForm) { editingLinkId = null; linkForm.type = 'spec'; linkForm.url = ''; }"
    @save-all="saveAll"
    @add-link="addLink"
    @copy-link="copyLink"
    @edit-link="startEditLink"
    @cancel-edit-link="cancelEditLink"
    @delete-link="deleteLink"
    @create-child-ticket="createChildTicket"
  />
</template>
