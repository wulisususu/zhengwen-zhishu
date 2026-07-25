import { ref } from "vue";
import { getSessionToken } from "../../../stores/auth.js";

export interface StructuredWorkspaceSummary {
  workspace_id: string;
  name: string;
  source_type: string;
  status: string;
  canvas: string;
}

const workspaces = ref<StructuredWorkspaceSummary[]>([]);
const loaded = ref(false);
const loading = ref(false);
const loadError = ref<string | null>(null);

function resolveBaseUrl(): string {
  const configured = import.meta.env.VITE_PPT_MASTER_BASE_URL;
  return (configured || window.location.origin).replace(/\/+$/, "");
}

export function useStructuredWorkspaces() {
  async function load(force = false) {
    if (loading.value) return;
    if (loaded.value && !force) return;
    loading.value = true;
    loadError.value = null;
    try {
      const token = await getSessionToken();
      const response = await fetch(`${resolveBaseUrl()}/api/v1/ppt-master/workspaces`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        if (response.status === 403 || response.status === 401) {
          workspaces.value = [];
          loaded.value = true;
          return;
        }
        throw new Error(`workspace list failed: ${response.status}`);
      }
      const body = await response.json();
      workspaces.value = Array.isArray(body?.data) ? body.data : [];
      loaded.value = true;
    } catch (cause) {
      loadError.value = cause instanceof Error ? cause.message : "workspace load failed";
      workspaces.value = [];
    } finally {
      loading.value = false;
    }
  }

  return { workspaces, loaded, loading, loadError, load };
}
