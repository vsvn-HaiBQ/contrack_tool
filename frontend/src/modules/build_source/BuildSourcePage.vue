<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import LoadingCircle from "../../shared/LoadingCircle.vue";
import { copyText } from "../../shared/clipboard";
import { HttpError } from "../../shared/http";
import { localServerApi, localServerBase } from "../../shared/localServer";
import { apiBackendBase, apiBoxOAuthCallbackPath, boxOAuthRedirectUri } from "../../shared/runtimeConfig";
import { sessionState } from "../../shared/session";
import { showToast } from "../../shared/toast";
import { auditApi } from "../audit/api";
import { boxApi } from "../box/api";
import { ticketsApi } from "../tickets/api";
import { usersApi } from "../users/api";
import type { BoxStatus, BoxUploadedItem, BuildJob, BuildJobLog } from "../../shared/types";

type BoxUploadStatus = "idle" | "pending" | "uploading" | "succeeded" | "failed" | "skipped";

const form = reactive({
  targetBranch: "",
  sourceFolder: "",
  buildFolder: "",
  jpIssueId: "",
  buildClient: false,
  buildServer: false,
  uploadToBox: false,
});

const job = ref<BuildJob | null>(null);
const boxStatus = ref<BoxStatus | null>(null);
const uploadedBoxItems = ref<BoxUploadedItem[]>([]);
const boxUploadLogs = ref<Record<string, BuildJobLog[]>>({});
const polling = ref<number | null>(null);
const logContainers: Record<string, HTMLElement | null> = {};
const stoppingBuildJobs = reactive<Record<string, boolean>>({});
const uploadingBoxJobIds = reactive<Record<string, boolean>>({});
const uploadedBoxJobIds = reactive<Record<string, boolean>>({});
const autoScroll = ref(true);
const localServerOnline = ref(false);
const checkingLocalServer = ref(false);
const uploadingToBox = ref(false);
const uploadCompletedJobId = ref<string | null>(null);
const boxUploadStatus = ref<BoxUploadStatus>("idle");
const lastAutoTargetBranch = ref("");

const running = computed(() =>
  job.value?.status === "queued" ||
  job.value?.status === "running" ||
  buildPanels.value.some((panel) => panel.job.status === "queued" || panel.job.status === "running")
);
const canBuild = computed(() =>
  Boolean(
    form.targetBranch.trim() &&
      form.sourceFolder.trim() &&
      form.buildFolder.trim() &&
      (form.buildClient || form.buildServer)
  )
);
const boxReady = computed(() => Boolean(boxStatus.value?.configured && boxStatus.value?.connected));
const showBoxUploadStatus = computed(() => form.uploadToBox || boxUploadStatus.value !== "idle");

const buildPanels = computed(() => {
  const current = job.value;
  if (!current) return [];
  const targets = current.target_jobs ?? {};
  const keys = ["client", "server"].filter((key) => Boolean(targets[key]));
  if (!keys.length) {
    return [buildPanel("build", "Build Log", current)];
  }
  return keys.map((key) => buildPanel(key, key === "client" ? "Client Log" : "Server Log", targets[key]!));
});

const buildPanelsGridClass = computed(() => {
  return buildPanels.value.length === 1 ? "" : "xl:grid-cols-2";
});

const artifacts = computed(() => {
  const current = job.value;
  if (!current) return [];
  const targetArtifacts = Object.values(current.target_jobs ?? {}).flatMap((targetJob) => targetJob?.artifacts ?? []);
  return targetArtifacts.length ? targetArtifacts : current.artifacts ?? [];
});
const manualUploadJobs = computed(() => {
  const current = job.value;
  if (!current || form.uploadToBox) return [];
  const targetJobs = Object.values(current.target_jobs ?? {}).filter(
    (targetJob): targetJob is BuildJob => Boolean(targetJob?.status === "succeeded" && targetJob.artifacts?.length)
  );
  if (targetJobs.length) return targetJobs;
  return current.status === "succeeded" && current.artifacts?.length ? [current] : [];
});
const canManualUploadToBox = computed(() => manualUploadJobs.value.length > 0);
const lastLogKey = computed(() =>
  buildPanels.value
    .map((panel) => {
      const logs = panel.logs;
      const last = logs[logs.length - 1];
      return `${panel.key}:${panel.job.updated_at ?? 0}:${last?.seq ?? last?.ts ?? "empty"}:${logs.length}`;
    })
    .join("|")
);

function buildPanel(key: string, title: string, targetJob: BuildJob) {
  const buildLogs = targetJob.logs ?? [];
  const logs = [...buildLogs, ...(boxUploadLogs.value[targetJob.job_id] ?? [])];
  return {
    key,
    title,
    job: targetJob,
    logs,
    hiddenLogCount: Math.max((targetJob.total_logs ?? buildLogs.length) - buildLogs.length, 0),
  };
}

function parseTicketIds(): string[] {
  return form.jpIssueId
    .split(/[\s,]+/)
    .map((value) => value.replace(/\D/g, ""))
    .filter(Boolean);
}

function buildAutoTargetBranch(): string {
  const defaultBaseBranch = sessionState.systemSettings.default_base_branch?.trim();
  const tickets = parseTicketIds();
  if (!defaultBaseBranch || !tickets.length) return "";
  return `${defaultBaseBranch}_${tickets.map((ticket) => `#${ticket}`).join("_")}`;
}

function appendBoxUploadLog(targetJob: BuildJob, level: BuildJobLog["level"], message: string) {
  const key = targetJob.job_id;
  const existing = boxUploadLogs.value[key] ?? [];
  boxUploadLogs.value = {
    ...boxUploadLogs.value,
    [key]: [...existing, { ts: Date.now() / 1000, level, source: "box", message }]
  };
}

function refreshUploadingToBox() {
  uploadingToBox.value = Object.keys(uploadingBoxJobIds).length > 0;
}

function setLogContainer(key: string, el: unknown) {
  logContainers[key] = el instanceof HTMLElement ? el : null;
}

function logLineClass(level: string): string {
  if (level === "error") return "text-red-300";
  if (level === "warn") return "text-amber-300";
  return "text-neutral-100";
}

function statusBadgeClass(status: string): string {
  if (status === "succeeded") return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
  if (status === "failed") return "bg-red-50 text-red-700 ring-1 ring-red-200";
  if (status === "canceled") return "bg-red-50 text-red-700 ring-1 ring-red-200";
  if (status === "partial") return "bg-amber-50 text-amber-800 ring-1 ring-amber-200";
  if (status === "running" || status === "queued") return "bg-sky-50 text-sky-700 ring-1 ring-sky-200";
  return "bg-neutral-100 text-[#5C5E62] ring-1 ring-neutral-200";
}

function statusLabel(status: string): string {
  return status === "succeeded" ? "success" : status;
}

function setBoxUploadStatus(status: BoxUploadStatus) {
  boxUploadStatus.value = status;
}

function boxUploadStatusLabel(): string {
  if (boxUploadStatus.value === "pending") return "Pending";
  if (boxUploadStatus.value === "uploading") return "Uploading";
  if (boxUploadStatus.value === "succeeded") return "Success";
  if (boxUploadStatus.value === "failed") return "Failed";
  if (boxUploadStatus.value === "skipped") return "Skipped";
  return boxReady.value ? "Ready" : "Not ready";
}

function boxUploadStatusClass(): string {
  if (boxUploadStatus.value === "succeeded") return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  if (boxUploadStatus.value === "failed") return "bg-red-50 text-red-700 ring-red-200";
  if (boxUploadStatus.value === "skipped") return "bg-amber-50 text-amber-800 ring-amber-200";
  if (boxUploadStatus.value === "pending" || boxUploadStatus.value === "uploading") return "bg-sky-50 text-sky-700 ring-sky-200";
  return boxReady.value ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-neutral-100 text-[#5C5E62] ring-neutral-200";
}

function canStopWorker(status: string): boolean {
  return status === "queued" || status === "running";
}

function formatTs(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
}

function boxLinkType(type: string): "client" | "server" {
  return type === "server" ? "server" : "client";
}

function boxTypeLabel(type: string): string {
  return boxLinkType(type) === "server" ? "Server" : "Client";
}

function boxTicketLinkLabel(item: BoxUploadedItem): string {
  return `${boxTypeLabel(item.type)} build ${item.dateFolderName} - ${item.fileName}`;
}

async function copyUploadedBoxLink(url: string) {
  try {
    await copyText(url);
    showToast("Box link copied", "success");
  } catch {
    showToast("Cannot copy Box link", "error");
  }
}

async function loadDefaults() {
  await refreshLocalServerStatus();
  await loadBoxStatus();
  let defaults: { sourceFolder: string; buildFolder: string };
  try {
    defaults = await localServerApi.defaultPaths();
  } catch (error) {
    localServerOnline.value = false;
    showToast((error as Error).message, "warning");
    return;
  }

  let savedPaths: Awaited<ReturnType<typeof usersApi.localPaths>> = {};
  try {
    savedPaths = await usersApi.localPaths();
  } catch (error) {
    showToast((error as Error).message, "warning");
  }
  form.sourceFolder = await validDirectoryOrFallback(savedPaths.build_source_folder, defaults.sourceFolder, "Saved source folder");
  form.buildFolder = await validDirectoryOrFallback(savedPaths.build_output_folder, defaults.buildFolder, "Saved build folder");
}

async function loadBoxStatus() {
  try {
    const status = await boxApi.status();
    boxStatus.value = status;
    form.uploadToBox = status.configured && status.connected;
    if (!form.uploadToBox && boxUploadStatus.value !== "idle") {
      setBoxUploadStatus("idle");
    }
  } catch (error) {
    boxStatus.value = { configured: false, connected: false, message: (error as Error).message };
    form.uploadToBox = false;
  }
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function syncBoxOAuthProxySettings() {
  if (boxOAuthRedirectUri !== `${localServerBase}/box/oauth/callback`) {
    return;
  }
  await localServerApi.setSetting("box.oauth.backend_base", apiBackendBase);
  await localServerApi.setSetting("box.oauth.callback_path", apiBoxOAuthCallbackPath);
}

async function connectBoxFromBuildSource(): Promise<boolean> {
  const popup = window.open("", "contrack_box_oauth", "width=720,height=760,popup=yes");
  try {
    await syncBoxOAuthProxySettings();
    const response = await boxApi.startOAuth({ redirect_uri: boxOAuthRedirectUri });
    if (popup && !popup.closed) {
      popup.opener = null;
      popup.location.href = response.authorize_url;
      setBoxUploadStatus("pending");
    } else if (!popup) {
      window.location.href = response.authorize_url;
      return false;
    } else {
      showToast("Box authorization window was closed", "warning");
      return false;
    }
    const deadline = Date.now() + 180000;
    while (Date.now() < deadline) {
      await wait(2000);
      const status = await boxApi.status();
      boxStatus.value = status;
      if (status.configured && status.connected) {
        showToast("Box connected", "success");
        return true;
      }
      if (popup.closed) break;
    }
    showToast("Box authorization is not complete yet", "warning");
    return false;
  } catch (error) {
    if (popup && !popup.closed) {
      popup.close();
    }
    showToast((error as Error).message, "error");
    return false;
  }
}

async function handleAutoUploadToggle() {
  if (!form.uploadToBox) {
    setBoxUploadStatus("idle");
    return;
  }
  await loadBoxStatus();
  if (!boxStatus.value?.configured) {
    form.uploadToBox = false;
    setBoxUploadStatus("failed");
    showToast(boxStatus.value?.message || "Box settings are incomplete", "warning");
    return;
  }
  if (!boxStatus.value.connected) {
    form.uploadToBox = false;
    const connected = await connectBoxFromBuildSource();
    await loadBoxStatus();
    form.uploadToBox = connected && Boolean(boxStatus.value?.connected);
    if (form.uploadToBox) {
      setBoxUploadStatus("pending");
    }
    return;
  }
  setBoxUploadStatus("pending");
}

async function validateDirectory(path: string, label: string) {
  const result = await localServerApi.validatePath(path, true);
  if (!result.valid) {
    // If folder doesn't exist, ask user if they want to create it
    if (!result.exists && result.path) {
      const shouldCreate = window.confirm(`Folder does not exist:\n${result.path}\n\nDo you want to create it?`);
      
      if (shouldCreate) {
        try {
          await localServerApi.createDirectory(result.path);
          showToast(`Created folder: ${result.path}`, "success");
          localServerOnline.value = true;
          return result.path;
        } catch (error) {
          throw new Error(`Failed to create ${label}: ${(error as Error).message}`);
        }
      } else {
        throw new Error(`${label}: ${result.message}`);
      }
    }
    throw new Error(`${label}: ${result.message}`);
  }
  localServerOnline.value = true;
  return result.path;
}

async function validDirectoryOrFallback(savedPath: string | null | undefined, fallback: string, label: string) {
  if (savedPath?.trim()) {
    try {
      return await validateDirectory(savedPath, label);
    } catch (error) {
      showToast((error as Error).message, "warning");
    }
  }
  if (fallback?.trim()) {
    try {
      return await validateDirectory(fallback, "Default folder");
    } catch {
      return fallback;
    }
  }
  return "";
}

async function refreshLocalServerStatus(showMessage = false) {
  checkingLocalServer.value = true;
  try {
    await localServerApi.health();
    localServerOnline.value = true;
    if (showMessage) showToast("Node processing server is running", "success");
  } catch (error) {
    localServerOnline.value = false;
    if (showMessage) showToast((error as Error).message, "error");
  } finally {
    checkingLocalServer.value = false;
  }
}

async function browseSource() {
  try {
    const selected = await localServerApi.selectDirectory(form.sourceFolder);
    if (selected) {
      form.sourceFolder = await validateDirectory(selected, "Source folder");
      await usersApi.updateLocalPaths({ build_source_folder: form.sourceFolder });
    }
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function browseBuild() {
  try {
    const selected = await localServerApi.selectDirectory(form.buildFolder);
    if (selected) {
      form.buildFolder = await validateDirectory(selected, "Build folder");
      await usersApi.updateLocalPaths({ build_output_folder: form.buildFolder });
    }
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function startBuild() {
  if (!canBuild.value) {
    showToast("Enter branch, source folder, build folder, and target", "warning");
    return;
  }
  try {
    uploadedBoxItems.value = [];
    boxUploadLogs.value = {};
    uploadCompletedJobId.value = null;
    for (const key of Object.keys(uploadingBoxJobIds)) delete uploadingBoxJobIds[key];
    for (const key of Object.keys(uploadedBoxJobIds)) delete uploadedBoxJobIds[key];
    setBoxUploadStatus(form.uploadToBox ? "pending" : "idle");
    form.sourceFolder = await validateDirectory(form.sourceFolder, "Source folder");
    form.buildFolder = await validateDirectory(form.buildFolder, "Build folder");
    await usersApi.updateLocalPaths({
      build_source_folder: form.sourceFolder,
      build_output_folder: form.buildFolder,
    });
    job.value = await localServerApi.build.start({
      targetBranch: form.targetBranch.trim(),
      sourceFolder: form.sourceFolder,
      buildFolder: form.buildFolder,
      buildClient: form.buildClient,
      buildServer: form.buildServer,
      repo: sessionState.systemSettings.git_repo,
      githubToken: sessionState.userSettings.github_token,
    });
    void auditApi.record({
      action: "build_start",
      target_type: "build_job",
      target_id: job.value.job_id,
      payload_after: {
        targetBranch: form.targetBranch.trim(),
        buildClient: form.buildClient,
        buildServer: form.buildServer,
        uploadToBox: form.uploadToBox,
        sourceFolder: form.sourceFolder,
        buildFolder: form.buildFolder
      }
    }).catch(() => undefined);
    localServerOnline.value = true;
    startPolling();
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

function requestStartBuild() {
  if (running.value) return;
  void startBuild();
}

function startPolling() {
  stopPolling();
  if (!job.value) return;
  polling.value = window.setInterval(async () => {
    if (!job.value) return;
    try {
      const next = await localServerApi.build.getJob(job.value.job_id);
      if (next) {
        job.value = next;
        uploadCompletedTargets(next);
        if (["succeeded", "failed", "partial", "canceled"].includes(next.status)) {
          stopPolling();
          void auditApi.record({
            action: "build_complete",
            target_type: "build_job",
            target_id: next.job_id,
            payload_after: {
              status: next.status,
              error: next.error,
              targetBranch: form.targetBranch.trim(),
              artifacts: (next.artifacts ?? []).map((artifact) => ({
                type: artifact.type,
                file_name: artifact.file_name,
                path: artifact.path
              }))
            }
          }).catch(() => undefined);
          showToast(buildStatusMessage(next), next.status === "succeeded" ? "success" : next.status === "partial" ? "warning" : "error");
          if (form.uploadToBox) {
            uploadCompletedTargets(next);
          }
          if (form.uploadToBox && ["failed", "canceled"].includes(next.status)) {
            setBoxUploadStatus("skipped");
          }
        }
      }
    } catch (error) {
      stopPolling();
      showToast((error as Error).message, "error");
    }
  }, 1000);
}

function buildStatusMessage(next: BuildJob) {
  if (next.status === "succeeded") return "Build completed";
  if (next.status === "canceled") return "Build stopped";
  if (next.status === "partial") return next.error || "Build completed partially";
  return next.error || "Build failed";
}

function stopPolling() {
  if (polling.value !== null) {
    window.clearInterval(polling.value);
    polling.value = null;
  }
}

async function openArtifact(path: string) {
  try {
    await localServerApi.openContainingFolder(path);
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function uploadBuildArtifacts(targetJob: BuildJob | null = job.value) {
  if (!targetJob || uploadingBoxJobIds[targetJob.job_id] || uploadedBoxJobIds[targetJob.job_id]) return;
  const ticketIds = parseTicketIds();
  const artifactsToUpload = targetJob.artifacts ?? [];
  if (!artifactsToUpload.length) {
    appendBoxUploadLog(targetJob, "warn", "No build artifacts to upload");
    setBoxUploadStatus("skipped");
    showToast("No build artifacts to upload", "warning");
    return;
  }
  uploadingBoxJobIds[targetJob.job_id] = true;
  refreshUploadingToBox();
  appendBoxUploadLog(targetJob, "info", `Uploading ${artifactsToUpload.length} ${targetJob.target ?? "build"} artifact(s) to Box`);
  setBoxUploadStatus("uploading");
  try {
    const uploadAccess = await boxApi.uploadAccess();
    const result = await localServerApi.box.uploadArtifacts({
      accessToken: uploadAccess.access_token,
      clientFolderId: uploadAccess.client_folder_id,
      serverFolderId: uploadAccess.server_folder_id,
      sharedLinkAccess: uploadAccess.shared_link_access,
      artifacts: artifactsToUpload,
    });
    let linkedCount = 0;
    let skippedLinkCount = 0;
    let failedLinkCount = 0;
    if (!ticketIds.length) {
      appendBoxUploadLog(targetJob, "warn", "No JP ticket entered; Box links will not be attached to tickets");
    }
    for (const item of result.items) {
      if (!item.sharedLink) {
        throw new Error(`Box did not return a shared link for ${item.fileName}`);
      }
      for (const ticketId of ticketIds) {
        try {
          await ticketsApi.upsertLink(Number(ticketId), {
            type: boxLinkType(item.type),
            label: boxTicketLinkLabel(item),
            url: item.sharedLink,
          });
          linkedCount += 1;
        } catch (error) {
          if (error instanceof HttpError && error.status === 404) {
            skippedLinkCount += 1;
            appendBoxUploadLog(targetJob, "warn", `Skipped JP #${ticketId}: managed ticket not found`);
          } else {
            failedLinkCount += 1;
            appendBoxUploadLog(targetJob, "warn", `Could not attach Box link to JP #${ticketId}: ${(error as Error).message}`);
          }
        }
      }
      appendBoxUploadLog(targetJob, "info", `Uploaded ${item.fileName} to Box: ${item.sharedLink}`);
    }
    uploadedBoxItems.value = [...uploadedBoxItems.value, ...result.items];
    uploadedBoxJobIds[targetJob.job_id] = true;
    uploadCompletedJobId.value = targetJob.job_id;
    const linkMessage = linkedCount
      ? `linked ${linkedCount} ticket link(s)`
      : skippedLinkCount || failedLinkCount
        ? "ticket link attach skipped"
        : "no ticket links attached";
    setBoxUploadStatus("succeeded");
    showToast(`Uploaded ${result.items.length} artifact(s) to Box; ${linkMessage}`, "success");
  } catch (error) {
    uploadedBoxJobIds[targetJob.job_id] = true;
    const errorMsg = (error as Error).message;
    appendBoxUploadLog(targetJob, "error", errorMsg);
    setBoxUploadStatus("failed");
    
    // Check if error is related to token expiry
    if (error instanceof HttpError && (error.status === 400 || error.status === 502)) {
      if (errorMsg.includes("authorization") || errorMsg.includes("token") || errorMsg.includes("refresh")) {
        appendBoxUploadLog(targetJob, "warn", "Box authorization may have expired. Please reconnect to Box.");
        showToast("Box authorization expired. Please reconnect.", "warning");
        // Reset Box connection status
        boxStatus.value = { configured: true, connected: false, message: "Box authorization is required" };
        form.uploadToBox = false;
        return;
      }
    }
    showToast(errorMsg, "error");
  } finally {
    delete uploadingBoxJobIds[targetJob.job_id];
    refreshUploadingToBox();
  }
}

async function uploadManualBuildArtifacts() {
  if (!canManualUploadToBox.value || uploadingToBox.value) return;
  if (!boxReady.value) {
    showToast("Box is not connected", "warning");
    return;
  }
  for (const targetJob of manualUploadJobs.value) {
    await uploadBuildArtifacts(targetJob);
  }
}

function uploadCompletedTargets(parentJob: BuildJob) {
  if (!form.uploadToBox) return;
  const targets = Object.values(parentJob.target_jobs ?? {});
  for (const targetJob of targets) {
    if (targetJob?.status === "succeeded" && targetJob.artifacts?.length) {
      void uploadBuildArtifacts(targetJob);
    } else if (targetJob && ["failed", "canceled"].includes(targetJob.status) && !uploadedBoxJobIds[targetJob.job_id]) {
      uploadedBoxJobIds[targetJob.job_id] = true;
      appendBoxUploadLog(targetJob, "warn", "Box upload skipped because this build target did not complete");
    }
  }
}

async function stopBuildWorker(jobId: string) {
  if (!job.value || stoppingBuildJobs[jobId]) return;
  stoppingBuildJobs[jobId] = true;
  try {
    await localServerApi.build.cancelJob(jobId);
    const next = await localServerApi.build.getJob(job.value.job_id);
    job.value = next;
    if (["succeeded", "failed", "partial", "canceled"].includes(next.status)) {
      stopPolling();
    }
    showToast("Build worker stop requested", "warning");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    delete stoppingBuildJobs[jobId];
  }
}

watch(
  lastLogKey,
  async () => {
    if (!autoScroll.value) return;
    await nextTick();
    for (const el of Object.values(logContainers)) {
      el?.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }
);

watch(
  () => [form.jpIssueId, sessionState.systemSettings.default_base_branch],
  () => {
    const nextBranch = buildAutoTargetBranch();
    if (!nextBranch) {
      if (form.targetBranch === lastAutoTargetBranch.value) {
        form.targetBranch = "";
      }
      lastAutoTargetBranch.value = "";
      return;
    }
    if (!form.targetBranch.trim() || form.targetBranch === lastAutoTargetBranch.value) {
      form.targetBranch = nextBranch;
      lastAutoTargetBranch.value = nextBranch;
    }
  }
);

onMounted(loadDefaults);
onBeforeUnmount(stopPolling);
</script>

<template>
  <section class="grid gap-6">
    <form class="grid gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm" @submit.prevent="requestStartBuild">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Build Source</h3>
          <p class="mt-1 text-sm text-[#5C5E62]">Client and server builds run on the Node processing server.</p>
        </div>
        <button
          type="button"
          class="rounded px-3 py-2 text-sm ring-1 transition"
          :class="localServerOnline ? 'bg-emerald-50 text-emerald-700 ring-emerald-200' : 'bg-amber-50 text-amber-800 ring-amber-200'"
          :disabled="checkingLocalServer"
          @click="refreshLocalServerStatus(true)"
        >
          {{ checkingLocalServer ? "Checking..." : localServerOnline ? "Node server online" : `Node server: ${localServerBase}` }}
        </button>
      </div>

      <div class="grid gap-4 lg:grid-cols-2">
        <div class="grid gap-2">
          <label class="text-sm font-medium text-[#393C41]">JP Ticket ID (optional)</label>
          <input
            v-model="form.jpIssueId"
            inputmode="numeric"
            class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
            placeholder="12345"
          />
        </div>
        <div class="grid gap-2">
          <label class="text-sm font-medium text-[#393C41]">Target Branch</label>
          <input
            v-model="form.targetBranch"
            class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
            placeholder="feature/example"
          />
        </div>
        <div class="grid gap-2">
          <label class="text-sm font-medium text-[#393C41]">Box Upload</label>
          <div class="flex min-h-10 flex-wrap items-center gap-3 rounded border border-[#D0D1D2] px-3 py-2">
            <label class="flex items-center gap-2 text-sm text-[#393C41]" :class="!boxReady ? 'opacity-60' : ''">
              <input v-model="form.uploadToBox" type="checkbox" class="size-4 accent-[#3E6AE1]" @change="handleAutoUploadToggle" />
              Auto upload to Box
            </label>
            <span v-if="showBoxUploadStatus" class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1" :class="boxUploadStatusClass()">{{ boxUploadStatusLabel() }}</span>
            <span class="text-xs text-[#5C5E62]">{{ boxStatus?.message || "Checking Box" }}</span>
          </div>
        </div>
        <div class="grid gap-2">
          <label class="text-sm font-medium text-[#393C41]">Build Target</label>
          <div class="flex min-h-10 flex-wrap items-center gap-4 rounded border border-[#D0D1D2] px-3 py-2">
            <label class="flex items-center gap-2 text-sm text-[#393C41]">
              <input v-model="form.buildClient" type="checkbox" class="size-4 accent-[#3E6AE1]" />
              Client
            </label>
            <label class="flex items-center gap-2 text-sm text-[#393C41]">
              <input v-model="form.buildServer" type="checkbox" class="size-4 accent-[#3E6AE1]" />
              Server
            </label>
          </div>
        </div>
        <div class="grid gap-2">
          <label class="text-sm font-medium text-[#393C41]">Source Folder</label>
          <div class="flex gap-2">
            <input v-model="form.sourceFolder" class="min-w-0 flex-1 rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
            <button type="button" class="rounded border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100" @click="browseSource">Browse</button>
          </div>
        </div>
        <div class="grid gap-2">
          <label class="text-sm font-medium text-[#393C41]">Build Folder</label>
          <div class="flex gap-2">
            <input v-model="form.buildFolder" class="min-w-0 flex-1 rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
            <button type="button" class="rounded border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100" @click="browseBuild">Browse</button>
          </div>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          class="inline-flex min-h-10 min-w-45 items-center justify-center gap-2 rounded-lg bg-[#3E6AE1] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="!canBuild || running || uploadingToBox"
        >
          <LoadingCircle v-if="running || uploadingToBox" />
          {{ uploadingToBox ? "Uploading..." : running ? "Building..." : "Start Build" }}
        </button>
        <span v-if="job" class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium" :class="statusBadgeClass(job.status)">{{ statusLabel(job.status) }}</span>
      </div>
    </form>

    <div v-if="buildPanels.length" class="grid gap-4" :class="buildPanelsGridClass">
      <div v-for="panel in buildPanels" :key="panel.key" class="relative grid gap-3 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
        <button
          v-if="canStopWorker(panel.job.status)"
          type="button"
          class="absolute top-3 right-3 inline-flex size-8 items-center justify-center rounded-full border border-red-200 bg-red-50 text-red-700 transition hover:bg-red-100 disabled:cursor-wait disabled:opacity-60"
          :disabled="Boolean(stoppingBuildJobs[panel.job.job_id])"
          title="Stop worker"
          aria-label="Stop worker"
          @click="stopBuildWorker(panel.job.job_id)"
        >
          <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="6" y="6" width="8" height="8" rx="1" />
          </svg>
        </button>
        <div class="flex flex-wrap items-center justify-between gap-3" :class="canStopWorker(panel.job.status) ? 'pr-10' : ''">
          <div class="flex items-center gap-3">
            <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">{{ panel.title }}</h3>
            <span class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium" :class="statusBadgeClass(panel.job.status)">{{ statusLabel(panel.job.status) }}</span>
            <span v-if="panel.hiddenLogCount" class="text-xs text-[#5C5E62]">showing last {{ panel.logs.length }} of {{ panel.job.total_logs }} lines</span>
          </div>
          <label class="flex items-center gap-2 text-xs text-[#5C5E62]">
            <input v-model="autoScroll" type="checkbox" class="size-3.5 accent-[#3E6AE1]" />
            Auto-scroll
          </label>
        </div>
        <div :ref="(el) => setLogContainer(panel.key, el)" class="build-log-output max-h-120 overflow-auto scroll-smooth rounded-lg bg-neutral-950 p-3">
          <div v-if="!panel.logs.length" class="text-neutral-500">Waiting for log output...</div>
          <div v-else class="grid gap-1">
            <div v-for="(entry, idx) in (panel.logs as BuildJobLog[])" :key="entry.seq ?? `${entry.ts}-${idx}`" class="flex gap-2" :class="logLineClass(entry.level)">
              <span class="shrink-0 text-neutral-500">{{ formatTs(entry.ts) }}</span>
              <span class="shrink-0 text-neutral-400">[{{ entry.source }}]</span>
              <span class="min-w-0 whitespace-pre-wrap wrap-break-word">{{ entry.message }}</span>
            </div>
          </div>
        </div>
        <p v-if="panel.job.error" class="whitespace-pre-wrap text-sm text-red-700">{{ panel.job.error }}</p>
      </div>
    </div>

    <div v-if="artifacts.length" class="grid gap-3 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Artifacts</h3>
        <div class="flex flex-wrap items-center gap-2">
          <span v-if="showBoxUploadStatus" class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1" :class="boxUploadStatusClass()">{{ boxUploadStatusLabel() }}</span>
          <button
            v-if="!form.uploadToBox"
            type="button"
            class="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-[#3E6AE1] bg-white px-3 py-2 text-sm font-medium text-[#3E6AE1] transition hover:bg-[#F5F8FF] disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="!canManualUploadToBox || uploadingToBox"
            @click="uploadManualBuildArtifacts"
          >
            <LoadingCircle v-if="uploadingToBox" class="text-current" />
            {{ uploadingToBox ? "Uploading..." : "Upload to Box" }}
          </button>
        </div>
      </div>
      <button
        v-for="artifact in artifacts"
        :key="artifact.path"
        class="flex items-center justify-between gap-4 rounded border border-neutral-200 bg-neutral-50 px-4 py-3 text-left transition hover:bg-neutral-100"
        @click="openArtifact(artifact.path)"
      >
        <span>
          <span class="block text-sm font-medium text-[#171A20]">{{ artifact.file_name }}</span>
          <span class="block break-all text-xs text-[#5C5E62]">{{ artifact.path }}</span>
        </span>
        <span class="rounded bg-white px-2 py-1 text-xs font-medium text-[#393C41] ring-1 ring-neutral-200">{{ artifact.type }}</span>
      </button>
      <div v-if="uploadedBoxItems.length" class="grid gap-2 rounded border border-emerald-200 bg-emerald-50 p-3">
        <div
          v-for="item in uploadedBoxItems"
          :key="item.boxFileId"
          class="flex items-center justify-between gap-3 rounded bg-white px-3 py-2 text-sm text-[#171A20] ring-1 ring-emerald-100 transition hover:bg-emerald-50"
        >
          <span class="min-w-0 flex-1">
            <span class="flex min-w-0 flex-wrap items-center gap-2">
              <span class="min-w-0 truncate font-medium">{{ item.fileName }}</span>
              <button
                type="button"
                class="inline-flex size-7 shrink-0 items-center justify-center rounded-full border border-emerald-200 bg-emerald-50 text-emerald-700 transition hover:bg-emerald-100"
                title="Copy Box link"
                @click="copyUploadedBoxLink(item.sharedLink)"
              >
                <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <rect x="7" y="7" width="9" height="9" rx="2"></rect>
                  <path d="M4 13V5a2 2 0 0 1 2-2h8"></path>
                </svg>
              </button>
            </span>
            <a :href="item.sharedLink" target="_blank" rel="noreferrer" class="block break-all text-xs text-[#3E6AE1] hover:underline">
              {{ item.sharedLink }}
            </a>
          </span>
          <span class="shrink-0 rounded bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200">{{ boxTypeLabel(item.type) }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.build-log-output {
  font-family:
    "Cascadia Mono",
    "Consolas",
    "Noto Sans Mono",
    "SFMono-Regular",
    "Menlo",
    monospace;
  font-size: 13px;
  line-height: 1.55;
}
</style>
