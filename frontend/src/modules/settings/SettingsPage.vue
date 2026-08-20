<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import SettingsView from "./SettingsView.vue";
import { sessionState } from "../../shared/session";
import { showToast } from "../../shared/toast";
import { boxApi } from "../box/api";
import { settingsApi } from "./api";
import { usersApi } from "../users/api";
import type { BoxSettings, IntegrationStatus, MenuPermission, Role } from "../../shared/types";

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
  shared_link_access: "company"
});
const boxClientSecretConfigured = ref(false);
const passwordDrafts = reactive<Record<number, string>>({});
const roleDrafts = reactive<Record<number, string>>({});
const roles = ref<Role[]>([]);
const menuPermissions = ref<MenuPermission[]>([]);
const showRoleForm = ref(false);
const editingRoleName = ref<string | null>(null);
const savingRole = ref(false);
const roleForm = reactive({
  name: "",
  permissions: [] as string[]
});
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
    await refreshUsers();
    createUserForm.username = "";
    createUserForm.password = "";
    createUserForm.role = roles.value.find((role) => role.name === "dev")?.name ?? roles.value[0]?.name ?? "";
    showCreateUserRow.value = false;
    showToast("User created", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

function syncRoleDrafts() {
  for (const user of sessionState.users) {
    roleDrafts[user.id] = user.role;
  }
}

async function refreshUsers() {
  sessionState.users = await usersApi.list();
  syncRoleDrafts();
}

async function loadRoles() {
  try {
    const response = await usersApi.roles();
    roles.value = response.items;
    menuPermissions.value = response.permissions;
    if (!roles.value.some((role) => role.name === createUserForm.role)) {
      createUserForm.role = roles.value.find((role) => role.name === "dev")?.name ?? roles.value[0]?.name ?? "";
    }
    syncRoleDrafts();
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

function createRole() {
  editingRoleName.value = null;
  roleForm.name = "";
  roleForm.permissions = [];
  showRoleForm.value = true;
}

function editRole(roleName: string) {
  const role = roles.value.find((item) => item.name === roleName);
  if (!role || role.name === "admin") return;
  editingRoleName.value = role.name;
  roleForm.name = role.name;
  roleForm.permissions = [...role.permissions];
  showRoleForm.value = true;
}

function cancelRoleEdit() {
  showRoleForm.value = false;
  editingRoleName.value = null;
  roleForm.name = "";
  roleForm.permissions = [];
}

function toggleRolePermission(permission: string) {
  const index = roleForm.permissions.indexOf(permission);
  if (index >= 0) roleForm.permissions.splice(index, 1);
  else roleForm.permissions.push(permission);
}

async function saveRole() {
  if (!roleForm.name.trim()) {
    showToast("Role name is required", "warning");
    return;
  }
  savingRole.value = true;
  try {
    const isEditing = Boolean(editingRoleName.value);
    const payload = { name: roleForm.name.trim(), permissions: [...roleForm.permissions] };
    if (editingRoleName.value) await usersApi.updateRole(editingRoleName.value, payload);
    else await usersApi.createRole(payload);
    await loadRoles();
    await refreshUsers();
    cancelRoleEdit();
    showToast(isEditing ? "Role updated" : "Role created", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    savingRole.value = false;
  }
}

async function deleteRole(roleName: string) {
  if (!window.confirm(`Delete role ${roleName}?`)) return;
  try {
    await usersApi.removeRole(roleName);
    await loadRoles();
    showToast("Role deleted", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function updateUserRole(userId: number) {
  const role = roleDrafts[userId]?.trim();
  if (!role) return;
  try {
    await usersApi.updateUserRole(userId, role);
    await refreshUsers();
    showToast("User role updated", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
    syncRoleDrafts();
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
    await refreshUsers();
    delete passwordDrafts[userId];
    showToast("User deleted", "success");
  } catch (error) {
    showToast((error as Error).message, "error");
  }
}

async function testIntegration(serviceName: string) {
  testingService.value = serviceName;
  try {
    let rawValue: string | null = null;
    if (serviceName === "redmine_jp") rawValue = sessionState.userSettings.redmine_jp_api_key ?? "";
    else if (serviceName === "redmine_vn") rawValue = sessionState.userSettings.redmine_vn_api_key ?? "";
    else if (serviceName === "github") rawValue = sessionState.userSettings.github_token ?? "";
    const result = await settingsApi.testIntegration(serviceName, rawValue);
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
    await Promise.all([loadBoxSettings(), loadRoles()]);
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
    :roles="roles"
    :menu-permissions="menuPermissions"
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
    :role-drafts="roleDrafts"
    :role-form="roleForm"
    :show-role-form="showRoleForm"
    :editing-role-name="editingRoleName"
    :saving-role="savingRole"
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
    @update-user-role="updateUserRole"
    @reset-password="resetPassword"
    @delete-user="deleteUser"
    @create-role="createRole"
    @edit-role="editRole"
    @cancel-role-edit="cancelRoleEdit"
    @toggle-role-permission="toggleRolePermission"
    @save-role="saveRole"
    @delete-role="deleteRole"
    @test-integration="testIntegration"
  />
</template>
