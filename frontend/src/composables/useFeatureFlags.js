import { ref } from 'vue'
import { getFeatureFlags } from '../api.js'

const flags = ref({ show_table: false, show_agents: false })
let loaded = false

export function useFeatureFlags() {
  async function load() {
    if (loaded) return
    try {
      const res = await getFeatureFlags()
      if (res.data) {
        flags.value = { ...res.data, show_agents: false }
      }
      loaded = true
    } catch (e) {
      console.warn('feature flags load failed', e)
    }
  }
  return { flags, load }
}

