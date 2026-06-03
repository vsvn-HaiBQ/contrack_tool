<script setup lang="ts">
import { ref } from "vue";
import LoadingCircle from "../../shared/LoadingCircle.vue";
import { showToast } from "../../shared/toast";
import { confluencePreviewApi, type ConfluencePreviewResult } from "./api";

const selectedFile = ref<File | null>(null);
const preview = ref<ConfluencePreviewResult | null>(null);
const loading = ref(false);
const previewFrameHeight = ref(640);

async function selectFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] ?? null;
  preview.value = null;
  previewFrameHeight.value = 640;
  if (file && !file.name.toLowerCase().endsWith(".confluence")) {
    selectedFile.value = null;
    input.value = "";
    showToast("Only .confluence files are supported", "warning");
    return;
  }
  selectedFile.value = file;
  if (file) {
    await loadPreview(file);
  }
}

async function loadPreview(file: File) {
  if (loading.value) return;
  loading.value = true;
  try {
    preview.value = await confluencePreviewApi.preview(file);
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    loading.value = false;
  }
}

function resizePreviewFrame(event: Event) {
  const frame = event.target as HTMLIFrameElement;
  const documentElement = frame.contentDocument?.documentElement;
  const body = frame.contentDocument?.body;
  const height = Math.max(
    documentElement?.scrollHeight ?? 0,
    body?.scrollHeight ?? 0,
    documentElement?.offsetHeight ?? 0,
    body?.offsetHeight ?? 0,
    640
  );
  previewFrameHeight.value = height;
}
</script>

<template>
  <section class="grid gap-6">
    <div class="grid gap-4 rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
      <div>
        <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Confluence Preview</h3>
      </div>

      <div class="grid gap-4">
        <label class="grid gap-2 text-sm font-medium text-[#393C41]">
          <input
            type="file"
            accept=".confluence"
            class="w-full cursor-pointer rounded border border-[#D0D1D2] bg-white px-2 py-2 text-[#171A20] outline-none transition file:mr-3 file:cursor-pointer file:rounded file:border-0 file:bg-neutral-100 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-[#393C41] focus:border-[#3E6AE1]"
            @change="selectFile"
          />
        </label>
      </div>
    </div>

    <div v-if="preview" class="overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-sm">
      <div class="border-b border-neutral-200 px-6 py-4">
        <h3 class="m-0 break-all text-xl leading-tight font-medium text-[#171A20]">{{ preview.file_name }}</h3>
      </div>
      <iframe
        class="block w-full border-0 bg-white"
        sandbox="allow-same-origin"
        scrolling="no"
        :style="{ height: `${previewFrameHeight}px` }"
        :srcdoc="preview.html"
        title="Confluence HTML Preview"
        @load="resizePreviewFrame"
      ></iframe>
    </div>
  </section>
</template>
