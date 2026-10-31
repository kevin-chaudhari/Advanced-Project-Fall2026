import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { cx } from '../ui'
import { StatusMark } from '../primitives'
import { AgentDetail, STAGE } from '../agents/AgentCard'
import { AGENT_STATUS } from '../../lib/diagnosis'

/** Individual agent contributions; the list stays one line per agent until opened. */
export default function AgentResponseAccordion({ agents, onEvidence }) {
  const [open, setOpen] = useState(null)
  if (!agents.length) return <p className="text-[13px] text-muted">The response did not include per-agent results.</p>
  return (
    <ul className="divide-y divide-line rounded-lg border border-line">
      {agents.map((a) => {
        const isOpen = open === a.key
        return (
          <li key={a.key}>
            <button type="button" onClick={() => setOpen(isOpen ? null : a.key)} aria-expanded={isOpen}
              className="grid w-full grid-cols-[14px_16px_minmax(0,170px)_minmax(0,1fr)_auto] items-center gap-2 px-3 py-2 text-left hover:bg-well/50 focus-ring rounded-lg max-sm:grid-cols-[14px_16px_minmax(0,1fr)_auto]">
              <ChevronRight size={13} className={cx('text-muted transition-transform', isOpen && 'rotate-90')} aria-hidden />
              <StatusMark status={a.status} />
              <span className="text-[13px] font-medium text-ink truncate">{a.name}</span>
              <span className="text-[12.5px] text-ink truncate first-letter:uppercase max-sm:hidden">{a.summary}</span>
              <span className="text-[12px] text-muted tabular-nums">{a.confidence != null ? `${Math.round(a.confidence * 100)}%` : ''}</span>
            </button>
            {isOpen && (
              <div className="px-4 pb-4 pt-1 sm:pl-[44px]">
                <p className="mb-2 text-[11.5px] text-muted">
                  {[STAGE[a.mode] && `Stage ${STAGE[a.mode].n}, ${STAGE[a.mode].text.toLowerCase()}`, AGENT_STATUS[a.status].label, a.passes > 1 && `${a.passes} passes`, a.persona, a.role].filter(Boolean).join(' · ')}
                </p>
                <p className="sm:hidden mb-2 text-[12.5px] text-ink first-letter:uppercase">{a.summary}</p>
                <AgentDetail agent={a} limit={8} onEvidence={onEvidence} />
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
