<script setup lang="ts">
import { computed, reactive } from "vue";
import type { GitEolDiffRow, GitEolStructuredDiff } from "../../shared/types";

const props = defineProps<{
  diff: GitEolStructuredDiff | null;
  loading: boolean;
}>();

const CONTEXT = 3;
const COLLAPSE_THRESHOLD = CONTEXT * 2 + 1; // need to hide at least 1 line to collapse

type Group =
  | { type: "rows"; rows: { row: GitEolDiffRow; index: number }[] }
  | { type: "fold"; rows: { row: GitEolDiffRow; index: number }[]; key: string };

type DiffTextToken =
  | { type: "text"; value: string }
  | { type: "space" }
  | { type: "tab" };

const expandedFolds = reactive<Record<string, boolean>>({});

const groups = computed<Group[]>(() => {
  if (!props.diff) return [];
  const rows = props.diff.rows;
  const isChanged = (r: GitEolDiffRow) => r.type !== "equal";

  // Find indices of all "interesting" rows (non-equal). EOL-only rows are treated as
  // changes for the purpose of grouping and highlighting so users can find them.
  const result: Group[] = [];
  let i = 0;
  const n = rows.length;
  while (i < n) {
    if (isChanged(rows[i])) {
      // collect a chunk of changed rows; allow up to (CONTEXT * 2) equal rows in
      // between to merge nearby changes into one hunk.
      let j = i;
      while (j < n) {
        if (isChanged(rows[j])) {
          j += 1;
          continue;
        }
        let k = j;
        while (k < n && !isChanged(rows[k])) k += 1;
        if (k < n && k - j <= CONTEXT * 2) {
          j = k;
          continue;
        }
        break;
      }
      result.push({
        type: "rows",
        rows: rows.slice(i, j).map((row, idx) => ({ row, index: i + idx })),
      });
      i = j;
    } else {
      // equal run
      let j = i;
      while (j < n && !isChanged(rows[j])) j += 1;
      const equalRows = rows.slice(i, j).map((row, idx) => ({ row, index: i + idx }));

      const isLeading = result.length === 0;
      const isTrailing = j >= n;
      // Decide how many context lines to keep on each side.
      const head = isLeading ? 0 : Math.min(CONTEXT, equalRows.length);
      const tail = isTrailing ? 0 : Math.min(CONTEXT, equalRows.length - head);
      const middle = equalRows.length - head - tail;

      if (head > 0) {
        result.push({ type: "rows", rows: equalRows.slice(0, head) });
      }
      if (middle >= 1 && equalRows.length >= COLLAPSE_THRESHOLD) {
        const foldRows = equalRows.slice(head, head + middle);
        result.push({
          type: "fold",
          rows: foldRows,
          key: `fold-${foldRows[0].index}-${foldRows[foldRows.length - 1].index}`,
        });
      } else if (middle > 0) {
        // Not enough to collapse, render inline with the rest.
        result.push({ type: "rows", rows: equalRows.slice(head, head + middle) });
      }
      if (tail > 0) {
        result.push({ type: "rows", rows: equalRows.slice(head + middle) });
      }
      i = j;
    }
  }
  return result;
});

// Compute total min-width so left and right sides each take half. Outer container
// scrolls horizontally; both sides scroll together because they live in the same
// scrollable element.
const innerMinWidth = computed(() => {
  if (!props.diff) return "100%";
  let max = 0;
  for (const r of props.diff.rows) {
    if (r.left?.text) max = Math.max(max, diffTextVisualLength(r.left.text));
    if (r.right?.text) max = Math.max(max, diffTextVisualLength(r.right.text));
  }
  // monospace ~0.62em per char + a little padding for the EOL glyph
  const sideEm = Math.max(20, max + 2) * 0.62;
  // 2 sides + 2 gutter columns (3rem each)
  return `calc(${sideEm * 2}em + 6rem)`;
});

const gridTemplate = "3rem 1fr 3rem 1fr";

function leftCellClass(type: string): string {
  if (type === "replace" || type === "eol") return "bg-yellow-50";
  if (type === "delete") return "bg-rose-50";
  if (type === "insert") return "bg-neutral-50";
  return "bg-white";
}

function rightCellClass(type: string): string {
  if (type === "replace" || type === "eol") return "bg-yellow-50";
  if (type === "insert") return "bg-emerald-50";
  if (type === "delete") return "bg-neutral-50";
  return "bg-white";
}

function leftGutterClass(type: string): string {
  if (type === "replace" || type === "eol") return "bg-yellow-100 text-yellow-800";
  if (type === "delete") return "bg-rose-100 text-rose-800";
  return "bg-neutral-50 text-neutral-400";
}

function rightGutterClass(type: string): string {
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

function diffTextVisualLength(text: string): number {
  return text.replace(/\t/g, "    ").length;
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

function expandFold(key: string) {
  expandedFolds[key] = true;
}

function collapseFold(key: string) {
  expandedFolds[key] = false;
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
    <!-- <div :style="{ width: '100%', minWidth: innerMinWidth }"> -->
    <div>
      <div
        class="grid sticky top-0 z-10 border-b border-neutral-200 bg-neutral-100 text-[10px] font-medium tracking-wide text-neutral-500 uppercase"
        :style="{ gridTemplateColumns: gridTemplate }"
      >
        <div class="px-2 py-1 text-right">#</div>
        <div class="px-3 py-1">Base</div>
        <div class="px-2 py-1 text-right">#</div>
        <div class="px-3 py-1">Source</div>
      </div>
      <template v-for="group in groups" :key="group.type === 'fold' ? group.key : `rows-${group.rows[0].index}`">
        <template v-if="group.type === 'fold' && !expandedFolds[group.key]">
          <button
            type="button"
            class="grid w-full border-y border-neutral-200 bg-sky-50 text-left text-[11px] font-medium text-sky-700 transition hover:bg-sky-100"
            :style="{ gridTemplateColumns: gridTemplate }"
            @click="expandFold(group.key)"
          >
            <span class="col-span-4 px-3 py-1.5">
              ⋯ Show {{ group.rows.length }} unchanged line{{ group.rows.length === 1 ? "" : "s" }}
            </span>
          </button>
        </template>
        <template v-else>
          <button
            v-if="group.type === 'fold'"
            type="button"
            class="grid w-full border-y border-neutral-200 bg-neutral-50 text-left text-[11px] font-medium text-neutral-500 transition hover:bg-neutral-100"
            :style="{ gridTemplateColumns: gridTemplate }"
            @click="collapseFold(group.key)"
          >
            <span class="col-span-4 px-3 py-1.5">
              ▲ Hide {{ group.rows.length }} unchanged line{{ group.rows.length === 1 ? "" : "s" }}
            </span>
          </button>
          <div
            v-for="entry in group.rows"
            :key="entry.index"
            class="grid border-t border-neutral-100"
            :style="{ gridTemplateColumns: gridTemplate }"
          >
            <div class="select-none px-2 text-right tabular-nums" :class="leftGutterClass(entry.row.type)">
              {{ entry.row.left?.lineno ?? "" }}
            </div>
            <div class="overflow-hidden px-3 whitespace-pre-wrap" :class="[leftCellClass(entry.row.type), leftTextColor(entry.row.type)]">
              <template v-for="(token, tokenIndex) in tokenizeDiffText(entry.row.left?.text)" :key="`left-${entry.index}-${tokenIndex}`">
                <span v-if="token.type === 'text'">{{ token.value }}</span>
                <span v-else-if="token.type === 'space'" class="text-neutral-400/60">·</span>
                <span v-else class="inline-block w-[4ch] text-center text-neutral-400/60">-&gt;</span>
              </template>
              <span
                v-if="entry.row.left"
                class="ml-1 select-none text-neutral-400"
                :title="eolTitle(entry.row.left.eol)"
              >{{ eolGlyph(entry.row.left.eol) }}</span>
            </div>
            <div class="select-none px-2 text-right tabular-nums" :class="rightGutterClass(entry.row.type)">
              {{ entry.row.right?.lineno ?? "" }}
            </div>
            <div class="overflow-hidden px-3 whitespace-pre-wrap" :class="[rightCellClass(entry.row.type), rightTextColor(entry.row.type)]">
              <template v-for="(token, tokenIndex) in tokenizeDiffText(entry.row.right?.text)" :key="`right-${entry.index}-${tokenIndex}`">
                <span v-if="token.type === 'text'">{{ token.value }}</span>
                <span v-else-if="token.type === 'space'" class="text-neutral-400/60">·</span>
                <span v-else class="inline-block w-[4ch] text-center text-neutral-400/60">-&gt;</span>
              </template>
              <span
                v-if="entry.row.right"
                class="ml-1 select-none text-neutral-400"
                :title="eolTitle(entry.row.right.eol)"
              >{{ eolGlyph(entry.row.right.eol) }}</span>
            </div>
          </div>
        </template>
      </template>
    </div>
  </div>
  <div v-else-if="diff" class="px-3 py-2 text-sm text-[#5C5E62]">No differences.</div>
</template>
