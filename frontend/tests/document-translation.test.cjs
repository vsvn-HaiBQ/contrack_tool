const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const vue = require("vue");
const { parse, compileScript } = require("@vue/compiler-sfc");
const ts = require("typescript");

const filename = path.join(__dirname, "../src/modules/document_translation/DocumentTranslationPage.vue");
const script = compileScript(parse(fs.readFileSync(filename, "utf8"), { filename }).descriptor, { id: "translation-test" });
const javascript = ts.transpileModule(script.content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const flush = () => new Promise((resolve) => setImmediate(resolve));

async function mountPage(t, saved = {}, healthOverride, saveOverride) {
  const intervals = new Map();
  let nextTimer = 0;
  const sessionState = vue.reactive({ userSettings: { document_translation: saved } });
  const writes = [];
  const starts = [];
  const healthCalls = [];
  const api = {
    documentTranslation: {
      health: async (processor) => {
        healthCalls.push(processor);
        return healthOverride ? healthOverride(processor) : {
          ok: true, file_processor: processor, processor: { ok: true, message: "Ready" }, codex: { ok: true },
        };
      },
      models: async () => [{ slug: "test-model", supported_reasoning_levels: [] }],
      start: async (payload) => {
        starts.push(payload);
        return { job_id: "job-1", status: "running", logs: [] };
      },
      cancelJob: async () => ({ job_id: "job-1", status: "canceled", logs: [] }),
      getJob: async () => ({ job_id: "job-1", status: "canceled", logs: [] }),
    },
    validatePath: async (value) => ({ path: value, valid: true, is_file: true }),
  };
  const dependencies = {
    vue,
    "../../shared/LoadingCircle.vue": {},
    "../../shared/localServer": { localServerApi: api, localServerBase: "http://localhost:3219" },
    "../../shared/session": { sessionState },
    "../../shared/toast": { showToast: () => {} },
    "../audit/api": { auditApi: { record: async () => {} } },
    "../users/api": { usersApi: { updateMySettings: async (payload) => {
      writes.push(structuredClone(payload));
      if (saveOverride) await saveOverride(payload);
      return { document_translation: { ...sessionState.userSettings.document_translation, ...payload.document_translation } };
    } } },
  };
  const window = {
    setTimeout, clearTimeout,
    setInterval: (callback) => { intervals.set(++nextTimer, callback); return nextTimer; },
    clearInterval: (id) => intervals.delete(id),
  };
  const module = { exports: {} };
  vm.runInNewContext(javascript, {
    require: (name) => { assert.ok(name in dependencies, `Unexpected import ${name}`); return dependencies[name]; },
    module, exports: module.exports, window,
  });
  const component = module.exports.default;
  component.render = () => null;
  const renderer = vue.createRenderer({
    createComment: () => ({}), insert: () => {}, remove: () => {},
    parentNode: () => null, nextSibling: () => null,
  });
  const app = renderer.createApp(component);
  const instance = app.mount({});
  t.after(() => app.unmount());
  await flush();
  return { state: instance.$.setupState, writes, starts, healthCalls, sessionState, intervals };
}

test("Translate defaults to FileHandler and persists a changed processor", async (t) => {
  const page = await mountPage(t);
  assert.equal(page.state.form.fileProcessor, "filehandler");
  assert.equal(page.state.processorSupported, true);
  page.state.form.fileProcessor = "openxml";
  await flush();
  await page.state.saveTranslationSettings();
  assert.equal(page.writes.at(-1).document_translation.file_processor, "openxml");
  assert.equal(page.sessionState.userSettings.document_translation.file_processor, "openxml");
  assert.equal(page.healthCalls.at(-1), "openxml");
  const reloaded = await mountPage(t, page.sessionState.userSettings.document_translation);
  assert.equal(reloaded.state.form.fileProcessor, "openxml");
});

test("a late health response cannot overwrite the newly selected processor status", async (t) => {
  const pending = {};
  const page = await mountPage(t, {}, (processor) => new Promise((resolve) => { pending[processor] = resolve; }));
  page.state.form.fileProcessor = "openxml";
  await flush();
  pending.openxml({ ok: true, file_processor: "openxml", processor: { ok: true }, codex: { ok: true } });
  await flush();
  pending.filehandler({ ok: false, file_processor: "filehandler", processor: { ok: false, message: "Offline" }, codex: { ok: true } });
  await flush();
  assert.equal(page.state.fileProcessorOk, true);
  assert.equal(page.state.healthMessage, "Ready");
});

test("canceling a job settles the queue and releases the processor lock", async (t) => {
  const page = await mountPage(t);
  page.state.filesQueue = ["one.txt", "two.txt"];
  const running = page.state.startTranslation();
  await flush();
  assert.equal(page.state.queueRunning, true);
  assert.equal(page.state.running, true);
  assert.equal(page.starts[0].file_processor, "filehandler");
  await page.state.stopTranslationWorker();
  assert.equal(page.intervals.size, 1);
  await [...page.intervals.values()][0]();
  await running;
  assert.equal(page.starts.length, 1);
  assert.equal(page.state.queueRunning, false);
  assert.equal(page.state.running, false);
  assert.equal(page.intervals.size, 0);
});

test("old Node health responses block translation with an update message", async (t) => {
  const page = await mountPage(t, {}, async () => ({ ok: true, openxml: { ok: true }, codex: { ok: true } }));
  page.state.filesQueue = ["one.txt"];
  assert.equal(page.state.canStart, false);
  assert.match(page.state.healthMessage, /Update the local Node/);
  await page.state.startTranslation();
  assert.equal(page.starts.length, 0);
});

test("processor preference survives rejection of unrelated legacy settings", async (t) => {
  const page = await mountPage(t, {}, undefined, async (payload) => {
    if (payload.document_translation.direction === "en_to_vi") throw new Error("Legacy direction validation");
  });
  page.state.form.fromLang = "English";
  page.state.form.fileProcessor = "openxml";
  await flush();
  await page.state.saveTranslationSettings();
  assert.equal(page.sessionState.userSettings.document_translation.file_processor, "openxml");
  assert.ok(page.writes.some((payload) => Object.keys(payload.document_translation).length === 1));
});
