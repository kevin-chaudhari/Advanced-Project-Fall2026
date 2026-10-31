import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Loader2, Trash2 } from 'lucide-react'
import FinalAgentResponse from './FinalAgentResponse'
import { summarize, fmtTime } from '../../lib/diagnosis'
import { DATASETS } from '../../state/DiagnosticsContext'

function Elapsed({ since }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [])
  return <span className="tabular-nums">{Math.max(0, Math.round((now - since) / 1000))} s</span>
}

/** One exchange: the question and the backend's answer (or its pending / error state). */
export default function ChatMessage({ run, onRemove, highlighted }) {
  const s = useMemo(() => (run.result ? summarize(run.result, run) : null), [run])
  const ds = DATASETS.find((d) => d.id === run.dataset)
  const pending = !run.result && !run.error
  return (
    <div id={`run-${run.id}`} className="scroll-mt-4">
      <div className="mb-3 flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 text-[11.5px] text-muted">
            <span>You asked</span>
            {ds && <span>· {ds.label}, {run.mode} data</span>}
            {run.startedAt && <span>· {fmtTime(run.startedAt)}</span>}
          </div>
          <p className={`mt-1 text-[15px] leading-snug text-ink ${highlighted ? 'underline decoration-primary-300 decoration-2 underline-offset-4' : ''}`}>{run.question}</p>
        </div>
        {!pending && onRemove && (
          <button type="button" onClick={() => onRemove(run.id)} className="btn-ghost p-1.5 shrink-0" aria-label="Remove this exchange from history" title="Remove from history">
            <Trash2 size={14} />
          </button>
        )}
      </div>

      {pending && (
        <div role="status" className="card flex items-center gap-3 px-5 py-4 text-[13px]">
          <Loader2 size={16} className="animate-spin text-primary-700 shrink-0" aria-hidden />
          <div className="min-w-0">
            <div className="font-medium text-ink">The six agents are analysing this question</div>
            <div className="text-[12px] text-muted">Retrieval, independent analysis, verification and the review gate run in sequence. Elapsed <Elapsed since={run.startedAt} />.</div>
          </div>
        </div>
      )}

      {run.error && (
        <div role="alert" className="card border-danger-100 bg-danger-50/60 flex gap-2.5 px-5 py-4 text-[13px] text-danger-700">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
          <div><b className="font-semibold">The diagnosis did not complete.</b> <span className="text-ink">{run.error}</span></div>
        </div>
      )}

      {s && <FinalAgentResponse s={s} result={run.result} question={run.question} />}
    </div>
  )
}
