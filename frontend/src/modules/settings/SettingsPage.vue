<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import SettingsView from "./SettingsView.vue";
import { sessionState } from "../../shared/session";
import { showToast } from "../../shared/toast";
import { boxApi } from "../box/api";
import { settingsApi } from "./api";
import { usersApi } from "../users/api";
import type { BoxSettings, IntegrationStatus } from "../../shared/types";

const integrationStatuses = ref<IntegrationStatus[]>([]);
const testingService = ref<string | null>(null);
const loadingAssignees = ref(false);
const loadingActivities = ref(false);
const loadingStatuses = ref(false);
const loadingTrackers = ref(false);
const showCreateUserRow = ref(false);
const changingPassword = ref(false);
const savingBoxSettings = ref(false);
const createUserForm = reactive({
  username: "",
  password: "",
  role: "dev"
});
const boxSettings = reactive({
  client_id: "",
  client_secret: "",
  server_folder_id: "",
  client_folder_id: "",
  shared_link_access: "company"
});
const boxClientSecretConfigured = ref(false);
const passwordDrafts = reactive<Record<number, string>>({});
const passwordForm = reactive({
  current_password: "",
  new_password: ""
});

async function loadIntegrationStatuses() {
  try {
    const response = await settingsApi.integrationStatus();
    integrationStatuses.value = response.items;
  } catch (error) {
    integrationStatuses.value = [];
    showToast((error as Error).message, "error");
  }
}

function applyBoxSettings(settings: BoxSettings) {
  boxSettings.client_id = settings.client_id ?? "";
  boxSettings.client_secret = "";
  boxSettings.server_folder_id = settings.server_folder_id ?? "";
  boxSettings.client_folder_id = settings.client_folder_id ?? "";
  boxSettings.shared_link_access = settings.shared_link_access ?? "company";
  boxClientSecretConfigured.value = settings.client_secret_configured;
}

async function loadBoxSettings() {
  try {
    applyBoxSettings(await boxApi.settings());
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function loadBoxUserStatus() {
  try {
    const status = await boxApi.status();
    boxClientSecretConfigured.value = status.configured;
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function saveBoxSettings() {
  savingBoxSettings.value = true;
  try {
    const payload: Record<string, string> = {
      client_id: boxSettings.client_id.trim(),
      server_folder_id: boxSettings.server_folder_id.trim(),
      client_folder_id: boxSettings.client_folder_id.trim(),
      shared_link_access: boxSettings.shared_link_access
    };
    if (boxSettings.client_secret.trim()) {
      payload.client_secret = boxSettings.client_secret.trim();
    }
    applyBoxSettings(await boxApi.updateSettings(payload));
    await loadIntegrationStatuses();
    showToast("Box settings saved", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    savingBoxSettings.value = false;
  }
}

async function saveUserSettings() {
  try {
    await usersApi.updateMySettings(sessionState.userSettings);
    await loadIntegrationStatuses();
    showToast("User settings saved", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function changePassword() {
  if (!passwordForm.current_password.trim() || !passwordForm.new_password.trim()) {
    showToast("Current password and new password are required", "warning");
    return;
  }

  changingPassword.value = true;
  try {
    await usersApi.changeMyPassword({
      current_password: passwordForm.current_password,
      new_password: passwordForm.new_password
    });
    passwordForm.current_password = "";
    passwordForm.new_password = "";
    showToast("Password updated", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    changingPassword.value = false;
  }
}

async function loadRedmineAssigneeCache() {
  loadingAssignees.value = true;
  try {
    sessionState.assignees = await usersApi.assignees();
    if (!sessionState.userSettings.default_assignee_id && sessionState.assignees.length) {
      sessionState.userSettings.default_assignee_id = sessionState.assignees[0].id;
    }
    showToast("Redmine assignee cache loaded", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    loadingAssignees.value = false;
  }
}

async function loadRedmineActivityCache() {
  loadingActivities.value = true;
  try {
    const activities = await usersApi.activities();
    showToast(`Loaded ${activities.length} Redmine activities`, "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    loadingActivities.value = false;
  }
}

async function loadRedmineStatusCache() {
  loadingStatuses.value = true;
  try {
    const statuses = await usersApi.statuses(true);
    showToast(`Loaded ${statuses.length} Redmine statuses and refreshed workflow cache`, "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    loadingStatuses.value = false;
  }
}

async function loadRedmineTrackerCache() {
  loadingTrackers.value = true;
  try {
    sessionState.trackers = await usersApi.trackers();
    showToast(`Loaded ${sessionState.trackers.length} Redmine trackers`, "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    loadingTrackers.value = false;
  }
}

async function saveSystemSettings() {
  try {
    await settingsApi.updateSystem({ values: sessionState.systemSettings });
    await loadIntegrationStatuses();
    showToast("System settings saved", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function createUser() {
  if (!showCreateUserRow.value) {
    showCreateUserRow.value = true;
    return;
  }
  if (!createUserForm.username.trim() || !createUserForm.password.trim()) {
    showToast("Username and password are required", "warning");
    return;
  }
  try {
    await usersApi.create({
      username: createUserForm.username.trim(),
      password: createUserForm.password,
      role: createUserForm.role
    });
    sessionState.users = await usersApi.list();
    createUserForm.username = "";
    createUserForm.password = "";
    createUserForm.role = "dev";
    showCreateUserRow.value = false;
    showToast("User created", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function resetPassword(userId: number) {
  if (!passwordDrafts[userId]?.trim()) {
    showToast("Enter a new password", "warning");
    return;
  }
  try {
    await usersApi.resetPassword(userId, passwordDrafts[userId]);
    passwordDrafts[userId] = "";
    showToast("Password reset", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function deleteUser(userId: number) {
  try {
    await usersApi.remove(userId);
    sessionState.users = await usersApi.list();
    delete passwordDrafts[userId];
    showToast("User deleted", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function testIntegration(serviceName: string) {
  testingService.value = serviceName;
  try {
    const result = await settingsApi.testIntegration(serviceName);
    integrationStatuses.value = integrationStatuses.value.map((item) =>
      item.service === serviceName ? { ...item, connected: result.success, message: result.message } : item
    );
    showToast(result.message, result.success ? "success" : "warning");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    testingService.value = null;
  }
}

onMounted(async () => {
  await loadIntegrationStatuses();
  if (sessionState.me?.role === "admin") {
    await loadBoxSettings();
  }
  await loadBoxUserStatus();
});
</script>

<template>
  <SettingsView
    v-if="sessionState.me"
    :me="sessionState.me"
    :assignees="sessionState.assignees"
    :users="sessionState.users"
    :user-settings="sessionState.userSettings"
    :system-settings="sessionState.systemSettings"
    :integration-statuses="integrationStatuses"
    :testing-service="testingService"
    :loading-assignees="loadingAssignees"
    :loading-activities="loadingActivities"
    :loading-statuses="loadingStatuses"
    :loading-trackers="loadingTrackers"
    :changing-password="changingPassword"
    :create-user-form="createUserForm"
    :show-create-user-row="showCreateUserRow"
    :password-drafts="passwordDrafts"
    :password-form="passwordForm"
    :box-settings="boxSettings"
    :box-client-secret-configured="boxClientSecretConfigured"
    :saving-box-settings="savingBoxSettings"
    @save-user-settings="saveUserSettings"
    @change-password="changePassword"
    @load-redmine-assignees="loadRedmineAssigneeCache"
    @load-redmine-activities="loadRedmineActivityCache"
    @load-redmine-statuses="loadRedmineStatusCache"
    @load-redmine-trackers="loadRedmineTrackerCache"
    @save-system-settings="saveSystemSettings"
    @save-box-settings="saveBoxSettings"
    @create-user="createUser"
    @reset-password="resetPassword"
    @delete-user="deleteUser"
    @test-integration="testIntegration"
  />
</template>
