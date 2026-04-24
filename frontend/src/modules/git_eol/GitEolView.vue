<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { GitEolCommitResult, GitEolFixResult, GitEolJobLog, GitEolPreview, GitEolPushResult, GitEolStructuredDiff } from "../../shared/types";
import LoadingCircle from "../../shared/LoadingCircle.vue";
import GitEolDiffTable from "./GitEolDiffTable.vue";

const props = defineProps<{
  form: { base_branch: string; source_branch: string };
  commitForm: { message: string };
  preview: GitEolPreview | null;
  selectedFiles: Record<string, boolean>;
  selectedCount: number;
  expandedFiles: Record<string, boolean>;
  diffCache: Record<string, GitEolStructuredDiff>;
  diffLoading: Record<string, boolean>;
  expandedResultFiles: Record<string, boolean>;
  resultDiffCache: Record<string, GitEolStructuredDiff>;
  resultDiffLoading: Record<string, boolean>;
  selectedResultFiles: Record<string, boolean>;
  selectedResultCount: number;
  fixResult: GitEolFixResult | null;
  commitResult: GitEolCommitResult | null;
  pushResult: GitEolPushResult | null;
  loadingPreview: boolean;
  fixing: boolean;
  committing: boolean;
  pushing: boolean;
  jobId: string | null;
  jobStatus: string;
  jobLogs: GitEolJobLog[];
  jobError: string | null;
}>();

const emit = defineEmits<{
  preview: [];
  fix: [];
  commitAndPush: [];
  selectAll: [];
  clearSelection: [];
  toggleFile: [path: string];
  toggleResultFile: [path: string];
  clearLogs: [];
}>();

const canPreview = computed(() => Boolean(props.form.base_branch.trim() && props.form.source_branch.trim()));
const changedFixedFiles = computed(() =>
  props.fixResult?.fixed_files.filter((f) => f.worktree_changed ?? f.restored_eol_lines > 0) ?? []
);
const noChangeFixedFiles = computed(() =>
  props.fixResult?.fixed_files.filter((f) => !(f.worktree_changed ?? f.restored_eol_lines > 0)) ?? []
);
const processableCount = computed(() => props.preview?.files.filter((file) => file.processable).length ?? 0);
const showLogPanel = computed(() => props.jobStatus !== "idle" || props.jobLogs.length > 0);
const hasAnyFixOutput = computed(() =>
  Boolean(
    props.fixResult &&
      (props.fixResult.fixed_files.length || props.fixResult.skipped_files.length || props.fixResult.failed_files.length)
  )
);

const logContainer = ref<HTMLElement | null>(null);
const autoScroll = ref(true);

watch(
  () => props.jobLogs.length,
  async () => {
    if (!autoScroll.value) {
      return;
    }
    await nextTick();
    const el = logContainer.value;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }
);

function eolLabel(value?: string | null) {
  if (!value) {
    return "-";
  }
  return value.toUpperCase();
}

function logLineClass(level: string): string {
  if (level === "error") return "text-red-300";
  if (level === "warn") return "text-amber-300";
  return "text-neutral-200";
}


function formatTs(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour12: false });
}

function statusBadgeClass(status: string): string {
  if (status === "succeeded") return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
  if (status === "failed") return "bg-red-50 text-red-700 ring-1 ring-red-200";
  if (status === "running" || status === "queued") return "bg-sky-50 text-sky-700 ring-1 ring-sky-200";
  return "bg-neutral-100 text-[#5C5E62] ring-1 ring-neutral-200";
}
</script>

<template>
  <section class="grid gap-6">
    <div class="grid gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div class="grid w-full gap-4 md:grid-cols-2">
          <div class="grid gap-2">
            <label class="text-sm font-medium text-[#393C41]">Base Branch</label>
            <input
              v-model="form.base_branch"
              class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
            />
          </div>
          <div class="grid gap-2">
            <label class="text-sm font-medium text-[#393C41]">Source Branch</label>
            <input
              v-model="form.source_branch"
              class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
            />
          </div>
        </div>
        <button
          class="inline-flex min-h-10 min-w-[160px] items-center justify-center gap-2 rounded-lg bg-[#171A20] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="!canPreview || loadingPreview"
          @click="emit('preview')"
        >
          <LoadingCircle v-if="loadingPreview" />
          {{ loadingPreview ? "Running..." : "Preview" }}
        </button>
      </div>
    </div>

    <div v-if="showLogPanel" class="grid gap-3 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-3">
          <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Worker Logs</h3>
          <span class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium" :class="statusBadgeClass(jobStatus)">{{ jobStatus }}</span>
          <span v-if="jobId" class="text-xs text-[#5C5E62]">job <code class="rounded bg-neutral-100 px-1.5 py-0.5">{{ jobId.slice(0, 12) }}</code></span>
        </div>
        <div class="flex items-center gap-3">
          <label class="flex items-center gap-2 text-xs text-[#5C5E62]">
            <input v-model="autoScroll" type="checkbox" class="size-3.5 accent-[#3E6AE1]" />
            Auto-scroll
          </label>
          <button class="rounded border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-[#393C41] transition hover:bg-neutral-100" @click="emit('clearLogs')">
            Clear
          </button>
        </div>
      </div>
      <div ref="logContainer" class="max-h-72 overflow-auto rounded-lg bg-neutral-900 p-3 font-mono text-xs leading-relaxed">
        <div v-if="!jobLogs.length" class="text-neutral-500">Waiting for log output...</div>
        <div v-for="(entry, idx) in jobLogs" :key="idx" class="flex gap-2" :class="logLineClass(entry.level)">
          <span class="shrink-0 text-neutral-500">{{ formatTs(entry.ts) }}</span>
          <span class="shrink-0 text-neutral-400">[{{ entry.source }}]</span>
          <span class="break-all whitespace-pre-wrap">{{ entry.message }}</span>
        </div>
      </div>
      <p v-if="jobError" class="text-sm text-red-700">{{ jobError }}</p>
    </div>

    <div class="grid gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Changed Files</h3>
          <p v-if="preview" class="mt-1 text-sm text-[#5C5E62]">
            Merge base <code class="rounded bg-neutral-100 px-1.5 py-0.5 text-xs">{{ preview.merge_base.slice(0, 12) }}</code>
          </p>
        </div>
        <div v-if="preview" class="flex flex-wrap items-center gap-2">
          <span class="text-sm text-[#5C5E62]">{{ selectedCount }} / {{ processableCount }} selected</span>
          <button class="rounded border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100" @click="emit('selectAll')">
            Select All
          </button>
          <button class="rounded border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100" @click="emit('clearSelection')">
            Clear
          </button>
        </div>
      </div>

      <div v-if="preview" class="w-full border border-neutral-200">
        <table class="w-full border-collapse text-left text-sm">
          <thead class="bg-neutral-50 text-xs font-medium text-[#5C5E62] uppercase">
            <tr>
              <th class="w-10 px-2 py-2"></th>
              <th class="px-3 py-2">File</th>
              <th class="w-24 px-3 py-2">Status</th>
              <th class="w-24 px-3 py-2">Base EOL</th>
              <th class="w-24 px-3 py-2">Source EOL</th>
              <th class="w-20 px-3 py-2 text-right">Changed</th>
              <th class="w-24 px-3 py-2 text-right">EOL-only</th>
              <th class="w-24 px-3 py-2">State</th>
              <th class="w-10 px-2 py-2"></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="file in preview.files" :key="file.path">
              <tr class="border-t border-neutral-200 cursor-pointer hover:bg-neutral-50" @click="emit('toggleFile', file.path)">
                <td class="px-3 py-2" @click.stop>
                  <input v-model="selectedFiles[file.path]" type="checkbox" :disabled="!file.processable" class="size-4 accent-[#3E6AE1]" />
                </td>
                <td class="px-3 py-2">
                  <div class="break-all font-medium text-[#171A20]">{{ file.path }}</div>
                  <div v-if="file.old_path && file.old_path !== file.path" class="break-all text-xs text-[#5C5E62]">{{ file.old_path }}</div>
                </td>
                <td class="px-3 py-2 text-[#393C41]">{{ file.status }}</td>
                <td class="px-3 py-2">
                  <span class="rounded bg-neutral-100 px-2 py-1 text-xs font-medium text-[#393C41]">{{ eolLabel(file.base_eol) }}</span>
                </td>
                <td class="px-3 py-2">
                  <span class="rounded bg-neutral-100 px-2 py-1 text-xs font-medium text-[#393C41]">{{ eolLabel(file.source_eol) }}</span>
                </td>
                <td class="px-3 py-2 text-right tabular-nums">{{ file.changed_lines }}</td>
                <td class="px-3 py-2 text-right tabular-nums">{{ file.eol_only_lines }}</td>
                <td class="px-3 py-2">
                  <span
                    class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium"
                    :class="file.processable ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' : 'bg-neutral-100 text-[#5C5E62] ring-1 ring-neutral-200'"
                  >
                    {{ file.processable ? "Ready" : file.reason }}
                  </span>
                </td>
                <td class="px-2 py-2 text-right">
                  <svg viewBox="0 0 10 10" class="size-3 transition-transform" :class="expandedFiles[file.path] ? 'rotate-90' : ''" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M3 1.5l4 3.5-4 3.5" />
                  </svg>
                </td>
              </tr>
              <tr v-if="expandedFiles[file.path]" class="border-t border-neutral-100 bg-neutral-50">
                <td colspan="9" class="p-0">
                  <GitEolDiffTable :diff="diffCache[file.path] ?? null" :loading="diffLoading[file.path] ?? false" />
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <p v-else-if="!loadingPreview" class="text-sm text-[#5C5E62]">No preview loaded.</p>

      <div v-if="preview" class="flex items-center gap-3">
        <button
          class="inline-flex min-h-10 min-w-[180px] items-center justify-center gap-2 rounded-lg bg-[#3E6AE1] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="!selectedCount || fixing"
          @click="emit('fix')"
        >
          <LoadingCircle v-if="fixing" />
          {{ fixing ? "Fixing..." : "Fix EOL" }}
        </button>
      </div>
    </div>

    <div class="grid gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Result</h3>
        <div v-if="changedFixedFiles.length" class="flex flex-wrap items-center gap-2">
          <span class="text-sm text-[#5C5E62]">{{ selectedResultCount }} / {{ changedFixedFiles.length }} selected</span>
          <button
            class="rounded border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100"
            @click="changedFixedFiles.forEach(f => selectedResultFiles[f.path] = true)"
          >Select All</button>
          <button
            class="rounded border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100"
            @click="changedFixedFiles.forEach(f => selectedResultFiles[f.path] = false)"
          >Clear</button>
        </div>
      </div>
      <div v-if="fixResult" class="grid gap-4">
        <div class="grid gap-3 md:grid-cols-4">
          <div class="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
            <p class="text-xs font-medium text-[#5C5E62] uppercase">Restored Lines</p>
            <p class="mt-1 text-2xl font-semibold text-[#171A20]">{{ fixResult.total_restored_eol_lines }}</p>
          </div>
          <div class="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
            <p class="text-xs font-medium text-[#5C5E62] uppercase">Checked Files</p>
            <p class="mt-1 text-2xl font-semibold text-[#171A20]">{{ fixResult.fixed_files.length }}</p>
          </div>
          <div class="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
            <p class="text-xs font-medium text-[#5C5E62] uppercase">Skipped</p>
            <p class="mt-1 text-2xl font-semibold text-[#171A20]">{{ fixResult.skipped_files.length }}</p>
          </div>
          <div class="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
            <p class="text-xs font-medium text-[#5C5E62] uppercase">Failed</p>
            <p class="mt-1 text-2xl font-semibold text-[#171A20]">{{ fixResult.failed_files.length }}</p>
          </div>
        </div>

        <div
          v-if="!hasAnyFixOutput || (fixResult.total_restored_eol_lines === 0 && !fixResult.skipped_files.length && !fixResult.failed_files.length)"
          class="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
        >
          No EOL changes were needed for the selected files.
        </div>

        <div v-if="noChangeFixedFiles.length" class="grid gap-2 rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-sm">
          <p class="font-medium text-[#171A20]">Files checked with no committable EOL changes</p>
          <div v-for="file in noChangeFixedFiles" :key="`noop-${file.path}`" class="break-all text-[#5C5E62]">
            {{ file.path }}<span v-if="file.message"> - {{ file.message }}</span>
          </div>
        </div>

        <!-- Fixed files with checkboxes + expandable diff -->
        <div v-if="changedFixedFiles.length" class="w-full border border-neutral-200">
          <table class="w-full border-collapse text-left text-sm">
            <thead class="bg-neutral-50 text-xs font-medium text-[#5C5E62] uppercase">
              <tr>
                <th class="w-10 px-2 py-2"></th>
                <th class="px-3 py-2">File</th>
                <th class="w-28 px-3 py-2 text-right">Restored EOL</th>
                <th class="w-32 px-3 py-2 text-right">Changed</th>
                <th class="w-32 px-3 py-2 text-right">EOL-only</th>
                <th class="w-28 px-3 py-2">Git Diff</th>
                <th class="w-10 px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="file in changedFixedFiles" :key="file.path">
                <tr class="cursor-pointer border-t border-neutral-200 hover:bg-neutral-50" @click="emit('toggleResultFile', file.path)">
                  <td class="px-3 py-2" @click.stop>
                    <input v-model="selectedResultFiles[file.path]" type="checkbox" class="size-4 accent-[#3E6AE1]" />
                  </td>
                  <td class="break-all px-3 py-2 font-medium text-[#171A20]">{{ file.path }}</td>
                  <td class="px-3 py-2 text-right tabular-nums">{{ file.restored_eol_lines }}</td>
                  <td class="px-3 py-2 text-right tabular-nums">{{ file.remaining_changed_lines }}</td>
                  <td class="px-3 py-2 text-right tabular-nums">{{ file.remaining_eol_only_lines }}</td>
                  <td class="px-3 py-2">
                    <span class="rounded bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200">Ready</span>
                  </td>
                  <td class="px-2 py-2 text-right">
                    <svg viewBox="0 0 10 10" class="size-3 transition-transform" :class="expandedResultFiles[file.path] ? 'rotate-90' : ''" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M3 1.5l4 3.5-4 3.5" />
                    </svg>
                  </td>
                </tr>
                <tr v-if="expandedResultFiles[file.path]" class="border-t border-neutral-100">
                  <td colspan="7" class="p-0">
                    <GitEolDiffTable :diff="resultDiffCache[file.path] ?? null" :loading="resultDiffLoading[file.path] ?? false" />
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <!-- Skipped / Failed -->
        <div v-if="fixResult.skipped_files.length || fixResult.failed_files.length" class="grid gap-2 text-sm">
          <div v-for="file in fixResult.skipped_files" :key="`skip-${file.path}`" class="rounded border border-neutral-200 bg-neutral-50 px-3 py-2">
            <span class="font-medium text-[#171A20]">{{ file.path }}</span>
            <span class="text-[#5C5E62]"> - {{ file.reason }}</span>
          </div>
          <div v-for="file in fixResult.failed_files" :key="`fail-${file.path}`" class="rounded border border-red-200 bg-red-50 px-3 py-2">
            <span class="font-medium text-red-800">{{ file.path }}</span>
            <span class="text-red-700"> - {{ file.error }}</span>
          </div>
        </div>

        <!-- Commit & Push -->
        <div v-if="selectedResultCount > 0" class="grid gap-3 rounded-lg border border-neutral-200 bg-neutral-50 p-4">
          <label class="text-sm font-medium text-[#393C41]">Commit Message</label>
          <input
            v-model="commitForm.message"
            class="w-full rounded border border-[#D0D1D2] bg-white px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
          />
          <div class="flex flex-wrap items-center gap-3">
            <button
              class="inline-flex min-h-10 min-w-[160px] items-center justify-center gap-2 rounded-lg bg-[#3E6AE1] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="committing || pushing"
              @click="emit('commitAndPush')"
            >
              <LoadingCircle v-if="committing || pushing" />
              {{ pushing ? "Pushing..." : committing ? "Committing..." : "Commit & Push" }}
            </button>
            <span v-if="commitResult" class="text-sm text-[#5C5E62]">
              {{ commitResult.committed ? `Committed ${commitResult.commit_sha?.slice(0, 12)}` : commitResult.message }}
            </span>
            <span v-if="pushResult" class="text-sm text-[#5C5E62]">{{ pushResult.message }}</span>
          </div>
        </div>
      </div>
      <p v-else-if="fixing" class="text-sm text-[#5C5E62]">Fixing selected files...</p>
    </div>
  </section>
</template>

