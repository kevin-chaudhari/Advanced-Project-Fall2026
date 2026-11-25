import { useMemo, useState } from 'react'
import { cx } from '../ui'
import { RunCard } from './GridChart'

/*
 * Response chart — Agent-Viz's "response curve" (factor value → final diagnosis as a step line),
 * upgraded with controls: choose the X factor (or overlay every sensor as % change from baseline),
 * the Y outcome, the colour, the normal band and the review-gate thresholds, plus a panel listing
 * every control variable that was held constant.
 */

const SENSOR_UNIT = { temperature: '°C', vibration: '', pressure: 'PSI', rpm: 'RPM', current: 'A', voltage: 'V', flow_rate: 'L/min' }
const SENSOR_LABEL = { temperature: 'Temperature', vibration: 'Vibration', pressure: 'Pressure', rpm: 'Speed', current: 'Current', voltage: 'Voltage', flow_rate: 'Flow rate' }
const SERIES = ['#6E5A3E', '#5C726F', '#A9773A', '#8E463D', '#66745A', '#7D6F8A', '#3B3731']
const REVIEW = ['AUTO_RESOLVE', 'REQUIRES_HUMAN_REVIEW']
const REVIEW_COLOR = { AUTO_RESOLVE: '#78866B', REQUIRES_HUMAN_REVIEW: '#C18D4D' }

const Y_METRICS = {
  answer: { label: 'Final diagnosis', kind: 'cat', get: (r) => r.answer },
  confidence: { label: 'Confidence', kind: 'num', get: (r) => r.confidence, fmt: (v) => `${Math.round(v * 100)}%`, domain: [0, 1], threshold: [0.65, 'review gate G1: 65%'] },
  margin: { label: 'Lead over runner-up', kind: 'num', get: (r) => r.outcome?.margin, fmt: (v) => v.toFixed(2), threshold: [0.15, 'review gate G2: 0.15'] },
  review: { label: 'Review decision', kind: 'cat', get: (r) => r.review_decision, cats: REVIEW },
  real_share: { label: 'Share of real evidence', kind: 'num', get: (r) => { const c = r.outcome?.evidence_composition; const t = c ? (c.real || 0) + (c.synthetic || 0) : 0; return t ? (c.real || 0) / t : null }, fmt: (v) => `${Math.round(v * 100)}%`, domain: [0, 1] },
  runner_up: { label: 'Runner-up diagnosis', kind: 'cat', get: (r) => r.outcome?.hypothesis_scores?.[1]?.label },
  feedback: { label: 'Extra evidence rounds', kind: 'num', get: (r) => r.feedback_rounds, fmt: (v) => String(Math.round(v)) },
  latency: { label: 'Time taken', kind: 'num', get: (r) => r.latency_ms, fmt: (v) => `${(v / 1000).toFixed(1)} s` },
}

const fmtX = (v) => (typeof v === 'number' ? Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 }) : String(v))

function baselineValue(base, factor) {
  if (!base) return null
  const sv = base.outcome?.sensor_view?.find((s) => s.sensor === factor)
  if (sv?.value != null) return sv.value
  if (factor === 'top_k' || factor === 'data_mode') return base.config?.[factor]
  return null
}

export default function ResponseChart({ exp, colorOf, onOpenRun, onCompare }) {
  const done = useMemo(() => (exp.runs || []).filter((r) => r.status === 'done'), [exp])
  const base = done.find((r) => r.is_baseline)
  const factors = useMemo(() => {
    const f = [...new Set(done.filter((r) => r.factor && !['all_readings', 'drop_evidence'].includes(r.factor)).map((r) => r.factor))]
    return f
  }, [done])
  const sensorFactors = factors.filter((f) => SENSOR_LABEL[f])
  const [xKey, setXKey] = useState(() => (sensorFactors.length > 1 ? '__all' : factors[0] || ''))
  const [yKey, setYKey] = useState('answer')
  const [colorBy, setColorBy] = useState('answer')
  const [showBand, setShowBand] = useState(true)
  const [showGate, setShowGate] = useState(true)
  const [pick, setPick] = useState(null)
  const metric = Y_METRICS[yKey]
  const overlay = xKey === '__all'

  // series: one per factor (overlay) or just the chosen factor; each point = one run (+ the baseline)
  const series = useMemo(() => {
    const keys = overlay ? sensorFactors : xKey ? [xKey] : []
    return keys.map((f, i) => {
      const bv = baselineValue(base, f)
      const pts = done.filter((r) => r.factor === f).map((r) => ({ run: r, raw: r.value }))
      if (base && bv != null) pts.push({ run: base, raw: bv, isBase: true })
      const numeric = pts.every((p) => typeof p.raw === 'number')
      const withX = pts.map((p) => ({ ...p, x: overlay ? (bv ? ((p.raw - bv) / bv) * 100 : 0) : p.raw, y: metric.get(p.run) }))
        .filter((p) => p.y != null)
      withX.sort((a, b) => (numeric ? a.x - b.x : String(a.x).localeCompare(String(b.x))))
      return { factor: f, color: SERIES[i % SERIES.length], numeric, baseValue: bv, points: withX }
    }).filter((s) => s.points.length)
  }, [done, base, xKey, overlay, sensorFactors, metric])

  const allPts = series.flatMap((s) => s.points)
  const numericX = series.every((s) => s.numeric)
  const cats = metric.kind === 'cat'
    ? (metric.cats || [...new Set(allPts.map((p) => p.y))].sort((a, b) => allPts.filter((p) => p.y === b).length - allPts.filter((p) => p.y === a).length))
    : null

  // geometry
  const W = 900, H = 300, L = cats ? 190 : 64, R = 880, T = 28, B = 238
  const xs = allPts.map((p) => p.x)
  let x
  let xCats = null
  if (numericX && xs.length) {
    let lo = Math.min(...xs), hi = Math.max(...xs)
    const band = !overlay && showBand && exp.spec?.bands?.[xKey]
    if (band) { lo = Math.min(lo, band[0]); hi = Math.max(hi, band[1]) }
    const pad = (hi - lo || Math.abs(hi) || 1) * 0.05
    lo -= pad; hi += pad
    x = (v) => L + ((v - lo) / (hi - lo)) * (R - L)
  } else {
    xCats = [...new Set(xs.map(String))]
    x = (v) => L + ((xCats.indexOf(String(v)) + 0.5) / Math.max(xCats.length, 1)) * (R - L)
  }
  let y, yTicks = []
  if (cats) {
    y = (v) => T + ((cats.indexOf(v) + 0.5) / cats.length) * (B - T)
  } else {
    const ys = allPts.map((p) => p.y)
    let lo = metric.domain ? metric.domain[0] : Math.min(...ys, metric.threshold?.[0] ?? Infinity)
    let hi = metric.domain ? metric.domain[1] : Math.max(...ys, metric.threshold?.[0] ?? -Infinity)
    if (hi === lo) { hi += 1; lo = Math.max(0, lo - 1) }
    y = (v) => B - ((v - lo) / (hi - lo)) * (B - T)
    yTicks = [0, 0.25, 0.5, 0.75, 1].map((t) => lo + t * (hi - lo))
  }
  const pointColor = (p, s) => (colorBy === 'answer' ? colorOf(p.run.answer) : colorBy === 'review' ? REVIEW_COLOR[p.run.review_decision] || '#8A8170' : s.color)
  const linePath = (s) => s.points.map((p, i) => {
    const px = x(p.x), py = y(p.y)
    if (!i) return `M ${px},${py}`
    return cats ? `H ${px} V ${py}` : `L ${px},${py}`
  }).join(' ')
  const transitions = !overlay && series[0] && series[0].numeric
    ? series[0].points.slice(1).map((p, i) => ({ a: series[0].points[i], b: p })).filter(({ a, b }) => a.run.answer !== b.run.answer)
    : []
  const band = !overlay && showBand && numericX && exp.spec?.bands?.[xKey]

  // control variables held constant
  const varied = new Set(overlay ? sensorFactors : [xKey])
  const held = [
    ['Knowledge base', exp.spec?.dataset_type], ['Data source', varied.has('data_mode') ? null : exp.spec?.data_mode],
    ['Evidence retrieved (top_k)', varied.has('top_k') ? null : exp.spec?.top_k],
    ['Agents', base?.outcome?.llm_mode], ['Embedding model', exp.versions?.embedder], ['Code version', exp.versions?.code_version],
    ...((base?.outcome?.sensor_view || []).filter((s) => s.value != null && !varied.has(s.sensor))
      .map((s) => [s.label, `${fmtX(s.value)} ${(s.unit || '').replace(/^\((.*)\)$/, '$1')}`])),
  ].filter(([, v]) => v != null && v !== '')

  if (!factors.length) return <p className="text-[12.5px] text-muted">No varied numeric factor in this experiment to chart.</p>
  const xTitle = overlay ? 'change from the baseline reading (%)' : `${SENSOR_LABEL[xKey] || xKey.replace(/_/g, ' ')}${SENSOR_UNIT[xKey] ? ` (${SENSOR_UNIT[xKey]})` : ''}`

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px]">
        <label className="inline-flex items-center gap-1.5 text-muted">X
          <select value={xKey} onChange={(e) => setXKey(e.target.value)} className="rounded-md border border-line bg-surface py-1 pl-2 pr-7 text-[12.5px] text-ink">
            {sensorFactors.length > 1 && <option value="__all">All sensors (% change)</option>}
            {factors.map((f) => <option key={f} value={f}>{SENSOR_LABEL[f] || f.replace(/_/g, ' ')}</option>)}
          </select></label>
        <label className="inline-flex items-center gap-1.5 text-muted">Y
          <select value={yKey} onChange={(e) => setYKey(e.target.value)} className="rounded-md border border-line bg-surface py-1 pl-2 pr-7 text-[12.5px] text-ink">
            {Object.entries(Y_METRICS).map(([k, m]) => <option key={k} value={k}>{m.label}</option>)}
          </select></label>
        <label className="inline-flex items-center gap-1.5 text-muted">Colour
          <select value={colorBy} onChange={(e) => setColorBy(e.target.value)} className="rounded-md border border-line bg-surface py-1 pl-2 pr-7 text-[12.5px] text-ink">
            <option value="answer">by diagnosis</option><option value="review">by review decision</option>{overlay && <option value="series">by sensor</option>}
          </select></label>
        {!overlay && exp.spec?.bands?.[xKey] && <label className="inline-flex cursor-pointer items-center gap-1.5 text-muted"><input type="checkbox" className="accent-primary-700" checked={showBand} onChange={(e) => setShowBand(e.target.checked)} />normal range</label>}
        {metric.threshold && <label className="inline-flex cursor-pointer items-center gap-1.5 text-muted"><input type="checkbox" className="accent-primary-700" checked={showGate} onChange={(e) => setShowGate(e.target.checked)} />review-gate line</label>}
      </div>

      <div className="mt-2 overflow-x-auto">
        <svg viewBox={`0 0 ${W} ${H}`} className="min-w-[640px] w-full" role="img" aria-label={`${metric.label} against ${xTitle}`}>
          {band && <g><rect x={x(band[0])} y={T} width={Math.max(x(band[1]) - x(band[0]), 0)} height={B - T} fill="#EEF2F1" />
            <text x={(x(band[0]) + x(band[1])) / 2} y={T + 12} textAnchor="middle" fontSize="10.5" fill="#475957">normal range</text></g>}
          {cats ? cats.map((c) => <g key={c}><line x1={L} x2={R} y1={y(c)} y2={y(c)} stroke="#E5DED1" /><text x={L - 10} y={y(c) + 4} textAnchor="end" fontSize="11.5" fill="#17140F">{c === 'REQUIRES_HUMAN_REVIEW' ? 'Human review' : c === 'AUTO_RESOLVE' ? 'Auto-resolve' : c}</text></g>)
            : yTicks.map((t) => <g key={t}><line x1={L} x2={R} y1={y(t)} y2={y(t)} stroke="#E5DED1" /><text x={L - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill="#4A453D">{metric.fmt(t)}</text></g>)}
          {!cats && showGate && metric.threshold && <g><line x1={L} x2={R} y1={y(metric.threshold[0])} y2={y(metric.threshold[0])} stroke="#8E463D" strokeDasharray="5 4" />
            <text x={R} y={y(metric.threshold[0]) - 5} textAnchor="end" fontSize="10.5" fill="#8E463D">{metric.threshold[1]}</text></g>}
          {overlay && <line x1={x(0)} x2={x(0)} y1={T} y2={B} stroke="#17140F" strokeOpacity="0.35" />}
          {transitions.map(({ a, b }) => { const mx = (x(a.x) + x(b.x)) / 2; return <g key={`${a.x}-${b.x}`}><line x1={mx} x2={mx} y1={T - 8} y2={B} stroke="#17140F" strokeDasharray="3 3" /><text x={mx} y={T - 12} textAnchor="middle" fontSize="10.5" fill="#17140F">answer changes</text></g> })}
          {series.map((s) => <path key={s.factor} d={linePath(s)} fill="none" stroke={overlay ? s.color : '#4A453D'} strokeWidth="2" strokeOpacity={overlay ? 0.9 : 0.55} />)}
          {series.map((s) => s.points.map((p) => (
            <g key={`${s.factor}-${p.run.run_index}-${p.x}`} onClick={() => setPick({ run: { ...p.run, margin: p.run.outcome?.margin }, label: `${SENSOR_LABEL[s.factor] || s.factor} ${fmtX(p.raw)}${p.isBase ? ' (baseline)' : ''}` })} style={{ cursor: 'pointer' }}>
              <circle cx={x(p.x)} cy={y(p.y)} r={p.isBase ? 8 : 6} fill={pointColor(p, s)} stroke={p.isBase ? '#17140F' : '#FFFCF5'} strokeWidth={p.isBase ? 2.5 : 1.5}>
                <title>{`${SENSOR_LABEL[s.factor] || s.factor} ${fmtX(p.raw)}${p.isBase ? ' (baseline)' : ''} → ${p.run.answer}, ${Math.round((p.run.confidence || 0) * 100)}%, ${p.run.review_decision === 'AUTO_RESOLVE' ? 'auto-resolve' : 'human review'}`}</title>
              </circle>
            </g>
          )))}
          {!overlay && series[0]?.points.map((p) => <text key={`xl-${p.run.run_index}`} x={x(p.x)} y={B + 16} textAnchor="middle" fontSize="10.5" fill="#4A453D">{fmtX(p.raw)}</text>)}
          {overlay && [-40, -20, 0, 20, 40].filter((v) => v >= Math.min(...xs) - 1 && v <= Math.max(...xs) + 1).map((v) => <text key={v} x={x(v)} y={B + 16} textAnchor="middle" fontSize="10.5" fill="#4A453D">{v > 0 ? `+${v}` : v}%</text>)}
          <text x={(L + R) / 2} y={H - 8} textAnchor="middle" fontSize="11.5" fill="#17140F">{xTitle}</text>
        </svg>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted">
        {overlay && series.map((s) => <span key={s.factor} className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4" style={{ background: s.color }} />{SENSOR_LABEL[s.factor]}</span>)}
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-full border-2 border-ink" />baseline</span>
        <span>Click a point for details.</span>
      </div>

      {pick && <RunCard run={pick.run} label={pick.label} colorOf={colorOf} baseIndex={base?.run_index} onCompare={(i) => onOpenRun?.(i)} onClose={() => setPick(null)} />}
      {transitions.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2">
          {transitions.map(({ a, b }) => (
            <li key={`${a.x}-${b.x}`}>
              <button type="button" onClick={() => onCompare?.([a.run.run_index, b.run.run_index])} className="rounded-md border border-line bg-surface px-2 py-1 text-left text-[12px] hover:bg-well focus-ring">
                <b className="tabular-nums">{fmtX(a.raw)} → {fmtX(b.raw)}</b>: {a.run.answer} → <b>{b.run.answer}</b> <span className="text-primary-700 underline underline-offset-2">compare</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <details className="mt-3 rounded-lg border border-line bg-well/50 px-3 py-2 text-[12px]" open>
        <summary className="cursor-pointer font-medium text-ink">Held constant ({held.length} control variables)</summary>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {held.map(([k, v]) => <span key={k} className={cx('rounded-md border border-line bg-surface px-1.5 py-0.5')}><span className="text-muted">{k}:</span> <span className="text-ink">{String(v)}</span></span>)}
        </div>
        <p className="mt-1.5 text-[11.5px] text-muted">Everything above was the same in every run on this chart; only {overlay ? 'one sensor at a time' : (SENSOR_LABEL[xKey] || xKey)} changed. Confidence is a recorded system score, not a calibrated probability.</p>
      </details>
    </div>
  )
}
