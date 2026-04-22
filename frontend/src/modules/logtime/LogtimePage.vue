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
    rows.value = response.rows;
    activities.value = response.activities;
    snapshotRows(response.rows);
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
