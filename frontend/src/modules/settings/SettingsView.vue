<script setup lang="ts">
import type { Assignee, IntegrationStatus, User } from "../../shared/types";
import LoadingCircle from "../../shared/LoadingCircle.vue";

const props = defineProps<{
  me: User;
  assignees: Assignee[];
  users: User[];
  userSettings: {
    redmine_jp_api_key: string;
    redmine_vn_api_key: string;
    github_token: string;
    default_assignee_id: number | null;
  };
  systemSettings: Record<string, string>;
  integrationStatuses: IntegrationStatus[];
  testingService: string | null;
  loadingAssignees: boolean;
  loadingActivities: boolean;
  loadingStatuses: boolean;
  loadingTrackers: boolean;
  changingPassword: boolean;
  createUserForm: {
    username: string;
    password: string;
    role: string;
  };
  showCreateUserRow: boolean;
  passwordDrafts: Record<number, string>;
  passwordForm: {
    current_password: string;
    new_password: string;
  };
}>();

function integrationStatus(service: string) {
  return props.integrationStatuses.find((item) => item.service === service);
}

const emit = defineEmits<{
  saveUserSettings: [];
  changePassword: [];
  loadRedmineAssignees: [];
  loadRedmineActivities: [];
  loadRedmineStatuses: [];
  loadRedmineTrackers: [];
  saveSystemSettings: [];
  createUser: [];
  resetPassword: [userId: number];
  deleteUser: [userId: number];
  testIntegration: [serviceName: string];
}>();
</script>

<template>
  <section class="grid gap-6">
    <div class="grid content-start gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex items-center justify-between gap-3">
        <div>
          <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">User Settings</h3>
          <p class="mt-1 text-sm text-[#5C5E62]">These values apply only to your own Redmine and GitHub access.</p>
        </div>
      </div>
      <div class="grid gap-4 rounded-xl border border-neutral-200 p-4">
        <div>
          <h4 class="text-base font-semibold text-[#171A20]">Access Credentials</h4>
          <p class="mt-1 text-sm text-[#5C5E62]">Tokens and API keys used by your own account.</p>
        </div>
        <div class="grid gap-4 md:grid-cols-2">
          <div class="grid gap-2">
            <label class="text-sm font-medium text-[#393C41]">Redmine JP API Key</label>
            <div class="relative">
              <input v-model="userSettings.redmine_jp_api_key" class="w-full rounded border border-[#D0D1D2] px-2 py-2 pr-11 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
              <button class="absolute top-1/2 right-2 flex size-7 -translate-y-1/2 items-center justify-center text-[#3E6AE1] transition hover:text-[#2F56BA] disabled:cursor-not-allowed disabled:text-[#9CA0A6]" :disabled="testingService === 'redmine_jp'" :title="testingService === 'redmine_jp' ? 'Testing...' : 'Test connection'" @click="emit('testIntegration', 'redmine_jp')">
                <svg v-if="testingService !== 'redmine_jp'" viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M3.5 10h13"></path>
                  <path d="m10.5 3 6.5 7-6.5 7"></path>
                </svg>
                <LoadingCircle v-else class="text-current" />
              </button>
            </div>
          </div>
          <div class="grid gap-2">
            <label class="text-sm font-medium text-[#393C41]">Redmine VN API Key</label>
            <div class="relative">
              <input v-model="userSettings.redmine_vn_api_key" class="w-full rounded border border-[#D0D1D2] px-2 py-2 pr-11 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
              <button class="absolute top-1/2 right-2 flex size-7 -translate-y-1/2 items-center justify-center text-[#3E6AE1] transition hover:text-[#2F56BA] disabled:cursor-not-allowed disabled:text-[#9CA0A6]" :disabled="testingService === 'redmine_vn'" :title="testingService === 'redmine_vn' ? 'Testing...' : 'Test connection'" @click="emit('testIntegration', 'redmine_vn')">
                <svg v-if="testingService !== 'redmine_vn'" viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M3.5 10h13"></path>
                  <path d="m10.5 3 6.5 7-6.5 7"></path>
                </svg>
                <LoadingCircle v-else class="text-current" />
              </button>
            </div>
          </div>
          <div class="grid gap-2">
            <label class="text-sm font-medium text-[#393C41]">GitHub Token</label>
            <div class="relative">
              <input v-model="userSettings.github_token" class="w-full rounded border border-[#D0D1D2] px-2 py-2 pr-11 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
              <button class="absolute top-1/2 right-2 flex size-7 -translate-y-1/2 items-center justify-center text-[#3E6AE1] transition hover:text-[#2F56BA] disabled:cursor-not-allowed disabled:text-[#9CA0A6]" :disabled="testingService === 'github'" :title="testingService === 'github' ? 'Testing...' : 'Test connection'" @click="emit('testIntegration', 'github')">
                <svg v-if="testingService !== 'github'" viewBox="0 0 20 20" fill="none" class="size-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M3.5 10h13"></path>
                  <path d="m10.5 3 6.5 7-6.5 7"></path>
                </svg>
                <LoadingCircle v-else class="text-current" />
              </button>
            </div>
          </div>
          <div class="grid gap-2">
            <label class="text-sm font-medium text-[#393C41]">Default Assignee</label>
            <select v-model="userSettings.default_assignee_id" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
              <option v-for="assignee in assignees" :key="assignee.id" :value="assignee.id">
                [{{ assignee.id }}] {{ assignee.name }}
              </option>
            </select>
          </div>
        </div>
      </div>
      <div class="flex items-center gap-3 pt-2">
        <button class="min-h-10 min-w-[200px] rounded-lg bg-[#3E6AE1] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95" @click="emit('saveUserSettings')">Save User Settings</button>
      </div>

      <div class="grid gap-4 rounded-xl border border-neutral-200 p-4">
        <div>
          <h4 class="text-base font-semibold text-[#171A20]">Change Password</h4>
          <p class="mt-1 text-sm text-[#5C5E62]">Update the password for your current account.</p>
        </div>
        <div class="grid gap-4 md:grid-cols-2">
          <div class="grid gap-2">
            <label class="text-sm font-medium text-[#393C41]">Current Password</label>
            <input v-model="passwordForm.current_password" type="password" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
          </div>
          <div class="grid gap-2">
            <label class="text-sm font-medium text-[#393C41]">New Password</label>
            <input v-model="passwordForm.new_password" type="password" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
          </div>
        </div>
        <div class="flex items-center gap-3">
          <button
            class="min-h-10 min-w-[200px] rounded-lg border border-[#171A20] bg-[#171A20] px-4 py-2 text-sm font-medium text-white transition hover:bg-black disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="changingPassword"
            @click="emit('changePassword')"
          >
            {{ changingPassword ? "Updating Password..." : "Change Password" }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="me.role === 'admin'" class="grid content-start gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm">
      <div class="flex items-center justify-between gap-3">
        <div>
          <h3 class="m-0 text-2xl leading-tight font-medium text-[#171A20]">Admin Settings</h3>
          <p class="mt-1 text-sm text-[#5C5E62]">Shared hosts, repo config, templates, and user administration.</p>
        </div>
        <span class="text-sm text-[#5C5E62]">Admin controls</span>
      </div>
      <div class="grid items-start gap-4 md:grid-cols-2">
        <div v-for="(value, key) in systemSettings" :key="key" :class="key === 'description_template' ? 'md:col-span-2' : ''">
          <label class="mb-2 block text-sm font-medium text-[#393C41]">{{ key }}</label>
          <textarea
            v-if="key === 'description_template'"
            v-model="systemSettings[key]"
            rows="7"
            class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
          />
          <input
            v-else
            v-model="systemSettings[key]"
            class="w-full max-w-md rounded border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
          />
        </div>
      </div>
      <div class="flex items-center gap-3 pt-2">
        <button class="min-h-10 min-w-[200px] rounded-lg bg-[#3E6AE1] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95" @click="emit('saveSystemSettings')">Save System Settings</button>
      </div>

      <div class="grid gap-4 rounded-xl border border-neutral-200 bg-neutral-50 p-4">
        <div>
          <h4 class="text-base font-semibold text-[#171A20]">Redmine Cache</h4>
          <p class="mt-1 text-sm text-[#5C5E62]">Admin-only cache refresh for assignees, activities, statuses, and trackers.</p>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <button
            class="inline-flex items-center gap-2 rounded border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="loadingAssignees"
            @click="emit('loadRedmineAssignees')"
          >
            <LoadingCircle v-if="loadingAssignees" class="text-current" />
            {{ loadingAssignees ? "Loading Redmine Cache..." : "Load Redmine Cache" }}
          </button>
          <button
            class="inline-flex items-center gap-2 rounded border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="loadingActivities"
            @click="emit('loadRedmineActivities')"
          >
            <LoadingCircle v-if="loadingActivities" class="text-current" />
            {{ loadingActivities ? "Loading Activity Cache..." : "Load Activity Cache" }}
          </button>
          <button
            class="inline-flex items-center gap-2 rounded border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="loadingStatuses"
            @click="emit('loadRedmineStatuses')"
          >
            <LoadingCircle v-if="loadingStatuses" class="text-current" />
            {{ loadingStatuses ? "Loading Status + Workflow Cache..." : "Load Status + Workflow Cache" }}
          </button>
          <button
            class="inline-flex items-center gap-2 rounded border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="loadingTrackers"
            @click="emit('loadRedmineTrackers')"
          >
            <LoadingCircle v-if="loadingTrackers" class="text-current" />
            {{ loadingTrackers ? "Loading Tracker Cache..." : "Load Tracker Cache" }}
          </button>
        </div>
      </div>

      <div class="overflow-hidden border border-neutral-200">
        <div class="grid grid-cols-[40px_220px_120px_320px_120px] gap-3 border-b border-neutral-200 px-3 py-2 text-xs font-medium text-[#5C5E62]">
          <span>
            <button class="flex size-7 items-center justify-center rounded-full border border-neutral-200 bg-white text-sm text-[#171A20] transition hover:bg-neutral-100" @click="emit('createUser')">+</button>
          </span>
          <span>User</span>
          <span>Role</span>
          <span>Reset Password</span>
          <span>Action</span>
        </div>
        <div v-if="showCreateUserRow" class="grid grid-cols-[40px_220px_120px_320px_120px] items-start gap-3 border-b border-neutral-200 px-3 py-2">
          <span></span>
          <input v-model="createUserForm.username" placeholder="username" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
          <select v-model="createUserForm.role" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]">
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          <input v-model="createUserForm.password" type="password" placeholder="password" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
          <button class="rounded border border-[#171A20] bg-[#171A20] px-3 py-2 text-sm font-medium text-white transition hover:bg-black" @click="emit('createUser')">Save</button>
        </div>
        <div v-for="user in users" :key="user.id" class="grid grid-cols-[40px_220px_120px_320px_120px] items-start gap-3 border-b border-neutral-200 px-3 py-2 last:border-b-0">
          <span></span>
          <span>{{ user.username }}</span>
          <span>{{ user.role }}</span>
          <div class="flex items-center gap-2">
            <input v-model="passwordDrafts[user.id]" type="password" class="w-full rounded border border-[#D0D1D2] px-2 py-2 text-sm text-[#171A20] outline-none transition focus:border-[#3E6AE1]" />
            <button class="rounded border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-[#393C41] transition hover:bg-neutral-100" @click="emit('resetPassword', user.id)">Reset</button>
          </div>
          <div>
            <button class="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100" @click="emit('deleteUser', user.id)">Delete</button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
