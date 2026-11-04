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

/* AgentTrace — every view below reads persisted trace rows from the backend (never sample data). */
export const listTraces = async ({ limit = 50, offset = 0, dataset = null, status = null } = {}) =>
  (await api.get('/traces', { params: { limit, offset, ...(dataset ? { dataset } : {}), ...(status ? { status } : {}) } })).data
export const getTrace = async (id) => (await api.get(`/traces/${id}`)).data
export const getTraceMessages = async (id) => (await api.get(`/traces/${id}/messages`)).data
export const getTraceTimeline = async (id) => (await api.get(`/traces/${id}/timeline`)).data
export const getTraceEvidence = async (id) => (await api.get(`/traces/${id}/evidence`)).data
export const getTraceHypotheses = async (id) => (await api.get(`/traces/${id}/hypotheses`)).data
export const getTraceAgents = async (id, includePrompts = false) =>
  (await api.get(`/traces/${id}/agents`, { params: { include_prompts: includePrompts } })).data
export const getTraceEvents = async (id, { limit = 500, offset = 0, eventType = null } = {}) =>
  (await api.get(`/traces/${id}/events`, { params: { limit, offset, ...(eventType ? { event_type: eventType } : {}) } })).data

export const getTraceLlmCalls = async (id, includeResponses = true) =>
  (await api.get(`/traces/${id}/llm-calls`, { params: { include_responses: includeResponses } })).data
export const getTraceScores = async (id) => (await api.get(`/traces/${id}/scores`)).data

/** Direct download URL for one trace: json | transcript | messages_csv | events_csv | executions_csv | evidence_csv
 *  | llm_calls_csv | scores_csv */
export const traceExportUrl = (id, format = 'json') => `${BASE_URL}/traces/${id}/export?format=${format}`
export const traceArchiveUrl = (limit = 20) => `${BASE_URL}/traces/export/archive?limit=${limit}&formats=json,transcript,messages_csv,llm_calls_csv,scores_csv,evidence_csv`

export default api
