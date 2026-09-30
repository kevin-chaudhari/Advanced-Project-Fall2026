import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const api = axios.create({ baseURL: BASE_URL, timeout: 180000, headers: { 'Content-Type': 'application/json' } })

export const checkHealth = async () => (await api.get('/health')).data

export const loadDataset = async (datasetType, file = null) => {
  if (file) {
    const form = new FormData()
    form.append('file', file)
    return (await api.post(`/load-data?dataset_type=${datasetType}`, form, { headers: { 'Content-Type': 'multipart/form-data' } })).data
  }
  return (await api.post(`/load-data?dataset_type=${datasetType}`)).data
}

/** @param {'real'|'synthetic'|'combined'} dataMode */
export const sendQuery = async (question, datasetType, dataMode = 'combined', topK = 8) =>
  (await api.post('/query', { question, dataset_type: datasetType, data_mode: dataMode, top_k: topK })).data

export const getDatasetSummary = async (dataset = 'afrb') => (await api.get('/datasets/summary', { params: { dataset } })).data
export const getEvaluation = async () => (await api.get('/evaluation/results')).data
export const getAnalyses = async (limit = 50, dataset = null) =>
  (await api.get('/analyses', { params: dataset ? { limit, dataset } : { limit } })).data
export const getAgentReport = async (limit = 200, dataset = null) =>
  (await api.get('/analyses/agent-report', { params: dataset ? { limit, dataset } : { limit } })).data

export default api
