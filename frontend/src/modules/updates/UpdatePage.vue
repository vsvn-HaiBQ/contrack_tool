<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import LoadingCircle from "../../shared/LoadingCircle.vue";
import { electronApi } from "../../shared/electron";
import { showToast } from "../../shared/toast";
import { checkClientUpdate, checkingUpdate, currentClientVersion, updateInfo } from "../../shared/update";

const sizeLabel = computed(() => {
  const size = updateInfo.value?.size_bytes;
  if (!size) return "-";
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size > 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
});
const versionLabel = ref("0.1.0");

async function refresh() {
  try {
    await checkClientUpdate();
    showToast(updateInfo.value?.message || "Đã kiểm tra update", updateInfo.value?.has_update ? "warning" : "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function openDownload() {
  const url = updateInfo.value?.download_url;
  if (!url) return;
  const api = electronApi();
  if (api) {
    await api.openPath(url);
  } else {
    window.open(url, "_blank");
  }
}

onMounted(async () => {
  versionLabel.value = await currentClientVersion();
  if (!updateInfo.value) {
    await refresh();
  }
});
</script>

<template>
  <section class="grid gap-6">
    <div class="grid gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Check Update</h3>
          <p class="mt-1 text-sm text-[#5C5E62]">Kiểm tra bản portable mới nhất từ server.</p>
        </div>
        <button
          class="inline-flex min-h-10 min-w-[160px] items-center justify-center gap-2 rounded-lg bg-[#171A20] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="checkingUpdate"
          @click="refresh"
        >
          <LoadingCircle v-if="checkingUpdate" />
          {{ checkingUpdate ? "Checking..." : "Check Now" }}
        </button>
      </div>

      <div class="grid gap-3 rounded-xl border border-neutral-200 bg-neutral-50 p-4 text-sm">
        <div class="grid gap-1 md:grid-cols-[180px_1fr]">
          <span class="font-medium text-[#5C5E62]">Current version</span>
          <span class="text-[#171A20]">{{ updateInfo?.current_version || versionLabel }}</span>
        </div>
        <div class="grid gap-1 md:grid-cols-[180px_1fr]">
          <span class="font-medium text-[#5C5E62]">Latest version</span>
          <span class="text-[#171A20]">{{ updateInfo?.latest_version || "-" }}</span>
        </div>
        <div class="grid gap-1 md:grid-cols-[180px_1fr]">
          <span class="font-medium text-[#5C5E62]">Status</span>
          <span :class="updateInfo?.has_update ? 'text-amber-700' : 'text-emerald-700'">{{ updateInfo?.message || "-" }}</span>
        </div>
        <div class="grid gap-1 md:grid-cols-[180px_1fr]">
          <span class="font-medium text-[#5C5E62]">File</span>
          <span class="break-all text-[#171A20]">{{ updateInfo?.file_name || "-" }}</span>
        </div>
        <div class="grid gap-1 md:grid-cols-[180px_1fr]">
          <span class="font-medium text-[#5C5E62]">Size</span>
          <span class="text-[#171A20]">{{ sizeLabel }}</span>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-3">
        <button
          class="min-h-10 min-w-[180px] rounded-lg bg-[#3E6AE1] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="!updateInfo?.download_url"
          @click="openDownload"
        >
          Download Update
        </button>
        <a v-if="updateInfo?.download_url" class="break-all text-sm" :href="updateInfo.download_url" target="_blank">{{ updateInfo.download_url }}</a>
      </div>
    </div>
  </section>
</template>
