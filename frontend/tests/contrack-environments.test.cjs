const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const { parse, compileScript } = require("@vue/compiler-sfc");
const ts = require("typescript");
const vue = require("vue");

const renderer = vue.createRenderer({
  createElement: type => ({ type }), createText: text => ({ text }), createComment: () => ({}),
  setText() {}, setElementText() {}, patchProp() {}, insert() {}, remove() {}, parentNode() {}, nextSibling() {},
});
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); await vue.nextTick(); };

function mount(t, overrides = {}) {
  const catalog = {
    enabled: true, busy: false,
    versions: [
      { bundleId: "CT-520", displayName: "ConTrack 5.2.0", databaseSchema: "5.2.0", status: "available", defaultDatabaseId: "DB-520", defaultRepositoryId: "SVN-1" },
      { bundleId: "CT-510", displayName: "ConTrack 5.1.0", databaseSchema: "5.1.0", status: "available", defaultDatabaseId: "DB-510", defaultRepositoryId: "SVN-1" },
    ],
    databases: [{ id: "DB-520", schema: "5.2.0", profile: "standard" }, { id: "DB-510", schema: "5.1.0", profile: "standard" }],
    repositories: [{ id: "SVN-1", type: "svn", name: "SVN Standard" }],
  };
  const run = { run_id: "20261117T100000-aaaaaaaaaaaa", status: "QUEUED", steps: {}, working_database: "ct_new" };
  const calls = [];
  let serverBusy = false;
  const api = {
    catalog: async () => catalog,
    current: async () => ({ environment: null, busy: serverBusy }),
    runs: async () => ({ items: [], total: 0 }),
    run: async () => run,
    validate: async payload => { calls.push(["validate", payload]); return { valid: true, recipe: { war: "WAR-520" } }; },
    prepare: async payload => { calls.push(["prepare", payload]); serverBusy = true; return run; },
    ...overrides,
  };
  const filename = path.join(__dirname, "../src/modules/contrack_environments/ConTrackEnvironmentsPage.vue");
  const parsed = parse(fs.readFileSync(filename, "utf8"), { filename });
  assert.deepEqual(parsed.errors, []);
  const script = compileScript(parsed.descriptor, { id: "environment-page" });
  const code = ts.transpileModule(script.content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } }).outputText;
  const module = { exports: {} };
  new Function("require", "module", "exports", code)(id => {
    if (id === "vue") return vue;
    if (id === "./api") return { environmentsApi: api };
    throw new Error(`Unexpected dependency ${id}`);
  }, module, module.exports);
  let state;
  // Mount the real setup in a harness to exercise lifecycle/watchers without a DOM dependency.
  const app = renderer.createApp({ setup() { state = module.exports.default.setup({}, { expose() {} }); return () => null; } });
  app.mount({});
  t.after(() => app.unmount());
  return { state, calls, catalog };
}

test("environment page selects bundle defaults and only matching database schemas", async t => {
  const { state } = mount(t);
  await flush();
  assert.equal(state.bundleId.value, "CT-520");
  assert.equal(state.databaseId.value, "DB-520");
  assert.equal(state.repositoryId.value, "SVN-1");
  assert.deepEqual(state.databases.value.map(item => item.id), ["DB-520"]);
  state.bundleId.value = "CT-510";
  await flush();
  assert.equal(state.databaseId.value, "DB-510");
  assert.deepEqual(state.databases.value.map(item => item.id), ["DB-510"]);
});

test("prepare sends only catalog IDs and blocks duplicate clicks while the request is pending", async t => {
  let finish;
  const requests = [];
  const { state } = mount(t, { prepare: payload => { requests.push(payload); return new Promise(resolve => { finish = resolve; }); } });
  await flush();
  const first = state.prepare();
  await state.prepare();
  assert.equal(requests.length, 1);
  assert.equal(state.locked.value, true);
  assert.deepEqual(requests[0], { bundle_id: "CT-520", database_profile_id: "DB-520", repository_profile_id: "SVN-1" });
  finish({ run_id: "20261117T100000-aaaaaaaaaaaa", status: "QUEUED", steps: {} });
  await first;
});

test("busy server and incompatible database selections block preparation", async t => {
  const { state, calls } = mount(t, { current: async () => ({ environment: null, busy: true }) });
  await flush();
  await state.prepare();
  assert.equal(calls.length, 0);
  state.busy.value = false;
  state.databaseId.value = "DB-510";
  await flush();
  assert.equal(state.valid.value, false);
  await state.prepare();
  assert.equal(calls.length, 0);
});

test("prepare error is visible and unlocks the form for retry", async t => {
  const { state } = mount(t, { prepare: async () => { throw new Error("Baseline restore is not configured"); } });
  await flush();
  await state.prepare();
  assert.match(state.actionError.value, /Baseline restore/);
  assert.equal(state.submitting.value, false);
  assert.equal(state.locked.value, false);
});

test("validation does not prepare and changing selection invalidates its preview", async t => {
  const { state, calls } = mount(t);
  await flush();
  await state.validate();
  assert.equal(calls[0][0], "validate");
  assert.equal(calls.length, 1);
  assert.equal(state.preview.value.war, "WAR-520");
  state.bundleId.value = "CT-510";
  await flush();
  assert.equal(state.preview.value, null);
});

test("disabled manager prevents requests and keeps an empty catalog usable", async t => {
  const { state, calls } = mount(t, { catalog: async () => ({ enabled: false, busy: false, versions: [], databases: [], repositories: [], message: "Not configured" }) });
  await flush();
  assert.equal(state.valid.value, false);
  await state.prepare();
  assert.equal(calls.length, 0);
});

function warCatalog() {
  return { enabled: true, operation_mode: "deploy_war", busy: false,
    versions: [], databases: [], repositories: [],
    wars: [{ id: "WAR-520", displayName: "ConTrack 5.2.0", status: "available", schema: "5.2.0", error: null }] };
}

function switchCatalog() {
  return { ...warCatalog(), operation_mode: "switch_version", configuration_error: null,
    wars: [
      { id: "WAR-520", displayName: "5.2.0", schema: "5.2.0", status: "available" },
      { id: "WAR-521", displayName: "5.2.1", schema: "5.2.1", status: "available" },
    ],
    databases: [
      { id: "DB-520", schema: "5.2.0", profile: "standard" },
      { id: "DB-521", schema: "5.2.1", profile: "standard" },
    ] };
}

test("host switch selects a compatible baseline without requiring a version bundle or repository", async t => {
  const { state } = mount(t, { catalog: async () => switchCatalog() });
  await flush();
  assert.equal(state.switchMode.value, true);
  assert.equal(state.warId.value, "WAR-520");
  assert.equal(state.databaseId.value, "DB-520");
  assert.equal(state.repositoryId.value, "");
  assert.equal(state.valid.value, true);
  state.warId.value = "WAR-521";
  await flush();
  assert.equal(state.databaseId.value, "DB-521");
  assert.deepEqual(state.databases.value.map(item => item.id), ["DB-521"]);
});

test("host switch validates and submits only selected IDs and prevents duplicate requests", async t => {
  const calls = [];
  let finish;
  const { state } = mount(t, {
    catalog: async () => switchCatalog(),
    validateSwitch: async (...ids) => { calls.push(["validateSwitch", ...ids]); return { recipe: { war: ids[0], database_baseline: ids[1] } }; },
    switchVersion: (...ids) => { calls.push(["switchVersion", ...ids]); return new Promise(resolve => { finish = resolve; }); },
    prepare: () => assert.fail("Full preparation must not run"),
    deployWar: () => assert.fail("Copy-only must not run"),
  });
  await flush();
  await state.validate();
  assert.equal(state.preview.value.database_baseline, "DB-520");
  const pending = state.prepare();
  await state.prepare();
  assert.deepEqual(calls, [["validateSwitch", "WAR-520", "DB-520"], ["switchVersion", "WAR-520", "DB-520"]]);
  finish({ run_id: "20261123T100000-aaaaaaaaaaaa", status: "QUEUED", operation_mode: "switch_version", steps: {} });
  await pending;
});

test("missing baseline or host SSH configuration blocks a host switch", async t => {
  const data = switchCatalog();
  data.databases = [];
  const { state } = mount(t, { catalog: async () => data });
  await flush();
  assert.equal(state.valid.value, false);
  data.databases = [{ id: "DB-520", schema: "5.2.0", profile: "standard" }];
  data.configuration_error = "Mount SSH key and verified known_hosts";
  await state.refresh(true);
  state.databaseId.value = "DB-520";
  await flush();
  assert.equal(state.valid.value, false);
});

test("changing a host switch baseline invalidates the validation preview", async t => {
  const { state } = mount(t, { catalog: async () => switchCatalog(),
    validateSwitch: async () => ({ recipe: { war: "WAR-520", database_baseline: "DB-520" } }) });
  await flush();
  await state.validate();
  assert.ok(state.preview.value);
  state.databaseId.value = "DB-521";
  await flush();
  assert.equal(state.preview.value, null);
  assert.equal(state.valid.value, false);
});

test("existing Tomcat mode selects WAR without requiring database or repository profiles", async t => {
  const { state } = mount(t, { catalog: async () => warCatalog() });
  await flush();
  assert.equal(state.warOnly.value, true);
  assert.equal(state.warId.value, "WAR-520");
  assert.equal(state.valid.value, true);
  assert.equal(state.databaseId.value, "");
  assert.equal(state.repositoryId.value, "");
});

test("WAR preview and selected catalog entry preserve the app.war destination", async t => {
  const data = warCatalog();
  data.wars[0].filename = "app.war";
  data.wars[0].destination = "runtime/server/webapps/app.war";
  const { state } = mount(t, {
    catalog: async () => data,
    validateWar: async warId => ({ valid: true, war_id: warId, destination: "runtime/server/webapps/app.war" }),
  });
  await flush();
  assert.equal(state.selectedWar.value.filename, "app.war");
  assert.equal(state.selectedWar.value.destination, "runtime/server/webapps/app.war");
  await state.validate();
  assert.match(state.warPreview.value, /webapps\/app\.war/);
});

test("existing Tomcat mode validates and deploys only the selected WAR and blocks duplicate clicks", async t => {
  const calls = [];
  let finish;
  const { state } = mount(t, {
    catalog: async () => warCatalog(),
    validateWar: async warId => { calls.push(["validateWar", warId]); return { valid: true, war_id: warId, destination: "runtime/server/webapps/contrack.war" }; },
    deployWar: warId => { calls.push(["deployWar", warId]); return new Promise(resolve => { finish = resolve; }); },
    validate: () => assert.fail("Full environment validation must not run in WAR mode"),
    prepare: () => assert.fail("Working DB preparation must not run in WAR mode"),
  });
  await flush();
  await state.validate();
  assert.match(state.warPreview.value, /WAR-520/);
  const pending = state.prepare();
  await state.prepare();
  assert.deepEqual(calls, [["validateWar", "WAR-520"], ["deployWar", "WAR-520"]]);
  finish({ run_id: "20261117T100000-aaaaaaaaaaaa", status: "DEPLOYED", operation_mode: "deploy_war", steps: {} });
  await pending;
});

test("catalog errors remain visible when the next background refresh succeeds for current and history", async t => {
  const { state } = mount(t, { catalog: async () => { throw new Error("Invalid wars manifest: 5.2.0/manifest.yaml"); } });
  await flush();
  await state.refresh();
  assert.match(state.catalogError.value, /Invalid wars manifest/);
  assert.equal(state.valid.value, false);
});

test("background refresh retries failed catalog and enables WAR deployment after the manifest is fixed", async t => {
  let fixed = false;
  let catalogCalls = 0;
  const { state } = mount(t, { catalog: async () => {
    ++catalogCalls;
    if (!fixed) throw new Error("Invalid wars manifest");
    return warCatalog();
  } });
  await flush();
  assert.equal(state.catalog.value, null);
  fixed = true;
  await state.refresh();
  await flush();
  assert.ok(catalogCalls >= 2);
  assert.equal(state.warOnly.value, true);
  assert.equal(state.valid.value, true);
  assert.equal(state.warId.value, "WAR-520");
  assert.equal(state.catalogError.value, "");
});

test("history request failure does not discard a valid catalog and disable WAR selection", async t => {
  const { state } = mount(t, {
    catalog: async () => warCatalog(),
    runs: async () => { throw new Error("Run history unavailable"); },
  });
  await flush();
  assert.equal(state.warOnly.value, true);
  assert.equal(state.valid.value, true);
  assert.match(state.error.value, /Run history unavailable/);
});

test("a later catalog error blocks stale WAR actions until a successful retry", async t => {
  let broken = false;
  const { state } = mount(t, { catalog: async () => {
    if (broken) throw new Error("Manifest changed and is invalid");
    return warCatalog();
  } });
  await flush();
  assert.equal(state.valid.value, true);
  broken = true;
  await state.refresh(true);
  assert.equal(state.valid.value, false);
  assert.match(state.catalogError.value, /Manifest changed/);
  broken = false;
  await state.refresh();
  assert.equal(state.valid.value, true);
  assert.equal(state.catalogError.value, "");
});

test("manual Refresh queues a catalog reload when a background request is already in flight", async t => {
  let slow = false;
  let finishCurrent;
  let catalogCalls = 0;
  const { state } = mount(t, {
    catalog: async () => { ++catalogCalls; return warCatalog(); },
    current: () => {
      if (slow) {
        slow = false;
        return new Promise(resolve => { finishCurrent = resolve; });
      }
      return Promise.resolve({ environment: null, busy: false });
    },
  });
  await flush();
  slow = true;
  const pending = state.refresh();
  await state.refresh(true);
  finishCurrent({ environment: null, busy: false });
  await pending;
  await flush();
  assert.equal(catalogCalls, 2);
  assert.equal(state.valid.value, true);
});
