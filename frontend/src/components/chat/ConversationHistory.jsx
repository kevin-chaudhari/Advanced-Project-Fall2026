import { Loader2, AlertTriangle } from 'lucide-react'
import { cx } from '../ui'
import { ReviewDecision } from '../primitives'
import { fmtTime } from '../../lib/diagnosis'

/** Index of earlier questions in this workspace, newest first. Selecting one scrolls to it. */
export default function ConversationHistory({ runs, activeId, onSelect, onClear }) {
  const list = [...runs].reverse()
  return (
    <nav aria-label="Conversation history" className="flex h-full flex-col">
      <div className="flex items-center justify-between px-4 pt-4 pb-2">
        <h2 className="section-title">History</h2>
        {runs.some((r) => r.result || r.error) && (
          <button type="button" onClick={onClear} className="text-[12px] text-muted hover:text-ink rounded px-1.5 py-0.5 focus-ring">Clear</button>
        )}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-2 pb-4">
        {list.length === 0 ? (
          <p className="px-2 text-[12.5px] leading-relaxed text-muted">Your questions and their diagnoses will be listed here.</p>
        ) : (
          <ul className="space-y-0.5">
            {list.map((r) => {
              const label = r.result?.harness?.predicted_label || r.result?.direct_answer
              return (
                <li key={r.id}>
                  <button type="button" onClick={() => onSelect(r.id)} aria-current={activeId === r.id ? 'true' : undefined}
                    className={cx('w-full rounded-lg px-2.5 py-2 text-left focus-ring transition-colors',
                      activeId === r.id ? 'bg-surface border border-line' : 'border border-transparent hover:bg-surface/70')}>
                    <div className="text-[12.5px] leading-snug text-ink line-clamp-2">{r.question}</div>
                    <div className="mt-1 flex items-center gap-2 text-[11.5px] text-muted">
                      {!r.result && !r.error && <><Loader2 size={11} className="animate-spin" aria-hidden /> Analysing</>}
                      {r.error && <span className="inline-flex items-center gap-1 text-danger-700"><AlertTriangle size={11} aria-hidden /> Failed</span>}
                      {label && <span className="truncate font-medium text-ink first-letter:uppercase">{label}</span>}
                      <span className="ml-auto shrink-0">{fmtTime(r.finishedAt || r.startedAt)}</span>
                    </div>
                    {r.result && <div className="mt-1"><ReviewDecision decision={r.result.review_decision} variant="inline" /></div>}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </nav>
  )
}
