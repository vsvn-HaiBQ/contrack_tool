<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import LogtimeView from "./LogtimeView.vue";
import { logtimeApi } from "./api";
import { ticketsApi } from "../tickets/api";
import { usersApi } from "../users/api";
import type { Assignee, LogtimeRow, LogtimeSaveResult, StatusOption } from "../../shared/types";
import { showToast } from "../../shared/toast";

const logtimeDate = ref(new Date().toISOString().slice(0, 10));
const rows = ref<LogtimeRow[]>([]);
const activities = ref<string[]>([]);
const statusOptions = ref<StatusOption[]>([]);
const assigneeOptions = ref<Assignee[]>([]);
const results = ref<LogtimeSaveResult[]>([]);
const originalRows = ref<Record<number, { status: string; assignee: string; activity: string; hours: number }>>({});
const loading = ref(false);
const saving = ref(false);

const activityDefaults = [
  { activity: "Development", pattern: /\bdev\b/i, aliases: ["Development", "Dev"] },
  { activity: "Fix bug", pattern: /fix\s*bug/i, aliases: ["Fix bug", "Bug fix"] },
  { activity: "Investigation", pattern: /research/i, aliases: ["Investigation", "Research"] },
  { activity: "Estimation", pattern: /estimate/i, aliases: ["Estimation", "Estimate"] },
  { activity: "Meeting", pattern: /meeting/i, aliases: ["Meeting"] },
  { activity: "Testing", pattern: /\btest(?:ing)?\b/i, aliases: ["Testing", "Test"] }
];

function isStory(row: LogtimeRow) {
  return (row.tracker || "").trim().toLowerCase() === "story";
}

const totalHours = computed(() =>
  rows.value
    .filter((row) => !isStory(row))
    .reduce((sum, row) => sum + Number(row.hours || 0), 0)
);

function snapshotRows(items: LogtimeRow[]) {
  originalRows.value = Object.fromEntries(
    items.map((row) => [
      row.issue_id,
      {
        status: row.status,
        assignee: row.assignee ?? "",
        activity: row.activity,
        hours: Number(row.hours || 0)
      }
    ])
  );
}

function clearRows() {
  rows.value = [];
  activities.value = [];
  results.value = [];
  originalRows.value = {};
}

function resolveActivityOption(options: string[], names: string[]) {
  const normalizedNames = names.map((name) => name.trim().toLowerCase()).filter(Boolean);
  return options.find((option) => normalizedNames.includes(option.trim().toLowerCase()));
}

function subjectVariants(subject: string) {
  const trimmed = subject.trim();
  const withoutTicketPrefix = trimmed.replace(/^#\d+:\s*/, "");
  return Array.from(new Set([trimmed, withoutTicketPrefix].filter(Boolean)));
}

function activityNamesForValue(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }

  const normalizedValue = trimmed.toLowerCase();
  const matchedRule = activityDefaults.find((rule) =>
    [rule.activity, ...rule.aliases].some((name) => name.trim().toLowerCase() === normalizedValue)
  );

  return matchedRule ? [matchedRule.activity, ...matchedRule.aliases] : [trimmed];
}

function normalizeActivityValue(value: string | undefined, options: string[]) {
  const trimmed = (value || "").trim();
  if (!trimmed) {
    return "";
  }

  return resolveActivityOption(options, activityNamesForValue(trimmed)) ?? trimmed;
}

function shouldUseSubjectDefault(row: LogtimeRow, normalizedActivity: string, options: string[]) {
  if (Number(row.hours || 0) > 0) {
    return false;
  }

  if (!normalizedActivity) {
    return true;
  }

  const defaultActivity = options[0]?.trim().toLowerCase();
  return Boolean(defaultActivity) && normalizedActivity.trim().toLowerCase() === defaultActivity;
}

function inferDefaultActivity(subject: string, options: string[]) {
  for (const candidate of subjectVariants(subject)) {
    for (const rule of activityDefaults) {
      if (rule.pattern.test(candidate)) {
        return resolveActivityOption(options, [rule.activity, ...rule.aliases]);
      }
    }
  }
  return undefined;
}

function applyDefaultActivities(items: LogtimeRow[], options: string[]) {
  return items.map((row) => {
    const normalizedActivity = normalizeActivityValue(row.activity, options);
    const inferredActivity = row.subject ? inferDefaultActivity(row.subject, options) : undefined;

    if (inferredActivity && shouldUseSubjectDefault(row, normalizedActivity, options)) {
      return inferredActivity === row.activity ? row : { ...row, activity: inferredActivity };
    }

    if (normalizedActivity) {
      return normalizedActivity === row.activity ? row : { ...row, activity: normalizedActivity };
    }

    if (!row.subject) {
      return row;
    }

    return inferredActivity ? { ...row, activity: inferredActivity } : row;
  });
}

function shiftDate(delta: number) {
  const parsed = new Date(`${logtimeDate.value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return;
  }

  parsed.setDate(parsed.getDate() + delta);
  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  logtimeDate.value = `${year}-${month}-${day}`;
}

async function goToday() {
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  if (logtimeDate.value === today) {
    clearRows();
    await refresh();
    return;
  }
  logtimeDate.value = today;
}

async function loadOptions() {
  try {
    const [statuses, assignees] = await Promise.all([usersApi.statuses(), usersApi.assignees()]);
    statusOptions.value = statuses;
    assigneeOptions.value = assignees;
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function refresh() {
  loading.value = true;
  try {
    const response = await logtimeApi.source(logtimeDate.value);
    activities.value = response.activities;
    rows.value = applyDefaultActivities(response.rows, response.activities);
    snapshotRows(rows.value);
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  try {
    const changedMetaRows = rows.value.filter((row) => {
      const original = originalRows.value[row.issue_id];
      return original && (original.status !== row.status || original.assignee !== (row.assignee ?? ""));
    });

    if (changedMetaRows.length) {
      const updateResults = await Promise.allSettled(
        changedMetaRows.map((row) =>
          ticketsApi.updateIssue(row.issue_id, { status: row.status, assignee: row.assignee ?? "" })
        )
      );
      const failedUpdates = updateResults.filter((item) => item.status === "rejected");
      if (failedUpdates.length) {
        showToast(`Status/assignee updated ${changedMetaRows.length - failedUpdates.length}/${changedMetaRows.length}`, "warning");
      }
    }

    const changedLogtimeRows = rows.value
      .filter((row) => !isStory(row))
      .filter((row) => {
        const original = originalRows.value[row.issue_id];
        return (
          !original ||
          original.activity !== row.activity ||
          Number(original.hours || 0) !== Number(row.hours || 0)
        );
      })
      .map((row) => ({
        issue_id: row.issue_id,
        activity: row.activity,
        hours: Number(row.hours || 0)
      }));

    results.value = changedLogtimeRows.length
      ? await logtimeApi.save({
          date: logtimeDate.value,
          rows: changedLogtimeRows
        })
      : [];

    snapshotRows(rows.value);
    showToast(
      changedLogtimeRows.length || changedMetaRows.length ? "Logtime saved" : "Nothing changed",
      totalHours.value > 8 ? "warning" : "success"
    );
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await loadOptions();
  await refresh();
});

watch(logtimeDate, async () => {
  clearRows();
  await refresh();
});
</script>

<template>
  <LogtimeView
    :logtime-date="logtimeDate"
    :rows="rows"
    :activities="activities"
    :status-options="statusOptions"
    :assignee-options="assigneeOptions"
    :total-hours="totalHours"
    :results="results"
    :loading="loading"
    :saving="saving"
    @update:logtime-date="logtimeDate = $event"
    @shift-date="shiftDate"
    @go-today="goToday"
    @save="save"
  />
</template>
