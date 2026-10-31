import { CheckCircle2, XCircle } from 'lucide-react'
import { cx, Cited, IdChip } from '../ui'

/*
 * Detail blocks shared by the dashboard trail and the chat response.
 * Each takes the summarize() view model and renders only what the backend returned.
 */

const List = ({ items, tone, onEvidence }) => (
  <ul className="space-y-1 text-[12.5px] leading-snug text-ink">
    {items.map((t, i) => <li key={i} className={cx('pl-2.5 border-l', tone || 'border-line')}><Cited text={typeof t === 'string' ? t : t.statement} onEvidence={onEvidence} /></li>)}
  </ul>
)

const Sub = ({ children }) => <div className="text-[11.5px] font-medium text-muted mb-1">{children}</div>

export function verificationMeta(s) {
  const v = s.verification
  if (!v) return 'Not reported'
  if (v.agents_disagree) return 'Agents disagree'
  if (v.agreement_without_evidence) return 'Agreement, weak evidence'
  return 'Verified'
}

export function VerificationDetail({ s, onEvidence }) {
  const v = s.verification
  if (!v) return <p className="text-[12.5px] text-muted">The response did not include a verification result.</p>
  const ar = v.adversarial_review || {}
  return (
    <div className="space-y-3">
      <p className="text-[12.5px] text-ink">
        Verified hypothesis <b className="font-semibold">{v.verified_label || '—'}</b>
        {v.alternative && <> over <span className="font-medium">{v.alternative}</span></>}
        {v.margin != null && <span className="text-muted"> (margin {v.margin.toFixed(2)})</span>}.
        {v.agreement_ratio != null && <span className="text-muted"> {Math.round(v.agreement_ratio * 100)}% of first-pass agents agree.</span>}
      </p>
      {ar.what_supports_it?.length > 0 && <div><Sub>What supports it</Sub><List items={ar.what_supports_it} tone="border-success-500/40" onEvidence={onEvidence} /></div>}
      {ar.what_contradicts_it?.length > 0 && <div><Sub>What contradicts it</Sub><List items={ar.what_contradicts_it} tone="border-danger-500/50" onEvidence={onEvidence} /></div>}
      {ar.what_is_missing?.length > 0 && <div><Sub>What is missing</Sub><List items={ar.what_is_missing} tone="border-warning-500/50" onEvidence={onEvidence} /></div>}
      {ar.alternative_explanation && <p className="text-[12px] text-muted"><span className="text-ink font-medium">Alternative:</span> {ar.alternative_explanation}</p>}
      {s.claims && (
        <p className="text-[12px] text-muted">
          Claim validation: {s.claims.SUPPORTED} supported, {s.claims.DERIVED || 0} derived, {s.claims.UNSUPPORTED || 0} unsupported
          {s.claims.removed ? `, ${s.claims.removed} removed from the answer` : ''} (of {s.claims.total_claims}).
        </p>
      )}
    </div>
  )
}

export function feedbackMeta(s) {
  if (s.feedbackRounds > 0) return `${s.feedbackRounds} feedback round${s.feedbackRounds > 1 ? 's' : ''}`
  if (s.extraRetrieval.length) return `${s.extraRetrieval.length} targeted retrieval${s.extraRetrieval.length > 1 ? 's' : ''}`
  return 'Not needed'
}

export function FeedbackDetail({ s, onEvidence }) {
  const def = s.deficiencies
  if (!def.length && !s.extraRetrieval.length) {
    return <p className="text-[12.5px] text-muted">The evidence check found the first retrieval sufficient, so no targeted retrieval or agent re-run was triggered.</p>
  }
  return (
    <div className="space-y-3">
      {def.length > 0 && (
        <div>
          <Sub>Evidence-check findings</Sub>
          <ul className="space-y-1 text-[12.5px]">
            {def.map((d, i) => (
              <li key={i} className="pl-2.5 border-l border-warning-500/50">
                <span className="font-mono text-[11px] text-warning-700">{d.code}</span> <span className="text-ink">{d.detail}</span>
                {d.rerun?.length > 0 && <span className="text-muted"> · re-ran {d.rerun.join(', ').replaceAll('_', ' ')}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {s.extraRetrieval.length > 0 && (
        <div>
          <Sub>Additional retrieval</Sub>
          <ul className="space-y-1 text-[12.5px]">
            {s.extraRetrieval.map((r, i) => (
              <li key={i} className="pl-2.5 border-l border-line text-ink">
                <span className="break-words">{String(r.action).replaceAll('_', ' ')}</span>
                <span className="text-muted"> · +{r.added} record{r.added === 1 ? '' : 's'}</span>
                {r.evidence_ids?.length > 0 && <span className="ml-1 inline-flex flex-wrap gap-1">{r.evidence_ids.map((id) => <IdChip key={id} id={id} onClick={onEvidence} />)}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export function councilMeta(s) {
  const c = s.council
  if (!c) return null
  return c.convened ? `${c.rounds} round${c.rounds === 1 ? '' : 's'}, ${c.messages} messages` : 'Not convened'
}

export function CouncilDetail({ s }) {
  const c = s.council
  if (!c) return null
  if (!c.convened) {
    return <p className="text-[12.5px] text-muted">The agents did not deliberate{c.reasons?.length ? `: ${c.reasons.join('; ')}` : ' — the first-pass result met the council criteria'}.</p>
  }
  const changed = c.verified_before && c.verified_after && c.verified_before !== c.verified_after
  return (
    <div className="space-y-2 text-[12.5px] text-ink">
      {c.reasons?.length > 0 && <p><span className="text-muted">Convened because</span> {c.reasons.join('; ')}.</p>}
      <p>
        {c.confidence_before != null && c.confidence_after != null && <>Confidence {c.confidence_before.toFixed(2)} → <b className="font-semibold">{c.confidence_after.toFixed(2)}</b>. </>}
        {changed ? <>Verified hypothesis changed from {c.verified_before} to <b className="font-semibold">{c.verified_after}</b>.</> : c.verified_after ? <>Verified hypothesis held: {c.verified_after}.</> : null}
      </p>
      <p className="text-muted">{c.resolved} question{c.resolved === 1 ? '' : 's'} resolved, {c.unresolved} left open{c.human_inputs?.length ? `, ${c.human_inputs.length} human input request(s)` : ''}.</p>
    </div>
  )
}

export function GateDetail({ s }) {
  if (!s.criteria.length) return <p className="text-[12.5px] text-muted">No gate criteria returned.</p>
  return (
    <ul className="space-y-1">
      {s.criteria.map((c) => (
        <li key={c.criterion_id} className="grid grid-cols-[16px_28px_minmax(0,1fr)_auto] items-start gap-1.5 text-[12px]">
          {c.passed ? <CheckCircle2 size={14} className="mt-px text-success-600" aria-label="passed" /> : <XCircle size={14} className="mt-px text-danger-600" aria-label="failed" />}
          <span className="font-mono text-[11px] text-muted mt-px">{c.criterion_id}</span>
          <span className={cx('leading-snug', c.passed ? 'text-ink' : 'text-ink font-medium')}>{c.description}</span>
          <span className="text-muted tabular-nums text-right">{c.observed}</span>
        </li>
      ))}
    </ul>
  )
}
