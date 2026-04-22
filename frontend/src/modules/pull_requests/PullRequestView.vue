<script setup lang="ts">
import { computed } from "vue";
import type { PrPreview, PrResult } from "../../shared/types";
import LoadingCircle from "../../shared/LoadingCircle.vue";

const props = defineProps<{
  prForm: { jp_tickets: string; base_branch: string; source_branch: string; title: string };
  preview: PrPreview | null;
  loadingPreview: boolean;
  result: PrResult | null;
}>();

const emit = defineEmits<{
  verify: [];
  submit: [];
}>();

const canVerify = computed(() => Boolean(props.prForm.jp_tickets.trim() && props.prForm.base_branch.trim() && props.prForm.source_branch.trim()));
</script>

<template>
  <section class="grid items-start gap-6 lg:grid-cols-2">
    <div class="grid content-start gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Create Pull Request</h3>
      <label class="text-sm font-medium text-[#393C41]">JP Tickets</label>
      <input v-model="prForm.jp_tickets" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" placeholder="xxxx,yyyy" />
      <label class="text-sm font-medium text-[#393C41]">Base Branch</label>
      <input v-model="prForm.base_branch" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
      <label class="text-sm font-medium text-[#393C41]">Source Branch</label>
      <input v-model="prForm.source_branch" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
      <div class="flex items-center gap-3 pt-2">
        <button
          class="inline-flex min-h-10 min-w-[200px] items-center justify-center gap-2 rounded-lg bg-[#171A20] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="!canVerify || loadingPreview"
          @click="emit('verify')"
        >
          <LoadingCircle v-if="loadingPreview" />
          {{ loadingPreview ? "Verifying..." : "Verify PR" }}
        </button>
      </div>
    </div>

    <div class="grid content-start gap-4">
      <div class="grid gap-3 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
        <div class="flex items-center justify-between gap-3">
          <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Preview</h3>
          <span v-if="loadingPreview" class="inline-flex items-center gap-2 text-xs text-[#5C5E62]">
            <LoadingCircle class="text-[#3E6AE1]" />
            Verifying...
          </span>
        </div>
        <div v-if="preview" class="grid gap-3">
          <div class="grid gap-1">
            <span class="text-xs font-medium uppercase tracking-wide text-[#5C5E62]">PR title</span>
            <input
              v-model="prForm.title"
              class="w-full rounded border border-[#D0D1D2] bg-white px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
              placeholder="PR title"
            />
          </div>
          <div class="grid gap-1">
            <span class="text-xs font-medium uppercase tracking-wide text-[#5C5E62]">Source branch</span>
            <div class="flex items-center gap-2 text-sm text-[#171A20]">
              <code class="rounded bg-white px-2 py-1 text-xs ring-1 ring-neutral-200">{{ preview.source_branch }}</code>
              <span
                class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium"
                :class="preview.branch_exists ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' : 'bg-rose-50 text-rose-700 ring-1 ring-rose-200'"
              >
                {{ preview.branch_exists ? "Verified" : "Missing" }}
              </span>
            </div>
          </div>
          <div class="grid gap-1">
            <span class="text-xs font-medium uppercase tracking-wide text-[#5C5E62]">JP tickets</span>
            <div class="grid gap-2">
              <a
                v-for="ticket in preview.tickets"
                :key="ticket.issue_id"
                :href="ticket.url"
                target="_blank"
                rel="noreferrer"
                class="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-[#171A20] transition hover:bg-neutral-50"
              >
                <span class="font-mono text-[#3E6AE1]">#{{ ticket.issue_id }}</span>
                {{ ticket.subject }}
              </a>
            </div>
          </div>
          <div v-if="preview.branch_exists" class="flex items-center gap-3 pt-2">
            <button class="min-h-10 min-w-[200px] rounded-lg bg-[#3E6AE1] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95" @click="emit('submit')">Create PR</button>
          </div>
        </div>
        <p v-else class="text-sm text-[#5C5E62]">Verify PR to preview title, source branch, and JP tickets.</p>
      </div>

      <div class="grid content-start gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
        <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">PR Result</h3>
        <div v-if="result" class="grid gap-2">
          <p><strong>{{ result.title }}</strong></p>
          <a :href="result.url" target="_blank" rel="noreferrer" class="break-all">{{ result.url }}</a>
          <p class="text-sm text-[#5C5E62]">Linked tickets: {{ result.linked_ticket_ids.join(", ") }}</p>
        </div>
        <p v-else class="text-sm text-[#5C5E62]">No PR created yet.</p>
      </div>
    </div>
  </section>
</template>
