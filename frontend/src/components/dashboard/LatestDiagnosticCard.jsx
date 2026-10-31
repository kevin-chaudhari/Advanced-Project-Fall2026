import { useNavigate } from 'react-router-dom'
import { ArrowUpRight, Wrench } from 'lucide-react'
import { Cited } from '../ui'
import { ConfidenceIndicator, ReviewDecision } from '../primitives'
import { fmtTime } from '../../lib/diagnosis'
import { DATASETS } from '../../state/DiagnosticsContext'

/**
 * The verdict: the most prominent element of the dashboard.
 * Shows the coordinator's conclusion, not the full response — that lives in Diagnostic Chat.
 */
export default function LatestDiagnosticCard({ run, s, fresh }) {
  const nav = useNavigate()
  const ds = DATASETS.find((d) => d.id === s.dataset)
  return (
    <section aria-labelledby="verdict-title" className="card relative flex flex-col p-5 sm:p-6 lg:p-7 min-h-0">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-[12.5px] text-muted">Latest question</h2>
          <p className="mt-1 text-[13.5px] leading-snug text-ink/80 line-clamp-2 max-w-[70ch]" title={run.question}>{run.question}</p>
        </div>
        <div className="hidden sm:block shrink-0 pt-1"><ReviewDecision decision={s.decision} animate={fresh} /></div>
      </div>

      <div key={run.id} className="mt-5 grid gap-6 lg:grid-cols-[minmax(0,1fr)_200px] items-end verdict-in">
        <div className="min-w-0">
          <div className="text-[12.5px] text-muted">Coordinator's diagnosis</div>
          <h1 id="verdict-title" className="mt-1 text-[30px] sm:text-[38px] leading-[1.05] font-semibold tracking-[-0.02em] text-ink first-letter:uppercase break-words">
            {s.label || s.answer || 'No diagnosis returned'}
          </h1>
          {s.explanation && (
            <p className="mt-3 text-[14px] leading-relaxed text-ink/85 line-clamp-3 max-w-[72ch]"><Cited text={s.explanation} /></p>
          )}
          {s.recommendation && (
            <p className="mt-3 flex gap-2 text-[13px] leading-snug text-muted max-w-[72ch]">
              <Wrench size={14} className="mt-0.5 shrink-0 text-primary-600" aria-hidden />
              <span className="line-clamp-2"><span className="text-ink font-medium">Next action:</span> {s.recommendation}</span>
            </p>
          )}
        </div>
        <div className="space-y-4">
          <div className="sm:hidden"><ReviewDecision decision={s.decision} animate={fresh} /></div>
          <ConfidenceIndicator value={s.confidence} threshold={s.reviewThreshold} size="lg" />
        </div>
      </div>

      <footer className="mt-auto pt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12px] text-muted">
        <span><b className="font-semibold text-ink tabular-nums">{s.evidenceCount}</b> evidence records</span>
        {ds && <span>{ds.label}, {s.dataMode} data</span>}
        {s.analysedAt && <span>Analysed {fmtTime(s.analysedAt)}</span>}
        {s.latencyMs != null && <span className="hidden xl:inline tabular-nums">{Math.round(s.latencyMs)} ms</span>}
        <button type="button" onClick={() => nav(`/chat#run-${run.id}`)}
          className="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-1 -mr-2 text-[12.5px] font-medium text-primary-700 hover:bg-well focus-ring">
          Open full response <ArrowUpRight size={14} aria-hidden />
        </button>
      </footer>
    </section>
  )
}
