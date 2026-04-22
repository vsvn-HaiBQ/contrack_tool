<script setup lang="ts">
import { reactive, watch } from "vue";
import { useRoute } from "vue-router";
import SyncTicketView from "./SyncTicketView.vue";
import { ticketsApi } from "./api";
import { sessionState } from "../../shared/session";
import { showToast } from "../../shared/toast";
import type { SyncResult, TicketCandidate } from "../../shared/types";

const DEFAULT_SUBTASK_LABELS: Record<string, string> = {
  fix_bug: "Fix bug",
  dev: "Dev",
  estimate: "Estimate",
  test: "Test"
};

const syncState = reactive({
  jp_issue_input: "",
  jp_issue_id: null as number | null,
  jp_subject: "",
  jp_issue_url: "",
  verified: false,
  verifying: false,
  candidates: [] as TicketCandidate[],
  subject: "",
  subject_prefix: "Bug" as "Bug" | "CR" | "",
  description: "",
  assignee_id: sessionState.userSettings.default_assignee_id,
  parent_issue_id: null as number | null,
  related_ticket_id: null as number | null,
  existing_vn_issue_id: null as number | null,
  selected_subtasks: [] as string[],
  subtask_titles: { ...DEFAULT_SUBTASK_LABELS } as Record<string, string>,
  extra_tracker: "Story"
});

const syncResult = reactive<SyncResult>({
  mode: "",
  message: "",
  story: null,
  subtasks: []
});

const route = useRoute();
let lastPrefillKey = "";

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

function buildStorySubject() {
  if (!syncState.jp_issue_id || !syncState.jp_subject) {
    return "";
  }

  const prefix = syncState.subject_prefix ? `[${syncState.subject_prefix}_${syncState.jp_issue_id}]` : `#${syncState.jp_issue_id}:`;
  return `${prefix} ${syncState.jp_subject}`;
}

watch(
  () => [syncState.jp_issue_id, syncState.jp_subject, syncState.subject_prefix],
  () => {
    syncState.subject = buildStorySubject();
  }
);

watch(
  () => sessionState.userSettings.default_assignee_id,
  (defaultAssigneeId) => {
    if (syncState.assignee_id == null) {
      syncState.assignee_id = defaultAssigneeId ?? sessionState.assignees[0]?.id ?? null;
    }
  },
  { immediate: true }
);

watch(
  () => sessionState.assignees,
  (assignees) => {
    if (syncState.assignee_id == null && assignees.length) {
      syncState.assignee_id = sessionState.userSettings.default_assignee_id ?? assignees[0].id;
    }
  },
  { immediate: true }
);

async function verify(existingVnIssueId: number | null = null) {
  const jpIssueId = parseJpIssueInput(syncState.jp_issue_input);
  if (!jpIssueId) {
    showToast("Enter a JP issue ID", "warning");
    return;
  }

  syncState.jp_issue_id = jpIssueId;
  syncState.verifying = true;

  try {
    const response = await ticketsApi.verifySync({ jp_issue_id: jpIssueId });

    syncState.jp_issue_id = response.jp_issue_id;
    syncState.jp_issue_input = String(response.jp_issue_id);
    syncState.jp_subject = response.jp_subject;
    syncState.jp_issue_url = response.jp_issue_url;
    syncState.verified = true;
    syncState.candidates = response.candidates;
    syncState.existing_vn_issue_id = existingVnIssueId;
    syncState.subject = buildStorySubject();

    if (!syncState.description) {
      const template = sessionState.systemSettings.description_template?.trim();
      if (template) {
        syncState.description = template
          .replace(/\{jp_issue_id\}/g, String(response.jp_issue_id))
          .replace(/\{jp_issue_url\}/g, response.jp_issue_url)
          .replace(/\{jp_subject\}/g, response.jp_subject);
      }
    }

    const prefix = `#${response.jp_issue_id}: `;
    for (const [key, label] of Object.entries(DEFAULT_SUBTASK_LABELS)) {
      const current = syncState.subtask_titles[key] ?? label;
      const stripped = current.startsWith(prefix) ? current.slice(prefix.length) : current;
      syncState.subtask_titles[key] = `${prefix}${stripped || label}`;
    }

    showToast("JP issue verified", "success");
  } catch (error) {
    syncState.verified = false;
    syncState.jp_subject = "";
    syncState.jp_issue_url = "";
    syncState.candidates = [];
    syncState.existing_vn_issue_id = null;
    showToast((error as Error).message, "error");
  } finally {
    syncState.verifying = false;
  }
}

async function runSync(mode: "create_new" | "link" = "create_new", existingVnIssueId?: number | null) {
  if (!syncState.verified || !syncState.jp_issue_id) {
    showToast("Verify the JP issue first", "warning");
    return;
  }

  const linkedIssueId = existingVnIssueId ?? syncState.existing_vn_issue_id;
  if (mode === "link" && !linkedIssueId) {
    showToast("Select a Story in VN Reference to link", "warning");
    return;
  }

  try {
    const result = await ticketsApi.sync({
      jp_issue_id: syncState.jp_issue_id,
      mode,
      subject: syncState.subject,
      description: syncState.description,
      assignee_id: syncState.assignee_id,
      parent_issue_id: syncState.parent_issue_id,
      related_ticket_id: syncState.related_ticket_id,
      existing_vn_issue_id: linkedIssueId,
      create_subtasks: syncState.selected_subtasks
        .map((key) => syncState.subtask_titles[key])
        .filter(Boolean),
      extra_tracker: syncState.extra_tracker
    });

    syncResult.mode = result.mode;
    syncResult.message = result.message;
    syncResult.story = result.story;
    syncResult.subtasks = result.subtasks;

    if (mode === "link") {
      syncState.existing_vn_issue_id = linkedIssueId ?? null;
    }

    showToast("Sync completed", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

function numberQuery(value: unknown) {
  const raw = Array.isArray(value) ? value[0] : value;
  if (raw == null || raw === "") return null;

  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function trackerQuery(value: unknown) {
  const raw = Array.isArray(value) ? value[0] : value;
  return typeof raw === "string" && raw.trim() ? raw : null;
}

async function applyRoutePrefill() {
  const jpIssueId = numberQuery(route.query.jpIssueId);
  const parentIssueId = numberQuery(route.query.parentIssueId);
  const relatedTicketId = numberQuery(route.query.relatedTicketId);
  const existingVnIssueId = numberQuery(route.query.existingVnIssueId);
  const tracker = trackerQuery(route.query.tracker);
  const prefillKey = JSON.stringify({ jpIssueId, parentIssueId, relatedTicketId, existingVnIssueId, tracker });

  if (!jpIssueId || prefillKey === lastPrefillKey) {
    return;
  }

  lastPrefillKey = prefillKey;
  syncState.jp_issue_input = String(jpIssueId);
  syncState.jp_issue_id = jpIssueId;
  syncState.parent_issue_id = parentIssueId;
  syncState.related_ticket_id = relatedTicketId;
  syncState.extra_tracker = tracker ?? syncState.extra_tracker;

  await verify(existingVnIssueId);
}

watch(
  () => route.fullPath,
  async () => {
    await applyRoutePrefill();
  },
  { immediate: true }
);
</script>

<template>
  <SyncTicketView
    :sync-state="syncState"
    :sync-result="syncResult"
    :assignees="sessionState.assignees"
    :trackers="sessionState.trackers"
    @verify="verify"
    @run-sync="(payload) => runSync(payload?.mode, payload?.existingVnIssueId)"
  />
</template>
