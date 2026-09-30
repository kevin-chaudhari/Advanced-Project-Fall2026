import { cx, Cited, Empty, Meter, fmtNum, StatusIcon, pct } from './ui'
import { CheckCircle2, XCircle } from 'lucide-react'

/* ── Hypothesis comparison (actual system scores) ─────────────────────────── */
export function HypothesisPanel({ harness, onEvidence }) {
  const scores = harness?.hypothesis_scores || []
  const hyps = harness?.hypotheses || []
  const verified = harness?.verification?.verified_label
  const qa = harness?.verification?.adversarial_review
  const max = Math.max(0.0001, ...scores.map((s) => s.score))
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div>
        <div className="eyebrow mb-2">Hypothesis evidence scores (normalised)</div>
        {!scores.length && <Empty>No hypotheses were scored.</Empty>}
        <div className="space-y-1.5" role="list">
          {scores.slice(0, 8).map((s) => (
            <div key={s.label} role="listitem" className="group" title={Object.entries(s.components || {}).map(([k, v]) => `${k}: ${v}`).join(' · ')}>
              <div className="flex items-center justify-between text-[12px]">
                <span className={cx('truncate', s.label === verified ? 'font-semibold text-ink' : 'text-ink')}>
                  {s.label}{s.label === verified && <span className="ml-1.5 text-[10px] text-primary-700 font-semibold">VERIFIED</span>}
                </span>
                <span className="tabular-nums text-muted">{s.score.toFixed(3)}</span>
              </div>
              <div className="h-2 rounded-r bg-slate-100 overflow-hidden">
                <div className={cx('h-full rounded-r', s.label === verified ? 'bg-primary-600' : 'bg-slate-400')} style={{ width: `${(s.score / max) * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
        {scores[0]?.components && (
          <p className="text-[11px] text-muted mt-2">Score = 0.6 × similarity-weighted vote of nearest historical cases + 0.4 × sensor-signature fit{scores[0].components.metadata_lift != null ? ' × equipment-type prior' : ''}. Hover a bar for its components.</p>
        )}
        {harness?.conflict_resolution && (
          <div className="mt-3 rounded-lg border border-secondary-100 bg-secondary-50/60 p-3 text-[12px]">
            <div className="font-semibold text-ink mb-1">Conflict resolution (Diagnostic Expert, pass 2)</div>
            {harness.conflict_resolution.discriminating.map((d) => (
              <div key={d.sensor} className="text-muted">Discriminating channel <b className="text-ink">{d.sensor}</b> — separation {d.separation}</div>
            ))}
            <div className="text-muted mt-1">Pairwise share: {Object.entries(harness.conflict_resolution.pairwise_share).map(([k, v]) => `${k} ${pct(v)}`).join(' vs ')}</div>
          </div>
        )}
      </div>
      <div>
        <div className="eyebrow mb-2">Adversarial verification of the leading hypothesis</div>
        {!qa ? <Empty>Verification did not run.</Empty> : (
          <dl className="space-y-2.5 text-[12px]">
            {[
              ['What supports it?', qa.what_supports_it],
              ['What contradicts it?', qa.what_contradicts_it],
              ['What evidence is missing?', qa.what_is_missing],
              ['Alternative explanation', [qa.alternative_explanation]],
              ['Unsupported agent claims', qa.unsupported_agent_claims],
              ['Irrelevant records', qa.irrelevant_records?.length ? [qa.irrelevant_records.join(', ')] : []],
            ].map(([q, items]) => (
              <div key={q}>
                <dt className="font-semibold text-ink">{q}</dt>
                <dd className="text-muted">
                  {items?.length ? <ul className="list-disc ml-4 space-y-0.5">{items.map((t, i) => <li key={i}><Cited text={t} onEvidence={onEvidence} /></li>)}</ul> : <span className="italic">none</span>}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
      {hyps.length > 1 && (
        <div className="lg:col-span-2">
          <div className="eyebrow mb-2">All candidates reviewed</div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead className="text-muted text-left"><tr><th className="py-1 pr-3 font-medium">Hypothesis</th><th className="pr-3 font-medium">Score</th><th className="pr-3 font-medium">Supporting</th><th className="pr-3 font-medium">Contradicting</th><th className="font-medium">Missing</th></tr></thead>
              <tbody>{hyps.map((h) => (
                <tr key={h.label} className="border-t border-line align-top">
                  <td className="py-1.5 pr-3 font-medium text-ink">{h.label}</td>
                  <td className="pr-3 tabular-nums">{h.score.toFixed(3)}</td>
                  <td className="pr-3">{h.supporting.length}</td>
                  <td className="pr-3">{h.contradicting.length}</td>
                  <td>{h.missing.length ? h.missing.join('; ') : '—'}</td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Confidence breakdown + gate ──────────────────────────────────────────── */
const FACTOR_LABEL = {
  evidence_quality: 'Evidence quality', hypothesis_separation: 'Hypothesis separation', historical_similarity: 'Historical similarity',
  data_completeness: 'Data completeness', contradictions: 'Contradictions (1 = none)', retrieval_quality: 'Retrieval quality',
  agent_agreement: 'Agent agreement', synthetic_reliance: 'Synthetic reliance',
}
export function ConfidencePanel({ harness }) {
  const c = harness?.confidence
  const gate = harness?.review
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div>
        <div className="flex items-baseline justify-between mb-2">
          <span className="eyebrow">Confidence factors</span>
          <span className="text-lg font-semibold tabular-nums">{c ? pct(c.confidence) : '—'}</span>
        </div>
        <div className="space-y-2.5">
          {(c?.factors || []).map((f) => (
            <div key={f.name}>
              <div className="flex justify-between text-[12px]"><span className="text-ink font-medium">{FACTOR_LABEL[f.name] || f.name}</span><span className="text-muted">weight {f.weight}</span></div>
              <Meter value={f.value} color={f.value >= 0.75 ? 'bg-primary-600' : f.value >= 0.5 ? 'bg-warning-500' : 'bg-danger-600'} label={f.name} />
              <div className="text-[11px] text-muted">{f.explanation}</div>
            </div>
          ))}
        </div>
        {c && <p className="mono text-muted mt-3">{c.formula}</p>}
      </div>
      <div>
        <div className="eyebrow mb-2">Human review gate — explicit criteria</div>
        <ul className="space-y-1.5">
          {(gate?.criteria || []).map((g) => (
            <li key={g.criterion_id} className="flex items-start gap-2 text-[12px]">
              {g.passed ? <CheckCircle2 size={14} className="text-success-600 mt-0.5 shrink-0" /> : <XCircle size={14} className="text-danger-600 mt-0.5 shrink-0" />}
              <span><span className="mono text-muted">{g.criterion_id}</span> {g.description} <span className="text-muted">— observed {g.observed}</span></span>
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-muted mt-3">AUTO_RESOLVE only when every criterion passes. Agent agreement is not a criterion: three agents agreeing on weak evidence still fails G1/G2.</p>
      </div>
    </div>
  )
}

/* ── Six agent reports ───────────────────────────────────────────────────── */
const AGENTS = [
  ['diagnostic_expert', '🧠', 'Diagnostic Expert', 'parallel'],
  ['pattern_agent', '🔍', 'Pattern Recognition', 'parallel'],
  ['aggressive_agent', '⚡', 'Rapid Triage', 'parallel · deterministic'],
  ['verification', '✅', 'Verification Analyst', 'adversarial review'],
  ['ambiguity', '🎯', 'Ambiguity Detection', 'uncertainty'],
  ['human_review_coordinator', '🏁', 'Human Review Coordinator', 'final + gate'],
]
export function AgentPanel({ harness, onEvidence }) {
  const agents = harness?.agents || {}
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {AGENTS.map(([k, emoji, name, role]) => {
        const a = agents[k]
        return (
          <article key={k} className="rounded-lg border border-line bg-white p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2"><span aria-hidden>{emoji}</span><span className="text-[13px] font-semibold">{name}</span></div>
              <span className="text-[10px] text-muted">{role}</span>
            </div>
            {!a ? <Empty>Not run.</Empty> : (
              <>
                <div className="mt-2 text-[13px] text-ink font-medium"><Cited text={a.finding} onEvidence={onEvidence} /></div>
                <div className="mt-1 flex items-center gap-2 text-[11px] text-muted">
                  <span>confidence {fmtNum(a.confidence, 2)}</span><span>·</span><span>{a.mode}</span><span>·</span><span>pass {a.pass_number}</span>
                  {a.claims_removed > 0 && <><span>·</span><span className="text-warning-700">{a.claims_removed} claim(s) removed</span></>}
                </div>
                <p className="mt-2 text-[12px] text-muted leading-relaxed"><Cited text={a.narrative} onEvidence={onEvidence} /></p>
                {a.supporting_evidence?.length > 0 && (
                  <ul className="mt-2 space-y-0.5 text-[12px]">
                    {a.supporting_evidence.slice(0, 4).map((s, i) => <li key={i} className="flex gap-1.5"><span className="text-success-600">+</span><Cited text={s.statement} onEvidence={onEvidence} /></li>)}
                    {a.contradicting_evidence?.slice(0, 2).map((s, i) => <li key={`c${i}`} className="flex gap-1.5"><span className="text-danger-600">−</span><Cited text={s.statement} onEvidence={onEvidence} /></li>)}
                    {a.missing_information?.slice(0, 2).map((s, i) => <li key={`m${i}`} className="flex gap-1.5 text-warning-700"><span>?</span>{s}</li>)}
                  </ul>
                )}
              </>
            )}
          </article>
        )
      })}
    </div>
  )
}

/* ── Sensor readings vs reference band ───────────────────────────────────── */
export function SensorPanel({ harness }) {
  const rows = harness?.sensor_view || []
  const notes = harness?.query_profile?.notes || []
  if (!rows.length) return <Empty>This dataset has no numeric sensor channels.</Empty>
  return (
    <div>
      <table className="w-full text-[12px]">
        <thead className="text-muted text-left"><tr><th className="py-1 font-medium">Channel</th><th className="font-medium">Reported</th><th className="font-medium w-1/2">Reference band</th><th className="font-medium">Status</th></tr></thead>
        <tbody>
          {rows.map((r) => {
            const lo = r.band_low, hi = r.band_high
            const span = hi - lo || 1
            const min = lo - span, max = hi + span
            const pos = r.value == null ? null : Math.max(0, Math.min(1, (r.value - min) / (max - min)))
            return (
              <tr key={r.sensor} className="border-t border-line">
                <td className="py-2 font-medium text-ink">{r.label} <span className="text-muted font-normal">{r.unit}</span></td>
                <td className={cx('tabular-nums', r.value == null && 'italic text-warning-700')}>{r.value == null ? 'unavailable' : fmtNum(r.value, 3)}</td>
                <td>
                  <div className="relative h-2 rounded bg-slate-100 mr-4" title={`band ${fmtNum(lo, 2)} – ${fmtNum(hi, 2)}`}>
                    <div className="absolute h-full rounded bg-success-100" style={{ left: '33.3%', width: '33.3%' }} />
                    {pos != null && <div className="absolute -top-1 w-1 h-4 rounded bg-ink" style={{ left: `calc(${pos * 100}% - 2px)` }} />}
                  </div>
                  <div className="flex justify-between text-[10px] text-muted mr-4 px-[30%]"><span>{fmtNum(lo, 2)}</span><span>{fmtNum(hi, 2)}</span></div>
                </td>
                <td className={cx('capitalize', r.status === 'high' || r.status === 'low' ? 'text-warning-700 font-semibold' : r.status === 'missing' ? 'text-warning-700' : 'text-muted')}>{r.status}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {notes.map((n, i) => <p key={i} className="text-[11px] text-warning-700 mt-2">Note: {n}</p>)}
      <p className="text-[11px] text-muted mt-2">Values are never imputed: a channel the user did not report stays unavailable throughout the pipeline.</p>
    </div>
  )
}

/* ── Audit trail, execution timeline, claim validation ────────────────────── */
export function AuditPanel({ harness }) {
  const tl = harness?.timeline || []
  const cv = harness?.claim_validation || {}
  const maxMs = Math.max(1, ...tl.map((t) => t.duration_ms || 0))
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <div className="xl:col-span-2">
        <div className="eyebrow mb-2">Execution timeline (measured)</div>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead className="text-muted text-left"><tr><th className="py-1 font-medium">#</th><th className="font-medium">Stage</th><th className="font-medium">Action</th><th className="font-medium w-40">Duration</th><th className="font-medium">Evidence</th></tr></thead>
            <tbody>{tl.map((t) => (
              <tr key={t.step} className="border-t border-line align-top">
                <td className="py-1.5 pr-2 text-muted tabular-nums">{t.step}</td>
                <td className="pr-2"><span className="inline-flex items-center gap-1"><StatusIcon status={t.status} size={12} />{t.stage}</span></td>
                <td className="pr-2"><div className="text-ink">{t.action}</div>{t.reason && <div className="text-[11px] text-muted max-w-md">{t.reason}</div>}</td>
                <td className="pr-2">
                  <div className="flex items-center gap-2"><div className="h-1.5 rounded bg-primary-500" style={{ width: `${Math.max(2, (t.duration_ms / maxMs) * 100)}px` }} /><span className="tabular-nums text-muted">{fmtNum(t.duration_ms, 1)} ms</span></div>
                </td>
                <td className="text-muted">{t.retrieval_count || (t.evidence_used?.length ?? 0) || ''}</td>
              </tr>))}
            </tbody>
          </table>
        </div>
      </div>
      <div>
        <div className="eyebrow mb-2">Claim validation</div>
        <div className="grid grid-cols-3 gap-2 text-center">
          {[['SUPPORTED', 'text-success-700'], ['DERIVED', 'text-primary-700'], ['UNSUPPORTED', 'text-danger-700']].map(([k, c]) => (
            <div key={k} className="rounded-lg border border-line p-2"><div className={cx('text-lg font-semibold tabular-nums', c)}>{cv[k] ?? 0}</div><div className="text-[10px] text-muted">{k}</div></div>
          ))}
        </div>
        <p className="text-[11px] text-muted mt-2">{cv.removed ?? 0} unsupported statement(s) removed before the final answer. Numbers must match the query, a retrieved record, a derived value (D-xxx) or a declared rule.</p>
        {cv.checks?.length > 0 && (
          <ul className="mt-2 space-y-1 text-[11px]">{cv.checks.slice(0, 8).map((c, i) => <li key={i} className="rounded border border-danger-100 bg-danger-50 px-2 py-1 text-danger-700"><span className="mono">{c.source}</span>: “{c.claim}” → {c.action}</li>)}</ul>
        )}
        <div className="eyebrow mt-4 mb-1">Derived values</div>
        <ul className="space-y-0.5 text-[11px] text-muted max-h-48 overflow-auto">
          {(harness?.derived_values || []).map((d) => <li key={d.derived_id}><span className="mono text-slate-600">{d.derived_id}</span> {d.description}{d.value != null && <> = <b className="text-ink">{fmtNum(d.value, 3)}</b></>}</li>)}
        </ul>
      </div>
    </div>
  )
}
