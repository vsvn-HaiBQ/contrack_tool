import { createRouter, createWebHashHistory, createWebHistory } from "vue-router";
import LoginPage from "./modules/auth/LoginPage.vue";
import AppShell from "./modules/layout/AppShell.vue";
import SettingsPage from "./modules/settings/SettingsPage.vue";
import SyncTicketPage from "./modules/tickets/SyncTicketPage.vue";
import TicketDetailPage from "./modules/tickets/TicketDetailPage.vue";
import LogtimePage from "./modules/logtime/LogtimePage.vue";
import PullRequestPage from "./modules/pull_requests/PullRequestPage.vue";
import GitEolPage from "./modules/git_eol/GitEolPage.vue";
import BuildSourcePage from "./modules/build_source/BuildSourcePage.vue";
import UpdatePage from "./modules/updates/UpdatePage.vue";
import { hasRequiredRedmineKeys, sessionReady, sessionState } from "./shared/session";
import { isElectronClient } from "./shared/electron";

function defaultRouteName() {
  if (!sessionState.me) {
    return "login";
  }
  return hasRequiredRedmineKeys() ? "detail" : "settings";
}

const router = createRouter({
  history: isElectronClient() ? createWebHashHistory() : createWebHistory(),
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
        { path: "tickets/sync", name: "sync", component: SyncTicketPage },
        { path: "tickets/detail/:jpIssueId?", name: "detail", component: TicketDetailPage },
        { path: "logtime", name: "logtime", component: LogtimePage },
        { path: "pull-requests", name: "pull-requests", component: PullRequestPage },
        { path: "git-eol", name: "git-eol", component: GitEolPage },
        { path: "build-source", name: "build-source", component: BuildSourcePage },
        { path: "updates", name: "updates", component: UpdatePage },
      ]
    }
  ]
});

router.beforeEach((to) => {
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
    !["settings", "updates", "git-eol", "build-source", "login"].includes(String(to.name))
  ) {
    return { name: "settings" };
  }
  if (authenticated && to.name === "login") {
    return { name: defaultRouteName() };
  }
  return true;
});

export default router;
