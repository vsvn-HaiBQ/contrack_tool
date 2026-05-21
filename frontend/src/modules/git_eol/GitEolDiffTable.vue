<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import type { GitEolDiffRow, GitEolStructuredDiff } from "../../shared/types";

const props = defineProps<{
  diff: GitEolStructuredDiff | null;
  loading: boolean;
  loadHiddenRows: (row: GitEolDiffRow) => Promise<GitEolDiffRow[]>;
}>();

type RenderEntry =
  | { type: "row"; row: GitEolDiffRow; key: string }
  | { type: "fold"; row: GitEolDiffRow; key: string };

type DiffTextToken =
  | { type: "text"; value: string }
  | { type: "space" }
  | { type: "tab" };

const expandedFolds = reactive<Record<string, boolean>>({});
const foldRows = reactive<Record<string, GitEolDiffRow[]>>({});
const foldLoading = reactive<Record<string, boolean>>({});
const foldErrors = reactive<Record<string, string>>({});

const gridTemplate = "3rem 1fr 3rem 1fr";

function clearRecord<T>(target: Record<string, T>) {
  Object.keys(target).forEach((key) => delete target[key]);
}

watch(
  () => props.diff?.rows,
  () => {
    clearRecord(expandedFolds);
    clearRecord(foldRows);
    clearRecord(foldLoading);
    clearRecord(foldErrors);
  }
);

function foldKey(row: GitEolDiffRow, index: number) {
  return [
    "fold",
    row.left_start ?? "",
    row.left_end ?? "",
    row.right_start ?? "",
    row.right_end ?? "",
    index
  ].join("-");
}

const entries = computed<RenderEntry[]>(() => {
  if (!props.diff) return [];
  const result: RenderEntry[] = [];
  props.diff.rows.forEach((row, index) => {
    if (row.type !== "fold") {
      result.push({ type: "row", row, key: `row-${index}` });
      return;
    }
    const key = foldKey(row, index);
    result.push({ type: "fold", row, key });
    if (expandedFolds[key] && foldRows[key]) {
      for (let hiddenIndex = 0; hiddenIndex < foldRows[key].length; hiddenIndex += 1) {
        result.push({ type: "row", row: foldRows[key][hiddenIndex], key: `${key}-hidden-${hiddenIndex}` });
      }
    }
  });
  return result;
});

function leftCellClass(type: string): string {
  if (type === "fixed_eol") return "bg-violet-50";
  if (type === "replace" || type === "eol") return "bg-yellow-50";
  if (type === "delete") return "bg-rose-50";
  if (type === "insert") return "bg-neutral-50";
  return "bg-white";
}

function rightCellClass(type: string): string {
  if (type === "fixed_eol") return "bg-violet-50";
  if (type === "replace" || type === "eol") return "bg-yellow-50";
  if (type === "insert") return "bg-emerald-50";
  if (type === "delete") return "bg-neutral-50";
  return "bg-white";
}

function leftGutterClass(type: string): string {
  if (type === "fixed_eol") return "bg-violet-100";
  if (type === "replace" || type === "eol") return "bg-yellow-100 text-yellow-800";
  if (type === "delete") return "bg-rose-100 text-rose-800";
  return "bg-neutral-50 text-neutral-400";
}

function rightGutterClass(type: string): string {
  if (type === "fixed_eol") return "bg-violet-100";
  if (type === "replace" || type === "eol") return "bg-yellow-100 text-yellow-800";
  if (type === "insert") return "bg-emerald-100 text-emerald-800";
  return "bg-neutral-50 text-neutral-400";
}

function leftTextColor(type: string): string {
  if (type === "replace" || type === "eol") return "text-yellow-950";
  if (type === "delete") return "text-rose-950";
  return "text-neutral-800";
}

function rightTextColor(type: string): string {
  if (type === "replace" || type === "eol") return "text-yellow-950";
  if (type === "insert") return "text-emerald-950";
  return "text-neutral-800";
}

function eolGlyph(eol?: string | null): string {
  if (eol === "lf") return "↓";
  if (eol === "crlf") return "↵";
  if (eol === "cr") return "␍";
  if (eol === "none") return "·";
  return "";
}

function eolTitle(eol?: string | null): string {
  if (eol === "lf") return "LF (\\n)";
  if (eol === "crlf") return "CRLF (\\r\\n)";
  if (eol === "cr") return "CR (\\r)";
  if (eol === "none") return "no end-of-line";
  return "";
}

function tokenizeDiffText(text?: string | null): DiffTextToken[] {
  if (!text) return [];

  const tokens: DiffTextToken[] = [];
  let current = "";

  for (const char of text) {
    if (char === " " || char === "\t") {
      if (current) {
        tokens.push({ type: "text", value: current });
        current = "";
      }
      tokens.push(char === " " ? { type: "space" } : { type: "tab" });
    } else {
      current += char;
    }
  }

  if (current) tokens.push({ type: "text", value: current });
  return tokens;
}

async function toggleFold(row: GitEolDiffRow, key: string) {
  if (expandedFolds[key]) {
    expandedFolds[key] = false;
    return;
  }
  expandedFolds[key] = true;
  if (foldRows[key] || foldLoading[key]) {
    return;
  }
  foldLoading[key] = true;
  delete foldErrors[key];
  try {
    foldRows[key] = await props.loadHiddenRows(row);
  } catch (error) {
    expandedFolds[key] = false;
    foldErrors[key] = (error as Error).message;
  } finally {
    foldLoading[key] = false;
  }
}
</script>

<template>
  <div v-if="loading" class="flex items-center gap-2 px-3 py-2 text-sm text-[#5C5E62]">
    Loading diff...
  </div>
  <div v-else-if="diff && diff.binary" class="px-3 py-2 text-sm text-[#5C5E62]">Binary file (skipped).</div>
  <div
    v-else-if="diff && diff.rows.length"
    class="overflow-x-auto rounded-lg border border-neutral-200 bg-white font-mono text-[12px] leading-5 text-neutral-800"
  >
    <div>
      <div
        class="sticky top-0 z-10 grid border-b border-neutral-200 bg-neutral-100 text-[10px] font-medium tracking-wide text-neutral-500 uppercase"
        :style="{ gridTemplateColumns: gridTemplate }"
      >
        <div class="px-2 py-1 text-right">#</div>
        <div class="px-3 py-1">Base</div>
        <div class="px-2 py-1 text-right">#</div>
        <div class="px-3 py-1">Source</div>
      </div>
      <template v-for="entry in entries" :key="entry.key">
        <template v-if="entry.type === 'fold'">
          <button
            type="button"
            class="grid w-full border-y border-neutral-200 bg-sky-50 text-left text-[11px] font-medium text-sky-700 transition hover:bg-sky-100 disabled:cursor-wait disabled:opacity-70"
            :style="{ gridTemplateColumns: gridTemplate }"
            :disabled="foldLoading[entry.key]"
            @click="toggleFold(entry.row, entry.key)"
          >
            <span class="col-span-4 px-3 py-1.5">
              {{ expandedFolds[entry.key] ? "Hide" : "Show" }}
              {{ entry.row.count ?? 0 }} unchanged line{{ entry.row.count === 1 ? "" : "s" }}
              <span v-if="foldLoading[entry.key]">...</span>
            </span>
          </button>
          <div
            v-if="foldErrors[entry.key]"
            class="grid border-y border-red-100 bg-red-50 text-[11px] text-red-700"
            :style="{ gridTemplateColumns: gridTemplate }"
          >
            <span class="col-span-4 px-3 py-1.5">{{ foldErrors[entry.key] }}</span>
          </div>
        </template>
        <div
          v-else
          class="grid border-t border-neutral-100"
          :style="{ gridTemplateColumns: gridTemplate }"
        >
          <div class="select-none px-2 text-right tabular-nums" :class="leftGutterClass(entry.row.type)">
            {{ entry.row.left?.lineno ?? "" }}
          </div>
          <div class="overflow-hidden px-3 whitespace-pre-wrap" :class="[leftCellClass(entry.row.type), leftTextColor(entry.row.type)]">
            <template v-for="(token, tokenIndex) in tokenizeDiffText(entry.row.left?.text)" :key="`left-${entry.key}-${tokenIndex}`">
              <span v-if="token.type === 'text'">{{ token.value }}</span>
              <span v-else-if="token.type === 'space'" class="text-neutral-400/60">.</span>
              <span v-else class="inline-block w-[4ch] text-center text-neutral-400/60">-&gt;</span>
            </template>
            <span
              v-if="entry.row.left"
              class="ml-1 select-none text-[10px] text-neutral-400"
              :title="eolTitle(entry.row.left.eol)"
            >{{ eolGlyph(entry.row.left.eol) }}</span>
          </div>
          <div class="select-none px-2 text-right tabular-nums" :class="rightGutterClass(entry.row.type)">
            {{ entry.row.right?.lineno ?? "" }}
          </div>
          <div class="overflow-hidden px-3 whitespace-pre-wrap" :class="[rightCellClass(entry.row.type), rightTextColor(entry.row.type)]">
            <template v-for="(token, tokenIndex) in tokenizeDiffText(entry.row.right?.text)" :key="`right-${entry.key}-${tokenIndex}`">
              <span v-if="token.type === 'text'">{{ token.value }}</span>
              <span v-else-if="token.type === 'space'" class="text-neutral-400/60">.</span>
              <span v-else class="inline-block w-[4ch] text-center text-neutral-400/60">-&gt;</span>
            </template>
            <span
              v-if="entry.row.right"
              class="ml-1 select-none text-[10px] text-neutral-400"
              :title="eolTitle(entry.row.right.eol)"
            >{{ eolGlyph(entry.row.right.eol) }}</span>
          </div>
        </div>
      </template>
    </div>
  </div>
  <div v-else-if="diff" class="px-3 py-2 text-sm text-[#5C5E62]">No differences.</div>
</template>
