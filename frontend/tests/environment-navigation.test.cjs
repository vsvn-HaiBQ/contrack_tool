const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const { parse, compileScript } = require("@vue/compiler-sfc");
const ts = require("typescript");
const vue = require("vue");

function loadShell(me, online) {
  const filename = path.join(__dirname, "../src/modules/layout/AppShell.vue");
  const parsed = parse(fs.readFileSync(filename, "utf8"), { filename });
  assert.deepEqual(parsed.errors, []);
  const script = compileScript(parsed.descriptor, { id: "navigation-regression" });
  const code = ts.transpileModule(script.content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 } }).outputText;
  const module = { exports: {} };
  const sessionState = vue.reactive({ me });
  const mocks = {
    "vue": { ...vue, onMounted() {}, onBeforeUnmount() {} },
    "vue-router": { useRouter: () => ({ currentRoute: { value: { path: "/settings" } } }) },
    "../../shared/session": { sessionState },
  };
  new Function("require", "module", "exports", code)(id => mocks[id] ?? {}, module, module.exports);
  const shell = module.exports.default.setup({}, { expose() {} });
  shell.nodeServerOnline.value = online;
  return { shell, sessionState };
}

test("admin sees the environment menu even when the local Node server is offline", () => {
  const { shell } = loadShell({ role: "admin", permissions: [] }, false);
  assert.ok(shell.visibleTabs.value.some(tab => tab.key === "/contrack-environments"));
  assert.ok(!shell.visibleTabs.value.some(tab => tab.key === "/build-source"));
});

test("a user granted the environment permission sees its menu without other menu permissions", () => {
  const { shell } = loadShell({ role: "dev", permissions: ["contrack_environments"] }, false);
  assert.deepEqual(shell.visibleTabs.value.map(tab => tab.key), ["/contrack-environments"]);
});

test("environment navigation still respects role grants and reacts when session permissions change", () => {
  const { shell, sessionState } = loadShell({ role: "qa", permissions: ["ticket_detail"] }, true);
  assert.ok(!shell.visibleTabs.value.some(tab => tab.key === "/contrack-environments"));
  sessionState.me.permissions.push("contrack_environments");
  assert.ok(shell.visibleTabs.value.some(tab => tab.key === "/contrack-environments"));
});
