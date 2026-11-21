import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Loader2, RotateCcw, ShieldQuestion } from 'lucide-react'
import { VerdictBanner } from './LabViews'
import { createExperiment, getExperiment, listExperiments, pollExperiment, whatIfLink } from '../../services/api'

/**
 * One-click robustness check for one diagnosis. Re-runs it with each reading moved by its typical
 * sensor error, all readings shifted together, the top cited evidence records left out, and — for
 * out-of-range readings — a wider sweep. Uses the trace's own settings, and shows an earlier check
 * for the same trace instead of starting a duplicate.
 */
export default function RobustnessCheck({ question, dataset, traceId, dataMode = 'combined', topK = 8 }) {
  const [exp, setExp] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const stopRef = useRef(null)

  const follow = (id) => {
    stopRef.current?.()
    stopRef.current = pollExperiment(id, (e) => setExp((x) => ({ ...(x || {}), ...e })), setExp)
  }

  // an earlier check of this trace? show it (and keep following it if it is still running)
  useEffect(() => {
    setExp(null); setError(null)
    if (!traceId) return undefined
    let live = true
    listExperiments(1, { source_trace_id: traceId, kind: 'robustness' }).then((r) => {
      const prev = live && r.items[0]
      if (!prev) return
      if (prev.status === 'running' || prev.status === 'queued') follow(prev.experiment_id)
      else getExperiment(prev.experiment_id).then((e) => live && setExp(e)).catch(() => {})
    }).catch(() => {})
    return () => { live = false; stopRef.current?.() }
  }, [traceId]) // eslint-disable-line react-hooks/exhaustive-deps

  const run = async () => {
    setBusy(true); setError(null)
    try {
      const r = await createExperiment({ kind: 'robustness', name: `Robustness: ${question.slice(0, 60)}`, question,
        dataset_type: dataset || 'afrb', data_mode: dataMode || 'combined', top_k: topK || 8, factors: { drop_evidence: 3 }, source_trace_id: traceId })
      follow(r.experiment_id)
    } catch (e) { setError(e.response?.data?.detail || e.message) } finally { setBusy(false) }
  }

  const p = exp?.progress
  const running = exp && (exp.status === 'running' || exp.status === 'queued')
  const verdict = exp?.verdict || exp?.analysis?.verdict
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
        {!exp && (
          <button type="button" onClick={run} disabled={busy || !question} className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 py-1 font-medium text-ink hover:bg-well focus-ring disabled:opacity-50">
            {busy ? <Loader2 size={13} className="animate-spin" /> : <ShieldQuestion size={13} />}Check robustness
          </button>
        )}
        {running && <span className="inline-flex items-center gap-1.5 text-muted"><Loader2 size={13} className="animate-spin" />Re-running with small disturbances… {p?.done ?? 0} of {p?.total ?? '…'} runs</span>}
        {exp && <Link to={`/lab/${exp.experiment_id}`} className="font-medium text-primary-700 underline underline-offset-2">{running ? 'Watch in Experiment lab' : 'See which step and agent changed'}</Link>}
        {exp && !running && <button type="button" onClick={run} disabled={busy} className="inline-flex items-center gap-1 text-muted hover:text-ink focus-ring rounded"><RotateCcw size={12} />Check again</button>}
        <Link to={whatIfLink(question, { traceId, dataset })} className="text-muted underline underline-offset-2 hover:text-ink">Custom what-if…</Link>
        {error && <span className="text-danger-700">{error}</span>}
      </div>
      {!exp && <p className="text-[11.5px] text-muted">Re-runs this diagnosis with each reading moved by its typical sensor error, all readings shifted together, and each top cited evidence record left out (about 15–30 runs, under a minute).</p>}
      {exp && !running && exp.created_at && <p className="text-[11px] text-muted">Checked {new Date(exp.created_at).toLocaleString()}{exp.versions?.code_version ? ` · code ${exp.versions.code_version}` : ''}</p>}
      {verdict && verdict.level !== 'incomplete' && <VerdictBanner verdict={verdict} caveats={exp?.analysis?.caveats} compact />}
    </div>
  )
}
