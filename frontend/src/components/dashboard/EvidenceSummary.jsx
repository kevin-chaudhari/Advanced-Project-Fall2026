import { CheckCircle2, ShieldAlert } from 'lucide-react'
import { cx } from '../ui'
import { ProvenanceBar } from '../primitives'

const FACTOR_LABEL = {
  evidence_quality: 'Evidence quality', hypothesis_separation: 'Separation from runner-up', historical_similarity: 'Historical similarity',
  data_completeness: 'Data completeness', contradictions: 'Free of contradictions', retrieval_quality: 'Retrieval quality',
  agent_agreement: 'Agent agreement', synthetic_reliance: 'Real-data support',
}
const label = (n) => FACTOR_LABEL[n] || String(n).replaceAll('_', ' ')

function Row({ title, children, aside }) {
  return (
    <div className="py-3 first:pt-0 last:pb-0">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-[12.5px] text-muted">{title}</h3>
        {aside}
      </div>
      <div className="mt-1.5">{children}</div>
    </div>
  )
}

/** Board explaining why the verdict can (or cannot) be trusted. Only backend-reported values. */
export default function EvidenceSummary({ s }) {
  const v = s.verification
  const claims = s.claims
  const factors = [...s.confidenceFactors].sort((a, b) => a.value - b.value)
  const failing = s.criteria.filter((c) => !c.passed)
  const agree = v?.agreement_ratio
  return (
    <section aria-label="Evidence and confidence" className="card p-5 shrink-0">
      <div className="divide-y divide-line">
        <Row title="Human review" aside={s.criteria.length ? <span className="text-[11.5px] text-muted tabular-nums">{s.criteriaPassed}/{s.criteria.length} gate checks passed</span> : null}>
          {s.needsReview ? (
            <div className="flex gap-2 text-[13px] text-warning-700">
              <ShieldAlert size={15} className="mt-0.5 shrink-0" aria-hidden />
              <div className="min-w-0">
                <div className="font-semibold">Required before acting</div>
                {failing.length > 0 && (
                  <ul className="mt-0.5 text-[12px] text-ink/80 space-y-0.5">
                    {failing.slice(0, 3).map((c) => <li key={c.criterion_id} className="truncate" title={`${c.description} (observed ${c.observed})`}>{c.description} <span className="text-muted">· observed {c.observed}</span></li>)}
                    {failing.length > 3 && <li className="text-muted">+{failing.length - 3} more</li>}
                  </ul>
                )}
              </div>
            </div>
          ) : s.decision ? (
            <div className="flex items-center gap-2 text-[13px] text-success-700 font-semibold"><CheckCircle2 size={15} aria-hidden /> Not required</div>
          ) : <span className="text-[12.5px] text-muted">No gate decision returned</span>}
        </Row>

        <Row title="Evidence" aside={<span className="text-[13px] font-semibold text-ink tabular-nums">{s.evidenceCount} records</span>}>
          <ProvenanceBar composition={s.provenance} />
        </Row>

        <Row title="Verification">
          {v ? (
            <div className="text-[12.5px] leading-snug text-ink">
              <span className="font-medium first-letter:uppercase">{v.verified_label || 'No verified label'}</span>
              <span className="text-muted">
                {agree != null && <> · {Math.round(agree * 100)}% of first-pass agents agree</>}
                {v.margin != null && <> · margin {v.margin.toFixed(2)}</>}
              </span>
              {claims && (
                <div className={cx('mt-1 text-[12px]', claims.UNSUPPORTED || claims.removed ? 'text-warning-700' : 'text-muted')}>
                  {claims.SUPPORTED + (claims.DERIVED || 0)} of {claims.total_claims} final claims backed by evidence
                  {claims.removed ? `, ${claims.removed} removed` : ''}
                </div>
              )}
            </div>
          ) : <span className="text-[12.5px] text-muted">Not reported</span>}
        </Row>

        {factors.length > 0 && (
          <Row title="What sets the confidence" aside={<span className="text-[11px] text-muted">weakest first</span>}>
            <ul className="space-y-1">
              {factors.map((f) => (
                <li key={f.name} className="grid grid-cols-[minmax(0,1fr)_72px_30px] items-center gap-2 text-[11.5px]" title={f.explanation}>
                  <span className="truncate text-ink/85">{label(f.name)}</span>
                  <span className="h-1 rounded-full bg-well overflow-hidden" aria-hidden>
                    <span className={cx('block h-full rounded-full', f.value >= 0.8 ? 'bg-success-500' : f.value >= 0.5 ? 'bg-warning-500' : 'bg-danger-500')} style={{ width: `${f.value * 100}%` }} />
                  </span>
                  <span className="text-right tabular-nums text-muted">{f.value.toFixed(2)}</span>
                </li>
              ))}
            </ul>
          </Row>
        )}
      </div>
    </section>
  )
}
