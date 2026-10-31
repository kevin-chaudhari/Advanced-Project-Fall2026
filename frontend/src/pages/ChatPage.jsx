import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useDiagnostics, DATASETS } from '../state/DiagnosticsContext'
import { SAMPLES } from '../lib/scenarios'
import ConversationHistory from '../components/chat/ConversationHistory'
import ChatMessage from '../components/chat/ChatMessage'
import ChatInput from '../components/chat/ChatInput'

function EmptyChat({ onPick }) {
  const { dataset, counts, loaded, health } = useDiagnostics()
  const ds = DATASETS.find((d) => d.id === dataset)
  const examples = (SAMPLES[dataset] || []).slice(0, 3)
  return (
    <div className="mx-auto max-w-[760px] pt-[8vh] pb-10">
      <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Ask about a machine</h1>
      <p className="mt-2 text-[14px] leading-relaxed text-ink">
        Give the readings you have: temperature, vibration, pressure, RPM, current, voltage, flow. Missing channels are
        never guessed. Three agents analyse the evidence independently, a verifier challenges them, extra retrieval runs
        if the evidence is weak, and a review gate decides whether a person must confirm the result.
      </p>
      <p className="mt-3 text-[12.5px] text-muted">
        {ds?.long}.{' '}
        {health && !health.offline && (loaded ? `${Object.entries(counts).map(([k, n]) => `${n.toLocaleString()} ${k}`).join(', ')} records available.` : 'Not loaded on the backend.')}
      </p>
      {examples.length > 0 && (
        <div className="mt-6">
          <h2 className="text-[12.5px] text-muted mb-2">Start from an example</h2>
          <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
            {examples.map((s) => (
              <li key={s.q}>
                <button type="button" onClick={() => onPick(s.q)} className="w-full px-4 py-3 text-left hover:bg-well/50 focus-ring rounded-xl">
                  <div className="text-[13px] font-medium text-ink">{s.tag}</div>
                  <div className="mt-0.5 text-[12.5px] text-muted line-clamp-1">{s.q}</div>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/**
 * Diagnostic Chat — the full workspace: every question, the complete coordinator answer,
 * agent reasoning and evidence. Scrolls vertically; the input stays pinned.
 */
export default function ChatPage() {
  const { runs, removeRun, clearRuns } = useDiagnostics()
  const { hash } = useLocation()
  const [draft, setDraft] = useState('')
  const [active, setActive] = useState(null)
  const scroller = useRef(null)
  const prevCount = useRef(runs.length)

  const scrollTo = useCallback((id, smooth = true) => {
    const el = document.getElementById(`run-${id}`)
    if (!el) return
    el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' })
    setActive(id)
  }, [])

  // arriving from the dashboard with #run-<id>
  useEffect(() => {
    const id = hash.startsWith('#run-') ? hash.slice(5) : null
    if (id) requestAnimationFrame(() => scrollTo(id, false))
    else if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight
  }, [hash, scrollTo])

  // follow a newly submitted question
  useEffect(() => {
    if (runs.length > prevCount.current) {
      const last = runs[runs.length - 1]
      requestAnimationFrame(() => scrollTo(last.id))
    }
    prevCount.current = runs.length
  }, [runs, scrollTo])

  const pick = (q) => { setDraft(q); requestAnimationFrame(() => document.getElementById('diag-question')?.focus()) }

  return (
    <div className="h-full grid lg:grid-cols-[272px_minmax(0,1fr)]">
      <aside className="hidden lg:block min-h-0 border-r border-line bg-well/40">
        <ConversationHistory runs={runs} activeId={active} onSelect={scrollTo} onClear={clearRuns} />
      </aside>
      <div className="flex min-h-0 flex-col">
        <div ref={scroller} className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
          <div className="w-full px-4 sm:px-6 lg:px-8 py-6">
            {runs.length === 0 ? <EmptyChat onPick={pick} /> : (
              <div className="space-y-10">
                {runs.map((r) => <ChatMessage key={r.id} run={r} onRemove={removeRun} highlighted={active === r.id && hash === `#run-${r.id}`} />)}
              </div>
            )}
          </div>
        </div>
        <div className="shrink-0 border-t border-line bg-canvas px-3 sm:px-6 lg:px-8 pt-3 pb-2">
          <ChatInput draft={draft} setDraft={setDraft} />
        </div>
      </div>
    </div>
  )
}
