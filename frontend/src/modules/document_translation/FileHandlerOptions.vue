<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { localServerApi } from "../../shared/localServer";
import type { FileHandlerInputOptions, FileHandlerMetadata, FileHandlerUnit } from "../../shared/types";

const props = defineProps<{ filePath: string; modelValue: FileHandlerInputOptions; disabled: boolean; timeoutSeconds: number }>();
const emit = defineEmits<{ "update:modelValue": [value: FileHandlerInputOptions]; valid: [value: boolean] }>();
type Part = { id: string; label: string; hidden: boolean; supported: boolean; state: string };
const parts = ref<Part[]>([]);
const loading = ref(false);
const error = ref("");
const previewing = ref(false);
const previewError = ref("");
const preview = ref<{ segments: string[]; segment_count: number; metadata?: FileHandlerMetadata; units?: FileHandlerUnit[] } | null>(null);
let discoverySequence = 0;
let previewSequence = 0;
const kind = computed(() => /\.xlsx$/i.test(props.filePath) ? "sheet" : /\.pptx$/i.test(props.filePath) ? "slide" : null);
const selected = computed(() => kind.value === "sheet" ? props.modelValue.sheetIds : props.modelValue.slideIds);
const custom = computed(() => selected.value !== undefined);
const chosen = computed(() => parts.value.filter(part => part.supported && (custom.value ? selected.value!.includes(part.id) : !part.hidden)));
const valid = computed(() => !kind.value || (!loading.value && !error.value && chosen.value.length > 0));
watch(valid, value => emit("valid", value), { immediate: true });

function updateSelection(ids: string[] | undefined) {
  if (props.disabled) return;
  emit("update:modelValue", { ...props.modelValue, [kind.value === "sheet" ? "sheetIds" : "slideIds"]: ids });
}

function togglePart(id: string, checked: boolean) {
  const ids = chosen.value.map(part => part.id);
  updateSelection(checked ? [...new Set([...ids, id])] : ids.filter(value => value !== id));
}

async function discover() {
  const sequence = ++discoverySequence;
  parts.value = [];
  error.value = "";
  if (!kind.value) return;
  loading.value = true;
  try {
    const input = { file_processor: "filehandler", filePath: props.filePath, timeoutSeconds: props.timeoutSeconds };
    const discovered: Part[] = kind.value === "sheet"
      ? (await localServerApi.documentTranslation.sheets(input)).map(sheet => {
          if (typeof sheet === "string") throw new Error("Update the local processing server to load FileHandler sheet options.");
          return { id: sheet.sheetId, label: sheet.name, hidden: sheet.state !== "visible", supported: sheet.canImport, state: sheet.state };
        })
      : (await localServerApi.documentTranslation.slides(input)).map(slide => ({
          id: slide.slideId, label: `${slide.index}. ${slide.title || "Untitled slide"}`, hidden: slide.hidden, supported: true, state: slide.hidden ? "hidden" : "visible",
        }));
    if (sequence === discoverySequence) parts.value = discovered;
  } catch (cause) {
    if (sequence === discoverySequence) error.value = (cause as Error).message;
  } finally {
    if (sequence === discoverySequence) loading.value = false;
  }
}

async function previewText() {
  const sequence = ++previewSequence;
  previewing.value = true;
  previewError.value = "";
  preview.value = null;
  try {
    const result = await localServerApi.documentTranslation.extract({
      file_processor: "filehandler", filePath: props.filePath, timeoutSeconds: props.timeoutSeconds, ...props.modelValue,
    });
    if (sequence === previewSequence) preview.value = result;
  } catch (cause) {
    if (sequence === previewSequence) previewError.value = (cause as Error).message;
  } finally {
    if (sequence === previewSequence) previewing.value = false;
  }
}

watch(() => props.filePath, discover, { immediate: true });
watch(() => props.modelValue, () => {
  ++previewSequence;
  preview.value = null;
  previewError.value = "";
  previewing.value = false;
}, { deep: true });
onBeforeUnmount(() => { ++discoverySequence; ++previewSequence; });
</script>

<template>
  <fieldset :disabled="disabled" class="grid min-w-0 gap-3 border-0 border-t border-neutral-200 pt-3 text-sm disabled:opacity-60">
    <legend class="sr-only">FileHandler options for {{ filePath }}</legend>
    <div v-if="kind" class="grid gap-2">
      <div class="flex flex-wrap items-center gap-2">
        <label class="flex items-center gap-2">
          {{ kind === 'sheet' ? 'Sheets to translate' : 'Slides to translate' }}
          <select :value="custom ? 'custom' : 'visible'" class="rounded border border-neutral-300 bg-white px-2 py-1"
            @change="updateSelection(($event.target as HTMLSelectElement).value === 'visible' ? undefined : chosen.map(part => part.id))">
            <option value="visible">Visible only</option>
            <option value="custom">Choose individually</option>
          </select>
        </label>
        <button type="button" :disabled="loading" class="rounded border border-neutral-300 px-2 py-1" @click="discover">{{ loading ? 'Loading…' : 'Reload list' }}</button>
      </div>
      <p v-if="error" role="alert" class="m-0 text-red-700">{{ error }}</p>
      <template v-else-if="!loading">
        <div v-if="custom" class="flex gap-3 text-xs text-blue-700">
          <button type="button" @click="updateSelection(parts.filter(part => part.supported).map(part => part.id))">Select all (including hidden)</button>
          <button type="button" @click="updateSelection([])">Clear selection</button>
        </div>
        <div class="grid max-h-48 gap-1 overflow-y-auto">
          <label v-for="part in parts" :key="part.id" class="flex items-center gap-2">
            <input type="checkbox" :checked="chosen.some(item => item.id === part.id)" :disabled="!custom || !part.supported"
              @change="togglePart(part.id, ($event.target as HTMLInputElement).checked)" />
            <span>{{ part.label }}</span>
            <span v-if="part.hidden || !part.supported" class="text-xs text-neutral-500">({{ !part.supported ? 'preserved, unsupported' : part.state }})</span>
          </label>
        </div>
        <p class="m-0 text-xs" :class="chosen.length ? 'text-neutral-600' : 'text-red-700'">
          {{ chosen.length }} {{ kind }}{{ chosen.length === 1 ? '' : 's' }} selected. Unselected content stays unchanged.
        </p>
        <p v-if="kind === 'sheet'" class="m-0 text-xs text-neutral-600">Selected sheet names and supported cell content are translated.</p>
      </template>
    </div>
    <p v-else class="m-0 text-xs text-neutral-600">Translate all supported text; preserve document formatting and protected content.</p>
    <label class="flex items-center gap-2">
      <input type="checkbox" :checked="modelValue.debug" @change="emit('update:modelValue', { ...modelValue, debug: ($event.target as HTMLInputElement).checked })" />
      Include source locations and detailed skip information
    </label>
    <div>
      <button type="button" :disabled="!valid || previewing" class="rounded border border-neutral-300 px-3 py-1" @click="previewText">
        {{ previewing ? 'Reading text…' : 'Preview text to translate' }}
      </button>
    </div>
    <p v-if="previewError" role="alert" class="m-0 text-red-700">{{ previewError }}</p>
    <div v-if="preview" class="grid gap-2 rounded bg-neutral-50 p-3">
      <p class="m-0 font-medium">{{ preview.segment_count }} text segments · {{ preview.metadata?.status }}</p>
      <p v-if="!preview.segment_count" class="m-0 text-amber-800">No text found. Review your selection before translating.</p>
      <p v-if="preview.metadata?.skipCount.warning" class="m-0 text-amber-800">{{ preview.metadata.skipCount.warning }} unsupported or skipped items; see details below.</p>
      <ol class="m-0 grid max-h-64 gap-2 overflow-auto pl-5">
        <li v-for="(text, index) in preview.segments.slice(0, 10)" :key="index">
          <span class="whitespace-pre-wrap break-words">{{ text.slice(0, 1000) }}{{ text.length > 1000 ? '…' : '' }}</span>
          <small v-if="preview.units?.[index]" class="block text-neutral-500">{{ preview.units[index].kind }} · {{ JSON.stringify(preview.units[index].location) }}</small>
        </li>
      </ol>
      <p v-if="preview.segment_count > 10" class="m-0 text-xs text-neutral-500">Showing the first 10 segments.</p>
      <details v-if="preview.metadata?.skipped.length">
        <summary>Preserved content</summary>
        <ul class="max-h-40 overflow-auto pl-5">
          <li v-for="(skip, index) in preview.metadata.skipped" :key="index">{{ skip.message }} ({{ skip.count }})</li>
        </ul>
      </details>
    </div>
  </fieldset>
</template>
