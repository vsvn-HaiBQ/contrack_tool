import { createRouter, createWebHistory } from "vue-router";
import LoginPage from "./modules/auth/LoginPage.vue";
import AppShell from "./modules/layout/AppShell.vue";
import SettingsPage from "./modules/settings/SettingsPage.vue";
import SyncTicketPage from "./modules/tickets/SyncTicketPage.vue";
import TicketDetailPage from "./modules/tickets/TicketDetailPage.vue";
import LogtimePage from "./modules/logtime/LogtimePage.vue";
import PullRequestPage from "./modules/pull_requests/PullRequestPage.vue";
import { hasRequiredRedmineKeys, sessionReady, sessionState } from "./shared/session";

function defaultRouteName() {
  if (!sessionState.me) {
    return "login";
  }
  return hasRequiredRedmineKeys() ? "detail" : "settings";
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
        { path: "tickets/sync", name: "sync", component: SyncTicketPage },
        { path: "tickets/detail", name: "detail", component: TicketDetailPage },
        { path: "logtime", name: "logtime", component: LogtimePage },
        { path: "pull-requests", name: "pull-requests", component: PullRequestPage }
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
  if (authenticated && !hasRequiredRedmineKeys() && to.name !== "settings" && to.name !== "login") {
    return { name: "settings" };
  }
  if (authenticated && to.name === "login") {
    return { name: defaultRouteName() };
  }
  return true;
});

export default router;
