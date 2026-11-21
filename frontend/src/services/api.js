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
export const listTraces = async ({ limit = 50, offset = 0, dataset = null, status = null, origin = 'live' } = {}) =>
  (await api.get('/traces', { params: { limit, offset, origin, ...(dataset ? { dataset } : {}), ...(status ? { status } : {}) } })).data
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

/* Experiment Lab — controlled what-if experiments; every run is a normal diagnosis with its own trace. */
export const planExperiment = async (question, datasetType = 'afrb', dataMode = 'combined', points = 4) =>
  (await api.post('/experiments/plan', { question, dataset_type: datasetType, data_mode: dataMode, points })).data
export const createExperiment = async (body) => (await api.post('/experiments', body)).data
export const listExperiments = async (limit = 50, filters = {}) => (await api.get('/experiments', { params: { limit, ...filters } })).data
/** light=true: status and progress only (cheap enough to poll) */
export const getExperiment = async (id, light = false) => (await api.get(`/experiments/${id}`, { params: light ? { light: true } : {} })).data
export const compareExperimentRuns = async (id, a, b) => (await api.get(`/experiments/${id}/compare`, { params: { a, b } })).data
export const cancelExperiment = async (id) => (await api.post(`/experiments/${id}/cancel`)).data
export const resumeExperiment = async (id) => (await api.post(`/experiments/${id}/resume`)).data
export const deleteExperiment = async (id) => (await api.delete(`/experiments/${id}`)).data

/** Link that opens the Lab with a question (and the trace it came from) already filled in. */
export const whatIfLink = (question, { traceId = null, dataset = null } = {}) => {
  const p = new URLSearchParams({ q: question || '' })
  if (traceId) p.set('trace', traceId)
  if (dataset) p.set('dataset', dataset)
  return `/lab/new?${p.toString()}`
}

/* Trace insights: step breakdown + signals for one trace, and an N-trace comparison (first id = reference) */
export const getTraceInsights = async (id) => (await api.get(`/trace-insights/${id}`)).data
export const traceReportUrl = (id) => `${BASE_URL}/trace-insights/${id}/report`
export const getFleet = async ({ origin = 'live', dataset = null, limit = 500 } = {}) =>
  (await api.get('/trace-insights/fleet/summary', { params: { origin, limit, ...(dataset ? { dataset } : {}) } })).data
export const compareTraces = async (ids, labels = null) =>
  (await api.get('/trace-insights/compare', { params: { ids: ids.join(','), ...(labels ? { labels: labels.join('|') } : {}) } })).data

/* Human reviewer sign-off on a diagnosis (approve | reject | change), logged per trace */
export const getReviews = async (traceId) => (await api.get(`/reviews/${traceId}`)).data
export const addReview = async (traceId, body) => (await api.post(`/reviews/${traceId}`, body)).data

/** Poll until an experiment stops running; retries on network errors with backoff. Returns a cancel function. */
export function pollExperiment(id, onUpdate, onDone) {
  let stop = false, timer, wait = 1500
  const tick = async () => {
    if (stop) return
    try {
      const e = await getExperiment(id, true)
      wait = 1500
      if (stop) return
      onUpdate?.(e)
      if (e.status === 'running' || e.status === 'queued') timer = setTimeout(tick, wait)
      else { const full = await getExperiment(id); if (!stop) onDone?.(full) }
    } catch {
      wait = Math.min(wait * 2, 15000)
      timer = setTimeout(tick, wait)
    }
  }
  tick()
  return () => { stop = true; clearTimeout(timer) }
}

export default api
