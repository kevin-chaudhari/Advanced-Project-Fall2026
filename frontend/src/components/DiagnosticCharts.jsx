import { CheckCircle2, ShieldAlert, XCircle } from 'lucide-react'
import { cx, fmtNum, pct, Empty } from './ui'

/*
 * Two compact charts for the Decision Explorer side column.
 * Both read only fields already present in the /query response (`result.harness`):
 *   - SensorHealthChart        ← harness.sensor_view   (built by the orchestrator from the parsed question)
 *   - HypothesisComparisonChart ← harness.hypothesis_scores + harness.review (gate criteria)
 * Nothing is imputed or estimated here: a channel without a reported number is drawn as such,
 * and the review margin is the gate's own observed value.
 */

/* ── Sensor health ───────────────────────────────────────────────────────── */

// status values emitted by the backend: normal | high | low | unknown | missing | not reported | reported high | reported low
const classify = (r) => {
  if (r.status === 'missing') return 'missing'
  if (r.value == null) return r.status?.startsWith('reported') ? 'qualitative' : 'unreported'
  if (r.status === 'high' || r.status === 'low') return 'out'
  if (r.status === 'normal') return 'in'
  return 'noref'
}

const KIND = {
  in: { text: 'In band', dot: 'bg-success-600', tone: 'text-success-700' },
  out: { text: 'Out of band', dot: 'bg-warning-500', tone: 'text-warning-700' },
  noref: { text: 'No reference', dot: 'bg-slate-400', tone: 'text-muted' },
  missing: { text: 'Unavailable', dot: 'bg-danger-600', tone: 'text-danger-700' },
  qualitative: { text: 'Described only', dot: 'bg-secondary-600', tone: 'text-secondary-700' },
  unreported: { text: 'Not reported', dot: 'bg-slate-300', tone: 'text-muted' },
}

const DECIMALS = { temperature: 1, vibration: 3, pressure: 1, rpm: 0, current: 1, voltage: 1, flow_rate: 1 }
const unitShort = (u) => (u === '(norm. index)' ? '' : u || '')

function SensorRow({ r }) {
  const kind = classify(r)
  const lo = r.band_low, hi = r.band_high
  const hasBand = lo != null && hi != null && Number.isFinite(lo) && Number.isFinite(hi)
  const span = hasBand ? (hi - lo || Math.abs(hi) || 1) : 1
  // Track shows the reference band in the middle third, with one band-width of margin on each side.
  const min = hasBand ? lo - span : 0, max = hasBand ? hi + span : 1
  const raw = r.value != null && hasBand ? (r.value - min) / (max - min) : null
  const pos = raw == null ? null : Math.max(0, Math.min(1, raw))
  const clipped = raw != null && (raw < 0 || raw > 1)
  const d = DECIMALS[r.sensor] ?? 2
  const valueText = r.value == null ? null : `${fmtNum(r.value, d)}${unitShort(r.unit) ? ` ${unitShort(r.unit)}` : ''}`
  const bandText = hasBand ? `reference band ${fmtNum(lo, d)}–${fmtNum(hi, d)}` : 'no reference band'
  const tip = r.value != null
    ? `${r.label}: ${valueText} — ${r.status === 'high' ? 'above' : r.status === 'low' ? 'below' : r.status === 'normal' ? 'inside' : 'not compared to'} ${bandText}`
    : `${r.label}: ${kind === 'missing' ? 'reported unavailable — value not imputed' : kind === 'qualitative' ? `${r.status} (no number given)` : 'not mentioned in the question'}`

  return (
    <li className="grid grid-cols-[minmax(64px,84px)_minmax(0,1fr)_minmax(56px,auto)] items-center gap-x-2 py-[3px]" title={tip} aria-label={tip}>
      <span className="text-[11.5px] text-ink truncate">{r.label}</span>
      <div className="relative h-3.5" aria-hidden>
        {kind === 'missing' ? (
          <div className="absolute inset-y-[3px] inset-x-0 rounded border border-dashed border-danger-600/50"
            style={{ backgroundImage: 'repeating-linear-gradient(135deg, rgba(220,38,38,.14) 0 3px, transparent 3px 7px)' }} />
        ) : kind === 'unreported' || kind === 'qualitative' ? (
          <div className="absolute inset-y-[5px] inset-x-0 rounded border border-dashed border-slate-300" />
        ) : (
          <>
            <div className="absolute inset-y-[5px] inset-x-0 rounded bg-slate-100" />
            {hasBand && <div className="absolute inset-y-[5px] rounded bg-success-100" style={{ left: '33.333%', width: '33.333%' }} />}
            {pos != null && (
              <div className={cx('absolute top-0 h-3.5 w-1.5 rounded-sm ring-2 ring-white', KIND[kind].dot)}
                style={{ left: `calc(${pos * 100}% - 3px)` }} />
            )}
            {clipped && (
              <span className={cx('absolute -top-[1px] text-[9px] font-bold', KIND[kind].tone)} style={raw > 1 ? { right: -2 } : { left: -2 }}>
                {raw > 1 ? '›' : '‹'}
              </span>
            )}
          </>
        )}
        {kind === 'qualitative' && (
          <span className="absolute inset-0 flex items-center justify-center text-[9.5px] text-secondary-700">{r.status}</span>
        )}
      </div>
      <span className={cx('text-right text-[11px] tabular-nums whitespace-nowrap', r.value == null ? cx('italic', KIND[kind].tone) : kind === 'out' ? 'font-semibold text-warning-700' : 'text-ink')}>
        {r.value != null ? valueText : kind === 'missing' ? 'unavailable' : kind === 'qualitative' ? 'no value' : '—'}
      </span>
    </li>
  )
}

export function SensorHealthChart({ harness }) {
  const rows = harness?.sensor_view || []
  if (!rows.length) return <Empty>This knowledge base has no numeric sensor channels, so there is nothing to chart.</Empty>
  const counts = rows.reduce((acc, r) => { const k = classify(r); acc[k] = (acc[k] || 0) + 1; return acc }, {})
  const reported = (counts.in || 0) + (counts.out || 0) + (counts.noref || 0)
  const order = ['in', 'out', 'noref', 'missing', 'qualitative', 'unreported']
  return (
    <figure className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] text-muted">{reported}/{rows.length} channels with a numeric reading</span>
      </div>
      {/* stacked coverage strip */}
      <div className="flex h-1.5 overflow-hidden rounded-full bg-slate-100" role="img"
        aria-label={order.filter((k) => counts[k]).map((k) => `${counts[k]} ${KIND[k].text.toLowerCase()}`).join(', ')}>
        {order.filter((k) => counts[k]).map((k) => (
          <div key={k} className={KIND[k].dot} style={{ width: `${(counts[k] / rows.length) * 100}%` }} title={`${KIND[k].text}: ${counts[k]}`} />
        ))}
      </div>
      <ul className="pt-0.5" aria-label="Sensor channels against reference band">
        {rows.map((r) => <SensorRow key={r.sensor} r={r} />)}
      </ul>
      <figcaption className="flex flex-wrap gap-x-2.5 gap-y-1 pt-1 text-[10.5px] text-muted">
        {order.filter((k) => counts[k]).map((k) => (
          <span key={k} className="inline-flex items-center gap-1">
            <span className={cx('h-2 w-2 rounded-sm', KIND[k].dot)} aria-hidden />{KIND[k].text} {counts[k]}
          </span>
        ))}
      </figcaption>
      <p className="text-[10.5px] leading-snug text-muted">
        Green zone = reference band from the knowledge base. Unavailable channels are never imputed and are not treated as healthy.
      </p>
    </figure>
  )
}

/* ── Fault hypothesis comparison ─────────────────────────────────────────── */

const MAX_BARS = 5
const niceMax = (v) => {
  const steps = [0.1, 0.2, 0.4, 0.5, 0.6, 0.8, 1]
  return steps.find((s) => s >= v - 1e-9) ?? Math.ceil(v * 10) / 10
}
const thresholdOf = (crit) => {
  const m = crit?.description?.match(/(\d+(?:\.\d+)?)\s*$/) || crit?.description?.match(/≥\s*(\d+(?:\.\d+)?)/)
  return m ? Number(m[1]) : null
}

function GateLine({ crit, label }) {
  if (!crit) return null
  return (
    <div className="flex items-start gap-1.5 text-[11px]" title={crit.description}>
      {crit.passed ? <CheckCircle2 size={12} className="mt-[1px] shrink-0 text-success-600" /> : <XCircle size={12} className="mt-[1px] shrink-0 text-danger-600" />}
      <span className="min-w-0">
        <span className="mono text-[10.5px] text-muted">{crit.criterion_id}</span> <span className="text-ink">{label}</span>{' '}
        <span className="text-muted">observed <b className={cx('tabular-nums', crit.passed ? 'text-ink' : 'text-danger-700')}>{crit.observed}</b>
          {thresholdOf(crit) != null && <> · needs ≥ {thresholdOf(crit).toFixed(2)}</>}</span>
      </span>
    </div>
  )
}

export function HypothesisComparisonChart({ harness, decision }) {
  const scores = (harness?.hypothesis_scores || []).filter((s) => s && Number.isFinite(s.score))
  const criteria = harness?.review?.criteria || []
  const g1 = criteria.find((c) => c.criterion_id === 'G1')
  const g2 = criteria.find((c) => c.criterion_id === 'G2')
  const reviewRequired = decision ? decision !== 'AUTO_RESOLVE' : null

  if (!scores.length) {
    return (
      <div className="space-y-2">
        <Empty>No fault hypotheses were scored for this run, so there is nothing to compare.</Empty>
        {reviewRequired && <ReviewNote required g1={g1} g2={g2} />}
      </div>
    )
  }

  const sorted = [...scores].sort((a, b) => b.score - a.score)
  const shown = sorted.slice(0, MAX_BARS)
  const leader = sorted[0]
  const runner = sorted[1]
  const gap = runner ? leader.score - runner.score : null
  const max = niceMax(Math.max(...shown.map((s) => s.score), 0.0001))
  const verified = harness?.verification?.verified_label
  const final = harness?.predicted_label
  const ticks = [0, max / 2, max]

  return (
    <figure className="space-y-2">
      <ul className="space-y-1.5" aria-label="Normalised hypothesis evidence scores">
        {shown.map((s, i) => {
          const isLead = i === 0
          const comp = Object.entries(s.components || {}).map(([k, v]) => `${k.replaceAll('_', ' ')} ${v}`).join(' · ')
          const tip = `${s.label}: score ${s.score.toFixed(3)} (${pct(s.score)} of total)${comp ? ` — ${comp}` : ''}`
          return (
            <li key={s.label} title={tip} aria-label={tip}>
              <div className="flex items-center justify-between gap-2 text-[11.5px]">
                <span className={cx('min-w-0 truncate', isLead ? 'font-semibold text-ink' : 'text-ink')}>
                  {s.label}
                  {s.label === final && <span className="ml-1.5 align-middle text-[9.5px] font-semibold text-primary-700">FINAL</span>}
                  {s.label === verified && s.label !== final && <span className="ml-1.5 align-middle text-[9.5px] font-semibold text-secondary-700">VERIFIED</span>}
                </span>
                <span className="tabular-nums text-muted shrink-0">{s.score.toFixed(3)}</span>
              </div>
              <div className="relative mt-0.5 h-2 rounded-r bg-slate-100">
                <div className={cx('h-full rounded-r', isLead ? 'bg-primary-600' : 'bg-slate-400')} style={{ width: `${Math.min(100, (s.score / max) * 100)}%` }} />
                {isLead && runner && (
                  <div className="absolute -top-0.5 h-3 w-0.5 rounded bg-ink/70" style={{ left: `calc(${Math.min(100, (runner.score / max) * 100)}% - 1px)` }}
                    title={`Runner-up (${runner.label}) at ${runner.score.toFixed(3)}`} aria-hidden />
                )}
              </div>
            </li>
          )
        })}
      </ul>
      <div className="flex justify-between text-[9.5px] tabular-nums text-muted" aria-hidden>
        {ticks.map((t, i) => <span key={i}>{t.toFixed(2)}</span>)}
      </div>
      {runner && (
        <div className="flex items-center gap-1.5 text-[10.5px] text-muted" aria-hidden>
          <span className="inline-block h-2.5 w-0.5 rounded bg-ink/70" /> runner-up score, marked on the leading bar
        </div>
      )}
      {sorted.length > MAX_BARS && <p className="text-[10.5px] text-muted">+{sorted.length - MAX_BARS} lower-scoring hypotheses not shown (see Detailed report).</p>}

      {gap != null && (
        <div className="rounded-lg border border-line bg-slate-50 px-2.5 py-1.5 text-[11px]">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-muted">Lead over runner-up</span>
            <b className="tabular-nums text-ink">+{gap.toFixed(3)}</b>
          </div>
          <div className="text-[10.5px] text-muted truncate" title={`${leader.label} vs ${runner.label}`}>{leader.label} vs {runner.label}</div>
        </div>
      )}

      <div className="space-y-1 pt-0.5">
        <GateLine crit={g1} label="confidence" />
        <GateLine crit={g2} label="separation margin" />
      </div>
      {reviewRequired != null && <ReviewNote required={reviewRequired} g1={g1} g2={g2} />}
      <figcaption className="text-[10.5px] leading-snug text-muted">
        Scores are the harness's normalised evidence scores (they sum to 1 across candidates), not probabilities. The gate values come from the review gate.
      </figcaption>
    </figure>
  )
}

function ReviewNote({ required, g1, g2 }) {
  const close = g2 && !g2.passed
  const low = g1 && !g1.passed
  if (!required) {
    return (
      <div className="flex items-center gap-1.5 rounded-lg border border-success-100 bg-success-50 px-2.5 py-1.5 text-[11px] text-success-700">
        <CheckCircle2 size={12} className="shrink-0" /> All gate criteria passed: auto-resolved
      </div>
    )
  }
  return (
    <div className="flex items-start gap-1.5 rounded-lg border border-warning-100 bg-warning-50 px-2.5 py-1.5 text-[11px] text-warning-700">
      <ShieldAlert size={12} className="mt-[1px] shrink-0" />
      <span><b>Human review required.</b>{' '}
        {low && close ? 'Confidence is low and the leading hypotheses are too close.'
          : low ? 'Confidence is below the gate threshold.'
            : close ? 'Competing hypotheses are too close to separate.'
              : 'Another gate criterion failed (see banner above).'}
      </span>
    </div>
  )
}
