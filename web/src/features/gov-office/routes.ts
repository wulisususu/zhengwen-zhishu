import type { RouteRecordRaw } from "vue-router";

/** Routes for the government-office workbench, mounted under /gov. Pages are lazy-loaded. */
export const govOfficeRoutes: RouteRecordRaw[] = [
  { path: "/gov", component: () => import("./pages/GovHomePage.vue") },
  { path: "/gov/policy-qa", component: () => import("./pages/PolicyQaPage.vue") },
  { path: "/gov/draft/:id?", component: () => import("./pages/DraftWorkbenchPage.vue") },
  { path: "/gov/proofread", component: () => import("./pages/ProofreadPage.vue") },
  { path: "/gov/review-center", component: () => import("./pages/ReviewCenterPage.vue") },
  { path: "/gov/library", component: () => import("./pages/PolicyLibraryPage.vue"), meta: { module: "library" } },
  { path: "/gov/summary", component: () => import("./pages/SummaryPage.vue") },
  { path: "/gov/audit-log", component: () => import("./pages/PlannedModulePage.vue"), meta: { module: "audit-log" } },
];
