<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import LoadingCircle from "../../shared/LoadingCircle.vue";
import { localServerApi, localServerBase } from "../../shared/localServer";
import { sessionState } from "../../shared/session";
import { showToast } from "../../shared/toast";
import { usersApi } from "../users/api";
import type { BuildJob, BuildJobLog } from "../../shared/types";

const form = reactive({
  targetBranch: "",
  sourceFolder: "",
  buildFolder: "",
  buildClient: true,
  buildServer: true,
});

const job = ref<BuildJob | null>(null);
const polling = ref<number | null>(null);
const logContainers: Record<string, HTMLElement | null> = {};
const stoppingBuildJobs = reactive<Record<string, boolean>>({});
const autoScroll = ref(true);
const localServerOnline = ref(false);
const checkingLocalServer = ref(false);

const running = computed(() =>
  job.value?.status === "queued" ||
  job.value?.status === "running" ||
  buildPanels.value.some((panel) => panel.job.status === "queued" || panel.job.status === "running")
);
const canBuild = computed(() =>
  Boolean(form.targetBranch.trim() && form.sourceFolder.trim() && form.buildFolder.trim() && (form.buildClient || form.buildServer))
);

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

const artifacts = computed(() => job.value?.artifacts ?? []);
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
  const logs = targetJob.logs ?? [];
  return {
    key,
    title,
    job: targetJob,
    logs,
    hiddenLogCount: Math.max((targetJob.total_logs ?? logs.length) - logs.length, 0),
  };
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

function canStopWorker(status: string): boolean {
  return status === "queued" || status === "running";
}

function formatTs(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
}

async function loadDefaults() {
  await refreshLocalServerStatus();
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

async function validateDirectory(path: string, label: string) {
  const result = await localServerApi.validatePath(path, true);
  if (!result.valid) {
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
    showToast("Enter branch, source folder, build folder, and select at least one target", "warning");
    return;
  }
  try {
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
        if (["succeeded", "failed", "partial", "canceled"].includes(next.status)) {
          stopPolling();
          showToast(buildStatusMessage(next), next.status === "succeeded" ? "success" : next.status === "partial" ? "warning" : "error");
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
          <label class="text-sm font-medium text-[#393C41]">Target Branch</label>
          <input
            v-model="form.targetBranch"
            class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
            placeholder="feature/example"
          />
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
          class="inline-flex min-h-10 min-w-[180px] items-center justify-center gap-2 rounded-lg bg-[#3E6AE1] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="!canBuild || running"
        >
          <LoadingCircle v-if="running" />
          {{ running ? "Building..." : "Start Build" }}
        </button>
        <span v-if="job" class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium" :class="statusBadgeClass(job.status)">{{ job.status }}</span>
      </div>
    </form>

    <div v-if="buildPanels.length" class="grid gap-4 xl:grid-cols-2">
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
            <span class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium" :class="statusBadgeClass(panel.job.status)">{{ panel.job.status }}</span>
            <span v-if="panel.hiddenLogCount" class="text-xs text-[#5C5E62]">showing last {{ panel.logs.length }} of {{ panel.job.total_logs }} lines</span>
          </div>
          <label class="flex items-center gap-2 text-xs text-[#5C5E62]">
            <input v-model="autoScroll" type="checkbox" class="size-3.5 accent-[#3E6AE1]" />
            Auto-scroll
          </label>
        </div>
        <div :ref="(el) => setLogContainer(panel.key, el)" class="build-log-output max-h-[30rem] overflow-auto scroll-smooth rounded-lg bg-neutral-950 p-3">
          <div v-if="!panel.logs.length" class="text-neutral-500">Waiting for log output...</div>
          <div v-else class="grid gap-1">
            <div v-for="(entry, idx) in (panel.logs as BuildJobLog[])" :key="entry.seq ?? `${entry.ts}-${idx}`" class="flex gap-2" :class="logLineClass(entry.level)">
              <span class="shrink-0 text-neutral-500">{{ formatTs(entry.ts) }}</span>
              <span class="shrink-0 text-neutral-400">[{{ entry.source }}]</span>
              <span class="min-w-0 whitespace-pre-wrap break-words">{{ entry.message }}</span>
            </div>
          </div>
        </div>
        <p v-if="panel.job.error" class="whitespace-pre-wrap text-sm text-red-700">{{ panel.job.error }}</p>
      </div>
    </div>

    <div v-if="artifacts.length" class="grid gap-3 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Artifacts</h3>
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
