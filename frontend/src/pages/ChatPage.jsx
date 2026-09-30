import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { Send, Loader2, AlertTriangle, Upload, RefreshCw } from 'lucide-react'
import AppShell from '../components/AppShell'
import DiagnosisReport from '../components/DiagnosisReport'
import { cx, SourceBadge } from '../components/ui'
import { checkHealth, loadDataset, sendQuery } from '../services/api'

const SAMPLES = {
  afrb: [
    { tag: 'Clear fault', q: 'Slurry pump in a mineral processing facility: temperature 95.0 °C, vibration 0.790, pressure 55.0 PSI, 2400 RPM, current 55.0 A, voltage 310.0 V, flow rate 100.0 L/min. What is the most likely fault?' },
    { tag: 'Missing sensor', q: 'Gearbox driving a paper mill roller: temperature reading unavailable, vibration 0.810, pressure 50.0 PSI, 2200 RPM, current 75.0 A, voltage 330.0 V, flow rate 100.0 L/min. Diagnose.' },
    { tag: 'Conflicting signals', q: 'Cooling tower circulation pump: temperature 56.0 °C, vibration 0.880, pressure 51.0 PSI, 2100 RPM, current 61.0 A, voltage 330.0 V, flow rate 108.0 L/min. What is wrong?' },
    { tag: 'Pump problem', q: 'Centrifugal pump: temperature 60 °C, vibration 0.55, pressure 22 PSI, 2400 RPM, current 70 A, voltage 325 V, flow rate 48 L/min. What failure does this indicate?' },
    { tag: 'Normal equipment', q: 'Booster pump station: temperature 54.0 °C, vibration 0.140, pressure 52.0 PSI, 2000 RPM, current 60.0 A, voltage 330.0 V, flow rate 110.0 L/min. Is anything wrong?' },
    { tag: 'No historical match', q: 'Axial fan unit: temperature 118.0 °C, vibration 0.040, pressure 97.0 PSI, 4800 RPM, current 30.0 A, voltage 470.0 V, flow rate 190.0 L/min. What is wrong?' },
    { tag: 'Qualitative only', q: 'Predict failure from elevated vibration and temperature readings.' },
  ],
  failure_iq: [
    { tag: 'Sensor → events', q: 'Which failure is likely when winding temperature rises in an electric motor?' },
    { tag: 'Sensor → events', q: 'What does abnormal oil debris indicate in a compressor?' },
    { tag: 'Sparse data', q: 'Why is vibration increasing in the pump?' },
  ],
}

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

  const refresh = useCallback(() => checkHealth().then(setHealth).catch(() => setHealth({ offline: true })), [])
  useEffect(() => { refresh(); setRuns([]) }, [dataset, refresh])
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [runs, loading])

  const modes = health?.data_modes?.[dataset] || []
  const counts = health?.record_counts?.[dataset] || {}
  const loaded = dataset === 'afrb' ? health?.afrb_loaded : health?.failure_iq_loaded
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
        </div>
      </div>
      <div>
        <div className="eyebrow px-2 mb-2">Try a scenario</div>
        <div className="space-y-1">
          {(SAMPLES[dataset] || []).map((s) => (
            <button key={s.q} onClick={() => setInput(s.q)} className="w-full text-left rounded-lg px-2 py-1.5 hover:bg-slate-50">
              <div className="text-[12px] font-medium text-ink">{s.tag}</div>
              <div className="text-[11px] text-muted line-clamp-2">{s.q}</div>
            </button>
          ))}
        </div>
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
      <div className="flex flex-col h-screen">
        <header className="h-14 shrink-0 border-b border-line bg-white px-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-[15px] font-semibold">{dataset === 'afrb' ? 'AFRB sensor diagnosis' : 'FailureSensorIQ relevance'}</h1>
            <SourceBadge source={effectiveMode} />
          </div>
          <div className="flex items-center gap-2 text-[12px]">
            {health?.offline ? <span className="text-danger-600">Backend offline</span> :
              <span className={loaded ? 'text-success-700' : 'text-warning-700'}>{loaded ? '● knowledge base ready' : '● not loaded'}</span>}
            <span className="text-muted">· {health?.llm_mode === 'llm+deterministic' ? 'LLM + deterministic agents' : 'deterministic agents (no LLM configured)'}</span>
            <button className="btn-ghost px-2" onClick={refresh} title="Refresh status"><RefreshCw size={14} /></button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-6xl mx-auto px-6 py-6 space-y-8">
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
                {r.result && <DiagnosisReport result={r.result} />}
                {r.error && <div className="card p-4 text-sm text-danger-700 flex gap-2"><AlertTriangle size={16} />{r.error}</div>}
                {!r.result && !r.error && (
                  <div className="card p-4 text-sm text-muted flex items-center gap-2">
                    <Loader2 size={16} className="animate-spin text-primary-600" /> Running the six-agent harness ({r.mode} data)…
                  </div>
                )}
              </div>
            ))}
            <div ref={bottom} />
          </div>
        </div>

        <footer className="shrink-0 border-t border-line bg-white px-6 py-3">
          <div className="max-w-6xl mx-auto flex items-end gap-2">
            <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={2} className="input resize-none"
              placeholder="e.g. Slurry pump: temperature 93 °C, vibration 0.79, current 55 A … what is the most likely fault?"
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }} />
            <button className="btn-primary h-[58px] px-4" disabled={!input.trim() || loading || !loaded} onClick={() => submit()} aria-label="Run diagnosis">
              {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            </button>
          </div>
          {error && <p className="max-w-6xl mx-auto text-[12px] text-danger-600 mt-1">{error}</p>}
        </footer>
      </div>
    </AppShell>
  )
}
