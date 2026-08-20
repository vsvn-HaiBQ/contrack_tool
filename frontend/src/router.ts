import { createRouter, createWebHistory } from "vue-router";
import LoginPage from "./modules/auth/LoginPage.vue";
import AppShell from "./modules/layout/AppShell.vue";
import SettingsPage from "./modules/settings/SettingsPage.vue";
import SyncTicketPage from "./modules/tickets/SyncTicketPage.vue";
import TicketDetailPage from "./modules/tickets/TicketDetailPage.vue";
import LogtimePage from "./modules/logtime/LogtimePage.vue";
import PullRequestPage from "./modules/pull_requests/PullRequestPage.vue";
import GitEolPage from "./modules/git_eol/GitEolPage.vue";
import BuildSourcePage from "./modules/build_source/BuildSourcePage.vue";
import ConfluencePreviewPage from "./modules/confluence_preview/ConfluencePreviewPage.vue";
import DocumentTranslationPage from "./modules/document_translation/DocumentTranslationPage.vue";
import NotesPage from "./modules/notes/NotesPage.vue";
import AuditPage from "./modules/audit/AuditPage.vue";
import { hasRequiredRedmineKeys, sessionReady, sessionState } from "./shared/session";
import { localServerApi } from "./shared/localServer";

const defaultMenuRoutes: Array<[string, string]> = [
  ["detail", "ticket_detail"],
  ["sync", "ticket_sync"],
  ["pull-requests", "pull_requests"],
  ["confluence-preview", "confluence_preview"],
  ["logtime", "logtime"],
  ["notes", "notes"],
  ["audit", "audit"],
  ["git-eol", "git_eol"],
  ["build-source", "build_source"],
  ["document-translation", "document_translation"],
];

function defaultRouteName() {
  if (!sessionState.me) {
    return "login";
  }
  if (!hasRequiredRedmineKeys()) return "settings";
  return defaultMenuRoutes.find(([, permission]) => hasPermission(permission))?.[0] ?? "settings";
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: LoginPage },
    {
      path: "/",
      component: AppShell,
      children: [
        {
          path: "",
          redirect: () => ({ name: defaultRouteName() })
        },
        { path: "settings", name: "settings", component: SettingsPage },
        { path: "tickets/sync", name: "sync", component: SyncTicketPage, meta: { permission: "ticket_sync" } },
        { path: "tickets/detail/:jpIssueId?", name: "detail", component: TicketDetailPage, meta: { permission: "ticket_detail" } },
        { path: "logtime", name: "logtime", component: LogtimePage, meta: { permission: "logtime" } },
        { path: "pull-requests", name: "pull-requests", component: PullRequestPage, meta: { permission: "pull_requests" } },
        { path: "git-eol", name: "git-eol", component: GitEolPage, meta: { keepAlive: true, permission: "git_eol" } },
        { path: "build-source", name: "build-source", component: BuildSourcePage, meta: { keepAlive: true, permission: "build_source" } },
        { path: "confluence-preview", name: "confluence-preview", component: ConfluencePreviewPage, meta: { keepAlive: true, permission: "confluence_preview" } },
        { path: "document-translation", name: "document-translation", component: DocumentTranslationPage, meta: { keepAlive: true, permission: "document_translation" } },
        { path: "notes", name: "notes", component: NotesPage, meta: { permission: "notes" } },
        { path: "audit", name: "audit", component: AuditPage, meta: { permission: "audit" } },
      ]
    }
  ]
});

const nodeOnlyRouteNames = new Set(["git-eol", "build-source", "document-translation"]);
function hasPermission(permission: unknown) {
  if (!permission || sessionState.me?.role === "admin") return true;
  return sessionState.me?.permissions?.includes(String(permission)) ?? false;
}

async function isNodeServerAvailable() {
  try {
    const health = await localServerApi.health();
    return Boolean(health.ok);
  } catch {
    return false;
  }
}

router.beforeEach(async (to) => {
  if (!sessionReady.value) {
    return true;
  }
  const authenticated = Boolean(sessionState.me);
  if (sessionState.needsSetup && to.name !== "login") {
    return { name: "login" };
  }
  if (!authenticated && to.name !== "login") {
    return { name: "login" };
  }
  if (
    authenticated &&
    !hasRequiredRedmineKeys() &&
    !["settings", "git-eol", "build-source", "confluence-preview", "document-translation", "login"].includes(String(to.name))
  ) {
    return { name: "settings" };
  }
  if (authenticated && to.name === "login") {
    return { name: defaultRouteName() };
  }
  if (authenticated && !hasPermission(to.meta.permission)) {
    return { name: defaultRouteName() };
  }
  if (authenticated && nodeOnlyRouteNames.has(String(to.name)) && !(await isNodeServerAvailable())) {
    return { name: defaultRouteName() };
  }
  return true;
});

export default router;
