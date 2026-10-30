import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { Send, Loader2, AlertTriangle, Upload, RefreshCw } from 'lucide-react'
import AppShell from '../components/AppShell'
import DiagnosisReport from '../components/DiagnosisReport'
import DecisionExplorer from '../components/DecisionExplorer'
import { cx, SourceBadge } from '../components/ui'
import { checkHealth, loadDataset, sendQuery } from '../services/api'

/*
 * Scenario prompts. These are ILLUSTRATIVE inputs written for demonstration — not measurements from
 * real equipment. They only pre-fill the question box; the diagnosis always comes from the backend
 * harness. Values sit near the patterns present in the knowledge base so retrieval has something to
 * compare against, and every fault named in a title is one of the existing AFRB labels.
 * `group` only controls how the sidebar lists them.
 */
const SAMPLES = {
  afrb: [
    { group: 'fault', tag: 'Clear fault', q: 'Slurry pump in a mineral processing facility: temperature 95.0 °C, vibration 0.790, pressure 55.0 PSI, 2400 RPM, current 55.0 A, voltage 310.0 V, flow rate 100.0 L/min. What is the most likely fault?' },
    { group: 'fault', tag: 'Pump problem', q: 'Centrifugal pump: temperature 60 °C, vibration 0.55, pressure 22 PSI, 2400 RPM, current 70 A, voltage 325 V, flow rate 48 L/min. What failure does this indicate?' },
    { group: 'fault', tag: 'Bearing overheating', q: 'Electric motor driving a conveyor belt: temperature 88.0 °C at the drive-end housing, vibration 0.700, pressure 54.0 PSI, 2450 RPM, current 61.0 A, voltage 312.0 V, flow rate 100.0 L/min. Temperature and vibration have both climbed over the last shift. What is the most likely fault?' },
    { group: 'fault', tag: 'Motor overload', q: 'Axial fan motor in a steel mill ventilation system: temperature 80.0 °C, vibration 0.210, pressure 53.0 PSI, 2300 RPM, current 97.0 A, voltage 386.0 V, flow rate 105.0 L/min. Current draw is well above its usual level. What is causing this?' },
    { group: 'fault', tag: 'Pump cavitation', q: 'Centrifugal pump in a municipal water treatment plant: temperature 57.0 °C, vibration 0.450, pressure 29.0 PSI and fluctuating, 2500 RPM, current 67.0 A, voltage 330.0 V, flow rate 62.0 L/min and unstable. What is the most likely fault?' },
    { group: 'fault', tag: 'Lubrication failure', q: 'Process gas compressor: temperature 92.0 °C, vibration 0.550, pressure 54.0 PSI, 2500 RPM, current 77.0 A, voltage 316.0 V, flow rate 97.0 L/min. Temperature and current keep rising between oil changes, suggesting increasing friction. Diagnose.' },
    { group: 'fault', tag: 'Normal equipment', q: 'Booster pump station: temperature 54.0 °C, vibration 0.140, pressure 52.0 PSI, 2000 RPM, current 60.0 A, voltage 330.0 V, flow rate 110.0 L/min. Is anything wrong?' },
    { group: 'data', tag: 'Missing sensor', q: 'Gearbox driving a paper mill roller: temperature reading unavailable, vibration 0.810, pressure 50.0 PSI, 2200 RPM, current 75.0 A, voltage 330.0 V, flow rate 100.0 L/min. Diagnose.' },
    { group: 'data', tag: 'Conflicting signals', q: 'Cooling tower circulation pump: temperature 56.0 °C, vibration 0.880, pressure 51.0 PSI, 2100 RPM, current 61.0 A, voltage 330.0 V, flow rate 108.0 L/min. What is wrong?' },
    { group: 'data', tag: 'Sensor drift', q: 'High-pressure feed pump in a petrochemical refinery: temperature 16.0 °C, vibration 0.200, pressure 55.0 PSI, 4000 RPM, current 143.0 A, voltage 326.0 V, flow rate 121.0 L/min. The temperature looks implausibly low for this load. Can these readings be trusted, and what is the likely fault?' },
    { group: 'data', tag: 'No historical match', q: 'Axial fan unit: temperature 118.0 °C, vibration 0.040, pressure 97.0 PSI, 4800 RPM, current 30.0 A, voltage 470.0 V, flow rate 190.0 L/min. What is wrong?' },
    { group: 'data', tag: 'Qualitative only', q: 'Predict failure from elevated vibration and temperature readings.' },
  ],
  // Real measured knowledge base (UCI #447 hydraulic test rig). Prompts use values typical of each recorded
  // condition but are still illustrative inputs; the rig has no RPM, current or voltage sensors.
  hydraulic: [
    { group: 'fault', tag: 'Hot oil, low flow', q: 'Hydraulic power unit: temperature 54.2 °C, vibration 0.65, pressure 158 bar, flow rate 6.48 L/min. What is the most likely fault?' },
    { group: 'fault', tag: 'Accumulator pressure', q: 'Hydraulic power unit: temperature 36.3 °C, vibration 0.565, pressure 160.5 bar, flow rate 6.65 L/min. Pressure recovery after each load step feels sluggish. What is the most likely fault?' },
    { group: 'fault', tag: 'Pump leakage', q: 'Hydraulic power unit: temperature 36.3 °C, vibration 0.543, pressure 160.4 bar, flow rate 6.42 L/min. Delivered flow is slightly down at constant load. Diagnose.' },
    { group: 'fault', tag: 'Valve switching', q: 'Hydraulic power unit: temperature 36.25 °C, vibration 0.55, pressure 160.6 bar, flow rate 6.49 L/min. Cycle timing has drifted. What is the most likely fault?' },
    { group: 'fault', tag: 'Healthy cycle', q: 'Hydraulic power unit: temperature 36.0 °C, vibration 0.551, pressure 161.0 bar, flow rate 6.71 L/min. Is anything wrong?' },
    { group: 'data', tag: 'Missing temperature', q: 'Hydraulic power unit: temperature reading unavailable, vibration 0.6, pressure 158 bar, flow rate 6.5 L/min. Diagnose.' },
  ],
  failure_iq: [
    { tag: 'Sensor → events', q: 'Which failure is likely when winding temperature rises in an electric motor?' },
    { tag: 'Sensor → events', q: 'What does abnormal oil debris indicate in a compressor?' },
    { tag: 'Sparse data', q: 'Why is vibration increasing in the pump?' },
  ],
}
const SAMPLE_GROUPS = [
  { id: 'fault', title: 'Fault patterns' },
  { id: 'data', title: 'Data quality & edge cases' },
]

const MODES = [
  { id: 'real', label: 'Real' },
  { id: 'synthetic', label: 'Synthetic' },
  { id: 'combined', label: 'Combined' },
]

export default function ChatPage() {
  const { dataset = 'afrb' } = useParams()
  const [health, setHealth] = useState(null)
  const [mode, setMode] = useState('combined')
  const [input, setInput] = useState('')
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const bottom = useRef(null)
  const fileRef = useRef(null)
  const inputRef = useRef(null)

  const refresh = useCallback(() => checkHealth().then(setHealth).catch(() => setHealth({ offline: true })), [])
  useEffect(() => { refresh(); setRuns([]) }, [dataset, refresh])
  // Only follow new runs / completion. Depending on `runs` itself scrolled to the bottom whenever a
  // run's view tab was switched (that also updates `runs`).
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [runs.length, loading])

  const modes = health?.data_modes?.[dataset] || []
  const counts = health?.record_counts?.[dataset] || {}
  const loaded = Object.values(counts).some((n) => n > 0)
  const effectiveMode = modes.includes(mode) ? mode : modes[0] || 'real'

  const submit = async (q = input) => {
    const question = q.trim()
    if (!question || loading) return
    setInput(''); setError(null); setLoading(true)
    setRuns((r) => [...r, { question, mode: effectiveMode }])
    try {
      const result = await sendQuery(question, dataset, effectiveMode)
      setRuns((r) => r.map((x, i) => (i === r.length - 1 ? { ...x, result } : x)))
    } catch (e) {
      const msg = e.response?.data?.detail || e.message
      setError(msg)
      setRuns((r) => r.map((x, i) => (i === r.length - 1 ? { ...x, error: msg } : x)))
    } finally { setLoading(false) }
  }

  // Uses the existing flow: a scenario only fills the input; submission stays with the user.
  const pickScenario = (q) => {
    setInput(q)
    requestAnimationFrame(() => {
      const el = inputRef.current
      if (el) { el.focus(); el.setSelectionRange(q.length, q.length) }
    })
  }

  const aside = (
    <div className="space-y-5 pt-2">
      <div>
        <div className="eyebrow px-2 mb-2">Dataset mode</div>
        <div role="radiogroup" className="grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1">
          {MODES.map((m) => {
            const ok = modes.includes(m.id)
            return (
              <button key={m.id} role="radio" aria-checked={effectiveMode === m.id} disabled={!ok} onClick={() => setMode(m.id)}
                className={cx('rounded-md py-1.5 text-[12px] font-medium', effectiveMode === m.id ? 'bg-white shadow-card text-ink' : 'text-muted', !ok && 'opacity-40 cursor-not-allowed')}>
                {m.label}
              </button>
            )
          })}
        </div>
        <div className="mt-2 px-2 text-[11px] text-muted space-y-0.5">
          <div className="flex justify-between"><span>Real records</span><b className="text-ink tabular-nums">{(counts.real ?? 0).toLocaleString()}</b></div>
          <div className="flex justify-between"><span>Synthetic records</span><b className="text-ink tabular-nums">{(counts.synthetic ?? 0).toLocaleString()}</b></div>
          {dataset === 'failure_iq' && <div className="text-[10px]">This knowledge base has no synthetic partition.</div>}
          {dataset === 'hydraulic' && <div className="text-[10px] leading-snug">Measured 60 s load cycles from the UCI #447 hydraulic test rig. No synthetic partition; RPM, current and voltage are not measured on this rig.</div>}
        </div>
      </div>
      <div>
        <div className="eyebrow px-2 mb-1">Try a scenario</div>
        <p className="px-2 mb-2 text-[10.5px] leading-snug text-muted">Illustrative inputs, not live plant measurements. Selecting one fills the question box.</p>
        {(() => {
          const list = SAMPLES[dataset] || []
          const groups = list.some((s) => s.group) ? SAMPLE_GROUPS.map((g) => ({ ...g, items: list.filter((s) => s.group === g.id) })) : [{ id: 'all', items: list }]
          return groups.filter((g) => g.items.length).map((g) => (
            <div key={g.id} className="mb-2 last:mb-0">
              {g.title && <div className="px-2 pt-1 pb-0.5 text-[10.5px] font-semibold text-slate-500">{g.title}</div>}
              <ul className="space-y-0.5">
                {g.items.map((s) => {
                  const active = input === s.q
                  return (
                    <li key={s.q}>
                      <button type="button" data-drawer-close title={s.q} aria-pressed={active} onClick={() => pickScenario(s.q)}
                        className={cx('w-full text-left rounded-lg px-2 py-1.5 border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
                          active ? 'border-primary-200 bg-primary-50' : 'border-transparent hover:bg-slate-50')}>
                        <div className={cx('text-[12px] font-medium', active ? 'text-primary-700' : 'text-ink')}>{s.tag}</div>
                        <div className="text-[11px] text-muted line-clamp-2 break-words">{s.q}</div>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))
        })()}
      </div>
      {dataset === 'afrb' && (
        <div className="px-2">
          <div className="eyebrow mb-2">Custom AFRB CSV</div>
          <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={async (e) => {
            const f = e.target.files?.[0]; if (!f) return
            setLoading(true); try { await loadDataset('afrb', f); await refresh() } catch (err) { setError(err.response?.data?.detail || err.message) } finally { setLoading(false) }
          }} />
          <button className="btn-ghost w-full border border-line" onClick={() => fileRef.current?.click()}><Upload size={14} /> Upload as REAL partition</button>
        </div>
      )}
    </div>
  )

  return (
    <AppShell aside={aside}>
      <div className="flex flex-col h-full min-h-0">
        <header className="min-h-14 shrink-0 border-b border-line bg-white px-4 sm:px-6 py-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
          <div className="flex items-center gap-3 min-w-0">
            <h1 className="text-[15px] font-semibold truncate">{({ afrb: 'AFRB sensor diagnosis', failure_iq: 'FailureSensorIQ relevance', hydraulic: 'Hydraulic rig diagnosis (real data)' })[dataset] || dataset}</h1>
            <SourceBadge source={effectiveMode} />
          </div>
          <div className="flex items-center gap-2 text-[12px] min-w-0">
            {health?.offline ? <span className="text-danger-600">Backend offline</span> :
              <span className={loaded ? 'text-success-700' : 'text-warning-700'}>{loaded ? '● knowledge base ready' : '● not loaded'}</span>}
            <span className="hidden lg:inline text-muted truncate">· {health?.llm_mode === 'llm+deterministic' ? 'LLM + deterministic agents' : 'deterministic agents (no LLM configured)'}</span>
            <button className="btn-ghost px-2" onClick={refresh} title="Refresh status"><RefreshCw size={14} /></button>
          </div>
        </header>

        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain scroll-pb-6">
          <div className="max-w-[1440px] mx-auto px-3 sm:px-6 pt-5 pb-10 space-y-8">
            {runs.length === 0 && (
              <div className="card p-8 text-center">
                <h2 className="text-lg font-semibold">Ask a diagnostic question</h2>
                <p className="text-sm text-muted mt-1 max-w-2xl mx-auto">
                  Include the readings you have (temperature, vibration, pressure, RPM, current, voltage, flow). Missing channels are
                  never guessed. Three independent agents analyse the evidence, the Verification Analyst challenges them, targeted retrieval
                  runs if the evidence is weak, and an explicit gate decides whether a human must review.
                </p>
              </div>
            )}
            {runs.map((r, i) => (
              <div key={i} className="space-y-3">
                <div className="flex justify-end">
                  <div className="max-w-3xl rounded-xl bg-primary-600 text-white px-4 py-2.5 text-sm">{r.question}</div>
                </div>
                {r.result && (
                  <div className="space-y-3">
                    <div role="tablist" aria-label="Result view" className="inline-flex rounded-lg bg-slate-100 p-1">
                      {[['explorer', 'Decision Explorer'], ['report', 'Detailed report']].map(([v, label]) => (
                        <button key={v} role="tab" aria-selected={(r.view || 'explorer') === v}
                          onClick={() => setRuns((all) => all.map((x, j) => (j === i ? { ...x, view: v } : x)))}
                          className={cx('rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
                            (r.view || 'explorer') === v ? 'bg-white shadow-card text-ink' : 'text-muted hover:text-ink')}>
                          {label}
                        </button>
                      ))}
                    </div>
                    {/* keep the explorer mounted while the report tab is shown so its panel state is not reset */}
                    <div hidden={(r.view || 'explorer') !== 'explorer'}>
                      <DecisionExplorer result={r.result} question={r.question} />
                    </div>
                    {r.view === 'report' && <DiagnosisReport result={r.result} />}
                  </div>
                )}
                {r.error && <div className="card p-4 text-sm text-danger-700 flex gap-2"><AlertTriangle size={16} />{r.error}</div>}
                {!r.result && !r.error && (
                  <div className="card p-4 text-sm text-muted flex items-center gap-2">
                    <Loader2 size={16} className="animate-spin text-primary-600" /> Running the six-agent harness ({r.mode} data)…
                  </div>
                )}
              </div>
            ))}
            <div ref={bottom} className="h-px" />
          </div>
        </div>

        <footer className="shrink-0 border-t border-line bg-white px-3 sm:px-6 py-3">
          <div className="max-w-[1440px] mx-auto flex items-end gap-2">
            <textarea ref={inputRef} aria-label="Diagnostic question" value={input} onChange={(e) => setInput(e.target.value)} rows={2} className="input resize-none"
              placeholder="e.g. Slurry pump: temperature 93 °C, vibration 0.79, current 55 A … what is the most likely fault?"
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }} />
            <button className="btn-primary h-[58px] px-4" disabled={!input.trim() || loading || !loaded} onClick={() => submit()} aria-label="Run diagnosis">
              {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            </button>
          </div>
          {error && <p className="max-w-[1440px] mx-auto text-[12px] text-danger-600 mt-1">{error}</p>}
        </footer>
      </div>
    </AppShell>
  )
}
