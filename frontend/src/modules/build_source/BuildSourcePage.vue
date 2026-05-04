<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import LoadingCircle from "../../shared/LoadingCircle.vue";
import { electronApi, isElectronClient } from "../../shared/electron";
import { sessionState } from "../../shared/session";
import { showToast } from "../../shared/toast";
import type { BuildJob } from "../../shared/types";

const form = reactive({
  targetBranch: "",
  sourceFolder: "",
  buildFolder: "",
  buildClient: true,
  buildServer: true,
});

const job = ref<BuildJob | null>(null);
const polling = ref<number | null>(null);
const logContainer = ref<HTMLElement | null>(null);
const autoScroll = ref(true);

const running = computed(() => job.value?.status === "queued" || job.value?.status === "running");
const canBuild = computed(() =>
  isElectronClient() &&
  Boolean(form.targetBranch.trim() && form.sourceFolder.trim() && form.buildFolder.trim() && (form.buildClient || form.buildServer))
);
const buildLogs = computed(() => job.value?.logs ?? []);
const hiddenLogCount = computed(() => Math.max((job.value?.total_logs ?? buildLogs.value.length) - buildLogs.value.length, 0));
const lastLogKey = computed(() => {
  const logs = buildLogs.value;
  const last = logs[logs.length - 1];
  return last ? `${job.value?.updated_at ?? 0}:${last.seq ?? last.ts}:${logs.length}` : `${job.value?.updated_at ?? 0}:empty`;
});

function logLineClass(level: string): string {
  if (level === "error") return "text-red-300";
  if (level === "warn") return "text-amber-300";
  return "text-neutral-200";
}

function statusBadgeClass(status: string): string {
  if (status === "succeeded") return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
  if (status === "failed") return "bg-red-50 text-red-700 ring-1 ring-red-200";
  if (status === "running" || status === "queued") return "bg-sky-50 text-sky-700 ring-1 ring-sky-200";
  return "bg-neutral-100 text-[#5C5E62] ring-1 ring-neutral-200";
}

function formatTs(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
}

async function loadDefaults() {
  const api = electronApi();
  if (!api) return;
  const defaults = await api.getDefaultPaths();
  form.sourceFolder = (await api.getSetting<string>("paths.buildSourceFolder")) || defaults.sourceFolder;
  form.buildFolder = (await api.getSetting<string>("paths.buildOutputFolder")) || defaults.buildFolder;
}

async function browseSource() {
  const api = electronApi();
  if (!api) return;
  const selected = await api.selectDirectory(form.sourceFolder);
  if (selected) {
    form.sourceFolder = selected;
    await api.setSetting("paths.buildSourceFolder", selected);
  }
}

async function browseBuild() {
  const api = electronApi();
  if (!api) return;
  const selected = await api.selectDirectory(form.buildFolder);
  if (selected) {
    form.buildFolder = selected;
    await api.setSetting("paths.buildOutputFolder", selected);
  }
}

async function startBuild() {
  const api = electronApi();
  if (!api) {
    showToast("Build source chỉ chạy trong Electron client", "warning");
    return;
  }
  if (!canBuild.value) {
    showToast("Nhập branch, source folder, build folder và chọn ít nhất một target", "warning");
    return;
  }
  await api.setSetting("paths.buildSourceFolder", form.sourceFolder);
  await api.setSetting("paths.buildOutputFolder", form.buildFolder);
  try {
    job.value = await api.build.start({
      targetBranch: form.targetBranch.trim(),
      sourceFolder: form.sourceFolder,
      buildFolder: form.buildFolder,
      buildClient: form.buildClient,
      buildServer: form.buildServer,
      repo: sessionState.systemSettings.git_repo,
      githubToken: sessionState.userSettings.github_token,
    });
    startPolling();
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

function startPolling() {
  stopPolling();
  const api = electronApi();
  if (!api || !job.value) return;
  polling.value = window.setInterval(async () => {
    if (!job.value) return;
    const next = await api.build.getJob(job.value.job_id);
    if (next) {
      job.value = next;
      if (next.status === "succeeded" || next.status === "failed") {
        stopPolling();
        showToast(next.status === "succeeded" ? "Build completed" : next.error || "Build failed", next.status === "succeeded" ? "success" : "error");
      }
    }
  }, 1000);
}

function stopPolling() {
  if (polling.value !== null) {
    window.clearInterval(polling.value);
    polling.value = null;
  }
}

async function openArtifact(path: string) {
  await electronApi()?.openPath(path);
}

watch(
  lastLogKey,
  async () => {
    if (!autoScroll.value) return;
    await nextTick();
    const el = logContainer.value;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }
);

onMounted(loadDefaults);
onBeforeUnmount(stopPolling);
</script>

<template>
  <section class="grid gap-6">
    <div class="grid gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Build Source</h3>
          <p class="mt-1 text-sm text-[#5C5E62]">Build chạy trên máy Windows của Electron client.</p>
        </div>
        <span v-if="!isElectronClient()" class="rounded bg-amber-50 px-3 py-2 text-sm text-amber-800 ring-1 ring-amber-200">
          Chức năng này chỉ khả dụng trong bản Electron.
        </span>
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
            <button class="rounded border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100" @click="browseSource">Browse</button>
          </div>
        </div>
        <div class="grid gap-2">
          <label class="text-sm font-medium text-[#393C41]">Build Folder</label>
          <div class="flex gap-2">
            <input v-model="form.buildFolder" class="min-w-0 flex-1 rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
            <button class="rounded border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100" @click="browseBuild">Browse</button>
          </div>
        </div>
      </div>

      <div class="flex items-center gap-3">
        <button
          class="inline-flex min-h-10 min-w-[180px] items-center justify-center gap-2 rounded-lg bg-[#3E6AE1] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="!canBuild || running"
          @click="startBuild"
        >
          <LoadingCircle v-if="running" />
          {{ running ? "Building..." : "Start Build" }}
        </button>
        <span v-if="job" class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium" :class="statusBadgeClass(job.status)">{{ job.status }}</span>
      </div>
    </div>

    <div v-if="job" class="grid gap-3 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-3">
          <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Build Logs</h3>
          <span class="text-xs text-[#5C5E62]">job <code class="rounded bg-neutral-100 px-1.5 py-0.5">{{ job.job_id.slice(0, 12) }}</code></span>
          <span v-if="hiddenLogCount" class="text-xs text-[#5C5E62]">showing last {{ buildLogs.length }} of {{ job.total_logs }} lines</span>
        </div>
        <label class="flex items-center gap-2 text-xs text-[#5C5E62]">
          <input v-model="autoScroll" type="checkbox" class="size-3.5 accent-[#3E6AE1]" />
          Auto-scroll
        </label>
      </div>
      <div ref="logContainer" class="max-h-96 overflow-auto scroll-smooth rounded-lg bg-neutral-900 p-3 font-mono text-xs leading-relaxed">
        <div v-if="!buildLogs.length" class="text-neutral-500">Waiting for log output...</div>
        <div v-else class="grid gap-0.5">
          <div v-for="(entry, idx) in buildLogs" :key="entry.seq ?? `${entry.ts}-${idx}`" class="flex gap-2 transition-colors duration-200" :class="logLineClass(entry.level)">
            <span class="shrink-0 text-neutral-500">{{ formatTs(entry.ts) }}</span>
            <span class="shrink-0 text-neutral-400">[{{ entry.source }}]</span>
            <span class="break-all whitespace-pre-wrap">{{ entry.message }}</span>
          </div>
        </div>
      </div>
      <p v-if="job.error" class="text-sm text-red-700">{{ job.error }}</p>
    </div>

    <div v-if="job?.artifacts.length" class="grid gap-3 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Artifacts</h3>
      <button
        v-for="artifact in job.artifacts"
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
