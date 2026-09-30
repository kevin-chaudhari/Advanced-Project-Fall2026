import { useState } from 'react'
import { ShieldAlert, CheckCircle2, AlertOctagon, Wrench } from 'lucide-react'
import { Card, DecisionBadge, SourceBadge, Tabs, Cited, pct, cx } from './ui'
import OrchestrationFlow from './OrchestrationFlow'
import EvidenceExplorer from './EvidenceExplorer'
import { HypothesisPanel, ConfidencePanel, AgentPanel, SensorPanel, AuditPanel } from './ReportPanels'

export default function DiagnosisReport({ result }) {
  const [focus, setFocus] = useState(null)
  const [tab, setTab] = useState(0)
  const h = result.harness || {}
  const decision = result.review_decision || h.review_decision
  const auto = decision === 'AUTO_RESOLVE'
  const insufficient = h.predicted_label === 'Insufficient Evidence'
  const comp = h.evidence_composition || {}
  const onEvidence = (id) => { setFocus(id); setTab((t) => t + 1) }

  const tone = insufficient ? 'border-l-danger-600' : auto ? 'border-l-success-600' : 'border-l-warning-500'
  const Icon = insufficient ? AlertOctagon : auto ? CheckCircle2 : ShieldAlert

  return (
    <div className="space-y-4">
      {/* Headline */}
      <section className={cx('card border-l-4 p-5', tone)}>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <DecisionBadge decision={decision} />
          <SourceBadge source={h.data_mode} />
          <span className="chip border-line bg-slate-50 text-slate-600">REAL {comp.real ?? 0} · SYNTHETIC {comp.synthetic ?? 0}</span>
          <span className="chip border-line bg-slate-50 text-slate-600">{h.llm_mode}</span>
          {h.feedback_rounds > 0 && <span className="chip border-secondary-100 bg-secondary-50 text-secondary-700">↻ {h.feedback_rounds} targeted round(s)</span>}
          <span className="text-[11px] text-muted ml-auto">run {h.run_id} · {Math.round(h.latency_ms || 0)} ms</span>
        </div>
        <div className="flex items-start gap-4">
          <Icon size={22} className={cx('mt-0.5 shrink-0', insufficient ? 'text-danger-600' : auto ? 'text-success-600' : 'text-warning-500')} />
          <div className="flex-1 min-w-0">
            <div className="eyebrow">Final diagnosis</div>
            <p className="text-[17px] font-semibold text-ink leading-snug mt-0.5"><Cited text={result.final_diagnosis} onEvidence={onEvidence} /></p>
            {result.direct_answer && result.direct_answer !== result.final_diagnosis && (
              <p className="text-sm text-muted mt-1">{result.direct_answer}</p>
            )}
          </div>
          <div className="text-right shrink-0">
            <div className="eyebrow">Measured confidence</div>
            <div className="text-3xl font-semibold tabular-nums text-ink">{pct(result.confidence)}</div>
          </div>
        </div>
        {!auto && h.review?.reasons?.length > 0 && (
          <div className="mt-3 rounded-lg bg-warning-50 border border-warning-100 px-3 py-2 text-[12px] text-warning-700">
            <b>Why human review:</b> {h.review.reasons.join(' · ')}
          </div>
        )}
        {result.recommendation && (
          <div className="mt-3 flex items-start gap-2 text-[13px] text-ink"><Wrench size={15} className="text-primary-600 mt-0.5" /><span>{result.recommendation}</span></div>
        )}
        {result.supporting_evidence?.length > 0 && (
          <ul className="mt-3 space-y-1 text-[12px] text-muted">
            {result.supporting_evidence.map((s, i) => <li key={i} className="flex gap-1.5"><span className="text-success-600">+</span><Cited text={s} onEvidence={onEvidence} /></li>)}
          </ul>
        )}
      </section>

      <Card title="Agent orchestration" subtitle="Built from the measured audit trail of this run — six agents, deterministic harness stages in between">
        <OrchestrationFlow harness={h} />
      </Card>

      <section className="card px-3 pb-4">
        <Tabs key={`${tab}-${focus}`} initial={focus && tab ? 'evidence' : 'hypotheses'} tabs={[
          { id: 'hypotheses', label: 'Hypotheses', render: () => <HypothesisPanel harness={h} onEvidence={onEvidence} /> },
          { id: 'evidence', label: 'Evidence explorer', count: h.evidence?.length, render: () => <EvidenceExplorer harness={h} focusId={focus} /> },
          { id: 'confidence', label: 'Confidence & gate', render: () => <ConfidencePanel harness={h} /> },
          { id: 'agents', label: 'Agents', count: 6, render: () => <AgentPanel harness={h} onEvidence={onEvidence} /> },
          { id: 'sensors', label: 'Sensors', render: () => <SensorPanel harness={h} /> },
          { id: 'audit', label: 'Audit & claims', render: () => <AuditPanel harness={h} /> },
        ]} />
      </section>

      {result.reasoning?.length > 0 && (
        <Card title="Reasoning trace" subtitle="Generated from the shared diagnostic state; every step is traceable">
          <ol className="space-y-1.5 text-[12px] text-ink">{result.reasoning.map((r, i) => <li key={i}><Cited text={r} onEvidence={onEvidence} /></li>)}</ol>
        </Card>
      )}
    </div>
  )
}
