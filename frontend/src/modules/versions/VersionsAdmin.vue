<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import LoadingCircle from "../../shared/LoadingCircle.vue";
import { refreshVersions, sessionState } from "../../shared/session";
import { showToast } from "../../shared/toast";
import type { Version } from "../../shared/types";
import { versionsApi } from "./api";

type DraftVersion = {
  id: number | null;
  name: string;
  default_base_branch: string;
  client_folder_id: string;
  server_folder_id: string;
  client_baseline_folder: string;
  server_baseline_folder: string;
};

const drafts = reactive<Record<number, DraftVersion>>({});
const newDraft = reactive<DraftVersion>(emptyDraft());
const showCreateRow = ref(false);
const savingIds = reactive<Record<number, boolean>>({});
const creating = ref(false);

function emptyDraft(): DraftVersion {
  return {
    id: null,
    name: "",
    default_base_branch: "",
    client_folder_id: "",
    server_folder_id: "",
    client_baseline_folder: "",
    server_baseline_folder: "",
  };
}

function toDraft(version: Version): DraftVersion {
  return {
    id: version.id,
    name: version.name ?? "",
    default_base_branch: version.default_base_branch ?? "",
    client_folder_id: version.client_folder_id ?? "",
    server_folder_id: version.server_folder_id ?? "",
    client_baseline_folder: version.client_baseline_folder ?? "",
    server_baseline_folder: version.server_baseline_folder ?? "",
  };
}

function syncDrafts() {
  for (const id of Object.keys(drafts)) delete drafts[Number(id)];
  for (const version of sessionState.versions) {
    drafts[version.id] = toDraft(version);
  }
}

function payloadFromDraft(draft: DraftVersion) {
  return {
    name: draft.name.trim(),
    default_base_branch: draft.default_base_branch.trim() || null,
    client_folder_id: draft.client_folder_id.trim() || null,
    server_folder_id: draft.server_folder_id.trim() || null,
    client_baseline_folder: draft.client_baseline_folder.trim() || null,
    server_baseline_folder: draft.server_baseline_folder.trim() || null,
  };
}

async function saveExisting(versionId: number) {
  const draft = drafts[versionId];
  if (!draft) return;
  if (!draft.name.trim()) {
    showToast("Version name is required", "warning");
    return;
  }
  savingIds[versionId] = true;
  try {
    await versionsApi.update(versionId, payloadFromDraft(draft));
    await refreshVersions();
    syncDrafts();
    showToast("Version updated", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    delete savingIds[versionId];
  }
}

async function createNew() {
  if (!showCreateRow.value) {
    showCreateRow.value = true;
    Object.assign(newDraft, emptyDraft());
    return;
  }
  if (!newDraft.name.trim()) {
    showToast("Version name is required", "warning");
    return;
  }
  creating.value = true;
  try {
    await versionsApi.create(payloadFromDraft(newDraft));
    await refreshVersions();
    syncDrafts();
    Object.assign(newDraft, emptyDraft());
    showCreateRow.value = false;
    showToast("Version created", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    creating.value = false;
  }
}

async function removeVersion(version: Version) {
  if (!window.confirm(`Delete version "${version.name}"? Users pinned to it will be reset.`)) return;
  try {
    await versionsApi.remove(version.id);
    if (sessionState.pinnedVersionId === version.id) {
      sessionState.pinnedVersionId = null;
      sessionState.userSettings.pinned_version_id = null;
    }
    await refreshVersions();
    syncDrafts();
    showToast("Version deleted", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

onMounted(async () => {
  if (!sessionState.versions.length) await refreshVersions();
  syncDrafts();
});
</script>

<template>
  <div class="grid gap-4 rounded-xl border border-neutral-200 bg-neutral-50 p-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h4 class="text-base font-semibold text-[#171A20]">Versions</h4>
        <p class="mt-1 text-sm text-[#5C5E62]">
          Configure each version's default base branch, Box folder ids, and baseline folders.
        </p>
      </div>
      <button
        class="rounded border border-[#171A20] bg-[#171A20] px-3 py-2 text-sm font-medium text-white transition hover:bg-black"
        @click="createNew"
      >
        {{ showCreateRow ? (creating ? "Creating..." : "Save New Version") : "+ Add Version" }}
      </button>
    </div>
    <div class="overflow-x-auto">
      <table class="min-w-full text-sm">
        <thead>
          <tr class="border-b border-neutral-200 text-left text-xs font-medium uppercase text-[#5C5E62]">
            <th class="px-2 py-2">Name</th>
            <th class="px-2 py-2">Default Base Branch</th>
            <th class="px-2 py-2">Client Folder ID</th>
            <th class="px-2 py-2">Server Folder ID</th>
            <th class="px-2 py-2">Client Baseline Folder</th>
            <th class="px-2 py-2">Server Baseline Folder</th>
            <th class="px-2 py-2">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="showCreateRow" class="border-b border-neutral-200 bg-white">
            <td class="px-2 py-2"><input v-model="newDraft.name" placeholder="e.g. v1.2" class="w-full rounded border border-[#D0D1D2] px-2 py-1.5 text-sm" /></td>
            <td class="px-2 py-2"><input v-model="newDraft.default_base_branch" placeholder="main" class="w-full rounded border border-[#D0D1D2] px-2 py-1.5 text-sm" /></td>
            <td class="px-2 py-2"><input v-model="newDraft.client_folder_id" class="w-full rounded border border-[#D0D1D2] px-2 py-1.5 text-sm" /></td>
            <td class="px-2 py-2"><input v-model="newDraft.server_folder_id" class="w-full rounded border border-[#D0D1D2] px-2 py-1.5 text-sm" /></td>
            <td class="px-2 py-2"><input v-model="newDraft.client_baseline_folder" placeholder="Box folder id" class="w-full rounded border border-[#D0D1D2] px-2 py-1.5 text-sm" /></td>
            <td class="px-2 py-2"><input v-model="newDraft.server_baseline_folder" placeholder="Box folder id" class="w-full rounded border border-[#D0D1D2] px-2 py-1.5 text-sm" /></td>
            <td class="px-2 py-2">
              <button class="text-sm text-[#5C5E62] hover:text-[#171A20]" @click="showCreateRow = false">Cancel</button>
            </td>
          </tr>
          <tr v-for="version in sessionState.versions" :key="version.id" class="border-b border-neutral-200 bg-white">
            <td class="px-2 py-2"><input v-if="drafts[version.id]" v-model="drafts[version.id].name" class="w-full rounded border border-[#D0D1D2] px-2 py-1.5 text-sm" /></td>
            <td class="px-2 py-2"><input v-if="drafts[version.id]" v-model="drafts[version.id].default_base_branch" class="w-full rounded border border-[#D0D1D2] px-2 py-1.5 text-sm" /></td>
            <td class="px-2 py-2"><input v-if="drafts[version.id]" v-model="drafts[version.id].client_folder_id" class="w-full rounded border border-[#D0D1D2] px-2 py-1.5 text-sm" /></td>
            <td class="px-2 py-2"><input v-if="drafts[version.id]" v-model="drafts[version.id].server_folder_id" class="w-full rounded border border-[#D0D1D2] px-2 py-1.5 text-sm" /></td>
            <td class="px-2 py-2"><input v-if="drafts[version.id]" v-model="drafts[version.id].client_baseline_folder" class="w-full rounded border border-[#D0D1D2] px-2 py-1.5 text-sm" /></td>
            <td class="px-2 py-2"><input v-if="drafts[version.id]" v-model="drafts[version.id].server_baseline_folder" class="w-full rounded border border-[#D0D1D2] px-2 py-1.5 text-sm" /></td>
            <td class="px-2 py-2">
              <div class="flex items-center gap-2">
                <button
                  class="inline-flex items-center gap-1 rounded border border-[#171A20] bg-[#171A20] px-3 py-1.5 text-xs font-medium text-white transition hover:bg-black disabled:opacity-60"
                  :disabled="savingIds[version.id]"
                  @click="saveExisting(version.id)"
                >
                  <LoadingCircle v-if="savingIds[version.id]" class="text-current" />
                  Save
                </button>
                <button class="rounded border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 transition hover:bg-red-100" @click="removeVersion(version)">Delete</button>
              </div>
            </td>
          </tr>
          <tr v-if="!sessionState.versions.length && !showCreateRow">
            <td colspan="7" class="px-2 py-4 text-center text-sm text-[#5C5E62]">No versions yet. Use "Add Version" to create one.</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
