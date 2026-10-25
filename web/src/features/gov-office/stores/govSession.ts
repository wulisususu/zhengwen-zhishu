import { defineStore } from "pinia";
import { getGovOfficeAdapter } from "../adapters";
import type { Actor, ActorRole, RuntimeStatus } from "../types";

const NAV_PREF_KEY = "gov-office-nav-collapsed";

function readNavPref(): boolean | null {
  try {
    const raw = localStorage.getItem(NAV_PREF_KEY);
    return raw === null ? null : raw === "1";
  } catch {
    return null;
  }
}

export const useGovSessionStore = defineStore("govSession", {
  state: () => ({
    runtime: null as RuntimeStatus | null,
    actor: null as Actor | null,
    adapterMode: getGovOfficeAdapter().mode,
    /** null = follow the page's automatic choice for the viewport. */
    navCollapsedPref: readNavPref(),
    loaded: false,
  }),
  getters: {
    isDemo: (state) => state.adapterMode === "mock",
    /**
     * The actor as seen from one workspace: drafting pages act as drafter,
     * the review center as reviewer, even if the account holds both roles.
     */
    actorAs: (state) => (role: ActorRole): Actor | null => {
      if (!state.actor) return null;
      return { ...state.actor, roles: state.actor.roles.includes(role) ? [role] : [] };
    },
  },
  actions: {
    async load() {
      if (this.loaded) return;
      const adapter = getGovOfficeAdapter();
      const [runtime, actor] = await Promise.all([adapter.getRuntimeStatus(), adapter.getCurrentActor()]);
      this.runtime = runtime;
      this.actor = actor;
      this.loaded = true;
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
