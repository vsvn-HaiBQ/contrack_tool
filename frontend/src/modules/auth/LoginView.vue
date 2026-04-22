<script setup lang="ts">
import LoadingCircle from "../../shared/LoadingCircle.vue";

defineProps<{
  setupMode: boolean;
  username: string;
  password: string;
  loading: boolean;
  setupUsername: string;
  setupPassword: string;
  setupConfirmPassword: string;
}>();

const emit = defineEmits<{
  "update:username": [value: string];
  "update:password": [value: string];
  "update:setup-username": [value: string];
  "update:setup-password": [value: string];
  "update:setup-confirm-password": [value: string];
  submit: [];
  submitSetup: [];
}>();
</script>

<template>
  <section class="min-h-screen bg-neutral-50">
    <div class="mx-auto grid min-h-screen max-w-6xl gap-10 px-4 py-8 sm:px-6 lg:grid-cols-[minmax(0,1fr)_420px] lg:px-8">
      <div class="flex items-center">
        <div class="max-w-2xl">
          <p class="text-sm font-semibold uppercase tracking-[0.08em] text-[#3E6AE1]">Contrack</p>
          <h1 class="mt-4 text-4xl leading-tight font-semibold text-[#171A20]">Manage JP tickets, VN execution, logtime, and PR flow in one place.</h1>
          <p class="mt-4 text-base leading-7 text-[#5C5E62]">
            A cleaner operational workspace for sync, ticket management, daily logtime, and GitHub pull requests.
          </p>
        </div>
      </div>
      <div class="flex items-center">
        <div class="grid w-full gap-3 rounded-2xl border border-neutral-200 bg-white p-8 shadow-sm">
          <template v-if="setupMode">
            <div>
              <p class="text-sm font-semibold uppercase tracking-[0.08em] text-[#3E6AE1]">Initial Setup</p>
              <h2 class="mt-2 text-2xl font-semibold text-[#171A20]">Create the first admin account</h2>
              <p class="mt-2 text-sm leading-6 text-[#5C5E62]">This is available only while the system has no users.</p>
            </div>
            <label class="text-sm font-medium text-[#393C41]">Admin Username</label>
            <input
              class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
              :value="setupUsername"
              @input="emit('update:setup-username', ($event.target as HTMLInputElement).value)"
            />
            <label class="text-sm font-medium text-[#393C41]">Password</label>
            <input
              class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
              :value="setupPassword"
              type="password"
              @input="emit('update:setup-password', ($event.target as HTMLInputElement).value)"
            />
            <label class="text-sm font-medium text-[#393C41]">Confirm Password</label>
            <input
              class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
              :value="setupConfirmPassword"
              type="password"
              @input="emit('update:setup-confirm-password', ($event.target as HTMLInputElement).value)"
            />
            <div class="flex items-center gap-3 pt-2">
              <button class="inline-flex min-h-10 min-w-[200px] items-center justify-center gap-2 rounded-lg bg-[#3E6AE1] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60" :disabled="loading" @click="emit('submitSetup')">
                <LoadingCircle v-if="loading" />
                {{ loading ? "Creating..." : "Create Admin" }}
              </button>
            </div>
          </template>
          <template v-else>
            <label class="text-sm font-medium text-[#393C41]">Username</label>
            <input
              class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
              :value="username"
              @input="emit('update:username', ($event.target as HTMLInputElement).value)"
            />
            <label class="text-sm font-medium text-[#393C41]">Password</label>
            <input
              class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
              :value="password"
              type="password"
              @input="emit('update:password', ($event.target as HTMLInputElement).value)"
            />
            <div class="flex items-center gap-3 pt-2">
              <button class="inline-flex min-h-10 min-w-[200px] items-center justify-center gap-2 rounded-lg bg-[#3E6AE1] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60" :disabled="loading" @click="emit('submit')">
                <LoadingCircle v-if="loading" />
                {{ loading ? "Signing in..." : "Login" }}
              </button>
            </div>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>
