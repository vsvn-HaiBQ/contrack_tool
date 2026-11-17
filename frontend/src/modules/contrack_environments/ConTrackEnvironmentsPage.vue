<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { environmentsApi } from "./api";
import type { Catalog, Environment, EnvironmentRun, Recipe, Selection } from "./api";

const catalog = ref<Catalog | null>(null);
const current = ref<Environment | null>(null);
const runs = ref<EnvironmentRun[]>([]);
const selectedRun = ref<EnvironmentRun | null>(null);
const bundleId = ref("");
const warId = ref("");
const warPreview = ref("");
const databaseId = ref("");
const repositoryId = ref("");
const error = ref("");
const catalogError = ref("");
const actionError = ref("");
const loading = ref(true);
const submitting = ref(false);
const validating = ref(false);
const busy = ref(false);
const preview = ref<Recipe | null>(null);
const offset = ref(0);
const total = ref(0);
const historyLoading = ref(false);
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
let refreshInProgress = false;
let catalogRefreshPending = false;
let detailRequest = 0;
let selectionRevision = 0;

const bundle = computed(() => catalog.value?.versions.find(item => item.bundleId === bundleId.value));
const warOnly = computed(() => catalog.value?.operation_mode === "deploy_war");
const selectedWar = computed(() => catalog.value?.wars?.find(item => item.id === warId.value));
const currentStatus = computed(() => current.value?.status ?? (!catalog.value
  ? (loading.value ? "LOADING" : "CONFIGURATION UNAVAILABLE")
  : (warOnly.value ? "NO RECORDED DEPLOYMENT" : "NOT PREPARED")));
const databases = computed(() => catalog.value?.databases.filter(item => item.schema === bundle.value?.databaseSchema) ?? []);
const locked = computed(() => submitting.value || validating.value || busy.value);
const valid = computed(() => !catalogError.value && (warOnly.value
  ? Boolean(catalog.value?.enabled && catalog.value?.wars?.some(item => item.id === warId.value && item.status === "available"))
  : catalog.value?.enabled && bundle.value?.status === "available" &&
  databases.value.some(item => item.id === databaseId.value) &&
  catalog.value.repositories.some(item => item.id === repositoryId.value)));
const activeRun = computed(() => runs.value.find(item => ["QUEUED", "PREPARING"].includes(item.status)));

watch(bundleId, () => {
  databaseId.value = bundle.value?.defaultDatabaseId ?? "";
  repositoryId.value = bundle.value?.defaultRepositoryId ?? "";
});
watch([bundleId, databaseId, repositoryId], () => { preview.value = null; actionError.value = ""; });
watch(warId, () => { warPreview.value = ""; actionError.value = ""; });

function selection(): Selection {
  return { bundle_id: bundleId.value, database_profile_id: databaseId.value, repository_profile_id: repositoryId.value };
}
function message(value: unknown) { return value instanceof Error ? value.message : "Request failed"; }
function date(value?: string) { return value ? new Date(value).toLocaleString() : "—"; }
function statusClass(status: string) {
  if (["READY", "RUNNING", "SUCCESS", "DEPLOYED"].includes(status)) return "bg-emerald-50 text-emerald-800";
  if (["FAILED", "INTERRUPTED", "UNKNOWN"].includes(status)) return "bg-red-50 text-red-800";
  return "bg-blue-50 text-blue-800";
}

async function viewRun(id: string) {
  const request = ++detailRequest;
  try {
    const run = await environmentsApi.run(id);
    if (!disposed && request === detailRequest) selectedRun.value = run;
  } catch (cause) { if (!disposed && request === detailRequest) error.value = message(cause); }
}

async function refresh(includeCatalog = false) {
  if (disposed) return;
  if (refreshInProgress) {
    if (includeCatalog) catalogRefreshPending = true;
    return;
  }
  refreshInProgress = true;
  const revision = selectionRevision;
  const loadCatalog = includeCatalog || !catalog.value || Boolean(catalogError.value);
  try {
    const [stateResult, historyResult, catalogResult] = await Promise.allSettled([
      environmentsApi.current(), environmentsApi.runs(offset.value),
      loadCatalog ? environmentsApi.catalog() : Promise.resolve(null),
    ]);
    if (disposed || revision !== selectionRevision) return;
    const errors: string[] = [];
    if (stateResult.status === "fulfilled") {
      current.value = stateResult.value.environment;
      busy.value = stateResult.value.busy;
    } else errors.push(message(stateResult.reason));
    if (historyResult.status === "fulfilled") {
      runs.value = historyResult.value.items;
      total.value = historyResult.value.total;
    } else errors.push(message(historyResult.reason));
    if (loadCatalog) {
      if (catalogResult.status === "fulfilled" && catalogResult.value) {
        const latestCatalog = catalogResult.value;
        catalog.value = latestCatalog;
        catalogError.value = "";
        busy.value = stateResult.status === "fulfilled" ? (busy.value || latestCatalog.busy) : latestCatalog.busy;
        if (!warId.value) warId.value = latestCatalog.wars?.find(item => item.status === "available")?.id ?? "";
        if (!bundleId.value) bundleId.value = latestCatalog.versions.find(item => item.status === "available")?.bundleId ?? "";
      } else if (catalogResult.status === "rejected") {
        catalogError.value = message(catalogResult.reason);
      }
    }
    error.value = errors.join(" · ");
    const id = selectedRun.value?.run_id ?? activeRun.value?.run_id;
    if (id) await viewRun(id);
  } catch (cause) { if (!disposed) error.value = message(cause); }
  finally {
    refreshInProgress = false;
    loading.value = false;
    if (catalogRefreshPending && !disposed) {
      catalogRefreshPending = false;
      void refresh(true);
    }
  }
}

async function poll() {
  await refresh();
  if (!disposed) timer = setTimeout(() => void poll(), 3000);
}

async function validate() {
  if (!valid.value || locked.value) return;
  validating.value = true;
  actionError.value = "";
  try {
    if (warOnly.value) {
      const result = await environmentsApi.validateWar(warId.value);
      warPreview.value = `Ready to copy ${result.war_id} to ${result.destination}`;
    } else preview.value = (await environmentsApi.validate(selection())).recipe;
  }
  catch (cause) { preview.value = null; warPreview.value = ""; actionError.value = message(cause); }
  finally { validating.value = false; }
}

async function prepare() {
  if (!valid.value || locked.value) return;
  submitting.value = true; // Lock immediately, including validation and request creation.
  ++selectionRevision; // Discard polling responses that started before this preparation.
  actionError.value = "";
  try {
    const run = warOnly.value ? await environmentsApi.deployWar(warId.value) : await environmentsApi.prepare(selection());
    selectedRun.value = run;
    busy.value = true;
    offset.value = 0;
    await refresh();
  } catch (cause) { actionError.value = message(cause); }
  finally { submitting.value = false; }
}

async function page(next: number) {
  if (historyLoading.value || refreshInProgress) return;
  historyLoading.value = true;
  offset.value = next;
  try { await refresh(); } finally { historyLoading.value = false; }
}

onMounted(async () => {
  await refresh(true);
  if (!disposed) timer = setTimeout(() => void poll(), 3000);
});
onBeforeUnmount(() => { disposed = true; ++detailRequest; if (timer) clearTimeout(timer); });
</script>

<template>
  <main class="mx-auto w-full max-w-7xl space-y-5 p-4 sm:p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold">ConTrack Environments</h1>
        <p class="mt-1 text-sm text-neutral-500">{{ !catalog ? 'Loading deployment configuration and version catalog.' : (warOnly ? 'Deploy a catalog WAR to the existing Tomcat server.' : 'Select a version to prepare its application, database and repository on the Linux server.') }}</p>
      </div>
      <button class="rounded-lg border border-neutral-200 px-4 py-2 text-sm disabled:opacity-50" :disabled="loading || submitting" @click="refresh(true)">Refresh</button>
    </div>

    <p v-if="loading" role="status" class="text-sm text-neutral-500">Loading environments…</p>
    <p v-if="error" role="alert" class="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{{ error }}</p>
    <div v-if="catalogError" role="alert" class="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <p class="font-medium">Version catalog could not be loaded</p>
      <p class="mt-1">{{ catalogError }}</p>
      <p class="mt-1">Correct the catalog error on the server. This page retries automatically; you can also click Refresh.</p>
    </div>
    <p v-if="catalog && !catalog.enabled" role="status" class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{{ catalog.message }}</p>
    <p v-if="busy" role="status" class="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">{{ warOnly ? 'WAR deployment is already in progress. You can follow its progress below.' : 'Environment preparation is already in progress. You can follow its progress below.' }}</p>

    <section class="rounded-2xl border border-neutral-200 bg-white p-5">
      <div class="mb-4 flex items-center justify-between gap-3">
        <h2 class="text-lg font-semibold">{{ !catalog ? 'Current deployment' : (warOnly ? 'Current WAR deployment' : 'Current environment') }}</h2>
        <span class="rounded-full px-3 py-1 text-xs font-medium" :class="statusClass(currentStatus)">{{ currentStatus }}</span>
      </div>
      <p v-if="current?.operation_mode === 'deploy_war'" class="mb-4 rounded-lg bg-blue-50 p-3 text-sm text-blue-900">{{ current.status === 'DEPLOYED' ? `WAR copied to ${current.destination}.` : 'WAR deployment status is uncertain; check the run log and destination file.' }} Application reload/restart is controlled by the existing Tomcat setup. Application health and database schema were not checked.</p>
      <dl v-if="current" class="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <div><dt class="text-neutral-500">ConTrack version</dt><dd class="mt-1 font-medium">{{ current.display_name || 'Unknown' }}</dd></div>
        <div><dt class="text-neutral-500">WAR</dt><dd class="mt-1 break-all">{{ current.war || '—' }}</dd></div>
        <template v-if="current.operation_mode !== 'deploy_war'">
          <div><dt class="text-neutral-500">Working database</dt><dd class="mt-1 break-all">{{ current.database || '—' }}</dd></div>
          <div><dt class="text-neutral-500">Database baseline / schema</dt><dd class="mt-1">{{ current.database_baseline || '—' }} / {{ current.schema_version || '—' }}</dd></div>
          <div><dt class="text-neutral-500">Repository</dt><dd class="mt-1">{{ current.repository || '—' }}</dd></div>
          <div><dt class="text-neutral-500">Last successful health check</dt><dd class="mt-1">{{ date(current.checked_at) }}</dd></div>
        </template>
      </dl>
      <p v-else-if="!catalog" class="text-sm text-neutral-500">{{ loading ? 'Loading deployment configuration…' : 'Deployment configuration could not be loaded. Check the catalog error above.' }}</p>
      <p v-else class="text-sm text-neutral-500">{{ warOnly ? 'No WAR deployment has been recorded by this tool yet. Your existing Tomcat may already be running. Select a catalog WAR below and use Deploy WAR to record a deployment.' : 'No environment has been prepared yet.' }}</p>
    </section>

    <section v-if="catalog" class="rounded-2xl border border-neutral-200 bg-white p-5">
      <h2 class="mb-4 text-lg font-semibold">{{ warOnly ? 'Deploy WAR to existing Tomcat' : 'Prepare environment' }}</h2>
      <form class="space-y-4" @submit.prevent="prepare">
        <fieldset :disabled="locked || !catalog.enabled || Boolean(catalogError)" class="grid gap-4 disabled:opacity-60 md:grid-cols-3">
          <label v-if="warOnly" class="space-y-2 text-sm md:col-span-3"><span class="font-medium">ConTrack WAR</span>
            <select v-model="warId" class="w-full rounded-lg border border-neutral-300 bg-white px-3 py-2.5" required>
              <option disabled value="">Select a WAR</option>
              <option v-for="item in catalog?.wars ?? []" :key="item.id" :value="item.id" :disabled="item.status !== 'available'">{{ item.displayName }}{{ item.filename ? ` — ${item.filename}` : '' }}{{ item.error ? ` (${item.error})` : '' }}</option>
            </select>
          </label>
          <label v-if="!warOnly" class="space-y-2 text-sm"><span class="font-medium">ConTrack Version</span>
            <select v-model="bundleId" class="w-full rounded-lg border border-neutral-300 bg-white px-3 py-2.5" required>
              <option disabled value="">Select a version</option>
              <option v-for="item in catalog?.versions ?? []" :key="item.bundleId" :value="item.bundleId" :disabled="item.status !== 'available'">{{ item.displayName }}{{ item.status !== 'available' ? ' (unavailable)' : '' }}</option>
            </select>
          </label>
          <label v-if="!warOnly" class="space-y-2 text-sm"><span class="font-medium">Database Profile</span>
            <select v-model="databaseId" class="w-full rounded-lg border border-neutral-300 bg-white px-3 py-2.5" required>
              <option disabled value="">Select a database profile</option>
              <option v-for="item in databases" :key="item.id" :value="item.id">{{ item.profile }} — {{ item.id }}</option>
            </select>
          </label>
          <label v-if="!warOnly" class="space-y-2 text-sm"><span class="font-medium">Repository</span>
            <select v-model="repositoryId" class="w-full rounded-lg border border-neutral-300 bg-white px-3 py-2.5" required>
              <option disabled value="">Select a repository</option>
              <option v-for="item in catalog?.repositories ?? []" :key="item.id" :value="item.id">{{ item.name }} ({{ item.type.toUpperCase() }})</option>
            </select>
          </label>
        </fieldset>
        <p v-if="catalog?.enabled && !(warOnly ? catalog.wars?.length : catalog.versions.length)" class="text-sm text-neutral-500">{{ warOnly ? 'The WAR catalog is empty. Ask an administrator to add a WAR and its manifest.' : 'The catalog is empty. Ask an administrator to add a version bundle and its artifacts.' }}</p>
        <ul v-if="catalog?.versions.some(item => item.error)" class="space-y-1 text-sm text-amber-800">
          <template v-for="item in catalog.versions" :key="item.bundleId"><li v-if="item.error">{{ item.displayName }}: {{ item.error }}</li></template>
        </ul>
        <p class="text-sm text-neutral-500">{{ warOnly ? `Copy the catalog WAR to ${selectedWar?.destination ?? 'the existing Tomcat webapps directory'}, preserving the filename declared in its manifest. Existing Tomcat configuration, database, repository and other application files are retained. This action does not restart Tomcat or check application compatibility.` : 'Each preparation creates a new working database from its baseline. A successful switch restarts the shared ConTrack server.' }}</p>
        <p v-if="actionError" role="alert" class="rounded-lg bg-red-50 p-3 text-sm text-red-800">{{ actionError }}</p>
        <div v-if="preview" role="status" class="rounded-lg bg-neutral-50 p-3 text-sm text-neutral-700">
          Compatible: {{ preview.war }} + {{ preview.database_baseline }} + {{ preview.repository }} (schema {{ preview.schema_version }}).
        </div>
        <p v-if="warPreview" role="status" class="rounded-lg bg-neutral-50 p-3 text-sm text-neutral-700">{{ warPreview }}</p>
        <div class="flex flex-wrap gap-3">
          <button type="button" class="rounded-lg border border-neutral-300 px-4 py-2.5 text-sm font-medium disabled:opacity-50" :disabled="!valid || locked" @click="validate">{{ validating ? 'Validating…' : 'Validate selection' }}</button>
          <button type="submit" class="rounded-lg bg-[#3E6AE1] px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50" :disabled="!valid || locked">{{ submitting ? (warOnly ? 'Deploying…' : 'Preparing…') : (warOnly ? 'Deploy WAR' : 'Prepare Environment') }}</button>
        </div>
      </form>
    </section>

    <section class="rounded-2xl border border-neutral-200 bg-white p-5">
      <h2 class="mb-4 text-lg font-semibold">Run history</h2>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm">
          <thead class="border-b border-neutral-200 text-neutral-500"><tr><th class="p-2">Started</th><th class="p-2">Version</th><th class="p-2">User</th><th class="p-2">Status</th><th class="p-2">Details</th></tr></thead>
          <tbody><tr v-for="run in runs" :key="run.run_id" class="border-b border-neutral-100"><td class="whitespace-nowrap p-2">{{ date(run.created_at) }}</td><td class="p-2">{{ run.display_name }}</td><td class="p-2">{{ run.actor }}</td><td class="p-2"><span class="rounded-full px-2 py-1 text-xs" :class="statusClass(run.status)">{{ run.status }}</span></td><td class="p-2"><button class="whitespace-nowrap text-[#3E6AE1] underline" @click="viewRun(run.run_id)">View run</button></td></tr></tbody>
        </table>
      </div>
      <p v-if="!runs.length" class="py-3 text-sm text-neutral-500">No preparation runs yet.</p>
      <div v-if="total > 10" class="mt-3 flex items-center justify-end gap-3 text-sm"><button :disabled="offset === 0 || historyLoading" class="disabled:opacity-40" @click="page(Math.max(0, offset - 10))">Previous</button><span>{{ offset + 1 }}–{{ Math.min(offset + 10, total) }} / {{ total }}</span><button :disabled="offset + 10 >= total || historyLoading" class="disabled:opacity-40" @click="page(offset + 10)">Next</button></div>
    </section>

    <section v-if="selectedRun" class="space-y-3 rounded-2xl border border-neutral-200 bg-white p-5" aria-live="polite">
      <div class="flex flex-wrap items-center justify-between gap-2"><h2 class="text-lg font-semibold">{{ selectedRun.display_name }}</h2><span class="rounded-full px-3 py-1 text-xs" :class="statusClass(selectedRun.status)">{{ selectedRun.status }}</span></div>
      <p class="break-all text-xs text-neutral-500">Run {{ selectedRun.run_id }}<template v-if="selectedRun.working_database"> · {{ selectedRun.working_database }}</template></p>
      <p v-if="selectedRun.operation_mode === 'deploy_war'" class="text-sm text-neutral-500">WAR deployment only. Application health and DB/repository compatibility are not checked.</p>
      <p v-if="selectedRun.error" role="alert" class="rounded-lg bg-red-50 p-3 text-sm text-red-800">{{ selectedRun.failed_step || 'Preparation' }}: {{ selectedRun.error.message }} ({{ selectedRun.error.code }})</p>
      <ol class="flex flex-wrap gap-2"><li v-for="(status, step) in selectedRun.steps" :key="step" class="rounded-lg px-3 py-2 text-xs" :class="statusClass(status)">{{ String(step).replaceAll('_', ' ') }}: {{ status }}</li></ol>
      <details v-if="selectedRun.recipe" class="text-sm"><summary class="cursor-pointer font-medium">Resolved artifacts</summary><dl class="mt-2 grid gap-2 rounded-lg bg-neutral-50 p-3 sm:grid-cols-2"><div><dt class="text-neutral-500">WAR</dt><dd>{{ selectedRun.recipe.war }}</dd></div><template v-if="selectedRun.operation_mode !== 'deploy_war'"><div><dt class="text-neutral-500">Database baseline</dt><dd>{{ selectedRun.recipe.database_baseline }}</dd></div><div><dt class="text-neutral-500">Repository</dt><dd>{{ selectedRun.recipe.repository }}</dd></div><div><dt class="text-neutral-500">Schema</dt><dd>{{ selectedRun.recipe.schema_version }}</dd></div></template><div v-else><dt class="text-neutral-500">Destination</dt><dd>{{ selectedRun.recipe.destination }}</dd></div></dl></details>
      <h3 class="text-sm font-medium">Run log</h3><pre class="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-neutral-900 p-4 text-xs leading-6 text-neutral-100">{{ selectedRun.log || 'Waiting for the first log entry…' }}</pre>
    </section>
  </main>
</template>
