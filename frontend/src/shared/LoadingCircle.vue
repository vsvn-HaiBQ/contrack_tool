<script setup lang="ts">
withDefaults(
  defineProps<{
    size?: string;
  }>(),
  {
    size: "size-4"
  }
);
</script>

<template>
  <svg
    viewBox="0 0 20 20"
    fill="none"
    aria-hidden="true"
    class="animate-spin"
    :class="size"
  >
    <circle cx="10" cy="10" r="7" class="opacity-25" stroke="currentColor" stroke-width="2"></circle>
    <path d="M17 10a7 7 0 0 0-7-7" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"></path>
  </svg>
</template>
