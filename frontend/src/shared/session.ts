import { reactive, ref } from "vue";
import type { Assignee, TrackerOption, User } from "./types";
import { authApi } from "../modules/auth/api";
import { settingsApi } from "../modules/settings/api";
import { usersApi } from "../modules/users/api";

export const sessionState = reactive({
  me: null as User | null,
  needsSetup: false,
  assignees: [] as Assignee[],
  trackers: [] as TrackerOption[],
  users: [] as User[],
  userSettings: {
    redmine_jp_api_key: "",
    redmine_vn_api_key: "",
    github_token: "",
    default_assignee_id: null as number | null
  },
  systemSettings: {
    git_repo: "",
    redmine_jp_host: "",
    redmine_vn_host: "",
    redmine_vn_project_id: "",
    default_base_branch: "",
    description_template: ""
  } as Record<string, string>
});

export const sessionReady = ref(false);

export function hasRequiredRedmineKeys() {
  return Boolean(
    sessionState.userSettings.redmine_jp_api_key.trim() &&
    sessionState.userSettings.redmine_vn_api_key.trim()
  );
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
  sessionState.userSettings.redmine_jp_api_key = "";
  sessionState.userSettings.redmine_vn_api_key = "";
  sessionState.userSettings.github_token = "";
  sessionState.userSettings.default_assignee_id = null;
  Object.keys(sessionState.systemSettings).forEach((key) => {
    sessionState.systemSettings[key] = "";
  });
  sessionReady.value = true;
}
