const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const { parse, compileScript } = require("@vue/compiler-sfc");
const ts = require("typescript");
const vue = require("vue");

function component(name, dependencies, inlineTemplate = true) {
  const filename = path.join(__dirname, "../src/modules/document_translation", `${name}.vue`);
  const parsed = parse(fs.readFileSync(filename, "utf8"), { filename });
  assert.deepEqual(parsed.errors, []);
  const script = compileScript(parsed.descriptor, { id: name, inlineTemplate });
  const code = ts.transpileModule(script.content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } }).outputText;
  const module = { exports: {} };
  new Function("require", "module", "exports", code)(id => {
    if (id === "vue") return vue;
    if (Object.hasOwn(dependencies, id)) return dependencies[id];
    throw new Error(`Unexpected dependency ${id}`);
  }, module, module.exports);
  return module.exports.default;
}

function node(type, text = "") { return { type, text, props: {}, children: [], parent: null }; }
const renderer = vue.createRenderer({
  createElement: type => node(type), createText: text => node("text", text), createComment: text => node("comment", text),
  setText: (target, text) => { target.text = text; },
  setElementText: (target, text) => { target.text = text; target.children = []; },
  patchProp: (target, key, _old, value) => { target.props[key] = value; },
  parentNode: target => target.parent,
  nextSibling: target => target.parent?.children[target.parent.children.indexOf(target) + 1] || null,
  insert(target, parent, anchor) {
    if (target.parent) target.parent.children.splice(target.parent.children.indexOf(target), 1);
    target.parent = parent;
    const index = parent.children.indexOf(anchor);
    parent.children.splice(index < 0 ? parent.children.length : index, 0, target);
  },
  remove(target) { target.parent?.children.splice(target.parent.children.indexOf(target), 1); },
});
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); await vue.nextTick(); };
const nodes = root => [root, ...root.children.flatMap(nodes)];
const content = root => root.type === "comment" ? "" : root.text + root.children.map(content).join("");
const find = (root, type, text) => nodes(root).find(item => item.type === type && (!text || content(item).includes(text)));

function mountOptions(t, filePath, api) {
  const options = vue.ref({ debug: false });
  const valid = vue.ref(false);
  const disabled = vue.ref(false);
  const Options = component("FileHandlerOptions", { "../../shared/localServer": { localServerApi: { documentTranslation: api } } });
  const root = node("root");
  const app = renderer.createApp({ render: () => vue.h(Options, {
    filePath, modelValue: options.value, disabled: disabled.value, timeoutSeconds: 120,
    "onUpdate:modelValue": value => { options.value = value; }, onValid: value => { valid.value = value; },
  }) });
  app.mount(root);
  t.after(() => app.unmount());
  return { root, options, valid, disabled };
}

test("Markdown shows preview/debug options and sends debug with the selected file", async (t) => {
  const requests = [];
  const { root, options, valid } = mountOptions(t, "C:/guide.md", {
    async extract(input) {
      requests.push(input);
      return { segment_count: 1, segments: ["Hello"], metadata: { status: "success", skipped: [], skipCount: { warning: 0, info: 0 } }, units: [{ index: 0, kind: "paragraph", location: { line: { start: 2, end: 2 } } }] };
    },
  });
  await flush();
  assert.equal(valid.value, true);
  assert.equal(find(root, "select"), undefined);
  find(root, "input").props.onChange({ target: { checked: true } });
  await flush();
  assert.equal(options.value.debug, true);
  await find(root, "button", "Preview text").props.onClick();
  await flush();
  assert.deepEqual(requests, [{ file_processor: "filehandler", filePath: "C:/guide.md", timeoutSeconds: 120, debug: true }]);
  assert.match(content(root), /Hello/);
  assert.match(content(root), /paragraph/);
  assert.match(content(root), /"start":2/);
});

test("Excel selection uses native IDs, includes hidden sheets explicitly, blocks empty selection", async (t) => {
  const { root, options, valid } = mountOptions(t, "C:/book.xlsx", {
    async sheets() { return [
      { sheetId: "7", name: "Sales", state: "visible", canImport: true },
      { sheetId: "42", name: "Internal", state: "veryHidden", canImport: true },
      { sheetId: "99", name: "Chart", state: "visible", canImport: false },
    ]; },
  });
  await flush();
  assert.equal(valid.value, true);
  assert.equal(options.value.sheetIds, undefined);
  find(root, "select").props.onChange({ target: { value: "custom" } });
  await flush();
  assert.deepEqual([...options.value.sheetIds], ["7"]);
  find(root, "button", "Select all").props.onClick();
  await flush();
  assert.deepEqual([...options.value.sheetIds], ["7", "42"]);
  find(root, "button", "Clear selection").props.onClick();
  await flush();
  assert.equal(valid.value, false);
  assert.equal(find(root, "button", "Preview text").props.disabled, true);
  find(root, "select").props.onChange({ target: { value: "visible" } });
  await flush();
  assert.equal(valid.value, true);
  assert.equal(options.value.sheetIds, undefined);
});

test("PowerPoint discovery failure blocks starting until a successful reload", async (t) => {
  let fail = true;
  const { root, valid, options } = mountOptions(t, "C:/slides.pptx", {
    async slides() {
      if (fail) throw new Error("API unavailable");
      return [{ slideId: "900", index: 1, title: "Overview", hidden: false }];
    },
  });
  await flush();
  assert.equal(valid.value, false);
  assert.match(content(root), /API unavailable/);
  fail = false;
  await find(root, "button", "Reload").props.onClick();
  await flush();
  assert.equal(valid.value, true);
  find(root, "select").props.onChange({ target: { value: "custom" } });
  await flush();
  assert.deepEqual([...options.value.slideIds], ["900"]);
});

test("translation page passes per-file debug and selection to the start request", async (t) => {
  const requests = [];
  const api = { documentTranslation: {
    models: async () => [],
    start: async input => { requests.push(input); return { job_id: "job1", status: "queued", logs: [] }; },
    getJob: async () => ({ job_id: "job1", status: "succeeded", logs: [], progress: {}, result: {} }),
  }, validatePath: async value => ({ valid: true, is_file: true, path: value }) };
  const Page = component("DocumentTranslationPage", {
    "../../shared/LoadingCircle.vue": { default: {} }, "./FileHandlerOptions.vue": { default: {} },
    "../../shared/localServer": { localServerApi: api, localServerBase: "http://local" },
    "../../shared/session": { sessionState: { userSettings: { document_translation: {} } } },
    "../../shared/toast": { showToast() {} },
    "../audit/api": { auditApi: { record: async () => {} } },
    "../users/api": { usersApi: { updateMySettings: async value => value } },
    "../settings/api": { settingsApi: {} },
  }, false);
  Page.render = () => null;
  const originalWindow = globalThis.window;
  globalThis.window = { setInterval: callback => setImmediate(callback), clearInterval: clearImmediate,
    setTimeout, clearTimeout };
  t.after(() => { globalThis.window = originalWindow; });
  const app = renderer.createApp(Page);
  app.mount(node("root"));
  const state = app._instance.setupState;
  await flush();
  state.fileProcessor = "filehandler";
  state.form.model = "test-model";
  state.fileOptions["C:/guide.md"] = { debug: true };
  await state.runOneFile("C:/guide.md", 1, 2);
  state.fileOptions["C:/book.xlsx"] = { debug: false, sheetIds: ["42"] };
  await state.runOneFile("C:/book.xlsx", 2, 2);
  assert.equal(requests[0].debug, true);
  assert.equal(requests[0].file_processor, "filehandler");
  assert.deepEqual([...requests[1].sheetIds], ["42"]);
  assert.equal(requests[1].debug, false);
  app.unmount();
});
