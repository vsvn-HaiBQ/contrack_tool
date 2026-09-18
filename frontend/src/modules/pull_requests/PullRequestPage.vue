<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import PullRequestView from "./PullRequestView.vue";
import { pullRequestsApi } from "./api";
import type { PrPreview, PrResult } from "../../shared/types";
import { showToast } from "../../shared/toast";
import { activeDefaultBaseBranch } from "../../shared/session";

const prForm = reactive({
  jp_tickets: "",
  base_branch: "",
  source_branch: "",
  title: ""
});
const result = ref<PrResult | null>(null);
const preview = ref<PrPreview | null>(null);
const loadingPreview = ref(false);
const creatingPr = ref(false);
const lastGeneratedTitle = ref("");
let previewSequence = 0;

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
  previewSequence++;
  preview.value = null;
  result.value = null;
  if (prForm.title === lastGeneratedTitle.value) {
    prForm.title = "";
  }
  lastGeneratedTitle.value = "";
}

async function verifyPreview() {
  if (loadingPreview.value || creatingPr.value) return;
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
  const sequence = ++previewSequence;
  result.value = null;
  try {
    const nextPreview = await pullRequestsApi.preview({
      jp_tickets: parsedTickets,
      base_branch: prForm.base_branch,
      source_branch: prForm.source_branch
    });
    if (sequence !== previewSequence) return;
    const shouldSyncTitle = !prForm.title.trim() || prForm.title === lastGeneratedTitle.value;
    preview.value = nextPreview;
    result.value = nextPreview.existing_pull_request;
    lastGeneratedTitle.value = nextPreview.title;
    if (shouldSyncTitle) {
      prForm.title = nextPreview.title;
    }
    showToast(nextPreview.existing_pull_request ? "Existing pull request found" : nextPreview.branch_exists ? "PR verified" : "Branch does not exist on remote", nextPreview.existing_pull_request || nextPreview.branch_exists ? "success" : "warning");
  } catch (error) {
    if (sequence !== previewSequence) return;
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

let lastAutoBaseBranch = "";
watch(
  activeDefaultBaseBranch,
  (defaultBaseBranch) => {
    if (!defaultBaseBranch) return;
    if (!prForm.base_branch.trim() || prForm.base_branch === lastAutoBaseBranch) {
      prForm.base_branch = defaultBaseBranch;
      lastAutoBaseBranch = defaultBaseBranch;
    }
  },
  { immediate: true }
);

async function submit() {
  if (creatingPr.value) {
    return;
  }
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
  if (preview.value.existing_pull_request?.state === "open") {
    result.value = preview.value.existing_pull_request;
    return;
  }
  creatingPr.value = true;
  const sequence = previewSequence;
  try {
    const created = await pullRequestsApi.create({
      jp_tickets: parsedTickets,
      base_branch: prForm.base_branch,
      source_branch: prForm.source_branch,
      title: prForm.title.trim() || undefined
    });
    if (sequence !== previewSequence) return;
    result.value = created;
    if (preview.value) preview.value.existing_pull_request = result.value;
    showToast(result.value.existing ? "Existing pull request found" : "Pull request created", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    creatingPr.value = false;
  }
}
</script>

<template>
  <PullRequestView
    :pr-form="prForm"
    :preview="preview"
    :loading-preview="loadingPreview"
    :creating-pr="creatingPr"
    :result="result"
    @verify="verifyPreview"
    @submit="submit"
  />
</template>
