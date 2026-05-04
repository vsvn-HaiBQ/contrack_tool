<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RouterView, useRouter } from "vue-router";
import { bootstrapSession, hasRequiredRedmineKeys, sessionState } from "./shared/session";
import { isElectronClient } from "./shared/electron";
import { checkClientUpdate } from "./shared/update";
import { showToast, toastState } from "./shared/toast";
import LoadingCircle from "./shared/LoadingCircle.vue";

const router = useRouter();
const bootstrapping = ref(true);

function authenticatedHomeRouteName() {
  return hasRequiredRedmineKeys() ? "detail" : "settings";
}

onMounted(async () => {
  try {
    if (isElectronClient()) {
      checkClientUpdate()
        .then((info) => {
          if (info.has_update) {
            showToast(`Có phiên bản client mới: ${info.latest_version}`, "warning");
          }
        })
        .catch(() => undefined);
    }
    await bootstrapSession();
    if (sessionState.me && router.currentRoute.value.name === "login") {
      await router.replace({ name: authenticatedHomeRouteName() });
    }
    if (!sessionState.me && router.currentRoute.value.name !== "login") {
      await router.replace({ name: "login" });
    }
  } catch (error) {
    showToast((error as Error).message, "error");
    await router.replace({ name: "login" });
  } finally {
    bootstrapping.value = false;
  }
});
</script>

<template>
  <div class="min-h-screen bg-white">
    <div v-if="bootstrapping" class="flex min-h-screen items-center justify-center bg-neutral-50">
      <div class="flex items-center gap-3 rounded-2xl border border-neutral-200 bg-white px-5 py-4 text-sm text-[#5C5E62] shadow-sm">
        <LoadingCircle class="text-[#3E6AE1]" />
        Loading workspace...
      </div>
    </div>
    <Transition name="toast" mode="out-in">
      <div
        v-if="toastState"
        :key="toastState.id"
        class="pointer-events-none fixed top-4 right-4 z-[1000] w-[min(420px,calc(100vw-2rem))] rounded border px-4 py-3 text-sm shadow-lg backdrop-blur"
        :class="
          toastState.tone === 'error'
            ? 'border-red-200 bg-red-50/95 text-red-700'
            : toastState.tone === 'warning'
              ? 'border-amber-200 bg-amber-50/95 text-amber-800'
              : 'border-emerald-200 bg-emerald-50/95 text-emerald-700'
        "
      >
        {{ toastState.message }}
      </div>
    </Transition>
    <RouterView v-if="!bootstrapping" />
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition:
    opacity 180ms ease,
    transform 180ms ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
