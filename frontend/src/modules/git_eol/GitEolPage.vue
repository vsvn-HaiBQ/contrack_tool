<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import GitEolView from "./GitEolView.vue";
import { gitEolApi } from "./api";
import { sessionState } from "../../shared/session";
import { showToast } from "../../shared/toast";
import type {
  GitEolCommitResult,
  GitEolFixResult,
  GitEolJobLog,
  GitEolPreview,
  GitEolPushResult,
  GitEolStructuredDiff
} from "../../shared/types";

const form = reactive({
  base_branch: "",
  source_branch: ""
});
const commitForm = reactive({
  message: "Fix EOL noise"
});
const selectedFiles = reactive<Record<string, boolean>>({});
const expandedFiles = reactive<Record<string, boolean>>({});
const diffCache = reactive<Record<string, GitEolStructuredDiff>>({});
const diffLoading = reactive<Record<string, boolean>>({});
const expandedResultFiles = reactive<Record<string, boolean>>({});
const resultDiffCache = reactive<Record<string, GitEolStructuredDiff>>({});
const resultDiffLoading = reactive<Record<string, boolean>>({});
const selectedResultFiles = reactive<Record<string, boolean>>({});
const preview = ref<GitEolPreview | null>(null);
const fixResult = ref<GitEolFixResult | null>(null);
const commitResult = ref<GitEolCommitResult | null>(null);
const pushResult = ref<GitEolPushResult | null>(null);
const fixing = ref(false);
const committing = ref(false);
const pushing = ref(false);

const jobId = ref<string | null>(null);
const jobStatus = ref<"queued" | "running" | "succeeded" | "failed" | "idle">("idle");
const jobLogs = ref<GitEolJobLog[]>([]);
const jobError = ref<string | null>(null);
let eventSource: EventSource | null = null;

const loadingPreview = computed(() => jobStatus.value === "queued" || jobStatus.value === "running");

const selectedPaths = computed(() =>
  preview.value?.files.filter((file) => file.processable && selectedFiles[file.path]).map((file) => file.path) ?? []
);

const selectedResultPaths = computed(() =>
  Object.keys(selectedResultFiles).filter((k) => selectedResultFiles[k])
);

function clearMap(target: Record<string, unknown>) {
  Object.keys(target).forEach((key) => delete target[key]);
}

function syncSelectedFiles(nextPreview: GitEolPreview) {
  clearMap(selectedFiles);
  clearMap(expandedFiles);
  clearMap(diffCache);
  clearMap(diffLoading);
  clearMap(expandedResultFiles);
  clearMap(resultDiffCache);
  clearMap(resultDiffLoading);
  nextPreview.files.forEach((file) => {
    selectedFiles[file.path] = file.processable;
  });
}

function clearResults() {
  fixResult.value = null;
  commitResult.value = null;
  pushResult.value = null;
  clearMap(expandedResultFiles);
  clearMap(resultDiffCache);
  clearMap(resultDiffLoading);
  clearMap(selectedResultFiles);
}

function closeStream() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

function pushLog(entry: GitEolJobLog) {
  jobLogs.value.push(entry);
  if (jobLogs.value.length > 5000) {
    jobLogs.value = jobLogs.value.slice(-4000);
  }
}

async function loadPreview() {
  if (!form.base_branch.trim() || !form.source_branch.trim()) {
    showToast("Base branch and source branch are required", "warning");
    return;
  }

  closeStream();
  preview.value = null;
  clearResults();
  jobLogs.value = [];
  jobError.value = null;
  jobStatus.value = "queued";

  try {
    const enqueue = await gitEolApi.preview({
      base_branch: form.base_branch.trim(),
      source_branch: form.source_branch.trim()
    });
    jobId.value = enqueue.job_id;
    pushLog({
      ts: Date.now() / 1000,
      level: "info",
      source: "system",
      message: `Job ${enqueue.job_id} queued, waiting for worker...`
    });
    openStream(enqueue.job_id);
  } catch (error) {
    jobStatus.value = "failed";
    jobError.value = (error as Error).message;
    showToast((error as Error).message, "error");
  }
}

function openStream(id: string) {
  const url = gitEolApi.jobStreamUrl(id);
  const source = new EventSource(url, { withCredentials: true });
  eventSource = source;

  source.onmessage = (event) => {
    let payload: any;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    if (payload.type === "log" && payload.log) {
      pushLog(payload.log);
    } else if (payload.type === "status" && payload.status) {
      const status = payload.status.status;
      jobStatus.value = status;
      if (status === "succeeded" && payload.status.result) {
        preview.value = payload.status.result as GitEolPreview;
        syncSelectedFiles(preview.value);
        const processableCount = preview.value.files.filter((file) => file.processable).length;
        showToast(`Preview ready: ${processableCount} processable files`, processableCount ? "success" : "warning");
        closeStream();
      } else if (status === "failed") {
        jobError.value = payload.status.error || "Preview failed";
        showToast(jobError.value!, "error");
        closeStream();
      }
    } else if (payload.type === "error") {
      jobError.value = payload.message;
      showToast(payload.message, "error");
    }
  };

  source.onerror = () => {
    if (jobStatus.value === "succeeded" || jobStatus.value === "failed") {
      closeStream();
      return;
    }
    pushLog({
      ts: Date.now() / 1000,
      level: "warn",
      source: "system",
      message: "Log stream disconnected, retrying..."
    });
  };
}

async function loadDiff(
  path: string,
  cache: Record<string, GitEolStructuredDiff>,
  loading: Record<string, boolean>,
  force = false
): Promise<void> {
  if (!preview.value) return;
  if (!force && cache[path]) return;
  loading[path] = true;
  try {
    cache[path] = await gitEolApi.diff(preview.value.session_id, path);
  } catch (error) {
    cache[path] = {
      session_id: preview.value.session_id,
      path,
      binary: false,
      rows: [],
      stats: {}
    };
    showToast(`Failed to load diff: ${(error as Error).message}`, "error");
  } finally {
    loading[path] = false;
  }
}

async function toggleFileExpanded(path: string) {
  const isOpen = !!expandedFiles[path];
  expandedFiles[path] = !isOpen;
  if (!isOpen) {
    await loadDiff(path, diffCache, diffLoading);
  }
}

async function toggleResultFileExpanded(path: string) {
  const isOpen = !!expandedResultFiles[path];
  expandedResultFiles[path] = !isOpen;
  if (!isOpen) {
    await loadDiff(path, resultDiffCache, resultDiffLoading);
  }
}

async function fixSelectedFiles() {
  if (!preview.value) {
    showToast("Preview first", "warning");
    return;
  }
  if (!selectedPaths.value.length) {
    showToast("Select at least one file", "warning");
    return;
  }

  fixing.value = true;
  commitResult.value = null;
  pushResult.value = null;
  clearMap(expandedResultFiles);
  clearMap(resultDiffCache);
  clearMap(resultDiffLoading);
  clearMap(selectedResultFiles);
  try {
    fixResult.value = await gitEolApi.fix({
      session_id: preview.value.session_id,
      files: selectedPaths.value
    });
    showToast(`Restored ${fixResult.value.total_restored_eol_lines} EOL lines`, "success");
    // Auto-select all changed fixed files for commit
    clearMap(selectedResultFiles);
    fixResult.value.fixed_files
      .filter((f) => f.worktree_changed ?? f.restored_eol_lines > 0)
      .forEach((f) => { selectedResultFiles[f.path] = true; });
    // Invalidate diffs of fixed files (worktree changed) and refresh open ones.
    const fixedPaths = fixResult.value.fixed_files.map((file) => file.path);
    fixedPaths.forEach((path) => {
      delete diffCache[path];
    });
    await Promise.all(
      fixedPaths
        .filter((path) => expandedFiles[path])
        .map((path) => loadDiff(path, diffCache, diffLoading, true))
    );
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    fixing.value = false;
  }
}

async function commitChanges() {
  if (!preview.value || !fixResult.value) {
    showToast("Fix EOL first", "warning");
    return;
  }

  committing.value = true;
  commitResult.value = null;
  pushResult.value = null;
  try {
    commitResult.value = await gitEolApi.commit({
      session_id: preview.value.session_id,
      message: commitForm.message
    });
    showToast(commitResult.value.committed ? "EOL fix committed" : commitResult.value.message, commitResult.value.committed ? "success" : "warning");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    committing.value = false;
  }
}

async function pushBranch() {
  if (!preview.value || !commitResult.value?.committed) {
    showToast("Commit before push", "warning");
    return;
  }

  pushing.value = true;
  pushResult.value = null;
  try {
    pushResult.value = await gitEolApi.push({
      session_id: preview.value.session_id
    });
    showToast("Branch pushed", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    pushing.value = false;
  }
}

async function commitAndPushBranch() {
  if (!preview.value || !fixResult.value) {
    showToast("Fix EOL first", "warning");
    return;
  }

  committing.value = true;
  pushing.value = true;
  commitResult.value = null;
  pushResult.value = null;
  try {
    commitResult.value = await gitEolApi.commit({
      session_id: preview.value.session_id,
      message: commitForm.message
    });
    if (!commitResult.value.committed) {
      showToast(commitResult.value.message, "warning");
      return;
    }
    pushResult.value = await gitEolApi.push({ session_id: preview.value.session_id });
    showToast("Committed and pushed", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    committing.value = false;
    pushing.value = false;
  }
}

function selectAll() {
  preview.value?.files.forEach((file) => {
    if (file.processable) {
      selectedFiles[file.path] = true;
    }
  });
}

function clearSelection() {
  preview.value?.files.forEach((file) => {
    selectedFiles[file.path] = false;
  });
}

function clearLogs() {
  jobLogs.value = [];
}

watch(
  () => [form.base_branch, form.source_branch],
  () => {
    preview.value = null;
    clearResults();
  }
);

watch(
  () => sessionState.systemSettings.default_base_branch,
  (defaultBaseBranch) => {
    if (!form.base_branch.trim() && defaultBaseBranch) {
      form.base_branch = defaultBaseBranch;
    }
  },
  { immediate: true }
);

onBeforeUnmount(() => {
  closeStream();
});
</script>

<template>
  <GitEolView
    :form="form"
    :commit-form="commitForm"
    :preview="preview"
    :selected-files="selectedFiles"
    :selected-count="selectedPaths.length"
    :expanded-files="expandedFiles"
    :diff-cache="diffCache"
    :diff-loading="diffLoading"
    :expanded-result-files="expandedResultFiles"
    :result-diff-cache="resultDiffCache"
    :result-diff-loading="resultDiffLoading"
    :selected-result-files="selectedResultFiles"
    :selected-result-count="selectedResultPaths.length"
    :fix-result="fixResult"
    :commit-result="commitResult"
    :push-result="pushResult"
    :loading-preview="loadingPreview"
    :fixing="fixing"
    :committing="committing"
    :pushing="pushing"
    :job-id="jobId"
    :job-status="jobStatus"
    :job-logs="jobLogs"
    :job-error="jobError"
    @preview="loadPreview"
    @fix="fixSelectedFiles"
    @commit-and-push="commitAndPushBranch"
    @select-all="selectAll"
    @clear-selection="clearSelection"
    @toggle-file="toggleFileExpanded"
    @toggle-result-file="toggleResultFileExpanded"
    @clear-logs="clearLogs"
  />
</template>
