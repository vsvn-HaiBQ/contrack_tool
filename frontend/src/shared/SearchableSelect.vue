<script setup lang="ts" generic="T extends number | string">
import { computed, ref, watch } from "vue";

type Option = { value: T; label: string };

const props = defineProps<{
  modelValue: T | null;
  options: Option[];
  placeholder?: string;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: T | null];
}>();

const open = ref(false);
const query = ref("");

const selectedOption = computed(() => props.options.find((opt) => opt.value === props.modelValue) ?? null);

watch(
  () => props.modelValue,
  () => {
    if (!open.value) query.value = selectedOption.value?.label ?? "";
  },
  { immediate: true }
);

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q || query.value === selectedOption.value?.label) return props.options;
  return props.options.filter((opt) => opt.label.toLowerCase().includes(q));
});

function focusInput() {
  if (props.disabled) return;
  open.value = true;
  query.value = "";
}

function blurInput() {
  setTimeout(() => {
    open.value = false;
    query.value = selectedOption.value?.label ?? "";
  }, 150);
}

function selectOption(option: Option) {
  emit("update:modelValue", option.value);
  query.value = option.label;
  open.value = false;
}

function clearSelection() {
  emit("update:modelValue", null);
  query.value = "";
}
</script>

<template>
  <div class="relative">
    <input
      v-model="query"
      type="text"
      :placeholder="placeholder ?? 'Search...'"
      :disabled="disabled"
      class="w-full rounded border border-[#D0D1D2] px-2 py-2 pr-7 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1] disabled:cursor-not-allowed disabled:bg-neutral-50"
      @focus="focusInput"
      @blur="blurInput"
    />
    <button
      v-if="modelValue !== null && !disabled"
      type="button"
      class="absolute top-1/2 right-1.5 flex size-5 -translate-y-1/2 items-center justify-center rounded text-[#5C5E62] hover:bg-neutral-100 hover:text-[#171A20]"
      title="Clear"
      @mousedown.prevent="clearSelection"
    >
      <svg viewBox="0 0 20 20" fill="none" class="size-3.5" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <path d="m5 5 10 10M15 5 5 15"></path>
      </svg>
    </button>
    <div v-if="open && filtered.length" class="absolute inset-x-0 top-full z-20 mt-1 max-h-60 overflow-auto rounded-lg border border-neutral-200 bg-white shadow-lg">
      <button
        v-for="option in filtered"
        :key="String(option.value)"
        type="button"
        class="block w-full px-3 py-2 text-left text-sm transition hover:bg-[#F5F8FF]"
        :class="option.value === modelValue ? 'bg-[#EAF1FF] text-[#2F56BA]' : 'text-[#171A20]'"
        @mousedown.prevent="selectOption(option)"
      >
        {{ option.label }}
      </button>
    </div>
    <div v-else-if="open && !filtered.length" class="absolute inset-x-0 top-full z-20 mt-1 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-[#5C5E62] shadow-lg">
      No results
    </div>
  </div>
</template>
