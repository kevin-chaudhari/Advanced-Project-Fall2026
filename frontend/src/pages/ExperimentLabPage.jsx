import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AlertTriangle, FlaskConical, Loader2, Play, Plus, RefreshCw, Square, Trash2 } from 'lucide-react'
import { cx } from '../components/ui'
import { ReviewDecision } from '../components/primitives'
import { AgentMatrix, AnswerChip, ReadingsStrip, VerdictBanner, CompareView, FactorSweeps, RunsTable, StepDivergence, StepRibbons, useAnswerColors } from '../components/lab/LabViews'
import { useDiagnostics, DATASETS } from '../state/DiagnosticsContext'
import { MultiCompare } from '../components/trace/InsightPanels'
import ResponseChart from '../components/lab/ResponseChart'
import GridChart from '../components/lab/GridChart'
import {
  cancelExperiment, compareExperimentRuns, createExperiment, deleteExperiment, getExperiment, listExperiments,
  planExperiment, pollExperiment, resumeExperiment,
} from '../services/api'

/*
 * Experiment Lab: controlled what-if experiments on the diagnostic council.
 * A user picks one question, a few things to vary, and the backend runs the normal pipeline once per
 * setting (one factor at a time around a baseline). Each run is an ordinary trace.
 */

const SECONDS_PER_RUN = 2
const KIND_LABEL = { sensor_sweep: 'What-if readings', settings: 'Pipeline settings', robustness: 'Robustness check', grid: 'Two sensors together' }
const VIEWS = [['sweeps', 'What changed the answer'], ['steps', 'Step by step'], ['agents', 'Agent by agent'], ['ribbons', 'Step ribbons'], ['runs', 'Runs & compare']]
const EXAMPLE_Q = 'Electric motor driving a conveyor belt in a manufacturing facility. Telemetry: temperature 65 °C, vibration 0.25, pressure 50 PSI, 2400 RPM, current 60 A, voltage 330 V, flow rate 110 L/min. Which failure is most probable and what should we do?'
const errText = (e) => e?.response?.data?.detail || (e?.code === 'ERR_NETWORK' ? 'Cannot reach the backend.' : e?.message || 'Request failed')
const STATUS_TEXT = { queued: 'Queued', running: 'Running', done: 'Finished', cancelled: 'Cancelled', interrupted: 'Interrupted (backend restarted)', failed: 'Failed' }
const parseList = (text) => text.split(/[\s,;]+/).map((t) => t.trim()).filter(Boolean).map(Number).filter((n) => Number.isFinite(n))

function ExperimentList({ items, selected, onRefresh, loading, error }) {
  return (
    <aside className="flex min-h-0 flex-col border-b md:border-b-0 md:border-r border-line bg-canvas" aria-label="Experiments">
      <div className="flex items-center gap-2 px-4 py-3">
        <h2 className="text-[13px] font-semibold text-ink">Experiments</h2>
        <span className="text-[12px] text-muted tabular-nums">{items.length}</span>
        <button type="button" onClick={onRefresh} className="btn-ghost ml-auto p-1 rounded-md" aria-label="Refresh experiments" title="Refresh">
          {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
        </button>
      </div>
      <div className="px-4 pb-3">
        <Link to="/lab/new" className={cx('flex items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-[12.5px] font-medium focus-ring',
          selected === 'new' ? 'border-ink bg-surface text-ink' : 'border-line bg-surface text-ink hover:bg-well')}>
          <Plus size={14} />New experiment
        </Link>
      </div>
      {error && <p className="px-4 pb-3 text-[12px] text-danger-700">{error}</p>}
      <ol className="min-h-0 flex-1 overflow-y-auto max-h-[200px] md:max-h-none">
        {items.map((e) => (
          <li key={e.experiment_id}>
            <Link to={`/lab/${e.experiment_id}`} aria-current={e.experiment_id === selected ? 'true' : undefined}
              className={cx('block border-l-2 px-4 py-2.5 focus-ring', e.experiment_id === selected ? 'border-ink bg-surface' : 'border-transparent hover:bg-well')}>
              <p className="text-[12.5px] font-medium leading-snug text-ink line-clamp-1">{e.name}</p>
              <p className="mt-0.5 text-[11.5px] leading-snug text-muted line-clamp-1">{e.question}</p>
              <p className="mt-1 flex flex-wrap gap-x-2 text-[11.5px] text-muted">
                <span>{KIND_LABEL[e.kind] || e.kind}</span>
                <span className="tabular-nums">{e.done_runs}/{e.total_runs} runs</span>
                {e.status !== 'done' && <span className={cx(e.status === 'running' || e.status === 'queued' ? 'text-primary-700' : 'text-warning-700')}>{STATUS_TEXT[e.status] || e.status}</span>}
              </p>
            </Link>
          </li>
        ))}
        {!items.length && !loading && <li className="px-4 text-[12px] text-muted">No experiments yet.</li>}
      </ol>
    </aside>
  )
}

/* ─── New experiment ─────────────────────────────────────────────────────── */

function NewExperiment({ onCreated }) {
  const [params] = useSearchParams()
  const { dataset: ctxDataset, health } = useDiagnostics()
  const [question, setQuestion] = useState(params.get('q') || '')
  const [dataset, setDataset] = useState(params.get('dataset') || (ctxDataset === 'failure_iq' ? 'afrb' : ctxDataset) || 'afrb')
  const sourceTrace = params.get('trace')
  const [kind, setKind] = useState('sensor_sweep')
  const [name, setName] = useState('')
  const [plan, setPlan] = useState(null)
  const [planErr, setPlanErr] = useState(null)
  const [planning, setPlanning] = useState(false)
  const [sweep, setSweep] = useState({})          // sensor -> { on, text }
  const [settings, setSettings] = useState({ modes: [], topk: '', drop: 0 })
  const [robust, setRobust] = useState({ tol: '', drop: 3 })
  const [grid, setGrid] = useState({ a: '', b: '', aText: '', bText: '' })
  // default the grid to the first two sensors in the question, with the suggested values
  useEffect(() => {
    if (!plan || (grid.a && grid.b)) return
    const inQ = plan.sensors.filter((x) => x.in_question)
    if (inQ.length < 2) return
    setGrid({ a: inQ[0].sensor, b: inQ[1].sensor, aText: inQ[0].suggested_values.join(', '), bText: inQ[1].suggested_values.join(', ') })
  }, [plan]) // eslint-disable-line react-hooks/exhaustive-deps
  const pickGrid = (key, sensor) => { const sv = plan?.sensors.find((x) => x.sensor === sensor); setGrid((g) => ({ ...g, [key]: sensor, [`${key}Text`]: sv ? sv.suggested_values.join(', ') : '' })) }
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const dataMode = 'combined'
  const latestQ = useRef(question)
  latestQ.current = question

  // read the readings out of the question (debounced) and propose values to try
  useEffect(() => {
    if (!question.trim()) { setPlan(null); return }
    const t = setTimeout(() => {
      setPlanning(true); setPlanErr(null)
      const asked = question
      planExperiment(question, dataset, dataMode)
        .then((p) => {
          if (asked !== latestQ.current) return
          setPlan(p)
          setSweep((prev) => {
            const next = {}
            let preselect = 0
            for (const s of p.sensors) {
              const old = prev[s.sensor]
              const on = old ? old.on : (s.in_question && preselect++ < 3)
              next[s.sensor] = { on, text: old?.touched ? old.text : s.suggested_values.join(', '), touched: old?.touched }
            }
            return next
          })
        })
        .catch((e) => { setPlan(null); setPlanErr(errText(e)) })
        .finally(() => setPlanning(false))
    }, 450)
    return () => clearTimeout(t)
  }, [question, dataset])

  const factors = useMemo(() => {
    if (kind === 'sensor_sweep') {
      return Object.fromEntries(Object.entries(sweep).filter(([, v]) => v.on).map(([k, v]) => [k, parseList(v.text)]).filter(([, v]) => v.length))
    }
    if (kind === 'grid') return grid.a && grid.b && grid.a !== grid.b ? { [grid.a]: parseList(grid.aText), [grid.b]: parseList(grid.bText) } : {}
    if (kind === 'robustness') return { ...(Number(robust.tol) ? { tolerance_pct: Number(robust.tol) } : {}), drop_evidence: Number(robust.drop) || 0 }
    return { data_mode: settings.modes, top_k: parseList(settings.topk), drop_evidence: Number(settings.drop) || 0 }
  }, [kind, sweep, settings, robust])

  const runCount = useMemo(() => {
    if (kind === 'sensor_sweep') {
      const base = plan?.readings || {}
      return 1 + Object.entries(factors).reduce((n, [s, vals]) => n + new Set(vals.filter((v) => base[s] == null || Math.abs(base[s] - v) > 1e-9)).size, 0)
    }
    if (kind === 'grid') {
      if (!grid.a || !grid.b || grid.a === grid.b) return 0
      const axis = (s, t) => new Set([...parseList(t), ...(plan?.readings?.[s] != null ? [plan.readings[s]] : [])]).size
      return axis(grid.a, grid.aText) * axis(grid.b, grid.bText)
    }
    if (kind === 'robustness') {
      const n = Object.keys(plan?.readings || {}).length
      const outOfBand = (plan?.sensors || []).filter((x) => x.status && x.status !== 'in_band').length
      return 1 + 2 * n + (n > 1 ? 2 : 0) + (Number(robust.drop) || 0) + 4 * outOfBand
    }
    return 1 + settings.modes.filter((m) => m !== dataMode).length + new Set(parseList(settings.topk).filter((k) => k !== 8)).size + (Number(settings.drop) || 0)
  }, [kind, factors, plan, settings, robust])

  const maxRuns = plan?.max_runs || 60
  const canRun = question.trim() && runCount > 1 && runCount <= maxRuns && !busy
  const modes = plan?.data_modes || ['real', 'synthetic', 'combined']

  const start = async () => {
    setBusy(true); setError(null)
    try {
      const auto = kind === 'sensor_sweep'
        ? `What-if: ${Object.keys(factors).map((s) => plan?.sensors.find((x) => x.sensor === s)?.label || s).join(', ')}`
        : kind === 'robustness' ? 'Robustness check' : kind === 'grid' ? `Two sensors: ${plan?.sensors.find((x) => x.sensor === grid.a)?.label} × ${plan?.sensors.find((x) => x.sensor === grid.b)?.label}` : 'Pipeline settings'
      const r = await createExperiment({ name: name.trim() || auto, kind, question, dataset_type: dataset, data_mode: dataMode, top_k: 8, factors, source_trace_id: sourceTrace })
      onCreated(r.experiment_id)
    } catch (e) { setError(errText(e)) } finally { setBusy(false) }
  }

  const setS = (sensor, patch) => setSweep((p) => ({ ...p, [sensor]: { ...p[sensor], ...patch } }))
  const preset = (p) => setSettings(p === 'source' ? { modes: modes.filter((m) => m !== dataMode), topk: '', drop: 0 }
    : p === 'depth' ? { modes: [], topk: '4, 12, 20', drop: 0 } : { modes: [], topk: '', drop: 5 })

  return (
    <div className="mx-auto max-w-[980px] px-4 sm:px-6 py-4">
      <p className="flex items-center gap-1.5 text-[12px] font-medium text-muted"><FlaskConical size={14} />Experiment Lab</p>
      <h1 className="mt-1 text-[22px] font-semibold tracking-[-0.01em] text-ink">Test how stable a diagnosis is</h1>
      <p className="mt-1.5 max-w-[680px] text-[13.5px] leading-relaxed text-muted">
        Pick one question and what to vary. The council diagnoses the baseline once, then once per change — one change at a time —
        and the Lab shows which changes flipped the answer and at which step the agents' reasoning first went a different way.
      </p>
      {sourceTrace && <p className="mt-2 text-[12px] text-muted">Started from trace <Link to={`/traces/${sourceTrace}`} className="mono text-primary-700 underline underline-offset-2">{sourceTrace}</Link></p>}

      <section className="mt-4 space-y-4">
        <div>
          <div className="flex items-baseline justify-between gap-3">
            <label htmlFor="lab-q" className="text-[13px] font-semibold text-ink">1. The question (baseline)</label>
            {!question && <button type="button" className="text-[12px] font-medium text-primary-700 underline underline-offset-2" onClick={() => setQuestion(EXAMPLE_Q)}>Use an example</button>}
          </div>
          <textarea id="lab-q" rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} className="input mt-1.5 resize-y text-[13.5px]"
            placeholder="Describe the equipment and its readings, e.g. “Pump at 82 °C, vibration 0.6, pressure 40 PSI …”" />
          <div className="mt-2 flex flex-wrap items-center gap-3 text-[12px] text-muted">
            <label className="inline-flex items-center gap-1.5">Knowledge base
              <select value={dataset} onChange={(e) => setDataset(e.target.value)} className="rounded-md border border-line bg-surface py-1 pl-2 pr-7 text-[12.5px] text-ink">
                {DATASETS.filter((d) => d.id !== 'failure_iq').map((d) => {
                  const loaded = Object.values(health?.record_counts?.[d.id] || {}).some((n) => n > 0)
                  return <option key={d.id} value={d.id}>{d.label}{health && !health.offline && !loaded ? ' (not loaded)' : ''}</option>
                })}
              </select>
            </label>
            {planning && <span className="inline-flex items-center gap-1"><Loader2 size={12} className="animate-spin" />Reading the readings…</span>}
            {plan && !planning && <span>Found {Object.keys(plan.readings).length} reading(s) in the question.</span>}
            {planErr && <span className="text-danger-700">{planErr}</span>}
          </div>
        </div>

        <div>
          <p className="text-[13px] font-semibold text-ink">2. What to vary</p>
          <div role="radiogroup" className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {[['sensor_sweep', 'What-if on the readings', 'Change one sensor value at a time: how far can a reading move before the diagnosis changes?'],
              ['settings', 'Pipeline settings', 'Same question, different retrieval: data source, how much evidence, and dropping one evidence record at a time.'],
              ['grid', 'Two sensors together', 'Change two readings at the same time, every combination: does one sensor’s effect depend on the other?'],
              ['robustness', 'Robustness check', 'Would this diagnosis survive sensor error? Each reading ±tolerance, and each top evidence record left out once.']].map(([k, t, d]) => (
              <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => setKind(k)}
                className={cx('rounded-lg border p-3 text-left focus-ring', kind === k ? 'border-ink bg-surface' : 'border-line bg-surface/60 hover:bg-well')}>
                <p className="text-[13px] font-semibold text-ink">{t}</p>
                <p className="mt-0.5 text-[12px] leading-snug text-muted">{d}</p>
              </button>
            ))}
          </div>

          {kind === 'sensor_sweep' && (
            <div className="mt-3 overflow-x-auto rounded-lg border border-line bg-surface">
              {!plan ? <p className="p-4 text-[12.5px] text-muted">{question.trim() ? 'Reading the question…' : 'Enter a question with sensor readings to see what can be varied.'}</p> : (
                <table className="w-full text-[12.5px]">
                  <thead className="bg-well text-left text-muted">
                    <tr><th className="w-8 px-3 py-2"><input type="checkbox" aria-label="Vary every sensor in the question" title="Vary every sensor in the question" className="accent-primary-700"
                      checked={plan.sensors.filter((x) => x.in_question).every((x) => sweep[x.sensor]?.on)}
                      onChange={(e) => setSweep((p) => Object.fromEntries(Object.entries(p).map(([k, v]) => [k, { ...v, on: e.target.checked && !!plan.sensors.find((x) => x.sensor === k)?.in_question }])))} /></th><th className="px-3 py-2 font-medium">Sensor <span className="font-normal">(tick the box on the left to vary all)</span></th><th className="px-3 py-2 font-medium">In question</th>
                      <th className="px-3 py-2 font-medium">Normal range</th><th className="px-3 py-2 font-medium">Values to try</th></tr>
                  </thead>
                  <tbody>
                    {plan.sensors.map((s) => {
                      const v = sweep[s.sensor] || {}
                      return (
                        <tr key={s.sensor} className={cx('border-t border-line', !v.on && 'text-muted')}>
                          <td className="px-3 py-1.5"><input type="checkbox" checked={!!v.on} onChange={(e) => setS(s.sensor, { on: e.target.checked })} aria-label={`Vary ${s.label}`} className="accent-primary-700" /></td>
                          <td className="px-3 py-1.5 font-medium text-ink">{s.label} <span className="font-normal text-muted">{s.unit}</span></td>
                          <td className={cx('px-3 py-1.5 tabular-nums', s.status && s.status !== 'in_band' && 'font-semibold text-warning-700')} title={s.status && s.status !== 'in_band' ? `Outside the normal range (${s.status})` : undefined}>{s.baseline ?? <span className="text-[11.5px]" title="Ticking it adds this reading to the question">not in question</span>}</td>
                          <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{s.band_low}–{s.band_high}</td>
                          <td className="px-3 py-1.5"><input value={v.text || ''} disabled={!v.on} onChange={(e) => setS(s.sensor, { text: e.target.value, touched: true })}
                            className="input py-1 text-[12.5px] tabular-nums disabled:opacity-60" aria-label={`Values to try for ${s.label}`} /></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {kind === 'grid' && (
            <div className="mt-3 space-y-2 rounded-lg border border-line bg-surface p-4 text-[12.5px]">
              {!plan ? <p className="text-muted">Enter a question with readings first.</p> : [['a', 'Across (X)'], ['b', 'Up (Y)']].map(([k, l]) => (
                <div key={k} className="flex flex-wrap items-center gap-2">
                  <span className="w-20 font-medium text-ink">{l}</span>
                  <select value={grid[k]} onChange={(e) => pickGrid(k, e.target.value)} className="rounded-md border border-line bg-surface py-1 pl-2 pr-7 text-[12.5px]">
                    <option value="">choose a sensor</option>
                    {plan.sensors.map((x) => <option key={x.sensor} value={x.sensor} disabled={x.sensor === grid[k === 'a' ? 'b' : 'a']}>{x.label}{x.baseline != null ? ` (now ${x.baseline})` : ' (not in question)'}</option>)}
                  </select>
                  <input value={grid[`${k}Text`]} onChange={(e) => setGrid((g) => ({ ...g, [`${k}Text`]: e.target.value }))} aria-label={`Values for ${l}`}
                    className="input min-w-[200px] flex-1 py-1 text-[12.5px] tabular-nums" placeholder="values, comma-separated" />
                </div>
              ))}
              <p className="text-muted">Every combination is run; the current reading of each sensor is added automatically so the baseline sits in the grid.</p>
            </div>
          )}

          {kind === 'robustness' && (
            <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-line bg-surface p-4 text-[12.5px]">
              <label>Sensor error ±<input type="number" min={0.5} max={25} step={0.5} value={robust.tol} placeholder="auto" onChange={(e) => setRobust((r) => ({ ...r, tol: e.target.value }))} className="input mx-1 inline-block w-16 py-1 text-[12.5px]" />% <span className="text-muted">(blank = each sensor's typical error)</span></label>
              <label>Leave out each of the top<input type="number" min={0} max={10} value={robust.drop} onChange={(e) => setRobust((r) => ({ ...r, drop: e.target.value }))} className="input mx-1 inline-block w-14 py-1 text-[12.5px]" />evidence records</label>
              <span className="text-muted">{Object.keys(plan?.readings || {}).length} reading(s) found: {(plan?.sensors || []).filter((x) => x.in_question).map((x) => `${x.label} ±${robust.tol || x.tolerance_pct}%`).join(', ')}. Readings outside their normal range also get a wider ±20/40% sweep.</span>
            </div>
          )}

          {kind === 'settings' && (
            <div className="mt-3 space-y-3 rounded-lg border border-line bg-surface p-4 text-[12.5px]">
              <div className="flex flex-wrap items-center gap-2 text-muted">Presets:
                {[['source', 'Data-source ablation'], ['depth', 'Retrieval depth'], ['drop', 'Leave one evidence out']].map(([p, l]) => (
                  <button key={p} type="button" onClick={() => preset(p)} className="rounded-md border border-line px-2 py-1 font-medium text-ink hover:bg-well focus-ring">{l}</button>
                ))}
              </div>
              <fieldset className="flex flex-wrap items-center gap-3">
                <legend className="mb-1 text-ink font-medium">Data source (baseline: {dataMode})</legend>
                {modes.filter((m) => m !== dataMode).map((m) => (
                  <label key={m} className="inline-flex items-center gap-1.5"><input type="checkbox" className="accent-primary-700" checked={settings.modes.includes(m)}
                    onChange={(e) => setSettings((s) => ({ ...s, modes: e.target.checked ? [...s.modes, m] : s.modes.filter((x) => x !== m) }))} />{m} only</label>
                ))}
                {modes.length <= 1 && <span className="text-muted">This knowledge base has only one data source.</span>}
              </fieldset>
              <label className="block"><span className="font-medium text-ink">Evidence records retrieved, top_k (baseline: 8)</span>
                <input value={settings.topk} onChange={(e) => setSettings((s) => ({ ...s, topk: e.target.value }))} placeholder="e.g. 4, 12, 20" className="input mt-1 max-w-[260px] py-1 text-[12.5px]" /></label>
              <label className="block"><span className="font-medium text-ink">Leave one evidence record out — for the top</span>{' '}
                <input type="number" min={0} max={10} value={settings.drop} onChange={(e) => setSettings((s) => ({ ...s, drop: e.target.value }))} className="input inline-block w-16 py-1 text-[12.5px]" />{' '}
                <span className="text-muted">records of the baseline</span></label>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-end gap-4 border-t border-line pt-5">
          <label className="min-w-[220px] flex-1"><span className="text-[13px] font-semibold text-ink">3. Name (optional)</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className="input mt-1.5 py-1.5" placeholder="e.g. Conveyor motor — temperature tolerance" /></label>
          <div className="text-[12.5px] text-muted">
            <b className={cx('tabular-nums', runCount > maxRuns ? 'text-danger-700' : 'text-ink')}>{runCount}</b> runs (1 baseline + {Math.max(runCount - 1, 0)} changes),
            about <b className="tabular-nums text-ink">{Math.max(1, Math.round((runCount * SECONDS_PER_RUN) / 60 * 10) / 10)}</b> min
            {runCount > maxRuns && <span className="text-danger-700"> — over the {maxRuns}-run limit</span>}
            {runCount > 1 && runCount < 8 && <span> — fewer than 8 runs gives anecdotal results</span>}
          </div>
          <button type="button" onClick={start} disabled={!canRun} className="btn-primary">
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}Run experiment
          </button>
        </div>
        {error && <p role="alert" className="text-[12.5px] text-danger-700">{error}</p>}
      </section>
    </div>
  )
}

/* ─── Experiment results ─────────────────────────────────────────────────── */

function ExperimentView({ id, onChanged }) {
  const nav = useNavigate()
  const [exp, setExp] = useState(null)
  const [error, setError] = useState(null)
  // tab and selected runs live in the URL (?view=&sel=) so Back from a trace returns to the same place
  const [sp, setSp] = useSearchParams()
  const selected = useMemo(() => (sp.get('sel') || '').split(',').filter(Boolean).map(Number), [sp])
  const view = sp.get('view') || 'sweeps'
  const update = (patch) => setSp((p) => { const n = new URLSearchParams(p); Object.entries(patch).forEach(([k, v]) => (v == null || v === '' ? n.delete(k) : n.set(k, v))); return n }, { replace: true })
  const setSelected = (v) => update({ sel: (typeof v === 'function' ? v(selected) : v).join(',') })
  const setView = (v) => update({ view: v === 'sweeps' ? null : v })
  // a new tab starts at its top (the previous tab may have been scrolled far down)
  useEffect(() => { const sec = document.getElementById('lab-tabs')?.parentElement; if (sec && sec.getBoundingClientRect().top < 0) sec.scrollIntoView({ block: 'start' }) }, [view])
  const [compare, setCompare] = useState(null)
  const [highlight, setHighlight] = useState(null)
  const timer = useRef(null)

  const load = useCallback(() => getExperiment(id).then((e) => { setExp(e); setError(null); return e }).catch((e) => { setError(errText(e)); return null }), [id])

  // full load once; while running, poll the cheap progress endpoint (retrying on errors), then load in full
  useEffect(() => {
    setExp(null); setCompare(null)
    let live = true
    load().then((e) => {
      if (!live || !e || !(e.status === 'running' || e.status === 'queued')) return
      let n = 0
      timer.current = pollExperiment(id, (lite) => {
        if (!live) return
        setExp((x) => ({ ...x, ...lite }))
        if (++n % 4 === 0) load()            // refresh partial results every few polls
      }, (full) => { if (live) { setExp(full); onChanged?.() } })
    })
    return () => { live = false; if (typeof timer.current === 'function') timer.current() }
  }, [id, load]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (selected.length !== 2) { setCompare(null); return }   // two-run compare: fallback for runs recorded before step snapshots
    const [a, b] = [...selected].sort((x, y) => x - y)
    compareExperimentRuns(id, a, b).then(setCompare).catch((e) => setError(errText(e)))
  }, [id, selected])

  const colorOf = useAnswerColors(exp?.analysis)
  const toggle = (i) => setSelected((s) => (s.includes(i) ? s.filter((x) => x !== i) : s.length >= 8 ? s : [...s, i]))
  const openRun = (i) => {
    setHighlight(i)
    const base = exp.runs.find((r) => r.is_baseline)
    update({ view: 'runs', ...(base && base.run_index !== i ? { sel: [base.run_index, i].join(',') } : {}) })
  }

  if (error && !exp) return <div role="alert" className="m-6 flex items-center gap-2 rounded-lg border border-danger-100 bg-danger-50 px-4 py-2.5 text-[13px] text-danger-700"><AlertTriangle size={15} />{error}</div>
  if (!exp) return <p className="p-6 text-[13px] text-muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" />Loading experiment…</p>

  const a = exp.analysis
  const p = exp.progress
  const running = exp.status === 'running' || exp.status === 'queued'
  const doneFrac = p.total ? (p.done + p.failed) / p.total : 0
  const reps = a.ready ? a.representative_runs : []

  return (
    <div className="mx-auto max-w-[1280px] px-4 sm:px-6 py-4 space-y-3">
      <header>
        <p className="flex flex-wrap items-center gap-x-2 text-[11.5px] text-muted">
          <span className="mono">{exp.experiment_id}</span>
          <span>{KIND_LABEL[exp.kind] || exp.kind}</span>
          <span>{DATASETS.find((d) => d.id === exp.spec.dataset_type)?.label}, {exp.spec.data_mode}</span>
          {exp.source_trace_id && <Link to={`/traces/${exp.source_trace_id}`} className="text-primary-700 underline underline-offset-2">from trace</Link>}
        </p>
        <div className="mt-1 flex flex-wrap items-start gap-3">
          <h1 className="min-w-0 flex-1 text-[17px] font-semibold leading-snug text-ink">{exp.name}</h1>
          <div className="flex items-center gap-2">
            {running && <button type="button" className="btn-ghost border border-line py-1.5 text-[12.5px]" onClick={async () => { await cancelExperiment(id); load() }}><Square size={13} />Stop</button>}
            {['cancelled', 'interrupted', 'failed'].includes(exp.status) && p.done < p.total && (
              <button type="button" className="btn-ghost border border-line py-1.5 text-[12.5px]" onClick={async () => { await resumeExperiment(id); window.location.reload() }}><Play size={13} />Resume</button>)}
            {!running && <button type="button" className="btn-ghost border border-line py-1.5 text-[12.5px]" title="Delete this experiment (its traces stay in the Trace explorer)"
              onClick={async () => { if (window.confirm('Delete this experiment? Its traces stay in the Trace explorer.')) { await deleteExperiment(id); onChanged?.(); nav('/lab') } }}><Trash2 size={13} />Delete</button>}
          </div>
        </div>
        <p className="mt-0.5 text-[12.5px] leading-snug text-muted line-clamp-2" title={exp.spec.question}>{exp.spec.question}</p>
        {exp.runs?.find((r) => r.is_baseline)?.outcome?.sensor_view && <div className="mt-1.5"><ReadingsStrip sensorView={exp.runs.find((r) => r.is_baseline).outcome.sensor_view} /></div>}
        <div className="mt-2 flex items-center gap-3">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-well"><div className={cx('h-full rounded-full transition-[width] duration-500', exp.status === 'done' ? 'bg-success-500' : 'bg-primary-500')} style={{ width: `${doneFrac * 100}%` }} /></div>
          <span className="whitespace-nowrap text-[12px] tabular-nums text-muted">
            {p.done}/{p.total} runs{p.failed ? `, ${p.failed} failed` : ''} · {STATUS_TEXT[exp.status] || exp.status}
            {running && p.running && <> · now: <span className="text-ink">{p.running}</span></>}
          </span>
        </div>
        {exp.error && <p className="mt-2 text-[12.5px] text-danger-700">{exp.error}</p>}
      </header>

      {!a.ready ? <p className="text-[13px] text-muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" />Waiting for the first run…</p> : (
        <>
          {(exp.verdict || a.verdict) && <VerdictBanner verdict={exp.verdict || a.verdict} caveats={a.caveats} />}
          <section className="flex flex-wrap items-stretch gap-x-6 gap-y-2 rounded-lg border border-line bg-surface px-4 py-2.5 text-[12.5px]">
            <div className="min-w-0">
              <p className="eyebrow">Baseline</p>
              {a.baseline ? <div className="flex items-center gap-2"><AnswerChip answer={a.baseline.answer} color={colorOf(a.baseline.answer)} className="text-[13.5px] font-semibold" />
                <span className="tabular-nums text-muted">{Math.round((a.baseline.confidence || 0) * 100)}%</span><ReviewDecision decision={a.baseline.review_decision} variant="inline" /></div>
                : <p className="text-muted">Not finished</p>}
            </div>
            <div><p className="eyebrow">Flipped the answer</p><p className="text-[16px] font-semibold tabular-nums text-ink">{a.runs_changed_vs_baseline.answer}<span className="text-[12px] font-normal text-muted"> / {Math.max(a.completed_runs - 1, 0)} changes</span></p></div>
            <div><p className="eyebrow">Flipped the review</p><p className="text-[16px] font-semibold tabular-nums text-ink">{a.runs_changed_vs_baseline.review}<span className="text-[12px] font-normal text-muted"> / {Math.max(a.completed_runs - 1, 0)}</span></p></div>
            <div className="min-w-0 flex-1"><p className="eyebrow">Answers seen</p>
              <div className="flex flex-wrap gap-x-3">{Object.entries(a.answer_counts).sort((x, y) => y[1] - x[1]).map(([ans, n]) => <AnswerChip key={ans} answer={`${ans} ×${n}`} color={colorOf(ans)} />)}</div></div>
            <details className="w-full text-[12px] text-muted">
              <summary className="cursor-pointer select-none"><AlertTriangle size={12} className="mr-1 inline text-warning-600" aria-hidden />{a.caveats.length} things to keep in mind when reading these results</summary>
              <ul className="mt-1 list-disc space-y-0.5 pl-5">{a.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
            </details>
          </section>
        </>
      )}

      <section>
        <div id="lab-tabs" role="tablist" aria-label="Experiment views" className="scroll-mt-0 sticky top-0 z-10 -mx-1 flex gap-5 overflow-x-auto border-b border-line bg-canvas px-1">
          {VIEWS.filter(([v]) => a.ready || v === 'runs').map(([v, label]) => (
            <button key={v} role="tab" type="button" aria-selected={view === v} onClick={() => setView(v)}
              className={cx('relative whitespace-nowrap py-2 text-[13px] focus-ring rounded-sm', view === v ? 'font-semibold text-ink after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:bg-ink' : 'text-muted hover:text-ink')}>
              {label}{v === 'runs' && selected.length >= 2 && <span className="ml-1.5 text-[11px] text-muted">comparing {selected.length}</span>}
            </button>
          ))}
        </div>
        <div className="pt-3" role="tabpanel">
          {a.ready && view === 'sweeps' && a.grid && <div className="rounded-xl border border-line bg-surface p-3">
            <p className="mb-2 text-[13px] font-semibold text-ink">Interaction map — {a.grid.x_label} × {a.grid.y_label}</p>
            <GridChart grid={a.grid} colorOf={colorOf} onOpenRun={openRun} /></div>}
          {a.ready && view === 'sweeps' && !a.grid && <>
            <div className="mb-5 rounded-xl border border-line bg-surface p-3"><p className="mb-2 text-[13px] font-semibold text-ink">Response chart</p>
              <ResponseChart exp={exp} colorOf={colorOf} onOpenRun={openRun} onCompare={(ids) => update({ sel: ids.join(','), view: 'runs' })} /></div>
            <p className="mb-3 text-[12px] text-muted">Each value tried, in order; colour = the diagnosis it produced, a vertical line = the answer changes. Click a value to compare it with the baseline.</p>
            <FactorSweeps factors={a.factors} colorOf={colorOf} onOpenRun={openRun} /></>}
          {a.ready && view === 'steps' && <><p className="mb-2 text-[12px] text-muted">Steps matched across runs by what they are. “Linked to the answer” = runs that decided the same here mostly reached the same diagnosis; the flag marks the first such step.</p>
            <StepDivergence steps={a.step_divergence} firstKey={a.first_divergent_step} colorOf={colorOf} total={a.completed_runs} /></>}
          {a.ready && view === 'agents' && <AgentMatrix agents={a.agents} runs={exp.runs} colorOf={colorOf} onPick={openRun} />}
          {a.ready && view === 'ribbons' && <StepRibbons runs={reps} divergence={a.step_divergence} colorOf={colorOf} />}
          {view === 'runs' && (
            <div className="space-y-4">
              <div><p className="mb-2 text-[12px] text-muted">Tick runs to compare (2–8).</p>
                <RunsTable runs={exp.runs} colorOf={colorOf} selected={selected} onToggle={toggle} highlight={highlight} /></div>
              <div id="lab-compare">
                {selected.length >= 2 ? (() => {
                  const chosen = [...selected].sort((x, y) => x - y).map((i) => exp.runs.find((r) => r.run_index === i)).filter((r) => r?.trace_id)
                  return <MultiCompare key={chosen.map((r) => r.trace_id).join()} ids={chosen.map((r) => r.trace_id)} labels={chosen.map((r) => r.label)}
                    fallback={compare ? <CompareView data={compare} colorOf={colorOf} /> : <p className="text-[12.5px] text-muted">These runs were recorded before step snapshots existed; select exactly two to compare them.</p>} />
                })() : <p className="rounded-lg border border-dashed border-line p-4 text-[12.5px] text-muted">Tick two or more runs (up to 8) to compare them step by step and agent by agent. The lowest-numbered run is the reference.</p>}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

/* ─── Page ───────────────────────────────────────────────────────────────── */

export default function ExperimentLabPage() {
  const { experimentId } = useParams()
  const nav = useNavigate()
  const [list, setList] = useState({ items: [], loading: true })

  const refresh = useCallback(() => {
    setList((l) => ({ ...l, loading: true }))
    listExperiments().then((r) => setList({ items: r.items, loading: false }))
      .catch((e) => setList({ items: [], loading: false, error: errText(e) }))
  }, [])
  useEffect(() => { refresh() }, [refresh])

  // /lab → newest experiment, or the form when there is none
  useEffect(() => {
    if (!experimentId && !list.loading) nav(list.items[0] ? `/lab/${list.items[0].experiment_id}` : '/lab/new', { replace: true })
  }, [experimentId, list, nav])

  const isNew = experimentId === 'new'
  return (
    <div className="h-full overflow-y-auto md:overflow-hidden md:grid md:grid-cols-[280px_minmax(0,1fr)] md:grid-rows-[minmax(0,1fr)]">
      <ExperimentList items={list.items} selected={experimentId} onRefresh={refresh} loading={list.loading} error={list.error} />
      <div className="md:min-h-0 md:overflow-y-auto">
        {isNew && <NewExperiment onCreated={(id) => { refresh(); nav(`/lab/${id}`) }} />}
        {experimentId && !isNew && <ExperimentView key={experimentId} id={experimentId} onChanged={refresh} />}
      </div>
    </div>
  )
}
