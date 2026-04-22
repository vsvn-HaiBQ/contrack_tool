import { ref } from "vue";

export type ToastTone = "success" | "error" | "warning";

export const toastState = ref<{ message: string; tone: ToastTone } | null>(null);

export function showToast(message: string, tone: ToastTone = "success") {
  toastState.value = { message, tone };
  window.setTimeout(() => {
    if (toastState.value?.message === message) {
      toastState.value = null;
    }
  }, 3000);
}
