import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CheckCircle2, AlertTriangle, CircleDot, ChevronDown, ArrowUpRight, Wrench, ShieldAlert } from 'lucide-react'
import { cx, Cited, IdChip } from '../ui'
import { ProvenanceBar, ReviewDecision } from '../primitives'
import { AgentDetail } from '../agents/AgentCard'
import EvidenceExplorer from '../EvidenceExplorer'
import { VerificationDetail, FeedbackDetail, CouncilDetail, GateDetail } from '../diagnosis/details'
import { AgentHead, ConfBar, SubHead } from './StageColumn'
import { agentColor, AGENT_SHORT } from '../../lib/agentColors'

const FACTOR_LABEL = {
  evidence_quality: 'Evidence quality', hypothesis_separation: 'Separation from runner-up', historical_similarity: 'Historical similarity',
  data_completeness: 'Data completeness', contradictions: 'Free of contradictions', retrieval_quality: 'Retrieval quality',
  agent_agreement: 'Agent agreement', synthetic_reliance: 'Real-data support',
}
const byKey = (s, k) => s.agents.find((a) => a.key === k)

/* ── shared bits ───────────────────────────────────────────────────────── */
function Checks({ items, icon = 'ok', limit, onEvidence }) {
  if (!items?.length) return null
  const Icon = icon === 'ok' ? CheckCircle2 : icon === 'warn' ? AlertTriangle : CircleDot
  const tone = icon === 'ok' ? 'text-success-600' : icon === 'warn' ? 'text-warning-600' : 'text-danger-600'
  const shown = limit ? items.slice(0, limit) : items
  return (
    <ul className="space-y-1.5">
      {shown.map((t, i) => (
        <li key={i} className="flex gap-2 text-[12.5px] leading-snug text-ink">
          <Icon size={14} className={cx('mt-0.5 shrink-0', tone)} aria-hidden />
          <span className="min-w-0"><Cited text={typeof t === 'string' ? t : t.statement} onEvidence={onEvidence} /></span>
        </li>
      ))}
      {limit && items.length > limit && <li className="pl-6 text-[12px] text-muted">+{items.length - limit} more (maximize to see all)</li>}
    </ul>
  )
}

/** Two-column layout for full-width stage cards (Agent dashboard); stacks in narrow columns and maximized views. */
function Split({ wide, main, side }) {
  if (!wide) return <>{main}{side}</>
  return (
    <div className="grid gap-x-8 gap-y-1 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
      <div className="min-w-0">{main}</div>
      <div className="min-w-0 lg:border-l lg:border-line lg:pl-6">{side}</div>
    </div>
  )
}

function Narrative({ text, clamp = 4 }) {
  if (!text) return null
  const clampClass = { 2: 'line-clamp-2', 3: 'line-clamp-3', 4: 'line-clamp-4' }[clamp] // static names so Tailwind keeps them
  return <p className={cx('mt-2.5 text-[12.5px] leading-relaxed text-ink', clampClass)}><Cited text={text} /></p>
}

/* ── 1. Retrieved evidence ─────────────────────────────────────────────── */
function SensorRow({ r }) {
  const has = r.value != null
  const lo = r.band_low, hi = r.band_high
  const bandOk = lo != null && hi != null && hi > lo
  let pos = null, b0 = null, b1 = null
  if (has && bandOk) {
    const min = Math.min(lo, r.value), max = Math.max(hi, r.value), pad = (max - min) * 0.12 || 1
    const d0 = min - pad, d1 = max + pad, w = d1 - d0
    pos = ((r.value - d0) / w) * 100; b0 = ((lo - d0) / w) * 100; b1 = ((hi - d0) / w) * 100
  }
  const st = String(r.status || (has ? '' : 'missing')).toLowerCase()
  const tone = st === 'high' || st === 'low' ? 'text-danger-700' : st === 'missing' ? 'text-warning-700' : 'text-success-700'
  const fmt = (v) => (Math.abs(v) >= 100 ? Math.round(v) : Number(v.toFixed(Math.abs(v) < 1 ? 3 : 1)))
  return (
    <li className="py-1.5">
      <div className="flex items-baseline gap-2 text-[12.5px]">
        <span className="font-medium text-ink truncate">{r.label || r.sensor}</span>
        <span className="ml-auto tabular-nums text-ink">{has ? fmt(r.value) : '—'}<span className="text-muted text-[11px] ml-0.5">{r.unit && !r.unit.startsWith('(') ? r.unit : ''}</span></span>
        <span className={cx('w-14 text-right text-[11.5px] font-semibold', tone)}>{st || 'n/a'}</span>
      </div>
      {pos != null && (
        <div className="relative mt-1 h-1.5 rounded-full bg-well" title={`normal band ${fmt(lo)} – ${fmt(hi)}`}>
          <div className="absolute inset-y-0 rounded-full bg-success-100" style={{ left: `${b0}%`, width: `${b1 - b0}%` }} />
          <div className="absolute -top-0.5 -bottom-0.5 w-1 rounded-full" style={{ left: `calc(${pos}% - 2px)`, background: st === 'normal' ? '#4F5B45' : '#A9594E' }} />
        </div>
      )}
    </li>
  )
}

function labelCounts(evidence) {
  const m = {}
  evidence.forEach((e) => { if (e.label) m[e.label] = (m[e.label] || 0) + 1 })
  return Object.entries(m).sort((a, b) => b[1] - a[1])
}

export function EvidenceBody({ s, result, compact }) {
  const sensors = result.harness?.sensor_view || []
  const qp = result.harness?.query_profile || {}
  const counts = labelCounts(s.evidence)
  return (
    <>
      {compact ? null : sensors.length ? (
        <>
          <SubHead>Reported readings vs normal band</SubHead>
          <ul className="divide-y divide-line/70">{sensors.map((r) => <SensorRow key={r.sensor} r={r} />)}</ul>
        </>
      ) : <p className="text-[12.5px] text-muted">No numeric sensor readings in the question; retrieval used the text only.</p>}
      {qp.missing_sensors?.length > 0 && <p className="mt-1.5 text-[12px] text-warning-700">Not reported: {qp.missing_sensors.join(', ')}</p>}
      <SubHead tone={compact ? 'text-ink mt-0' : undefined}>{s.evidenceCount} evidence records retrieved</SubHead>
      <ProvenanceBar composition={s.provenance} />
      {counts.length > 0 && (
        <>
          <SubHead>What the records point to</SubHead>
          <ul className="space-y-1">
            {counts.slice(0, 4).map(([label, n]) => (
              <li key={label} className="grid grid-cols-[minmax(0,1fr)_60px_20px] items-center gap-2 text-[12px]">
                <span className="truncate text-ink first-letter:uppercase">{label}</span>
                <span className="h-1.5 rounded-full bg-well overflow-hidden"><span className="block h-full bg-primary-500" style={{ width: `${(n / s.evidence.length) * 100}%` }} /></span>
                <span className="tabular-nums text-right text-muted">{n}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <SubHead>Context</SubHead>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[12px]">
        {qp.equipment_phrase && <><dt className="text-muted">Asset</dt><dd className="text-ink truncate" title={qp.equipment_phrase}>{qp.equipment_phrase}</dd></>}
        {qp.equipment_type && <><dt className="text-muted">Type</dt><dd className="text-ink">{qp.equipment_type}</dd></>}
        <dt className="text-muted">Mode</dt><dd className="text-ink">{s.dataMode} data</dd>
        {result.harness?.retrieval?.scheme && <><dt className="text-muted">Retrieval</dt><dd className="text-ink">{result.harness.retrieval.scheme} scheme</dd></>}
      </dl>
    </>
  )
}

export function EvidenceFull({ s, result }) {
  return (
    <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
      <div className="card p-5 self-start"><EvidenceBody s={s} result={result} /></div>
      <div className="card p-5 min-w-0"><EvidenceExplorer harness={result.harness} /></div>
    </div>
  )
}

/* ── 2. Initial agent analysis (three independent agents in one box) ──── */
export const INITIAL_KEYS = ['diagnostic_expert', 'pattern_agent', 'aggressive_agent']

function InitialAgent({ agent }) {
  const [open, setOpen] = useState(false)
  const color = agentColor(agent.key)
  return (
    <article className="rounded-lg border border-line bg-surface p-3" style={{ borderLeft: `3px solid ${color}` }}>
      <AgentHead agent={agent} compact />
      <p className="mt-2 text-[13px] font-semibold text-ink first-letter:uppercase">{agent.summary || 'No finding'}</p>
      <Narrative text={agent.narrative} clamp={open ? 0 : 3} />
      {agent.evidenceIds.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1 text-[11.5px]">
          <span className="text-muted mr-0.5">Key evidence</span>
          {agent.evidenceIds.slice(0, open ? 99 : 4).map((id) => <IdChip key={id} id={id} />)}
          {!open && agent.evidenceIds.length > 4 && <span className="text-muted">+{agent.evidenceIds.length - 4}</span>}
        </div>
      )}
      {open && <div className="mt-2.5 border-t border-line pt-2.5"><AgentDetail agent={{ ...agent, narrative: null, evidenceIds: [] }} limit={6} /></div>}
      <ConfBar value={agent.confidence} color={color} />
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-ink rounded focus-ring">
        <ChevronDown size={13} className={cx('transition-transform', open && 'rotate-180')} aria-hidden /> {open ? 'Show less' : 'Show reasoning'}
      </button>
    </article>
  )
}

export function InitialBody({ s, horizontal }) {
  const agents = INITIAL_KEYS.map((k) => byKey(s, k)).filter(Boolean)
  if (!agents.length) return <p className="text-[12.5px] text-muted">No first-pass agent results in this response.</p>
  return (
    <div className={horizontal ? 'grid items-start gap-3 md:grid-cols-3' : 'space-y-2.5'}>
      {agents.map((a) => <InitialAgent key={a.key} agent={a} />)}
    </div>
  )
}

export function InitialFull({ s }) {
  const agents = INITIAL_KEYS.map((k) => byKey(s, k)).filter(Boolean)
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      {agents.map((a) => (
        <article key={a.key} className="card p-5" style={{ boxShadow: `inset 0 3px 0 ${agentColor(a.key)}` }}>
          <AgentHead agent={a} />
          {a.purpose && <p className="mt-2 text-[12.5px] text-muted">{a.purpose}</p>}
          <p className="mt-3 text-[15px] font-semibold first-letter:uppercase">{a.summary}</p>
          <ConfBar value={a.confidence} color={agentColor(a.key)} />
          <div className="mt-4"><AgentDetail agent={a} limit={50} /></div>
          {a.hypotheses?.length > 0 && (
            <>
              <SubHead>Hypotheses considered</SubHead>
              <ul className="space-y-1 text-[12.5px]">
                {a.hypotheses.map((h, i) => <li key={i} className="flex justify-between gap-2"><span className="first-letter:uppercase">{h.label}</span><span className="tabular-nums text-muted">{h.score?.toFixed?.(2)}</span></li>)}
              </ul>
            </>
          )}
        </article>
      ))}
    </div>
  )
}

/* ── 3. Verification ───────────────────────────────────────────────────── */
export function VerificationBody({ s, wide }) {
  const a = byKey(s, 'verification')
  const v = s.verification || {}
  const ar = v.adversarial_review || {}
  const confounders = [...(ar.what_contradicts_it || []), ...(ar.what_is_missing || [])]
  const main = (
    <>
      {a ? <AgentHead agent={a} /> : null}
      <p className="mt-2.5 text-[13px] text-ink">
        {v.verified_label ? <>The evidence supports <b className="font-semibold">{v.verified_label}</b>{v.margin != null && <> (margin {v.margin.toFixed(2)})</>}.</> : 'No verified hypothesis.'}
        {v.agents_disagree && <span className="text-warning-700"> First-pass agents disagree.</span>}
      </p>
      {ar.what_supports_it?.length > 0 && <><SubHead>Supporting evidence</SubHead><Checks items={ar.what_supports_it} limit={4} /></>}
    </>
  )
  const side = (
    <>
      <SubHead>Potential confounders</SubHead>
      {confounders.length ? <Checks items={confounders} icon="warn" limit={3} /> : <p className="text-[12.5px] text-muted">None found in the evidence.</p>}
      {ar.alternative_explanation && <p className="mt-2 text-[12px] text-muted"><span className="font-medium text-ink">Alternative:</span> {ar.alternative_explanation}</p>}
      {s.claims && (
        <p className="mt-2 text-[12px] text-ink">
          <b className="font-semibold tabular-nums">{s.claims.SUPPORTED + (s.claims.DERIVED || 0)}/{s.claims.total_claims}</b> final claims backed by evidence
          {s.claims.removed ? <span className="text-warning-700">, {s.claims.removed} removed</span> : ''}
        </p>
      )}
      {(s.feedbackRounds > 0 || s.extraRetrieval.length > 0) && (
        <p className="mt-1 text-[12px] text-warning-700">Feedback loop: {s.extraRetrieval.length} targeted retrieval(s), {s.feedbackRounds} round(s)</p>
      )}
      {a && <ConfBar value={a.confidence} color={agentColor('verification')} />}
    </>
  )
  return <Split wide={wide} main={main} side={side} />
}

export function VerificationFull({ s }) {
  const a = byKey(s, 'verification')
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <div className="card p-5">{a && <><AgentHead agent={a} /><div className="mt-4"><AgentDetail agent={a} limit={50} /></div><ConfBar value={a.confidence} color={agentColor('verification')} /></>}</div>
      <div className="space-y-5">
        <div className="card p-5"><h3 className="section-title mb-3">Adversarial review and claim validation</h3><VerificationDetail s={s} /></div>
        <div className="card p-5"><h3 className="section-title mb-3">Evidence check and targeted retrieval</h3><FeedbackDetail s={s} /></div>
      </div>
    </div>
  )
}

/* ── 4. Ambiguity assessment ───────────────────────────────────────────── */
function questions(result) {
  return (result.harness?.messages || []).filter((m) => m.kind === 'QUESTION')
}

export function AmbiguityBody({ s, result, wide }) {
  const a = byKey(s, 'ambiguity')
  const amb = s.ambiguity || {}
  const alts = (result.harness?.hypothesis_scores || []).filter((h) => h.label !== s.label).slice(0, 3)
  const qs = questions(result)
  const factors = [...s.confidenceFactors].sort((x, y) => x.value - y.value).slice(0, 3)
  const level = amb.ambiguity_level
  const openQuestions = qs.length > 0 && (
    <>
      <SubHead>Open questions raised</SubHead>
      <ul className="space-y-1.5">
        {qs.slice(0, 3).map((m) => (
          <li key={m.message_id} className="flex gap-2 text-[12.5px] leading-snug">
            <CircleDot size={13} className={cx('mt-0.5 shrink-0', m.resolved ? 'text-success-600' : 'text-warning-600')} aria-label={m.resolved ? 'resolved' : 'open'} />
            <span className="line-clamp-2">{m.text}</span>
          </li>
        ))}
        {qs.length > 3 && <li className="pl-5 text-[12px] text-muted">+{qs.length - 3} more</li>}
      </ul>
    </>
  )
  const main = (
    <>
      {a && <AgentHead agent={a} />}
      {level && (
        <p className="mt-2.5 text-[13px] text-ink">
          Ambiguity level <b className={cx('font-semibold', level === 'LOW' ? 'text-success-700' : level === 'HIGH' ? 'text-danger-700' : 'text-warning-700')}>{level.toLowerCase()}</b>.
        </p>
      )}
      <SubHead>Uncertainty sources</SubHead>
      {amb.flags?.length ? <Checks items={amb.flags.map((f) => f.replace(/^[A-Z_]+:\s*/, ''))} icon="risk" limit={3} />
        : <p className="text-[12.5px] text-muted">No material uncertainty source detected.</p>}
      {wide && openQuestions}
    </>
  )
  const side = (
    <>
      {factors.length > 0 && (
        <>
          <SubHead>Weakest confidence factors</SubHead>
          <ul className="space-y-1">
            {factors.map((f) => (
              <li key={f.name} className="grid grid-cols-[minmax(0,1fr)_56px_32px] items-center gap-2 text-[12px]" title={f.explanation}>
                <span className="truncate text-ink">{FACTOR_LABEL[f.name] || f.name}</span>
                <span className="h-1.5 rounded-full bg-well overflow-hidden"><span className={cx('block h-full', f.value >= 0.8 ? 'bg-success-500' : f.value >= 0.5 ? 'bg-warning-500' : 'bg-danger-500')} style={{ width: `${f.value * 100}%` }} /></span>
                <span className="tabular-nums text-right text-muted">{f.value.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {alts.length > 0 && (
        <>
          <SubHead>Plausible alternatives</SubHead>
          <ul className="space-y-0.5 text-[12.5px]">
            {alts.map((h) => <li key={h.label} className="flex justify-between gap-2"><span className="truncate first-letter:uppercase">{h.label}</span><span className="tabular-nums text-muted">{h.score.toFixed(2)}</span></li>)}
          </ul>
        </>
      )}
      {!wide && openQuestions}
      {a && <ConfBar value={a.confidence} color={agentColor('ambiguity')} label="Measured confidence" />}
    </>
  )
  return <Split wide={wide} main={main} side={side} />
}

export function AmbiguityFull({ s, result }) {
  const msgs = result.harness?.messages || []
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <div className="card p-5"><AmbiguityBody s={s} result={result} /></div>
      <div className="space-y-5">
        <div className="card p-5">
          <h3 className="section-title mb-3">All confidence factors</h3>
          <ul className="space-y-2">
            {s.confidenceFactors.map((f) => (
              <li key={f.name} className="text-[12.5px]">
                <div className="flex justify-between"><span className="font-medium">{FACTOR_LABEL[f.name] || f.name}</span><span className="tabular-nums">{f.value.toFixed(2)}</span></div>
                <div className="text-muted">{f.explanation}</div>
              </li>
            ))}
          </ul>
        </div>
        {s.council && <div className="card p-5"><h3 className="section-title mb-3">Agent council</h3><CouncilDetail s={s} /></div>}
        {msgs.length > 0 && (
          <div className="card p-5">
            <h3 className="section-title mb-3">Council messages ({msgs.length})</h3>
            <ol className="space-y-2.5">
              {msgs.map((m) => (
                <li key={m.message_id} className="text-[12.5px] leading-snug" style={{ borderLeft: `3px solid ${agentColor(m.sender)}`, paddingLeft: 10 }}>
                  <div className="text-[11.5px] text-muted"><b className="font-semibold" style={{ color: agentColor(m.sender) }}>{AGENT_SHORT[m.sender] || m.sender}</b> · {m.kind.toLowerCase().replaceAll('_', ' ')} · round {m.round}{m.resolved === true ? ' · resolved' : m.resolved === false ? ' · open' : ''}</div>
                  <Cited text={m.text} />
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── 5. Final recommendation ───────────────────────────────────────────── */
export function FinalBody({ s, runId, wide }) {
  const nav = useNavigate()
  const a = byKey(s, 'human_review_coordinator')
  const failing = s.criteria.filter((c) => !c.passed)
  const main = (
    <>
      {a && <AgentHead agent={a} />}
      <p className="mt-3 text-[20px] leading-tight font-semibold text-ink first-letter:uppercase">{s.label || s.answer}</p>
      {s.answer && <p className="mt-1.5 text-[13px] text-ink">{s.answer}</p>}
      <Narrative text={s.explanation} clamp={3} />
      {s.recommendation && (
        <>
          <SubHead>Recommendation</SubHead>
          <p className="flex gap-2 text-[12.5px] leading-snug text-ink"><Wrench size={14} className="mt-0.5 shrink-0" style={{ color: agentColor('human_review_coordinator') }} aria-hidden /><span className="line-clamp-4"><Cited text={s.recommendation} /></span></p>
        </>
      )}
    </>
  )
  const side = (
    <>
      <SubHead>Human-review gate</SubHead>
      <div className="flex items-center gap-3">
        <ReviewDecision decision={s.decision} variant="inline" />
        <span className="text-[12px] text-muted tabular-nums">{s.criteriaPassed}/{s.criteria.length} criteria passed</span>
      </div>
      {failing.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 text-[12px] text-warning-700">
          {failing.map((c) => <li key={c.criterion_id} className="flex gap-1.5"><ShieldAlert size={12} className="mt-0.5 shrink-0" aria-hidden />{c.description} <span className="text-muted">({c.observed})</span></li>)}
        </ul>
      )}
      <ConfBar value={s.confidence} color={agentColor('human_review_coordinator')} label="Final confidence" />
      <button type="button" onClick={() => nav(`/chat#run-${runId}`)}
        className="mt-3 w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-line bg-canvas px-3 py-2 text-[12.5px] font-medium text-ink hover:border-slate-400 focus-ring">
        Open full response in chat <ArrowUpRight size={14} aria-hidden />
      </button>
    </>
  )
  return <Split wide={wide} main={main} side={side} />
}

export function FinalFull({ s, runId }) {
  const a = byKey(s, 'human_review_coordinator')
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
      <div className="card p-6">
        <FinalBody s={s} runId={runId} />
        {a && <div className="mt-5 border-t border-line pt-4"><AgentDetail agent={{ ...a, narrative: null }} limit={50} /></div>}
      </div>
      <div className="space-y-5">
        <div className="card p-5"><h3 className="section-title mb-3">Gate criteria</h3><GateDetail s={s} /></div>
        {s.reasoning.length > 0 && (
          <div className="card p-5">
            <h3 className="section-title mb-3">How the answer was reached</h3>
            <ol className="space-y-1.5 text-[12.5px] leading-snug">{s.reasoning.map((r, i) => <li key={i}><Cited text={r} /></li>)}</ol>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── compact stage cards (Agent dashboard) ─────────────────────────────────
   Short versions in the Decision Explorer style: agent + verdict on the left,
   confidence and the key numbers on the right. Maximize shows the full stage. */
function CompactRow({ main, side }) {
  return (
    <div className="grid gap-x-6 gap-y-2 md:grid-cols-[minmax(0,1fr)_240px]">
      <div className="min-w-0 space-y-1.5">{main}</div>
      <div className="min-w-0 md:border-l md:border-line md:pl-4 space-y-1.5">{side}</div>
    </div>
  )
}
function Count({ icon: Icon, n, label, tone }) {
  return <span className="inline-flex items-center gap-1 whitespace-nowrap text-[12px] text-ink"><Icon size={13} className={cx('shrink-0', n ? tone : 'text-slate-300')} aria-hidden />{n} {label}</span>
}

export function VerificationCompact({ s }) {
  const a = byKey(s, 'verification')
  const v = s.verification || {}
  const ar = v.adversarial_review || {}
  return (
    <CompactRow
      main={<>
        {a && <AgentHead agent={a} compact />}
        <p className="text-[13px] text-ink">
          {v.verified_label ? <>Evidence supports <b className="font-semibold">{v.verified_label}</b>{v.margin != null && <> (margin {v.margin.toFixed(2)})</>}.</> : 'No verified hypothesis.'}
          {v.agents_disagree && <span className="text-warning-700"> First-pass agents disagree.</span>}
        </p>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <Count icon={CheckCircle2} n={ar.what_supports_it?.length || 0} label="supporting" tone="text-success-600" />
          <Count icon={AlertTriangle} n={ar.what_contradicts_it?.length || 0} label="contradicting" tone="text-danger-600" />
          <Count icon={CircleDot} n={ar.what_is_missing?.length || 0} label="missing" tone="text-warning-600" />
        </div>
        {ar.alternative_explanation && <p className="text-[12px] text-muted line-clamp-1" title={ar.alternative_explanation}><span className="font-medium text-ink">Alternative:</span> {ar.alternative_explanation}</p>}
      </>}
      side={<>
        {a && <ConfBar value={a.confidence} color={agentColor('verification')} />}
        {s.claims && <p className="text-[12px] text-ink"><b className="font-semibold tabular-nums">{s.claims.SUPPORTED + (s.claims.DERIVED || 0)}/{s.claims.total_claims}</b> final claims evidence-backed</p>}
        {(s.feedbackRounds > 0) && <p className="text-[12px] text-warning-700">Feedback loop: {s.feedbackRounds} round(s)</p>}
      </>}
    />
  )
}

export function AmbiguityCompact({ s, result }) {
  const a = byKey(s, 'ambiguity')
  const amb = s.ambiguity || {}
  const level = amb.ambiguity_level
  const flags = (amb.flags || []).map((f) => f.replace(/^[A-Z_]+:\s*/, ''))
  const weakest = [...s.confidenceFactors].sort((x, y) => x.value - y.value)[0]
  const alts = (result.harness?.hypothesis_scores || []).filter((h) => h.label !== s.label).slice(0, 2)
  return (
    <CompactRow
      main={<>
        {a && <AgentHead agent={a} compact />}
        {level && <p className="text-[13px] text-ink">Ambiguity level <b className={cx('font-semibold', level === 'LOW' ? 'text-success-700' : level === 'HIGH' ? 'text-danger-700' : 'text-warning-700')}>{level.toLowerCase()}</b>{flags.length ? <span className="text-muted"> · {flags.length} uncertainty source(s)</span> : <span className="text-muted"> · no material uncertainty source</span>}</p>}
        {flags.length > 0 && <Checks items={flags} icon="risk" limit={2} />}
      </>}
      side={<>
        {a && <ConfBar value={a.confidence} color={agentColor('ambiguity')} label="Measured confidence" />}
        {weakest && <p className="text-[12px] text-ink" title={weakest.explanation}>Weakest factor: <span className="font-medium">{(FACTOR_LABEL[weakest.name] || weakest.name).toLowerCase()}</span> <span className="tabular-nums text-muted">{weakest.value.toFixed(2)}</span></p>}
        {alts.length > 0 && <p className="text-[12px] text-muted truncate" title={alts.map((h) => `${h.label} ${h.score.toFixed(2)}`).join(', ')}>Alternatives: {alts.map((h) => `${h.label} ${h.score.toFixed(2)}`).join(', ')}</p>}
      </>}
    />
  )
}

export function FinalCompact({ s, runId }) {
  const nav = useNavigate()
  const a = byKey(s, 'human_review_coordinator')
  const failing = s.criteria.filter((c) => !c.passed)
  return (
    <CompactRow
      main={<>
        {a && <AgentHead agent={a} compact />}
        <p className="text-[17px] leading-tight font-semibold text-ink first-letter:uppercase">{s.label || s.answer}</p>
        {s.answer && <p className="text-[12.5px] text-ink line-clamp-2">{s.answer}</p>}
        {s.recommendation && <p className="flex gap-2 text-[12px] leading-snug text-muted"><Wrench size={13} className="mt-0.5 shrink-0" style={{ color: agentColor('human_review_coordinator') }} aria-hidden /><span className="line-clamp-2"><Cited text={s.recommendation} /></span></p>}
      </>}
      side={<>
        <div className="flex flex-wrap items-center gap-2">
          <ReviewDecision decision={s.decision} variant="inline" />
          <span className="text-[12px] text-muted tabular-nums">{s.criteriaPassed}/{s.criteria.length} criteria</span>
        </div>
        {failing.slice(0, 2).map((c) => <p key={c.criterion_id} className="flex gap-1.5 text-[11.5px] text-warning-700"><ShieldAlert size={12} className="mt-0.5 shrink-0" aria-hidden /><span className="line-clamp-1" title={c.description}>{c.description}</span></p>)}
        {failing.length > 2 && <p className="pl-5 text-[11.5px] text-muted">+{failing.length - 2} more</p>}
        <ConfBar value={s.confidence} color={agentColor('human_review_coordinator')} label="Final confidence" />
        <button type="button" onClick={() => nav(`/chat#run-${runId}`)}
          className="inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-ink rounded focus-ring">
          Open full response in chat <ArrowUpRight size={13} aria-hidden />
        </button>
      </>}
    />
  )
}
