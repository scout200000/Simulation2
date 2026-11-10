import { createRouter, createWebHashHistory } from "vue-router";
import { isAuthenticated } from "../core/auth.js";
import PortalView from "../views/PortalView.vue";

const legacyConsolePaths = ["/v1", "/v2", "/v3", "/v4"];

const router = createRouter({
  history: createWebHashHistory(),
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition;
    return { top: 0 };
  },
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("../views/LoginView.vue")
    },
    {
      path: "/workspace",
      name: "workspace",
      component: () => import("../views/WorkspaceView.vue"),
      meta: { requiresAuth: true }
    },
    {
      path: "/settings",
      name: "settings",
      component: () => import("../views/SettingsView.vue"),
      meta: { requiresAuth: true }
    },
    {
      path: "/report",
      name: "report",
      component: () => import("../views/ReportView.vue"),
      meta: { requiresAuth: true }
    },
    {
      path: "/",
      name: "portal",
      component: PortalView
    },
    {
      path: "/console",
      name: "console",
      component: () => import("../views/ConsoleView.vue"),
      meta: { requiresAuth: true }
    },
    ...legacyConsolePaths.map((path) => ({
      path,
      redirect: (to) => ({
        name: "console",
        query: to.query,
        hash: to.hash
      })
    })),
    {
      path: "/history",
      name: "history",
      component: () => import("../views/HistoryView.vue"),
      meta: { requiresAuth: true }
    },
    {
      path: "/graph",
      name: "graph",
      component: () => import("../views/GraphView.vue"),
      meta: { requiresAuth: true }
    },
    {
      path: "/:pathMatch(.*)*",
      redirect: "/"
    }
  ]
});

router.beforeEach((to) => {
  const authenticated = isAuthenticated();

  if (to.name === "login" && authenticated) {
    return { name: "workspace" };
  }

  if (to.meta.requiresAuth && !authenticated) {
    return { name: "login" };
  }

  return true;
});

export default router;


