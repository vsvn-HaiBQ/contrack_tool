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
