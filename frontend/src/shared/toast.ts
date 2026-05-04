import { ref } from "vue";

export type ToastTone = "success" | "error" | "warning";

export const toastState = ref<{ id: number; message: string; tone: ToastTone } | null>(null);

let toastId = 0;

export function showToast(message: string, tone: ToastTone = "success") {
  const id = ++toastId;
  toastState.value = { id, message, tone };
  window.setTimeout(() => {
    if (toastState.value?.id === id) {
      toastState.value = null;
    }
  }, 3000);
}
