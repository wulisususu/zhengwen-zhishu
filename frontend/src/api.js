import axios from 'axios'
import { clearStoredSession, getSessionToken, syncAuthCookie } from './stores/auth.js'

const api = axios.create({ baseURL: '/api/v1' })

export function isUnauthorizedError(error) {
  return error?.response?.status === 401 || error?.status === 401
}

export function handleUnauthorized() {
  clearStoredSession()
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('mqw-auth-expired'))
  }
}

api.interceptors.request.use((config) => {
  const token = getSessionToken()
  if (token) {
    config.headers.Authorization = 'Bearer ' + token
    syncAuthCookie(token)
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (isUnauthorizedError(error)) handleUnauthorized()
    return Promise.reject(error)
  },
)

export async function getKnowledgeStatus() {
  const { data } = await api.get('/knowledge/status')
  return data
}

export async function uploadKnowledgeDocument(file) {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await api.post('/knowledge/documents', formData)
  return data
}

export async function listKnowledgeDocuments() {
  const { data } = await api.get('/knowledge/documents')
  return data
}

export async function deleteKnowledgeDocument(docId) {
  const { data } = await api.delete('/knowledge/documents/' + docId)
  return data
}

export function getKnowledgeDocumentFileUrl(docId) {
  return api.defaults.baseURL + '/knowledge/documents/' + docId + '/file'
}

export async function searchKnowledge(query, topK = 5) {
  const { data } = await api.post('/knowledge/search', { query, top_k: topK })
  return data
}

export async function getFeatureFlags() {
  const { data } = await api.get('/settings/feature-flags')
  return data
}

export default api

// --- 35B external model config ---

export async function getExternalModel() {
  const { data } = await api.get("/settings/external-model")
  return data
}

export async function setExternalModel(config) {
  const { data } = await api.put("/settings/external-model", config)
  return data
}

export async function testExternalModel(config) {
  const { data } = await api.post("/settings/external-model/test", config)
  return data
}

export async function getLocalModels() {
  const { data } = await api.get("/settings/local-models")
  return data
}
