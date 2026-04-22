<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import PullRequestView from "./PullRequestView.vue";
import { pullRequestsApi } from "./api";
import type { PrPreview, PrResult } from "../../shared/types";
import { showToast } from "../../shared/toast";
import { sessionState } from "../../shared/session";

const prForm = reactive({
  jp_tickets: "",
  base_branch: "",
  source_branch: "",
  title: ""
});
const result = ref<PrResult | null>(null);
const preview = ref<PrPreview | null>(null);
const loadingPreview = ref(false);
const lastGeneratedTitle = ref("");

function parseTickets() {
  return Array.from(
    new Set(
      prForm.jp_tickets
        .split(",")
        .map((value) => Number(value.trim()))
        .filter(Boolean)
    )
  );
}

function buildSourceBranch() {
  const tickets = parseTickets();
  if (!prForm.base_branch.trim() || !tickets.length) {
    prForm.source_branch = "";
    return;
  }
  prForm.source_branch = `${prForm.base_branch.trim()}_${tickets.map((ticket) => `#${ticket}`).join("_")}`;
}

function clearPreviewState() {
  preview.value = null;
  if (prForm.title === lastGeneratedTitle.value) {
    prForm.title = "";
  }
  lastGeneratedTitle.value = "";
}

async function verifyPreview() {
  const parsedTickets = parseTickets();
  if (!parsedTickets.length) {
    showToast("Enter at least one JP ticket", "warning");
    return;
  }
  if (!prForm.base_branch.trim() || !prForm.source_branch.trim()) {
    showToast("Base branch and source branch are required", "warning");
    return;
  }

  loadingPreview.value = true;
  try {
    const nextPreview = await pullRequestsApi.preview({
      jp_tickets: parsedTickets,
      base_branch: prForm.base_branch,
      source_branch: prForm.source_branch
    });
    const shouldSyncTitle = !prForm.title.trim() || prForm.title === lastGeneratedTitle.value;
    preview.value = nextPreview;
    lastGeneratedTitle.value = nextPreview.title;
    if (shouldSyncTitle) {
      prForm.title = nextPreview.title;
    }
    showToast(nextPreview.branch_exists ? "PR verified" : "Branch does not exist on remote", nextPreview.branch_exists ? "success" : "warning");
  } catch (error) {
    clearPreviewState();
    showToast((error as Error).message, "error");
  } finally {
    loadingPreview.value = false;
  }
}

watch(
  () => prForm.base_branch,
  () => {
    buildSourceBranch();
  }
);

watch(
  () => prForm.jp_tickets,
  () => {
    buildSourceBranch();
  }
);

watch(
  () => [prForm.jp_tickets, prForm.base_branch, prForm.source_branch],
  () => {
    clearPreviewState();
  }
);

watch(
  () => sessionState.systemSettings.default_base_branch,
  (defaultBaseBranch) => {
    if (!prForm.base_branch.trim() && defaultBaseBranch) {
      prForm.base_branch = defaultBaseBranch;
    }
  },
  { immediate: true }
);

async function submit() {
  const parsedTickets = parseTickets();
  if (!parsedTickets.length) {
    showToast("Enter at least one JP ticket", "warning");
    return;
  }
  if (!prForm.base_branch.trim() || !prForm.source_branch.trim()) {
    showToast("Base branch and source branch are required", "warning");
    return;
  }
  if (!preview.value) {
    showToast("Verify PR first", "warning");
    return;
  }
  if (!preview.value.branch_exists) {
    showToast("Source branch does not exist on remote", "warning");
    return;
  }
  try {
    result.value = await pullRequestsApi.create({
      jp_tickets: parsedTickets,
      base_branch: prForm.base_branch,
      source_branch: prForm.source_branch,
      title: prForm.title.trim() || undefined
    });
    showToast("Pull request created", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}
</script>

<template>
  <PullRequestView
    :pr-form="prForm"
    :preview="preview"
    :loading-preview="loadingPreview"
    :result="result"
    @verify="verifyPreview"
    @submit="submit"
  />
</template>
