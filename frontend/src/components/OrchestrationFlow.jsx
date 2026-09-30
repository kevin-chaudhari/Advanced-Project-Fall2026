import { ArrowRight, RotateCcw, CornerDownRight } from 'lucide-react'
import { cx, StatusIcon, DecisionBadge } from './ui'

const AGENT_LABEL = {
  diagnostic_expert: 'Diagnostic Expert',
  pattern_agent: 'Pattern Recognition',
  aggressive_agent: 'Rapid Triage',
  verification: 'Verification',
  ambiguity: 'Ambiguity',
  human_review_coordinator: 'Final Coordinator',
}

function Node({ title, sub, status = 'ok', kind = 'stage', dim }) {
  const tone = {
    agent: 'border-primary-200 bg-primary-50/60',
    stage: 'border-line bg-white',
    loop: 'border-secondary-100 bg-secondary-50/70',
  }[kind]
  return (
    <div className={cx('rounded-lg border px-3 py-2 min-w-[118px]', tone, dim && 'opacity-50')}>
      <div className="flex items-center gap-1.5">
        {!dim && <StatusIcon status={status} size={13} />}
        <span className="text-[12px] font-semibold text-ink whitespace-nowrap">{title}</span>
      </div>
      {sub && <div className="text-[11px] text-muted mt-0.5 leading-snug max-w-[160px] truncate" title={sub}>{sub}</div>}
    </div>
  )
}

const Arrow = () => <ArrowRight size={14} className="text-slate-300 shrink-0" aria-hidden />

/** Pipeline view built from the backend audit timeline (no simulated steps). */
export default function OrchestrationFlow({ harness }) {
  const tl = harness?.timeline || []
  const first = (pred) => tl.find(pred)
  const worst = (events) => (events.some((e) => e.status === 'error') ? 'error' : events.some((e) => e.status === 'warning') ? 'warning' : events.some((e) => e.status === 'loop') ? 'loop' : 'ok')
  const agentEv = (key) => tl.filter((e) => e.agent === key)
  const phase1 = ['diagnostic_expert', 'pattern_agent', 'aggressive_agent']
  const verif = agentEv('verification')
  const checks = tl.filter((e) => e.stage === 'evidence_check')
  const targeted = tl.filter((e) => e.stage === 'targeted_rag')
  const reruns = tl.filter((e) => e.stage === 'targeted_rerun')
  const gate = first((e) => e.stage === 'review_gate')
  const rounds = harness?.feedback_rounds || 0
  const history = harness?.deficiencies_history || []
  const agents = harness?.agents || {}

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Node title="Query" sub={first((e) => e.stage === 'query_prep')?.reason} />
        <Arrow />
        <Node title="Multi-stage RAG" sub={`${first((e) => e.stage === 'initial_rag')?.retrieval_count ?? 0} evidence records`} />
        <Arrow />
        <div className="flex flex-col gap-1.5 rounded-xl border border-dashed border-primary-200 p-1.5">
          {phase1.map((k) => {
            const ev = agentEv(k)
            return <Node key={k} kind="agent" title={AGENT_LABEL[k]} status={worst(ev)}
              sub={`${agents[k]?.finding ?? '—'}${ev.length > 1 ? ` · ${ev.length} passes` : ''}`} />
          })}
        </div>
        <Arrow />
        <Node kind="agent" title="Verification" status={worst(verif)} sub={`${agents.verification?.finding ?? '—'}${verif.length > 1 ? ` · ${verif.length} passes` : ''}`} />
        <Arrow />
        <Node title="Evidence check" status={checks[0]?.status === 'warning' ? 'warning' : 'ok'}
          sub={checks[0]?.status === 'warning' ? 'evidence weak' : 'evidence sufficient'} />
        <Arrow />
        <Node kind="loop" title={rounds ? `Targeted RAG ↻${rounds}` : 'Targeted RAG'} dim={!rounds} status="loop"
          sub={rounds ? `${targeted.length} targeted retrieval(s)` : 'not needed'} />
        <Arrow />
        <Node kind="agent" title="Ambiguity" status={worst(agentEv('ambiguity'))} sub={agents.ambiguity?.finding} />
        <Arrow />
        <Node kind="agent" title="Final Coordinator" status={worst(agentEv('human_review_coordinator'))} sub={harness?.predicted_label} />
        <Arrow />
        <div className="rounded-lg border border-line bg-white px-3 py-2">
          <div className="text-[12px] font-semibold text-ink mb-1">Human review gate</div>
          {gate ? <DecisionBadge decision={harness.review_decision} /> : '—'}
        </div>
      </div>

      {/* Feedback loop narrative */}
      <div className="rounded-lg border border-line bg-slate-50/60 p-3">
        <div className="flex items-center gap-2 mb-2">
          <RotateCcw size={14} className="text-secondary-600" />
          <span className="text-[12px] font-semibold text-ink">Controlled feedback loop</span>
          <span className="text-[11px] text-muted">{rounds ? `${rounds} round(s)` : 'no targeted round needed'}</span>
        </div>
        <ol className="space-y-1.5 text-[12px] text-ink">
          <li className="flex gap-2"><StatusIcon status="ok" size={13} /> Initial retrieval → 3 independent analyses → verification</li>
          {history.map((defs, i) => {
            const actionable = defs.filter((d) => d.action !== 'none')
            const info = defs.filter((d) => d.action === 'none')
            const isLast = i === history.length - 1
            return (
              <li key={i} className="pl-0">
                <div className="flex gap-2">
                  <StatusIcon status={actionable.length && !isLast ? 'warning' : 'ok'} size={13} />
                  <span>
                    Evidence check {i + 1}:{' '}
                    {defs.length === 0 ? <span className="text-success-700">sufficient</span> :
                      defs.map((d) => <span key={d.code} className="mr-2"><span className="mono text-warning-700">{d.code}</span> <span className="text-muted">({d.detail})</span></span>)}
                    {isLast && actionable.length > 0 && <span className="text-muted"> — remaining uncertainty passed to Ambiguity</span>}
                  </span>
                </div>
                {!isLast && actionable.length > 0 && (
                  <div className="ml-6 mt-1 space-y-0.5 text-muted">
                    {actionable.map((d) => (
                      <div key={d.code} className="flex items-center gap-1.5">
                        <CornerDownRight size={12} /> {d.action.replaceAll('_', ' ')}
                        {d.rerun?.length > 0 && <> → re-run <b className="text-ink font-medium">{d.rerun.map((r) => AGENT_LABEL[r]).join(', ')}</b></>}
                      </div>
                    ))}
                    <div className="flex items-center gap-1.5"><CornerDownRight size={12} /> re-verify</div>
                  </div>
                )}
                {info.length > 0 && !isLast && null}
              </li>
            )
          })}
        </ol>
        {reruns.length > 0 && (
          <p className="text-[11px] text-muted mt-2">Only the affected agents were re-run ({[...new Set(reruns.map((r) => AGENT_LABEL[r.agent]))].join(', ')}); Rapid Triage is never re-run so it stays an independent signal.</p>
        )}
      </div>
    </div>
  )
}
