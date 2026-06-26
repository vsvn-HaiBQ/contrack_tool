import { reactive, ref, computed } from "vue";
import type { Assignee, TrackerOption, User, UserSettings, Version } from "./types";
import { authApi } from "../modules/auth/api";
import { settingsApi } from "../modules/settings/api";
import { usersApi } from "../modules/users/api";
import { versionsApi } from "../modules/versions/api";

export const sessionState = reactive({
  me: null as User | null,
  needsSetup: false,
  assignees: [] as Assignee[],
  trackers: [] as TrackerOption[],
  users: [] as User[],
  versions: [] as Version[],
  pinnedVersionId: null as number | null,
  userSettings: {
    redmine_jp_api_key: "",
    redmine_vn_api_key: "",
    github_token: "",
    team_automate_url: "",
    default_assignee_id: null,
    pinned_version_id: null,
    document_translation: {}
  } as UserSettings,
  systemSettings: {
    git_repo: "",
    redmine_jp_host: "",
    redmine_vn_host: "",
    redmine_vn_project_id: "",
    description_template: ""
  } as Record<string, string>
});

export const sessionReady = ref(false);

export const activeVersion = computed<Version | null>(() => {
  if (!sessionState.pinnedVersionId) return null;
  return sessionState.versions.find((v) => v.id === sessionState.pinnedVersionId) ?? null;
});

export const activeDefaultBaseBranch = computed<string>(() => {
  return activeVersion.value?.default_base_branch?.trim() ?? "";
});

export function hasRequiredRedmineKeys() {
  return Boolean(
    sessionState.userSettings.redmine_jp_api_key.trim() &&
    sessionState.userSettings.redmine_vn_api_key.trim()
  );
}

export async function refreshVersions() {
  try {
    const response = await versionsApi.list();
    sessionState.versions = response.items ?? [];
  } catch {
    sessionState.versions = [];
  }
}

export async function pinVersion(versionId: number | null) {
  await versionsApi.pin(versionId);
  sessionState.pinnedVersionId = versionId;
  sessionState.userSettings.pinned_version_id = versionId;
}

export async function bootstrapSession() {
  const response = await authApi.me();
  sessionState.me = response.user;
  sessionState.needsSetup = response.needs_setup;
  if (!sessionState.me) {
    sessionReady.value = true;
    return;
  }
  const mySettings = await usersApi.mySettings();
  const settingsResponse = await settingsApi.system();
  Object.entries(settingsResponse.values).forEach(([key, value]) => {
    sessionState.systemSettings[key] = value ?? "";
  });
  sessionState.userSettings.redmine_jp_api_key = mySettings.redmine_jp_api_key ?? "";
  sessionState.userSettings.redmine_vn_api_key = mySettings.redmine_vn_api_key ?? "";
  sessionState.userSettings.github_token = mySettings.github_token ?? "";
  sessionState.userSettings.team_automate_url = mySettings.team_automate_url ?? "";
  sessionState.userSettings.document_translation = mySettings.document_translation ?? {};
  sessionState.userSettings.pinned_version_id = mySettings.pinned_version_id ?? null;
  sessionState.pinnedVersionId = mySettings.pinned_version_id ?? null;
  await refreshVersions();
  if (sessionState.versions.length > 0) {
    const stillExists = sessionState.pinnedVersionId !== null &&
      sessionState.versions.some((v) => v.id === sessionState.pinnedVersionId);
    if (!stillExists) {
      const firstId = sessionState.versions[0].id;
      try {
        await pinVersion(firstId);
      } catch {
        sessionState.pinnedVersionId = firstId;
        sessionState.userSettings.pinned_version_id = firstId;
      }
    }
  }
  try {
    sessionState.assignees = await usersApi.assignees();
  } catch {
    sessionState.assignees = [];
  }
  try {
    sessionState.trackers = await usersApi.trackers();
  } catch {
    sessionState.trackers = [];
  }
  sessionState.userSettings.default_assignee_id = mySettings.default_assignee_id ?? sessionState.assignees[0]?.id ?? null;
  if (sessionState.me.role === "admin") {
    sessionState.users = await usersApi.list();
  }
  sessionReady.value = true;
}

export function clearSession() {
  sessionState.me = null;
  sessionState.needsSetup = false;
  sessionState.assignees = [];
  sessionState.trackers = [];
  sessionState.users = [];
  sessionState.versions = [];
  sessionState.pinnedVersionId = null;
  sessionState.userSettings.redmine_jp_api_key = "";
  sessionState.userSettings.redmine_vn_api_key = "";
  sessionState.userSettings.github_token = "";
  sessionState.userSettings.team_automate_url = "";
  sessionState.userSettings.default_assignee_id = null;
  sessionState.userSettings.pinned_version_id = null;
  sessionState.userSettings.document_translation = {};
  Object.keys(sessionState.systemSettings).forEach((key) => {
    sessionState.systemSettings[key] = "";
  });
  sessionReady.value = true;
}

