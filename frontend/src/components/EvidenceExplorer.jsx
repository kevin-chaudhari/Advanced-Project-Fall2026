import { useMemo, useState, useEffect, useRef } from 'react'
import { cx, SourceBadge, Empty, fmtNum } from './ui'

const SENSOR_ORDER = ['temperature', 'vibration', 'pressure', 'rpm', 'current', 'voltage', 'flow_rate']
const SENSOR_LABEL = { temperature: 'Temp °C', vibration: 'Vib', pressure: 'PSI', rpm: 'RPM', current: 'A', voltage: 'V', flow_rate: 'L/min' }
const AGENT_SHORT = { diagnostic_expert: 'Diagnostic', pattern_agent: 'Pattern', aggressive_agent: 'Triage', verification: 'Verification', ambiguity: 'Ambiguity', human_review_coordinator: 'Coordinator' }

export default function EvidenceExplorer({ harness, focusId }) {
  const [filter, setFilter] = useState('all')
  const ev = harness?.evidence || []
  const label = harness?.predicted_label
  const verifiedLabel = harness?.verification?.verified_label
  const target = verifiedLabel || label
  const refs = useRef({})

  useEffect(() => {
    if (focusId && refs.current[focusId]) {
      setFilter('all')
      refs.current[focusId].scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [focusId])

  const filters = useMemo(() => [
    { id: 'all', label: 'All', f: () => true },
    { id: 'support', label: 'Supporting', f: (e) => e.label && e.label === target },
    { id: 'contra', label: 'Contradicting / alternative', f: (e) => e.label && e.label !== target },
    { id: 'historical', label: 'Historical (sensor-profile) matches', f: (e) => e.method_scores?.numeric != null },
    { id: 'targeted', label: 'Targeted re-RAG', f: (e) => e.retrieval_round > 0 },
    { id: 'real', label: 'REAL', f: (e) => e.source_type === 'real' },
    { id: 'synthetic', label: 'SYNTHETIC', f: (e) => e.source_type === 'synthetic' },
  ], [target])
  const cur = filters.find((x) => x.id === filter)
  const shown = ev.filter(cur.f)
  const comp = harness?.evidence_composition || {}

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted mr-1">Evidence: <b className="text-ink">REAL — {comp.real ?? 0}</b> · <b className="text-ink">SYNTHETIC — {comp.synthetic ?? 0}</b></span>
        {filters.map((x) => (
          <button key={x.id} onClick={() => setFilter(x.id)}
            className={cx('rounded-full border px-2.5 py-0.5 text-[12px]', filter === x.id ? 'border-primary-600 bg-primary-50 text-primary-700' : 'border-line text-muted hover:text-ink')}>
            {x.label} <span className="text-[11px] opacity-70">{ev.filter(x.f).length}</span>
          </button>
        ))}
      </div>
      {!shown.length && <Empty>No evidence in this view.</Empty>}
      <div className="grid gap-3 md:grid-cols-2">
        {shown.map((e) => {
          const sens = e.content?.sensors || {}
          const hasSens = SENSOR_ORDER.some((s) => s in sens)
          return (
            <article key={e.evidence_id} ref={(el) => (refs.current[e.evidence_id] = el)}
              className={cx('rounded-lg border bg-white p-3 transition-shadow', focusId === e.evidence_id ? 'border-primary-500 shadow-lift' : 'border-line')}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="mono font-semibold text-primary-700">{e.evidence_id}</span>
                  <SourceBadge source={e.source_type} size="xs" />
                  {e.retrieval_round > 0 && <span className="chip border-secondary-100 bg-secondary-50 text-secondary-700 text-[10px] py-0">round {e.retrieval_round}</span>}
                </div>
                <span className="text-[11px] text-muted tabular-nums">score {fmtNum(e.retrieval_score, 3)} · {e.retrieval_method}</span>
              </div>
              <div className="mt-1.5 flex items-center justify-between gap-2">
                <div className="text-[13px] font-semibold text-ink truncate">{e.label || 'unlabelled'}</div>
                <div className="mono text-muted truncate">{e.dataset}/{e.record_id}</div>
              </div>
              {e.content?.system_context && <div className="text-[12px] text-muted truncate">{e.content.system_context}</div>}
              {hasSens && (
                <table className="mt-2 w-full text-[11px]">
                  <thead><tr>{SENSOR_ORDER.map((s) => <th key={s} className="text-left font-medium text-muted pr-1">{SENSOR_LABEL[s]}</th>)}</tr></thead>
                  <tbody><tr>{SENSOR_ORDER.map((s) => (
                    <td key={s} className={cx('tabular-nums pr-1', sens[s] == null ? 'text-warning-700 italic' : 'text-ink')}>{sens[s] == null ? 'n/a' : fmtNum(sens[s], 3)}</td>
                  ))}</tr></tbody>
                </table>
              )}
              {!hasSens && e.content?.relevant_items && (
                <div className="mt-2 text-[12px] text-ink">Relevant: {e.content.relevant_items.join(', ')}</div>
              )}
              <div className="mt-2 text-[11px] text-muted"><span className="font-medium text-ink">Why selected:</span> {e.selection_reason}</div>
              {e.used_by?.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">{e.used_by.map((u) => <span key={u} className="chip border-line bg-slate-50 text-slate-600 text-[10px] py-0">{AGENT_SHORT[u] || u}</span>)}</div>
              )}
            </article>
          )
        })}
      </div>
    </div>
  )
}
