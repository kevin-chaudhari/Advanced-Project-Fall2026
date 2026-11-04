import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { checkHealth, loadDataset, sendQuery } from '../services/api'

/*
 * Application-wide diagnostic state shared by the Agent Dashboard and Diagnostic Chat.
 *
 * Every run stores the untouched /query response. Nothing here invents results: the dashboard
 * shows the latest run that came back from the backend, and the chat shows all of them.
 * Runs are cached in localStorage so a reload keeps the conversation; storage is best-effort.
 */

export const DATASETS = [
  { id: 'afrb', label: 'AFRB sensors', long: 'AFRB sensor diagnosis' },
  { id: 'failure_iq', label: 'FailureSensorIQ', long: 'FailureSensorIQ relevance' },
  { id: 'hydraulic', label: 'Hydraulic rig', long: 'Hydraulic rig diagnosis (real data)' },
]
/*
 * Every question is answered from the real and synthetic records together ("combined").
 * A dataset that has only one partition (the hydraulic rig is real-only) uses that one.
 */
const PREFERRED_MODE = 'combined'

const STORE_KEY = 'ida.runs.v1'
const PREFS_KEY = 'ida.prefs.v1'
const MAX_STORED = 12

const read = (k, fallback) => {
  try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : fallback } catch { return fallback }
}
const write = (k, v) => {
  try { localStorage.setItem(k, JSON.stringify(v)); return true } catch { return false }
}

const Ctx = createContext(null)
let seq = 0
const newId = () => `${Date.now().toString(36)}${(seq++).toString(36)}`

export function DiagnosticsProvider({ children }) {
  const prefs = read(PREFS_KEY, {})
  const [health, setHealth] = useState(null)
  const [dataset, setDataset] = useState(DATASETS.some((d) => d.id === prefs.dataset) ? prefs.dataset : 'afrb')
  // runs restored from storage that never finished are marked as interrupted, not left "running"
  const [runs, setRuns] = useState(() => read(STORE_KEY, []).map((r) => (r.result || r.error ? r : { ...r, error: 'Interrupted before the backend replied (page was reloaded).' })))
  const [uploading, setUploading] = useState(false)
  const [notice, setNotice] = useState(null)
  const pending = useRef(0)

  const refreshHealth = useCallback(() => checkHealth().then(setHealth).catch(() => setHealth({ offline: true })), [])
  useEffect(() => { refreshHealth() }, [refreshHealth])
  useEffect(() => { write(PREFS_KEY, { dataset }) }, [dataset])

  // persist finished runs; drop oldest until it fits the storage quota
  useEffect(() => {
    let keep = runs.filter((r) => r.result || r.error).slice(-MAX_STORED)
    while (keep.length && !write(STORE_KEY, keep)) keep = keep.slice(1)
  }, [runs])

  const modesFor = useCallback((ds) => health?.data_modes?.[ds] || [], [health])
  const modes = modesFor(dataset)
  const effectiveMode = modes.includes(PREFERRED_MODE) ? PREFERRED_MODE : modes[0] || 'real'
  const counts = health?.record_counts?.[dataset] || {}
  const loaded = Object.values(counts).some((n) => n > 0)
  const running = runs.some((r) => !r.result && !r.error)

  /** Same request as before: POST /query {question, dataset_type, data_mode, top_k} */
  const submit = useCallback(async (q) => {
    const question = (q || '').trim()
    if (!question || pending.current) return null
    const id = newId()
    const run = { id, question, dataset, mode: effectiveMode, startedAt: Date.now() }
    pending.current += 1
    setRuns((rs) => [...rs, run])
    try {
      const result = await sendQuery(question, dataset, effectiveMode)
      setRuns((rs) => rs.map((r) => (r.id === id ? { ...r, result, finishedAt: Date.now() } : r)))
    } catch (e) {
      const msg = e.response?.data?.detail || (e.code === 'ERR_NETWORK' ? 'Cannot reach the backend. Check that it is running on the configured API URL.' : e.message)
      setRuns((rs) => rs.map((r) => (r.id === id ? { ...r, error: String(msg), finishedAt: Date.now() } : r)))
    } finally { pending.current -= 1 }
    return id
  }, [dataset, effectiveMode])

  const removeRun = useCallback((id) => setRuns((rs) => rs.filter((r) => r.id !== id)), [])
  const clearRuns = useCallback(() => setRuns((rs) => rs.filter((r) => !r.result && !r.error)), [])

  /** Existing upload flow: POST /load-data?dataset_type=afrb with a CSV becomes a REAL partition. */
  const uploadCsv = useCallback(async (file) => {
    setUploading(true); setNotice(null)
    try {
      const res = await loadDataset('afrb', file)
      setNotice({ tone: 'ok', text: res?.message || 'CSV loaded as a REAL partition.' })
      await refreshHealth()
    } catch (e) {
      setNotice({ tone: 'error', text: e.response?.data?.detail || e.message })
    } finally { setUploading(false) }
  }, [refreshHealth])

  const latest = useMemo(() => [...runs].reverse().find((r) => r.result) || null, [runs])
  const lastRun = runs[runs.length - 1] || null

  const value = {
    health, refreshHealth, dataset, setDataset, modes, modesFor, effectiveMode, counts, loaded,
    runs, latest, lastRun, running, submit, removeRun, clearRuns, uploadCsv, uploading, notice, setNotice,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useDiagnostics() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useDiagnostics must be used inside <DiagnosticsProvider>')
  return v
}
