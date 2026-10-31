import { useId } from 'react'
import { ChevronDown } from 'lucide-react'
import { cx, Cited, IdChip } from '../ui'
import { StatusMark } from '../primitives'
import { AGENT_STATUS } from '../../lib/diagnosis'

export const STAGE = {
  parallel: { n: 1, text: 'Independent analysis' },
  review: { n: 2, text: 'Verification' },
  calibration: { n: 3, text: 'Uncertainty check' },
  synthesis: { n: 4, text: 'Final decision' },
}

function Statements({ title, items, tone, limit = 3, onEvidence }) {
  if (!items?.length) return null
  return (
    <div>
      <div className={cx('text-[11.5px] font-medium', tone)}>{title}</div>
      <ul className="mt-0.5 space-y-1 text-[12px] leading-snug text-ink">
        {items.slice(0, limit).map((it, i) => <li key={i} className="pl-2.5 border-l border-line"><Cited text={it.statement} onEvidence={onEvidence} /></li>)}
        {items.length > limit && <li className="pl-2.5 text-muted">+{items.length - limit} more</li>}
      </ul>
    </div>
  )
}

/** Detail block reused by the dashboard card (expanded) and the chat accordion. */
export function AgentDetail({ agent, limit = 3, onEvidence }) {
  return (
    <div className="space-y-2.5">
      {agent.narrative && <p className="text-[12.5px] leading-relaxed text-ink"><Cited text={agent.narrative} onEvidence={onEvidence} /></p>}
      <Statements title="Supporting" items={agent.supporting} tone="text-success-700" limit={limit} onEvidence={onEvidence} />
      <Statements title="Contradicting" items={agent.contradicting} tone="text-danger-700" limit={limit} onEvidence={onEvidence} />
      <Statements title="Missing information" items={agent.missing} tone="text-warning-700" limit={limit} onEvidence={onEvidence} />
      {agent.evidenceIds.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-[11.5px] text-muted mr-1">Evidence cited</span>
          {agent.evidenceIds.map((id) => <IdChip key={id} id={id} onClick={onEvidence} />)}
        </div>
      )}
      {agent.recommendation && <p className="text-[12px] text-muted"><span className="text-ink font-medium">Suggests:</span> {agent.recommendation}</p>}
    </div>
  )
}

/** Compact agent card for the dashboard: name, real status and one-line contribution; expandable. */
export default function AgentCard({ agent, expanded, onToggle }) {
  const id = useId()
  const st = AGENT_STATUS[agent.status]
  const stage = STAGE[agent.mode]
  return (
    <article className={cx('rounded-lg border bg-surface transition-colors', expanded ? 'border-primary-300' : 'border-line hover:border-slate-300')}>
      <button type="button" onClick={onToggle} aria-expanded={expanded} aria-controls={id}
        className="w-full text-left px-3.5 py-3 focus-ring rounded-lg">
        <div className="flex items-center gap-2">
          <StatusMark status={agent.status} />
          <h3 className="text-[13px] font-semibold text-ink truncate">{agent.name}</h3>
          <ChevronDown size={14} className={cx('ml-auto shrink-0 text-muted transition-transform', expanded && 'rotate-180')} aria-hidden />
        </div>
        <p className="mt-1 text-[12.5px] leading-snug text-ink line-clamp-1 first-letter:uppercase" title={agent.summary || undefined}>
          {agent.summary || <span className="text-muted">No finding reported</span>}
        </p>
        <div className="mt-1.5 flex items-center gap-2 text-[11.5px] text-muted">
          {stage && <span title={stage.text} className="shrink-0 whitespace-nowrap">Stage {stage.n}</span>}
          <span className="truncate">{st.label}{agent.passes > 1 ? `, ${agent.passes} passes` : ''}</span>
          {agent.confidence != null && <span className="ml-auto shrink-0 tabular-nums">{Math.round(agent.confidence * 100)}%</span>}
        </div>
      </button>
      {expanded && (
        <div id={id} className="border-t border-line px-3.5 py-3">
          {(agent.persona || agent.role) && <p className="mb-2 text-[11.5px] text-muted">{[agent.persona, agent.role].filter(Boolean).join(', ')}</p>}
          <AgentDetail agent={agent} limit={2} />
        </div>
      )}
    </article>
  )
}
