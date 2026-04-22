<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import LoginView from "./LoginView.vue";
import { authApi } from "./api";
import { bootstrapSession, hasRequiredRedmineKeys } from "../../shared/session";
import { showToast } from "../../shared/toast";

const router = useRouter();
const loading = ref(false);
const form = reactive({ username: "", password: "" });
const setupMode = ref(false);
const setupForm = reactive({ username: "", password: "", confirmPassword: "" });

function authenticatedHomeRouteName() {
  return hasRequiredRedmineKeys() ? "detail" : "settings";
}

async function login() {
  try {
    loading.value = true;
    await authApi.login(form);
    await bootstrapSession();
    showToast("Logged in", "success");
    await router.replace({ name: authenticatedHomeRouteName() });
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    loading.value = false;
  }
}

async function setupAdmin() {
  if (!setupForm.username.trim() || !setupForm.password.trim()) {
    showToast("Username and password are required", "warning");
    return;
  }
  if (setupForm.password !== setupForm.confirmPassword) {
    showToast("Password confirmation does not match", "warning");
    return;
  }
  try {
    loading.value = true;
    await authApi.setup({ username: setupForm.username.trim(), password: setupForm.password });
    await bootstrapSession();
    showToast("Initial admin created", "success");
    await router.replace({ name: authenticatedHomeRouteName() });
  } catch (error) {
    showToast((error as Error).message, "error");
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  try {
    const status = await authApi.setupStatus();
    setupMode.value = status.needs_setup;
  } catch {
    setupMode.value = false;
  }
});
</script>

<template>
  <LoginView
    :setup-mode="setupMode"
    :username="form.username"
    :password="form.password"
    :loading="loading"
    :setup-username="setupForm.username"
    :setup-password="setupForm.password"
    :setup-confirm-password="setupForm.confirmPassword"
    @update:username="form.username = $event"
    @update:password="form.password = $event"
    @update:setup-username="setupForm.username = $event"
    @update:setup-password="setupForm.password = $event"
    @update:setup-confirm-password="setupForm.confirmPassword = $event"
    @submit="login"
    @submit-setup="setupAdmin"
  />
</template>
