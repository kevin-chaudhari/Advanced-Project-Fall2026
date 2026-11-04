import { useEffect, useRef, useState } from 'react'
import { Loader2, Upload, ListPlus, X, CornerDownLeft } from 'lucide-react'
import { useDiagnostics, DATASETS } from '../../state/DiagnosticsContext'
import { SAMPLES, SAMPLE_GROUPS } from '../../lib/scenarios'

const PLACEHOLDER = {
  afrb: 'Describe the equipment and the readings you have, e.g. slurry pump at 93 °C, vibration 0.79, current 55 A. What is the most likely fault?',
  hydraulic: 'e.g. Hydraulic power unit: temperature 54 °C, pressure 158 bar, flow 6.5 L/min. What is the most likely fault?',
  failure_iq: 'e.g. Which failure is likely when winding temperature rises in an electric motor?',
}

function Scenarios({ dataset, onPick, onClose }) {
  const list = SAMPLES[dataset] || []
  const groups = list.some((s) => s.group) ? SAMPLE_GROUPS.map((g) => ({ ...g, items: list.filter((s) => s.group === g.id) })) : [{ id: 'all', items: list }]
  return (
    <div className="mb-2 rounded-xl border border-line bg-surface p-3 max-h-[42vh] overflow-y-auto">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[12px] text-muted">Example inputs, not live plant measurements. Choosing one fills the question box; nothing is sent until you run it.</p>
        <button type="button" onClick={onClose} className="btn-ghost p-1 shrink-0" aria-label="Close examples"><X size={14} /></button>
      </div>
      {groups.filter((g) => g.items.length).map((g) => (
        <div key={g.id} className="mt-2">
          {g.title && <div className="text-[11.5px] font-medium text-muted mb-1">{g.title}</div>}
          <div className="flex flex-wrap gap-1.5">
            {g.items.map((s) => (
              <button key={s.q} type="button" title={s.q} onClick={() => onPick(s.q)}
                className="rounded-md border border-line bg-canvas px-2.5 py-1 text-[12px] text-ink hover:border-primary-300 hover:bg-primary-50 focus-ring">
                {s.tag}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/** Multiline question box with examples and (AFRB) CSV upload. Every run uses real + synthetic records combined. */
export default function ChatInput({ draft, setDraft, onSubmitted }) {
  const { dataset, loaded, health, running, submit, uploadCsv, uploading, notice, setNotice } = useDiagnostics()
  const [showExamples, setShowExamples] = useState(false)
  const ta = useRef(null)
  const file = useRef(null)
  const ds = DATASETS.find((d) => d.id === dataset)

  // grow with content up to ~8 lines
  useEffect(() => {
    const el = ta.current; if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [draft])

  const blocked = health?.offline ? 'The backend is offline.' : health && !loaded ? `${ds?.label} is not loaded on the backend.` : null
  const canSend = draft.trim() && !running && !blocked && health

  const send = async () => {
    if (!canSend) return
    const q = draft
    setDraft('')
    setShowExamples(false)
    const id = submit(q)
    onSubmitted?.()
    await id
  }

  return (
    <div className="w-full">
      {showExamples && <Scenarios dataset={dataset} onClose={() => setShowExamples(false)}
        onPick={(q) => { setDraft(q); setShowExamples(false); requestAnimationFrame(() => { ta.current?.focus(); ta.current?.setSelectionRange(q.length, q.length) }) }} />}

      <div className="rounded-xl border border-line bg-surface focus-within:border-primary-500 focus-within:ring-2 focus-within:ring-primary-100 transition-shadow">
        <label htmlFor="diag-question" className="sr-only">Diagnostic question</label>
        <textarea id="diag-question" ref={ta} rows={2} value={draft} onChange={(e) => setDraft(e.target.value)}
          placeholder={PLACEHOLDER[dataset] || PLACEHOLDER.afrb}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }}
          className="block w-full resize-none bg-transparent px-4 pt-3 pb-1 text-[14px] leading-relaxed text-ink placeholder:text-slate-500 outline-none" />
        <div className="flex flex-wrap items-center gap-2 px-2.5 pb-2.5 pt-1">
          <button type="button" onClick={() => setShowExamples((v) => !v)} aria-expanded={showExamples}
            className="btn-ghost px-2 py-1 text-[12px]"><ListPlus size={14} aria-hidden /> Examples</button>
          {dataset === 'afrb' && (
            <>
              <input ref={file} type="file" accept=".csv" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) uploadCsv(f) }} />
              <button type="button" onClick={() => file.current?.click()} disabled={uploading || running}
                className="btn-ghost px-2 py-1 text-[12px]" title="Upload an AFRB CSV; it becomes a new REAL partition">
                {uploading ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Upload size={14} aria-hidden />} {uploading ? 'Loading CSV…' : 'Upload CSV'}
              </button>
            </>
          )}
          <span className="ml-auto hidden sm:inline text-[11.5px] text-muted">
            <CornerDownLeft size={11} className="inline -mt-px" aria-hidden /> to run, Shift + Enter for a new line
          </span>
          <button type="button" onClick={send} disabled={!canSend} className="btn-primary px-4 py-1.5 text-[13px]">
            {running ? <><Loader2 size={14} className="animate-spin" aria-hidden /> Analysing…</> : 'Run diagnosis'}
          </button>
        </div>
      </div>
      <div aria-live="polite" className="min-h-[18px] mt-1.5 px-1 text-[12px]">
        {blocked ? <span className="text-danger-700">{blocked} {health?.offline ? 'Start it and recheck the connection in the top bar.' : 'Load it from the backend, then recheck.'}</span>
          : notice ? <span className={notice.tone === 'error' ? 'text-danger-700' : 'text-success-700'}>{notice.text} <button type="button" className="underline ml-1" onClick={() => setNotice(null)}>Dismiss</button></span>
            : running ? <span className="text-muted">Diagnosis in progress. You can switch to the dashboard; the result will appear there too.</span>
              : null}
      </div>
    </div>
  )
}
