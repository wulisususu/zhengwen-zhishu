import { defineStore } from "pinia"
import { ref } from "vue"
import { getExternalModel, setExternalModel, testExternalModel, getLocalModels } from "../api.js"

export const useSettingsStore = defineStore("settings", () => {
  // --- external model ---
  const externalModel = ref({
    base_url: "",
    api_key: "",
    model: "",
    timeout_seconds: 240,
    source: "default",
    applied: false,
    agent_status: "unknown",
    last_verified: null,
  })

  const saving = ref(false)
  const saveError = ref("")

  const testing = ref(false)
  const testResult = ref(null)  // { connectivity: {ok, message}, tool_call: {ok, message}, all_passed }

  async function loadExternalModel() {
    try {
      const res = await getExternalModel()
      if (res.code === 0 && res.data) {
        externalModel.value = { ...externalModel.value, ...res.data }
      }
    } catch (e) {
      console.warn("loadExternalModel failed", e)
    }
  }

  async function runTest(config) {
    testing.value = true
    testResult.value = null
    saveError.value = ""
    try {
      const res = await testExternalModel(config)
      if (res.code === 0 && res.data) {
        testResult.value = res.data
      } else {
        saveError.value = res.message || "测试请求失败"
      }
    } catch (e) {
      const msg = e?.response?.data?.message || e?.message || "请求失败"
      saveError.value = msg
    } finally {
      testing.value = false
    }
  }

  async function saveExternalModel(config) {
    saving.value = true
    saveError.value = ""
    testResult.value = null  // clear test result after save
    try {
      const res = await setExternalModel(config)
      if (res.code === 0 && res.data) {
        externalModel.value = { ...externalModel.value, ...res.data }
      } else {
        saveError.value = res.message || "保存失败"
      }
    } catch (e) {
      const msg = e?.response?.data?.message || e?.message || "请求失败"
      saveError.value = msg
    } finally {
      saving.value = false
    }
  }

  // --- local models ---
  const localModels = ref([])

  async function loadLocalModels() {
    try {
      const res = await getLocalModels()
      if (res.code === 0 && res.data?.models) {
        localModels.value = res.data.models
      }
    } catch (e) {
      console.warn("loadLocalModels failed", e)
    }
  }

  return {
    externalModel,
    localModels,
    saving,
    saveError,
    testing,
    testResult,
    loadExternalModel,
    runTest,
    saveExternalModel,
    loadLocalModels,
  }
})
