<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import LoadingCircle from "../../shared/LoadingCircle.vue";
import { localServerApi, localServerBase, type CodexModelOption } from "../../shared/localServer";
import { sessionState } from "../../shared/session";
import { showToast } from "../../shared/toast";
import { auditApi } from "../audit/api";
import { usersApi } from "../users/api";
import type { BuildJobLog, DocumentTranslationJob, DocumentTranslationSettings } from "../../shared/types";

const LANGUAGE_OPTIONS = ["Japanese", "Vietnamese", "English"] as const;

const LANGUAGE_CODE_MAP: Record<string, string> = {
  Japanese: "ja",
  Vietnamese: "vi",
  English: "en",
};

const LANGUAGE_NAME_MAP: Record<string, string> = {
  ja: "Japanese",
  vi: "Vietnamese",
  en: "English",
};

function langToKey(lang: string): string {
  const trimmed = lang.trim();
  return LANGUAGE_CODE_MAP[trimmed] ?? trimmed.toLowerCase().replace(/\s+/g, "_");
}

function keyToLang(code: string): string {
  return LANGUAGE_NAME_MAP[code] ?? code;
}

const form = reactive({
  filePath: "",
  outputDirectory: "",
  fromLang: "Japanese" as string,
  toLang: "Vietnamese" as string,
  model: "gpt-5.4",
  reasoningEffort: "low",
  fastMode: false,
  timeoutSeconds: 120,
  batchSize: 100,
  contextWindow: 20,
  glossary: "",
  instructions: "",
});

const job = ref<DocumentTranslationJob | null>(null);
const polling = ref<number | null>(null);
const logContainer = ref<HTMLElement | null>(null);
const stoppingTranslation = ref(false);
const autoScroll = ref(true);
const localServerOnline = ref(false);
const checkingHealth = ref(false);
const healthMessage = ref("");
const openXmlOk = ref(false);
const codexOk = ref(false);
const codexModels = ref<CodexModelOption[]>([]);
const settingsReady = ref(false);
const savingSettings = ref(false);
const activeDirectionField = ref<"from" | "to" | null>(null);
let saveSettingsTimer: number | null = null;
let directionMenuTimer: number | null = null;

const fallbackModels: CodexModelOption[] = [
  { slug: "gpt-5.5", display_name: "GPT-5.5" },
  { slug: "gpt-5.4", display_name: "gpt-5.4" },
  { slug: "gpt-5.4-mini", display_name: "GPT-5.4-Mini" },
  { slug: "gpt-5.3-codex", display_name: "gpt-5.3-codex" },
  { slug: "gpt-5.2", display_name: "gpt-5.2" }
];

const direction = computed(() => {
  const from = langToKey(form.fromLang || "Japanese");
  const to = langToKey(form.toLang || "Vietnamese");
  return `${from}_to_${to}`;
});

const running = computed(() => job.value?.status === "queued" || job.value?.status === "running");
const progress = computed(() => job.value?.progress ?? null);
const progressPercent = computed(() => {
  const current = progress.value;
  if (!current || current.translatable_segments <= 0) return 0;
  return Math.min(100, Math.round((current.translated_segments / current.translatable_segments) * 100));
});
const canStart = computed(() => Boolean(form.filePath.trim()) && !running.value);
const result = computed(() => job.value?.result ?? null);
const logs = computed(() => job.value?.logs ?? []);
const modelOptions = computed(() => {
  const options = new Map<string, CodexModelOption>();
  for (const model of [...codexModels.value, ...fallbackModels]) {
    if (model.slug) options.set(model.slug, model);
  }
  if (form.model && !options.has(form.model)) {
    options.set(form.model, { slug: form.model, display_name: `${form.model} (saved)` });
  }
  return Array.from(options.values());
});

const directionLanguageOptions = computed(() => {
  const options = new Map<string, string>();
  for (const language of LANGUAGE_OPTIONS) {
    options.set(language, language);
  }

  for (const value of [form.fromLang, form.toLang]) {
    const trimmed = value.trim();
    if (trimmed && !options.has(trimmed)) {
      options.set(trimmed, trimmed);
    }
  }

  return Array.from(options.values());
});

function openDirectionMenu(field: "from" | "to") {
  if (directionMenuTimer !== null) {
    window.clearTimeout(directionMenuTimer);
    directionMenuTimer = null;
  }
  activeDirectionField.value = field;
}

function closeDirectionMenu(field: "from" | "to") {
  if (directionMenuTimer !== null) {
    window.clearTimeout(directionMenuTimer);
  }
  directionMenuTimer = window.setTimeout(() => {
    if (activeDirectionField.value === field) {
      activeDirectionField.value = null;
    }
    directionMenuTimer = null;
  }, 120);
}

function selectDirectionLanguage(field: "from" | "to", value: string) {
  if (field === "from") {
    form.fromLang = value;
  } else {
    form.toLang = value;
  }
}

function isDirectionLanguageSelected(field: "from" | "to", value: string) {
  const current = field === "from" ? form.fromLang : form.toLang;
  return current.trim().toLowerCase() === value.trim().toLowerCase();
}

function statusBadgeClass(status?: string) {
  if (status === "succeeded") return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
  if (status === "failed") return "bg-red-50 text-red-700 ring-1 ring-red-200";
  if (status === "canceled") return "bg-red-50 text-red-700 ring-1 ring-red-200";
  if (status === "running" || status === "queued") return "bg-sky-50 text-sky-700 ring-1 ring-sky-200";
  return "bg-neutral-100 text-[#5C5E62] ring-1 ring-neutral-200";
}

function healthBadgeClass(ok: boolean) {
  return ok ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-amber-50 text-amber-800 ring-1 ring-amber-200";
}

function logLineClass(level: string) {
  if (level === "error") return "text-red-300";
  if (level === "warn") return "text-amber-300";
  return "text-neutral-100";
}

function canStopWorker(status?: string): boolean {
  return status === "queued" || status === "running";
}

function formatTs(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
}

function isSupportedDocumentFile(filePath: string) {
  return /\.(txt|md|docx|xlsx|pptx)$/i.test(filePath.trim());
}

function normalizeNumber(value: number, fallback: number, min: number, max: number) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(Math.floor(parsed), min), max);
}

function translationSettingsPayload(): DocumentTranslationSettings {
  return {
    output_directory: form.outputDirectory.trim() || null,
    direction: direction.value,
    model: form.model.trim() || null,
    reasoning_effort: form.reasoningEffort,
    timeout_seconds: normalizeNumber(form.timeoutSeconds, 120, 5, 3600),
    batch_size: normalizeNumber(form.batchSize, 100, 1, 200),
    context_window: normalizeNumber(form.contextWindow, 20, 0, 200),
    fast_mode: form.fastMode,
    glossary: form.glossary.trim() ? form.glossary : null,
    instructions: form.instructions.trim() ? form.instructions : null
  };
}

function applySavedTranslationSettings() {
  const saved = sessionState.userSettings.document_translation ?? {};
  form.outputDirectory = saved.output_directory ?? "";
  const savedDir = saved.direction ?? "ja_to_vi";
  const [fromCode, toCode] = savedDir.split("_to_");
  form.fromLang = keyToLang(fromCode ?? "ja");
  form.toLang = keyToLang(toCode ?? "vi");
  form.model = saved.model?.trim() || form.model;
  form.reasoningEffort = saved.reasoning_effort?.trim() || form.reasoningEffort;
  form.fastMode = Boolean(saved.fast_mode);
  form.timeoutSeconds = normalizeNumber(saved.timeout_seconds ?? form.timeoutSeconds, 120, 5, 3600);
  form.batchSize = normalizeNumber(saved.batch_size ?? form.batchSize, 100, 1, 200);
  form.contextWindow = normalizeNumber(saved.context_window ?? form.contextWindow, 20, 0, 200);
  form.glossary = saved.glossary ?? "";
  form.instructions = saved.instructions ?? "";
}

async function saveTranslationSettings() {
  if (!settingsReady.value || savingSettings.value) return;
  savingSettings.value = true;
  try {
    const saved = await usersApi.updateMySettings({ document_translation: translationSettingsPayload() });
    sessionState.userSettings.document_translation = saved.document_translation ?? translationSettingsPayload();
  } catch {
    // Keep autosave silent; starting a translation will surface validation or server errors.
  } finally {
    savingSettings.value = false;
  }
}

function scheduleSaveTranslationSettings() {
  if (!settingsReady.value) return;
  if (saveSettingsTimer !== null) {
    window.clearTimeout(saveSettingsTimer);
  }
  saveSettingsTimer = window.setTimeout(() => {
    saveSettingsTimer = null;
    void saveTranslationSettings();
  }, 700);
}

async function loadCodexModels() {
  try {
    codexModels.value = await localServerApi.documentTranslation.models();
  } catch {
    codexModels.value = fallbackModels;
  }
}

async function refreshHealth(showMessage = false) {
  checkingHealth.value = true;
  try {
    const health = await localServerApi.documentTranslation.health();
    localServerOnline.value = true;
    openXmlOk.value = Boolean(health.openxml.ok);
    codexOk.value = Boolean(health.codex.ok);
    healthMessage.value = health.ok ? "Ready" : [health.openxml.message, health.codex.message].filter(Boolean).join(" | ");
    if (showMessage) showToast(health.ok ? "Document translation server is ready" : healthMessage.value, health.ok ? "success" : "warning");
  } catch (error) {
    localServerOnline.value = false;
    openXmlOk.value = false;
    codexOk.value = false;
    healthMessage.value = (error as Error).message;
    if (showMessage) showToast((error as Error).message, "error");
  } finally {
    checkingHealth.value = false;
  }
}

async function browseFile() {
  try {
    const selected = await localServerApi.selectFile(form.filePath);
    if (selected) {
      form.filePath = await validateFile(selected);
    }
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function browseOutputDirectory() {
  try {
    const selected = await localServerApi.selectDirectory(form.outputDirectory);
    if (selected) {
      form.outputDirectory = await validateDirectory(selected, "Output folder");
    }
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function validateFile(filePath: string) {
  const result = await localServerApi.validatePath(filePath, false);
  if (!result.valid || !result.is_file) {
    throw new Error(`Document file: ${result.message}`);
  }
  if (!isSupportedDocumentFile(result.path)) {
    throw new Error("Document file must be .txt, .md, .docx, .xlsx, or .pptx");
  }
  return result.path;
}

async function validateDirectory(path: string, label: string) {
  const result = await localServerApi.validatePath(path, true);
  if (!result.valid) {
    throw new Error(`${label}: ${result.message}`);
  }
  return result.path;
}

function startPolling() {
  stopPolling();
  if (!job.value) return;
  polling.value = window.setInterval(async () => {
    if (!job.value) return;
    try {
      const next = await localServerApi.documentTranslation.getJob(job.value.job_id);
      job.value = next;
      if (["succeeded", "failed", "canceled"].includes(next.status)) {
        stopPolling();
        void auditApi.record({
          action: "document_translation_complete",
          target_type: "document_translation_job",
          target_id: next.job_id,
          payload_after: {
            status: next.status,
            error: next.error,
            filePath: form.filePath,
            outputPath: next.result?.output_path ?? null,
            direction: direction.value,
            model: (next.result?.model ?? form.model.trim()) || null,
            totalSegments: next.result?.total_segments ?? null,
            translatedSegments: next.progress?.translated_segments ?? null
          }
        }).catch(() => undefined);
        showToast(
          next.status === "succeeded" ? "Document translated" : next.status === "canceled" ? "Translation stopped" : next.error || "Translation failed",
          next.status === "succeeded" ? "success" : "error"
        );
      }
    } catch (error) {
      stopPolling();
      showToast((error as Error).message, "error");
    }
  }, 1500);
}

function stopPolling() {
  if (polling.value !== null) {
    window.clearInterval(polling.value);
    polling.value = null;
  }
}

async function startTranslation() {
  if (!form.filePath.trim()) {
    showToast("Document file is required", "warning");
    return;
  }

  try {
    form.filePath = await validateFile(form.filePath);
    if (form.outputDirectory.trim()) {
      form.outputDirectory = await validateDirectory(form.outputDirectory, "Output folder");
    }
    form.timeoutSeconds = normalizeNumber(form.timeoutSeconds, 120, 5, 3600);
    form.batchSize = normalizeNumber(form.batchSize, 100, 1, 200);
    form.contextWindow = normalizeNumber(form.contextWindow, 20, 0, 200);
    await saveTranslationSettings();

    job.value = await localServerApi.documentTranslation.start({
      filePath: form.filePath,
      outputDirectory: form.outputDirectory || undefined,
      direction: direction.value,
      model: form.model.trim() || undefined,
      reasoningEffort: form.reasoningEffort,
      fastMode: form.fastMode,
      timeoutSeconds: form.timeoutSeconds,
      batchSize: form.batchSize,
      contextWindow: form.contextWindow,
      glossary: form.glossary,
      instructions: form.instructions,
    });
    void auditApi.record({
      action: "document_translation_start",
      target_type: "document_translation_job",
      target_id: job.value.job_id,
      payload_after: {
        filePath: form.filePath,
        outputDirectory: form.outputDirectory || null,
        direction: direction.value,
        model: form.model.trim() || null,
        reasoningEffort: form.reasoningEffort,
        fastMode: form.fastMode,
        timeoutSeconds: form.timeoutSeconds,
        batchSize: form.batchSize,
        contextWindow: form.contextWindow
      }
    }).catch(() => undefined);
    startPolling();
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function openOutput() {
  if (!result.value?.output_path) return;
  try {
    await localServerApi.openContainingFolder(result.value.output_path);
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function stopTranslationWorker() {
  if (!job.value || stoppingTranslation.value) return;
  stoppingTranslation.value = true;
  try {
    job.value = await localServerApi.documentTranslation.cancelJob(job.value.job_id);
    stopPolling();
    showToast("Translation worker stop requested", "warning");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    stoppingTranslation.value = false;
  }
}

watch(
  () => logs.value.length,
  async () => {
    if (!autoScroll.value) return;
    await nextTick();
    logContainer.value?.scrollTo({ top: logContainer.value.scrollHeight, behavior: "smooth" });
  }
);

watch(
  () => translationSettingsPayload(),
  scheduleSaveTranslationSettings,
  { deep: true }
);

onMounted(async () => {
  applySavedTranslationSettings();
  settingsReady.value = true;
  await Promise.all([refreshHealth(false), loadCodexModels()]);
});
onBeforeUnmount(() => {
  stopPolling();
  if (directionMenuTimer !== null) {
    window.clearTimeout(directionMenuTimer);
  }
  if (saveSettingsTimer !== null) {
    window.clearTimeout(saveSettingsTimer);
  }
  void saveTranslationSettings();
});
</script>

<template>
  <section class="grid gap-6">
    <div class="grid gap-4 rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Translate Docs</h3>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <span class="rounded px-2 py-1 text-xs font-medium" :class="healthBadgeClass(localServerOnline)">Node</span>
          <span class="rounded px-2 py-1 text-xs font-medium" :class="healthBadgeClass(openXmlOk)">OpenXML</span>
          <span class="rounded px-2 py-1 text-xs font-medium" :class="healthBadgeClass(codexOk)">Codex</span>
          <button
            class="rounded border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="checkingHealth"
            @click="refreshHealth(true)"
          >
            {{ checkingHealth ? "Checking..." : localServerBase }}
          </button>
        </div>
      </div>

      <p v-if="healthMessage && (!openXmlOk || !codexOk)" class="m-0 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
        {{ healthMessage }}
      </p>

      <div class="grid gap-4 lg:grid-cols-2">
        <div class="grid gap-2 lg:col-span-2">
          <label class="text-sm font-medium text-[#393C41]">Document File</label>
          <div class="flex gap-2">
            <input
              v-model="form.filePath"
              class="min-w-0 flex-1 rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
              placeholder="C:\\Docs\\source.docx / source.md"
            />
            <button class="rounded border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100" @click="browseFile">
              Browse
            </button>
          </div>
        </div>

        <div class="grid gap-2 lg:col-span-2">
          <label class="text-sm font-medium text-[#393C41]">Output Folder</label>
          <div class="flex gap-2">
            <input
              v-model="form.outputDirectory"
              class="min-w-0 flex-1 rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
              placeholder="Same folder as source"
            />
            <button class="rounded border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100" @click="browseOutputDirectory">
              Browse
            </button>
          </div>
        </div>

        <div class="grid gap-2">
          <label class="text-sm font-medium text-[#393C41]">Direction</label>
          <div class="flex items-center gap-2">
            <div class="relative flex-1">
              <input
                v-model="form.fromLang"
                autocomplete="off"
                placeholder="From"
                class="w-full rounded border border-[#D0D1D2] bg-white px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
                @focus="openDirectionMenu('from')"
                @input="openDirectionMenu('from')"
                @blur="closeDirectionMenu('from')"
                @keydown.escape="activeDirectionField = null"
              />
              <div v-if="activeDirectionField === 'from'" class="absolute inset-x-0 top-full z-10 mt-1 overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-lg">
                <button
                  v-for="lang in directionLanguageOptions"
                  :key="`from-${lang}`"
                  type="button"
                  class="flex w-full items-center justify-between px-3 py-2 text-left text-sm transition hover:bg-[#F5F8FF]"
                  :class="isDirectionLanguageSelected('from', lang) ? 'bg-[#EAF1FF] text-[#2F56BA]' : 'text-[#171A20]'"
                  @mousedown.prevent="selectDirectionLanguage('from', lang)"
                >
                  <span>{{ lang }}</span>
                  <svg v-if="isDirectionLanguageSelected('from', lang)" viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="m4.5 10 3.5 3.5 7.5-8"></path>
                  </svg>
                </button>
              </div>
            </div>
            <span class="shrink-0 text-sm text-[#5C5E62]">&rarr;</span>
            <div class="relative flex-1">
              <input
                v-model="form.toLang"
                autocomplete="off"
                placeholder="To"
                class="w-full rounded border border-[#D0D1D2] bg-white px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
                @focus="openDirectionMenu('to')"
                @input="openDirectionMenu('to')"
                @blur="closeDirectionMenu('to')"
                @keydown.escape="activeDirectionField = null"
              />
              <div v-if="activeDirectionField === 'to'" class="absolute inset-x-0 top-full z-10 mt-1 overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-lg">
                <button
                  v-for="lang in directionLanguageOptions"
                  :key="`to-${lang}`"
                  type="button"
                  class="flex w-full items-center justify-between px-3 py-2 text-left text-sm transition hover:bg-[#F5F8FF]"
                  :class="isDirectionLanguageSelected('to', lang) ? 'bg-[#EAF1FF] text-[#2F56BA]' : 'text-[#171A20]'"
                  @mousedown.prevent="selectDirectionLanguage('to', lang)"
                >
                  <span>{{ lang }}</span>
                  <svg v-if="isDirectionLanguageSelected('to', lang)" viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="m4.5 10 3.5 3.5 7.5-8"></path>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <details class="rounded-lg border border-neutral-200 bg-neutral-50">
        <summary class="cursor-pointer select-none px-4 py-3 text-sm font-medium text-[#393C41]">
          Codex config
        </summary>
        <div class="grid gap-4 border-t border-neutral-200 bg-white p-4 lg:grid-cols-2">
        <div class="grid gap-2">
          <label class="text-sm font-medium text-[#393C41]">Model</label>
          <select v-model="form.model" class="w-full rounded border border-[#D0D1D2] bg-white px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
            <option v-for="model in modelOptions" :key="model.slug" :value="model.slug">
              {{ model.display_name || model.slug }}
            </option>
          </select>
        </div>

        <div class="grid gap-2">
          <label class="text-sm font-medium text-[#393C41]">Reasoning</label>
          <select v-model="form.reasoningEffort" class="w-full rounded border border-[#D0D1D2] bg-white px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="xhigh">xhigh</option>
          </select>
        </div>

        <div class="grid gap-2">
          <label class="text-sm font-medium text-[#393C41]">Mode</label>
          <label class="flex min-h-10 items-center gap-2 rounded border border-[#D0D1D2] bg-white px-3 py-2 text-sm font-medium text-[#393C41]">
            <input v-model="form.fastMode" type="checkbox" class="size-3.5 accent-[#3E6AE1]" />
            Fast
          </label>
        </div>

        <div class="grid grid-cols-3 gap-3">
          <label class="grid gap-2 text-sm font-medium text-[#393C41]">
            Timeout
            <input v-model.number="form.timeoutSeconds" type="number" min="5" max="3600" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
          </label>
          <label class="grid gap-2 text-sm font-medium text-[#393C41]">
            Batch
            <input v-model.number="form.batchSize" type="number" min="1" max="200" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
          </label>
          <label class="grid gap-2 text-sm font-medium text-[#393C41]">
            Context
            <input v-model.number="form.contextWindow" type="number" min="0" max="200" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
          </label>
        </div>

        <div class="grid gap-2 lg:col-span-2">
          <label class="text-sm font-medium text-[#393C41]">Glossary</label>
          <textarea
            v-model="form.glossary"
            rows="4"
            class="w-full resize-y rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
            placeholder="source => target"
          />
        </div>

        <div class="grid gap-2 lg:col-span-2">
          <label class="text-sm font-medium text-[#393C41]">Instructions</label>
          <textarea
            v-model="form.instructions"
            rows="3"
            class="w-full resize-y rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
          />
        </div>
        </div>
      </details>

      <div class="flex flex-wrap items-center gap-3">
        <button
          class="inline-flex min-h-10 min-w-45 items-center justify-center gap-2 rounded-lg bg-[#3E6AE1] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="!canStart"
          @click="startTranslation"
        >
          <LoadingCircle v-if="running" />
          {{ running ? "Translating..." : "Translate" }}
        </button>
        <span v-if="job" class="inline-flex rounded px-2 py-1 text-xs font-medium" :class="statusBadgeClass(job.status)">{{ job.status }}</span>
        <span v-if="progress" class="text-sm text-[#5C5E62]">
          {{ progress.translated_segments }}/{{ progress.translatable_segments }} segments
        </span>
      </div>

      <div v-if="progress" class="h-2 overflow-hidden rounded bg-neutral-100">
        <div class="h-full bg-[#3E6AE1] transition-all" :style="{ width: `${progressPercent}%` }" />
      </div>
    </div>

    <div v-if="result" class="grid gap-3 rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="m-0 text-xl leading-tight font-medium text-[#171A20]">Output</h3>
          <p class="m-0 mt-1 break-all text-sm text-[#5C5E62]">{{ result.output_path }}</p>
        </div>
        <button class="rounded border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100" @click="openOutput">
          Open Folder
        </button>
      </div>
    </div>

    <div v-if="job" class="relative grid gap-3 rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
      <button
        v-if="canStopWorker(job.status)"
        type="button"
        class="absolute top-3 right-3 inline-flex size-8 items-center justify-center rounded-full border border-red-200 bg-red-50 text-red-700 transition hover:bg-red-100 disabled:cursor-wait disabled:opacity-60"
        :disabled="stoppingTranslation"
        title="Stop worker"
        aria-label="Stop worker"
        @click="stopTranslationWorker"
      >
        <svg viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="6" y="6" width="8" height="8" rx="1" />
        </svg>
      </button>
      <div class="flex flex-wrap items-center justify-between gap-3" :class="canStopWorker(job.status) ? 'pr-10' : ''">
        <h3 class="m-0 text-xl leading-tight font-medium text-[#171A20]">Log</h3>
        <label class="flex items-center gap-2 text-xs text-[#5C5E62]">
          <input v-model="autoScroll" type="checkbox" class="size-3.5 accent-[#3E6AE1]" />
          Auto-scroll
        </label>
      </div>
      <div ref="logContainer" class="translation-log max-h-104 overflow-auto scroll-smooth rounded bg-neutral-950 p-3">
        <div v-if="!logs.length" class="text-neutral-500">Waiting for log output...</div>
        <div v-else class="grid gap-1">
          <div v-for="(entry, idx) in (logs as BuildJobLog[])" :key="entry.seq ?? `${entry.ts}-${idx}`" class="flex gap-2" :class="logLineClass(entry.level)">
            <span class="shrink-0 text-neutral-500">{{ formatTs(entry.ts) }}</span>
            <span class="shrink-0 text-neutral-400">[{{ entry.source }}]</span>
            <span class="min-w-0 whitespace-pre-wrap wrap-break-word">{{ entry.message }}</span>
          </div>
        </div>
      </div>
      <p v-if="job.error" class="m-0 whitespace-pre-wrap text-sm text-red-700">{{ job.error }}</p>
    </div>
  </section>
</template>

<style scoped>
.translation-log {
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
