import { defineStore } from "pinia";
import { getGovOfficeAdapter, GovOfficeError } from "../adapters";
import type { Actor, RuntimeStatus } from "../types";

const NAV_PREF_KEY = "gov-office-nav-collapsed";

function readNavPref(): boolean | null {
  try {
    const raw = localStorage.getItem(NAV_PREF_KEY);
    return raw === null ? null : raw === "1";
  } catch {
    return null;
  }
}

let loading: Promise<void> | null = null;

export const useGovSessionStore = defineStore("govSession", {
  state: () => ({
    runtime: null as RuntimeStatus | null,
    actor: null as Actor | null,
    /** Demo identities offered by the mock adapter; empty with a real backend. */
    demoActors: [] as Actor[],
    adapterMode: getGovOfficeAdapter().mode,
    /** null = follow the page's automatic choice for the viewport. */
    navCollapsedPref: readNavPref(),
    loaded: false,
    error: "",
  }),
  getters: {
    isDemo: (state) => state.adapterMode === "mock",
    isDrafter: (state) => !!state.actor?.roles.includes("drafter"),
    isReviewer: (state) => !!state.actor?.roles.includes("reviewer"),
  },
  actions: {
    load() {
      if (this.loaded) return Promise.resolve();
      if (!loading) {
        const adapter = getGovOfficeAdapter();
        loading = Promise.all([
          adapter.getRuntimeStatus(),
          adapter.getCurrentActor(),
          adapter.listDemoActors ? adapter.listDemoActors() : Promise.resolve([] as Actor[]),
        ]).then(([runtime, actor, demoActors]) => {
          this.runtime = runtime;
          this.actor = actor;
          this.demoActors = demoActors;
          this.loaded = true;
          loading = null;
        });
      }
      return loading;
    },
    async switchDemoActor(account: string) {
      const adapter = getGovOfficeAdapter();
      if (!adapter.switchDemoActor) return;
      try {
        this.actor = await adapter.switchDemoActor(account);
        this.error = "";
      } catch (err) {
        this.error = err instanceof GovOfficeError ? err.message : "切换演示身份失败。";
      }
    },
    setNavCollapsed(collapsed: boolean) {
      this.navCollapsedPref = collapsed;
      try {
        localStorage.setItem(NAV_PREF_KEY, collapsed ? "1" : "0");
      } catch {
        // Storage can be unavailable (private mode); the preference just won't persist.
      }
    },
  },
});
