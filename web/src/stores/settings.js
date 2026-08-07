import { defineStore } from "pinia"
import { ref } from "vue"
import { getExternalModel, setExternalModel, testExternalModel, getLocalModels } from "../api.js"

export const useSettingsStore = defineStore("settings", () => {
  const externalModel = ref({ base_url:"", api_key:"", api_key_configured:false, model:"", timeout_seconds:600, context_window:262144, max_tokens:32768, source:"project .env", applied:false, agent_status:"unknown" })
  const saving = ref(false), testing = ref(false), saveError = ref(""), testResult = ref(null)
  async function loadExternalModel() { try { const r=await getExternalModel(); if(r.code===0&&r.data) externalModel.value={...externalModel.value,...r.data} } catch(e){ console.warn("loadExternalModel failed",e) } }
  async function runTest(config) { testing.value=true; testResult.value=null; saveError.value=""; try { const r=await testExternalModel(config); if(r.code===0&&r.data) testResult.value=r.data; else saveError.value=r.message||"测试请求失败" } catch(e){ saveError.value=e?.response?.data?.message||e?.message||"请求失败" } finally { testing.value=false } }
  async function saveExternalModel(config) { saving.value=true; saveError.value=""; try { const r=await setExternalModel(config); if(r.code===0&&r.data) externalModel.value={...externalModel.value,...r.data}; else saveError.value=r.message||"保存失败" } catch(e){ saveError.value=e?.response?.data?.message||e?.message||"请求失败" } finally { saving.value=false } }
  const localModels=ref([])
  async function loadLocalModels(){ try { const r=await getLocalModels(); if(r.code===0&&r.data?.models)localModels.value=r.data.models }catch(e){console.warn("loadLocalModels failed",e)} }
  return { externalModel,localModels,saving,testing,saveError,testResult,loadExternalModel,runTest,saveExternalModel,loadLocalModels }
})
