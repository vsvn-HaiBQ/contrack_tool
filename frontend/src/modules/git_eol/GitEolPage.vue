<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import GitEolView from "./GitEolView.vue";
import { gitEolApi } from "./api";
import { localServerApi, localServerBase } from "../../shared/localServer";
import { activeDefaultBaseBranch, sessionState } from "../../shared/session";
import { showToast } from "../../shared/toast";
import { auditApi } from "../audit/api";
import { usersApi } from "../users/api";
import type {
  GitEolCommitResult,
  GitEolDiffRow,
  GitEolFixResult,
  GitEolJobLog,
  GitEolPreview,
  GitEolPushResult,
  GitEolStructuredDiff
} from "../../shared/types";

const form = reactive({
  mode: "working_tree" as "branch" | "working_tree",
  base_branch: "",
  source_branch: "",
  local_source_folder: ""
});
const commitForm = reactive({
  message: "fix eol"
});
const selectedFiles = reactive<Record<string, boolean>>({});
const expandedFiles = reactive<Record<string, boolean>>({});
const diffCache = reactive<Record<string, GitEolStructuredDiff>>({});
const diffLoading = reactive<Record<string, boolean>>({});
const expandedResultFiles = reactive<Record<string, boolean>>({});
const resultDiffCache = reactive<Record<string, GitEolStructuredDiff>>({});
const resultDiffLoading = reactive<Record<string, boolean>>({});
const selectedResultFiles = reactive<Record<string, boolean>>({});
const fixSpaceOnly = ref(false);
const fixProgress = ref<{ current: number; total: number; path: string } | null>(null);
const previewProgress = ref<{ current: number; total: number; path: string } | null>(null);
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
const localServerOnline = ref(false);
let eventSource: EventSource | null = null;

const loadingPreview = computed(() => jobStatus.value === "queued" || jobStatus.value === "running");
const isWorkingTreeMode = computed(() => form.mode === "working_tree");

const selectedPaths = computed(() =>
  preview.value?.files
    .filter(
      (file) =>
        file.processable &&
        selectedFiles[file.path] &&
        (file.eol_only_lines > 0 || (fixSpaceOnly.value && file.space_only_lines > 0))
    )
    .map((file) => file.path) ?? []
);

const selectedResultPaths = computed(() =>
  Object.keys(selectedResultFiles).filter((k) => selectedResultFiles[k])
);

function hasFixedOutput(file: GitEolFixResult["fixed_files"][number]) {
  return Boolean(file.committable || file.worktree_changed || file.restored_eol_lines > 0 || (file.restored_space_only_lines ?? 0) > 0);
}

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
    selectedFiles[file.path] = file.processable && file.eol_only_lines > 0;
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
  const progress = /^Scanning file (\d+)\/(\d+): (.+)$/.exec(entry.message);
  if (progress) {
    previewProgress.value = {
      current: Number(progress[1]),
      total: Number(progress[2]),
      path: progress[3],
    };
  }
  if (jobLogs.value.length > 5000) {
    jobLogs.value = jobLogs.value.slice(-4000);
  }
}

async function loadPreview() {
  if (isWorkingTreeMode.value) {
    await loadWorkingTreePreview();
    return;
  }
  if (!form.base_branch.trim() || !form.source_branch.trim()) {
    showToast("Base branch and source branch are required", "warning");
    return;
  }

  closeStream();
  preview.value = null;
  clearResults();
  jobLogs.value = [];
  jobError.value = null;
  previewProgress.value = null;
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

async function loadWorkingTreePreview() {
  if (!form.local_source_folder.trim()) {
    showToast("Target source folder is required", "warning");
    return;
  }

  closeStream();
  preview.value = null;
  clearResults();
  jobLogs.value = [];
  jobError.value = null;
  previewProgress.value = { current: 0, total: 0, path: "" };
  jobStatus.value = "running";
  jobId.value = null;
  try {
    form.local_source_folder = await validateLocalDirectory(form.local_source_folder, "Source folder");
    await usersApi.updateLocalPaths({ git_eol_source_folder: form.local_source_folder });
    pushLog({
      ts: Date.now() / 1000,
      level: "info",
      source: "local-node",
      message: `Comparing working tree with HEAD at ${form.local_source_folder}`
    });
    const started = await localServerApi.gitEol.startWorkingTreePreview({ sourceFolder: form.local_source_folder });
    jobId.value = started.job_id;
    let loggedScanIndex = 0;
    while (true) {
      const job = await localServerApi.gitEol.workingTreePreviewJob(started.job_id);
      previewProgress.value = { current: job.current, total: job.total, path: job.path };
      if (job.current > 0 && job.current !== loggedScanIndex) {
        loggedScanIndex = job.current;
        pushLog({
          ts: Date.now() / 1000,
          level: "info",
          source: "local-node",
          message: `Scanning file ${job.current}/${job.total}: ${job.path}`,
        });
      }
      if (job.status === "succeeded") {
        if (!job.result) throw new Error("Preview completed without a result");
        preview.value = job.result;
        break;
      }
      if (job.status === "failed") {
        throw new Error(job.error || "Preview failed");
      }
      await new Promise<void>((resolve) => window.setTimeout(resolve, 100));
    }
    localServerOnline.value = true;
    syncSelectedFiles(preview.value);
    jobStatus.value = "succeeded";
    previewProgress.value = null;
    const processableCount = preview.value.files.filter((file) => file.processable).length;
    pushLog({
      ts: Date.now() / 1000,
      level: "info",
      source: "local-node",
      message: `Preview ready: ${processableCount} processable files`
    });
    showToast(`Preview ready: ${processableCount} processable files`, processableCount ? "success" : "warning");
  } catch (error) {
    jobStatus.value = "failed";
    previewProgress.value = null;
    jobError.value = (error as Error).message;
    pushLog({
      ts: Date.now() / 1000,
      level: "error",
      source: "local-node",
      message: (error as Error).message
    });
    showToast((error as Error).message, "error");
  }
}

function openStream(id: string) {
  const source = new EventSource(gitEolApi.jobStreamUrl(id), { withCredentials: true });
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
        previewProgress.value = null;
        const processableCount = preview.value.files.filter((file) => file.processable).length;
        showToast(`Preview ready: ${processableCount} processable files`, processableCount ? "success" : "warning");
        closeStream();
      } else if (status === "failed") {
        jobError.value = payload.status.error || "Preview failed";
        previewProgress.value = null;
        showToast(jobError.value, "error");
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
  force = false,
  includeFixed = false
): Promise<void> {
  if (!preview.value) return;
  if (!force && cache[path]) return;
  loading[path] = true;
  try {
    cache[path] = isWorkingTreeMode.value
      ? await localServerApi.gitEol.structuredDiff({ sessionId: preview.value.session_id, path, foldUnchanged: true, context: 3, includeFixed })
      : await gitEolApi.diff(preview.value.session_id, path, { foldUnchanged: true, context: 3, includeFixed });
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

async function loadHiddenRows(path: string, row: GitEolDiffRow, includeFixed = false): Promise<GitEolDiffRow[]> {
  if (!preview.value) return [];
  const leftStart = row.left_start ?? null;
  const leftEnd = row.left_end ?? null;
  const rightStart = row.right_start ?? null;
  const rightEnd = row.right_end ?? null;
  if (!leftStart || !leftEnd || !rightStart || !rightEnd) {
    throw new Error("Hidden diff range is missing");
  }
  const diff = isWorkingTreeMode.value
    ? await localServerApi.gitEol.structuredDiff({
        sessionId: preview.value.session_id,
        path,
        leftStart,
        leftEnd,
        rightStart,
        rightEnd,
        includeFixed
      })
    : await gitEolApi.diff(preview.value.session_id, path, {
        leftStart,
        leftEnd,
        rightStart,
        rightEnd,
        includeFixed
      });
  return diff.rows;
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
    await loadDiff(path, resultDiffCache, resultDiffLoading, false, true);
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
  fixProgress.value = null;
  try {
    const paths = selectedPaths.value;
    const combined: GitEolFixResult = {
      session_id: preview.value.session_id,
      fixed_files: [],
      skipped_files: [],
      failed_files: [],
      total_restored_eol_lines: 0,
      total_restored_space_only_lines: 0,
    };
    for (let index = 0; index < paths.length; index += 1) {
      const path = paths[index];
      fixProgress.value = { current: index + 1, total: paths.length, path };
      const result = isWorkingTreeMode.value
        ? await localServerApi.gitEol.fixWorkingTree({
            sessionId: preview.value.session_id,
            files: [path],
            fixSpaceOnly: fixSpaceOnly.value,
            resetExisting: index === 0,
          })
        : await gitEolApi.fix({
            session_id: preview.value.session_id,
            files: [path],
            fix_space_only: fixSpaceOnly.value,
            reset_existing: index === 0,
          });
      combined.fixed_files.push(...result.fixed_files);
      combined.skipped_files.push(...result.skipped_files);
      combined.failed_files.push(...result.failed_files);
      combined.total_restored_eol_lines += result.total_restored_eol_lines;
      combined.total_restored_space_only_lines =
        (combined.total_restored_space_only_lines ?? 0) + (result.total_restored_space_only_lines ?? 0);
    }
    fixResult.value = combined;
    if (isWorkingTreeMode.value) {
      void auditApi.record({
        action: "git_eol_fix",
        target_type: "git_eol_session",
        target_id: preview.value.session_id,
        payload_after: {
          mode: "working_tree",
          files: selectedPaths.value,
          fix_space_only: fixSpaceOnly.value,
          fixed_files: fixResult.value.fixed_files.map((file) => file.path),
          total_restored_eol_lines: fixResult.value.total_restored_eol_lines,
          total_restored_space_only_lines: fixResult.value.total_restored_space_only_lines,
        }
      }).catch(() => undefined);
    }
    if (isWorkingTreeMode.value) {
      const appliedCount = fixResult.value.fixed_files.filter((f) => f.worktree_changed).length;
      const committableCount = fixResult.value.fixed_files.filter((f) => f.committable).length;
      showToast(
        appliedCount || committableCount
          ? `Applied ${appliedCount} file(s); ${committableCount} file(s) ready to commit`
          : "No EOL changes were needed",
        appliedCount || committableCount ? "success" : "warning"
      );
    } else {
      showToast(
        `Restored ${fixResult.value.total_restored_eol_lines} EOL line(s); reverted ${fixResult.value.total_restored_space_only_lines ?? 0} whitespace-only line(s)`,
        "success"
      );
    }
    // Auto-select all changed fixed files for commit
    clearMap(selectedResultFiles);
    fixResult.value.fixed_files
      .filter(hasFixedOutput)
      .forEach((f) => { selectedResultFiles[f.path] = true; });
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    fixing.value = false;
    fixProgress.value = null;
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
    commitResult.value = isWorkingTreeMode.value
      ? await localServerApi.gitEol.commitWorkingTree({
          sessionId: preview.value.session_id,
          message: commitForm.message
        })
      : await gitEolApi.commit({
          session_id: preview.value.session_id,
          message: commitForm.message
        });
    if (!commitResult.value.committed) {
      showToast(commitResult.value.message, "warning");
      return;
    }
    pushResult.value = isWorkingTreeMode.value
      ? await localServerApi.gitEol.pushWorkingTree({
          sessionId: preview.value.session_id,
          githubToken: sessionState.userSettings.github_token
        })
      : await gitEolApi.push({ session_id: preview.value.session_id });
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
    if (file.processable && (file.eol_only_lines > 0 || (fixSpaceOnly.value && file.space_only_lines > 0))) {
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
  () => [form.mode, form.base_branch, form.source_branch, form.local_source_folder],
  () => {
    preview.value = null;
    clearResults();
  }
);

async function browseLocalSourceFolder() {
  try {
    const selected = await localServerApi.selectDirectory(form.local_source_folder);
    if (selected) {
      form.local_source_folder = await validateLocalDirectory(selected, "Source folder");
      await usersApi.updateLocalPaths({ git_eol_source_folder: form.local_source_folder });
    }
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function validateLocalDirectory(path: string, label: string) {
  const result = await localServerApi.validatePath(path, true);
  if (!result.valid) {
    throw new Error(`${label}: ${result.message}`);
  }
  localServerOnline.value = true;
  return result.path;
}

async function loadLocalPathSetting() {
  try {
    const health = await localServerApi.health();
    localServerOnline.value = Boolean(health.ok);
  } catch {
    localServerOnline.value = false;
    return;
  }

  try {
    const paths = await usersApi.localPaths();
    if (paths.git_eol_source_folder?.trim()) {
      form.local_source_folder = await validateLocalDirectory(paths.git_eol_source_folder, "Saved source folder");
    }
  } catch (error) {
    showToast((error as Error).message, "warning");
  }
}

let lastAutoBaseBranch = "";
watch(
  activeDefaultBaseBranch,
  (defaultBaseBranch) => {
    if (!defaultBaseBranch) return;
    if (!form.base_branch.trim() || form.base_branch === lastAutoBaseBranch) {
      form.base_branch = defaultBaseBranch;
      lastAutoBaseBranch = defaultBaseBranch;
    }
  },
  { immediate: true }
);

onBeforeUnmount(closeStream);
onMounted(loadLocalPathSetting);
</script>

<template>
  <GitEolView
    :form="form"
    :local-client="true"
    :local-server-online="localServerOnline"
    :local-server-base="localServerBase"
    :commit-form="commitForm"
    :preview="preview"
    :selected-files="selectedFiles"
    :selected-count="selectedPaths.length"
    :fix-space-only="fixSpaceOnly"
    :fix-progress="fixProgress"
    :preview-progress="previewProgress"
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
    @update-fix-space-only="fixSpaceOnly = $event"
    @clear-logs="clearLogs"
    @browse-local-source-folder="browseLocalSourceFolder"
    :load-hidden-rows="loadHiddenRows"
  />
</template>
