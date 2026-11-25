import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Flag, Info, Loader2, OctagonAlert } from 'lucide-react'
import { cx } from '../ui'
import { ReviewDecision } from '../primitives'
import { AnswerChip, numberedName, stepName, useAnswerColors } from '../lab/LabViews'
import { compareTraces, listTraces } from '../../services/api'

/*
 * Agent-Viz views inside the Trace explorer: the step breakdown and signals of one trace,
 * and a comparison of any number of traces (one column each, first = reference).
 */

const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)
const STATUS_CELL = { ok: 'bg-primary-200', warning: 'bg-warning-500', error: 'bg-danger-500', loop: 'bg-secondary-500' }
const SEV = {
  high: ['border-danger-100 bg-danger-50', 'text-danger-700', OctagonAlert],
  medium: ['border-warning-100 bg-warning-50', 'text-warning-700', AlertTriangle],
  info: ['border-line bg-surface', 'text-muted', Info],
}

/** Rule-based signals a reviewer should look at. */
export function SignalsPanel({ signals, onGoToStep, steps }) {
  const num = Object.fromEntries((steps || []).map((s) => [s.key, s.position + 1]))
  if (!signals?.length) return <p className="text-[13px] text-muted">No signals: nothing in this trace tripped a check.</p>
  const gaps = signals.filter((s) => s.kind === 'gap')
  const rest = signals.filter((s) => s.kind !== 'gap')
  return (
    <div className="space-y-4">
      {gaps.length > 0 && <div><h3 className="mb-1.5 text-[13px] font-semibold text-ink">Gaps — things that should have happened and did not</h3><SignalList items={gaps} onGoToStep={onGoToStep} num={num} /></div>}
      {rest.length > 0 && <div><h3 className="mb-1.5 text-[13px] font-semibold text-ink">Signals</h3><SignalList items={rest} onGoToStep={onGoToStep} num={num} /></div>}
    </div>
  )
}

function SignalList({ items, onGoToStep, num = {} }) {
  return (
    <ul className="grid gap-2 lg:grid-cols-2">
      {items.map((s) => {
        const [box, tone, Icon] = SEV[s.severity]
        return (
          <li key={s.id} className={cx('rounded-lg border px-3 py-2', box)}>
            <p className={cx('flex items-center gap-1.5 text-[13px] font-semibold', tone)}><Icon size={14} aria-hidden />{s.title}
              <span className="ml-auto text-[10.5px] font-medium uppercase tracking-wide opacity-80">{s.severity}</span></p>
            <p className="mt-0.5 text-[12.5px] leading-snug text-ink">{s.detail}</p>
            {s.step && <button type="button" onClick={() => onGoToStep(s.step)} className="mt-1 text-[12px] font-medium text-primary-700 underline underline-offset-2">Show step: {numberedName({ key: s.step }, num[s.step])}</button>}
          </li>
        )
      })}
    </ul>
  )
}

/** The pipeline's steps in order, each reduced to the decision it made; flagged steps are marked. */
export function StepBreakdown({ data, focus }) {
  const [onlyFlagged, setOnlyFlagged] = useState(false)
  const flagged = new Set(data.flagged_steps)
  const sigFor = (k) => data.signals.filter((s) => s.step === k)
  const steps = onlyFlagged ? data.steps.filter((s) => flagged.has(s.key) || s.status === 'warning' || s.status === 'error') : data.steps
  useEffect(() => { if (focus) document.getElementById(`step-${focus}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }, [focus])
  return (
    <div>
      <div className="flex gap-px" aria-label="Step ribbon">
        {data.steps.map((s) => (
          <a key={s.key} href={`#step-${s.key}`} title={`${numberedName(s, s.position + 1)}: ${s.signature}`}
            className={cx('h-5 min-w-[6px] flex-1 rounded-[2px]', STATUS_CELL[s.status] || 'bg-slate-300', flagged.has(s.key) && 'ring-2 ring-ink ring-offset-1 ring-offset-canvas')} />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted">
        <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-primary-200" />ok</span>
        <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-secondary-500" />loop / re-run</span>
        <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-warning-500" />warning</span>
        <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-danger-500" />error</span>
        <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm ring-2 ring-ink" />has a signal</span>
        <label className="ml-auto inline-flex cursor-pointer items-center gap-1.5">
          <input type="checkbox" className="accent-primary-700" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} />Only steps with a warning or signal
        </label>
      </div>
      <ol className="mt-3 divide-y divide-line rounded-lg border border-line bg-surface">
        {steps.map((s) => {
          const sigs = sigFor(s.key)
          return (
            <li key={s.key} id={`step-${s.key}`} className={cx('grid gap-x-3 px-3 py-2 sm:grid-cols-[28px_220px_minmax(0,1fr)_60px]', focus === s.key && 'bg-primary-50')}>
              <span className="text-[11.5px] tabular-nums text-slate-400">{s.position + 1}.</span>
              <span className="text-[12.5px] font-medium text-ink">
                {s.key === data.first_problem_step && <Flag size={12} className="mr-1 inline text-danger-600" aria-label="First problem" />}
                <span className={cx('mr-1.5 inline-block h-2 w-2 rounded-full', STATUS_CELL[s.status] || 'bg-slate-300')} aria-hidden />{stepName(s)}
              </span>
              <div className="min-w-0 text-[12.5px]">
                <p className="text-ink">{s.signature}</p>
                <p className="line-clamp-2 text-[11.5px] text-muted" title={s.reason}>{s.reason}</p>
                {sigs.map((g) => <p key={g.id} className={cx('mt-0.5 text-[11.5px] font-medium', SEV[g.severity][1])}>⚑ {g.title}</p>)}
              </div>
              <span className="text-right text-[11px] tabular-nums text-muted">{s.duration_ms != null ? `${Math.round(s.duration_ms)} ms` : ''}</span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

/** Pick traces to compare with the current one. */
export function TracePicker({ current, onCompare }) {
  const [items, setItems] = useState(null)
  const [origin, setOrigin] = useState('live')
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState([])
  useEffect(() => { listTraces({ limit: 150, origin }).then((r) => setItems(r.traces)).catch(() => setItems([])) }, [origin])
  const others = (items || []).filter((t) => t.trace_id !== current.trace_id)
  const shown = others.filter((t) => !q || `${t.query} ${t.final_label} ${t.trace_id}`.toLowerCase().includes(q.toLowerCase()))
  const sameQ = others.filter((t) => t.query === current.query).map((t) => t.trace_id)
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= 11 ? p : [...p, id]))
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="flex flex-wrap items-center gap-2 text-[12px]">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by question, answer or id" className="input max-w-[280px] py-1 text-[12.5px]" />
        {sameQ.length > 0 && <button type="button" onClick={() => setPicked(sameQ.slice(0, 11))} className="rounded-md border border-line px-2 py-1 font-medium text-ink hover:bg-well">Pick reruns of the same question ({sameQ.length})</button>}
        <label className="inline-flex items-center gap-1.5 text-muted"><input type="checkbox" className="accent-primary-700" checked={origin === 'all'} onChange={(e) => setOrigin(e.target.checked ? 'all' : 'live')} />include experiment runs</label>
        <button type="button" disabled={!picked.length} onClick={() => onCompare([current.trace_id, ...picked])} className="btn-primary ml-auto py-1.5 text-[12.5px]">
          Compare {picked.length + 1} traces
        </button>
      </div>
      <p className="mt-1.5 text-[11.5px] text-muted">This trace is the reference (first column). Pick up to 11 more.</p>
      <ol className="mt-2 max-h-[260px] overflow-y-auto divide-y divide-line rounded-md border border-line">
        {!items && <li className="p-2 text-[12px] text-muted">Loading…</li>}
        {shown.map((t) => (
          <li key={t.trace_id}>
            <label className="flex cursor-pointer items-start gap-2 px-2 py-1.5 hover:bg-well">
              <input type="checkbox" className="mt-0.5 accent-primary-700" checked={picked.includes(t.trace_id)} onChange={() => toggle(t.trace_id)} />
              <span className="min-w-0 text-[12px]">
                <span className="line-clamp-1 text-ink">{t.query}</span>
                <span className="text-muted"><b className="font-medium text-ink">{t.final_label || '—'}</b> · {pct(t.final_confidence)} · {t.data_mode}{t.is_experiment ? ' · experiment run' : ''} · <span className="mono">{t.trace_id.slice(-8)}</span></span>
              </span>
            </label>
          </li>
        ))}
      </ol>
    </div>
  )
}

/** N traces side by side: inputs, steps and agents; cells that differ from the reference are highlighted. */
export function MultiCompare({ ids, labels, fallback = null }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [view, setView] = useState('steps')
  const [onlyDiff, setOnlyDiff] = useState(true)
  const key = ids.join(',')
  useEffect(() => {
    let live = true
    setData(null); setError(null)
    compareTraces(ids, labels).then((d) => live && setData(d)).catch((e) => live && setError(e.response?.data?.detail || e.message))
    return () => { live = false }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  const counts = useMemo(() => {
    const c = {}
    for (const t of data?.traces || []) c[t.answer] = (c[t.answer] || 0) + 1
    return { baseline: { answer: data?.traces?.[0]?.answer }, answer_counts: c }
  }, [data])
  const colorOf = useAnswerColors(counts)
  if (error) return fallback || <p role="alert" className="text-[12.5px] text-danger-700">{error}</p>
  if (!data) return <p className="flex items-center gap-2 text-[13px] text-muted"><Loader2 size={14} className="animate-spin" />Aligning traces…</p>
  const n = data.traces.length
  const cols = `minmax(150px,200px) repeat(${n}, minmax(150px,1fr))`
  const steps = onlyDiff ? data.steps.filter((s) => s.changed) : data.steps
  const agents = onlyDiff ? data.agents.filter((a) => a.changed) : data.agents
  const inputs = onlyDiff ? data.inputs.filter((i) => i.differs) : data.inputs
  const cellTone = (state) => (state === 'different' ? 'border-warning-500 bg-warning-50/70' : state === 'ref' ? 'border-ink/40' : 'border-line')

  return (
    <div>
      <p className="rounded-lg border border-line bg-well/60 px-3 py-2 text-[12.5px] text-ink">
        {n} traces, <b>{data.summary.answers}</b> different answer(s). {data.summary.steps_changed} step(s) and {data.summary.agents_changed} agent(s) differ from the reference
        {data.first_divergence && <> — first at <b>{stepName({ key: data.first_divergence })}</b></>}.
        {data.missing.length > 0 && <span className="text-warning-700"> {data.missing.length} trace(s) skipped: made before step recording existed.</span>}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-[12px]">
        <div role="tablist" className="inline-flex rounded-md border border-line p-0.5">
          {[['steps', 'Step by step'], ['agents', 'Agent by agent'], ['inputs', 'Inputs & settings']].map(([v, l]) => (
            <button key={v} role="tab" type="button" aria-selected={view === v} onClick={() => setView(v)}
              className={cx('rounded px-2.5 py-1 font-medium focus-ring', view === v ? 'bg-ink text-surface' : 'text-muted hover:text-ink')}>{l}</button>
          ))}
        </div>
        <label className="ml-auto inline-flex cursor-pointer items-center gap-1.5 text-muted">
          <input type="checkbox" className="accent-primary-700" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} />Only rows that differ
        </label>
      </div>

      <div className="mt-3 overflow-x-auto">
        <div className="min-w-max space-y-1">
          <div className="grid gap-1.5" style={{ gridTemplateColumns: cols }}>
            <span />
            {data.traces.map((t, j) => (
              <div key={t.trace_id} className={cx('rounded-md border bg-surface p-2', j === 0 ? 'border-ink/60' : 'border-line')}>
                <p className="truncate text-[11.5px] text-muted" title={t.question}>{j === 0 ? 'Reference · ' : ''}{t.label}</p>
                <AnswerChip answer={t.answer} color={colorOf(t.answer)} />
                <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11.5px] tabular-nums text-muted">
                  {pct(t.confidence)}{t.review_decision && <ReviewDecision decision={t.review_decision} variant="inline" />}
                  <Link to={`/traces/${t.trace_id}`} className="font-medium text-primary-700 underline underline-offset-2">open</Link>
                </div>
              </div>
            ))}
          </div>

          {view === 'inputs' && inputs.map((r) => (
            <div key={r.sensor} className="grid gap-1.5" style={{ gridTemplateColumns: cols }}>
              <span className="pt-1 text-[12px] font-medium text-muted">{r.label}{r.unit ? ` (${r.unit})` : ''}</span>
              {r.values.map((v, j) => (
                <span key={j} className={cx('rounded-md border px-2 py-1 text-[12.5px] tabular-nums text-ink', j > 0 && String(v) !== String(r.values[0]) ? 'border-warning-500 bg-warning-50/70' : 'border-line')}>{v ?? '—'}</span>
              ))}
            </div>
          ))}

          {view === 'steps' && steps.map((s) => (
            <div key={s.key} className="grid gap-1.5" style={{ gridTemplateColumns: cols }}>
              <span className="pt-1 text-[12px] font-medium text-muted">
                {s.key === data.first_divergence && <Flag size={12} className="mr-1 inline text-danger-600" aria-hidden />}{stepName(s)}
              </span>
              {s.cells.map((c, j) => (
                <div key={j} className={cx('rounded-md border px-2 py-1 text-[12px]', c ? cellTone(c.state) : 'border-dashed border-line')} title={c?.reason}>
                  {c ? <p className="text-ink">{c.signature}</p> : <p className="italic text-muted">did not run</p>}
                </div>
              ))}
            </div>
          ))}

          {view === 'agents' && agents.map((a) => (
            <div key={a.agent} className="grid gap-1.5" style={{ gridTemplateColumns: cols }}>
              <span className="pt-1 text-[12px] font-medium text-muted">{a.name}</span>
              {a.cells.map((c, j) => (
                <div key={j} className={cx('rounded-md border px-2 py-1 text-[12px]', !c ? 'border-dashed border-line' : c.changed ? 'border-warning-500 bg-warning-50/70' : j === 0 ? 'border-ink/40' : 'border-line')}>
                  {c ? <>
                    <AnswerChip answer={c.finding} color={colorOf(c.finding)} />
                    <p className="text-[11px] tabular-nums text-muted">{pct(c.confidence)}{c.pass_number > 1 ? `, pass ${c.pass_number}` : ''}
                      {c.cited && Object.keys(c.cited).length > 0 && ` · cites ${Object.entries(c.cited).map(([l, k]) => `${l} ×${k}`).join(', ')}`}</p>
                  </> : <p className="italic text-muted">did not run</p>}
                </div>
              ))}
            </div>
          ))}
          {((view === 'steps' && !steps.length) || (view === 'agents' && !agents.length) || (view === 'inputs' && !inputs.length)) &&
            <p className="text-[12.5px] text-muted">No differences here{onlyDiff ? ' — untick “Only rows that differ” to see everything' : ''}.</p>}
        </div>
      </div>
    </div>
  )
}
