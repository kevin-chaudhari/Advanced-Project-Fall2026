import { Brain, ScanSearch, Zap, ShieldCheck, CircleHelp, Flag, Maximize2, Database } from 'lucide-react'
import { cx } from '../ui'
import { StatusMark } from '../primitives'
import { agentColor } from '../../lib/agentColors'
import { AGENT_STATUS } from '../../lib/diagnosis'

export const AGENT_ICON = {
  diagnostic_expert: Brain, pattern_agent: ScanSearch, aggressive_agent: Zap,
  verification: ShieldCheck, ambiguity: CircleHelp, human_review_coordinator: Flag,
}

/** One stage of the pipeline: numbered header, maximize control, internally scrolling body. */
export function StageColumn({ n, title, subtitle, accent, onMaximize, children, className, bodyClass }) {
  return (
    <section className={cx('card flex min-h-0 min-w-0 flex-col overflow-hidden', className)}
      style={accent ? { boxShadow: `inset 0 3px 0 ${accent}` } : undefined}>
      <header className="flex items-start gap-2 px-4 pt-3.5 pb-2.5 border-b border-line">
        <div className="min-w-0">
          <h2 className="text-[13.5px] font-semibold text-ink leading-tight">
            {n != null && <span className="tabular-nums">{n}. </span>}{title}
          </h2>
          {subtitle && <p className="mt-0.5 text-[12px] text-muted leading-snug">{subtitle}</p>}
        </div>
        {onMaximize && (
          <button type="button" onClick={onMaximize} title="Maximize" aria-label={`Maximize ${title}`}
            className="ml-auto -mr-1 shrink-0 rounded-md p-1.5 text-muted hover:bg-well hover:text-ink focus-ring">
            <Maximize2 size={14} />
          </button>
        )}
      </header>
      <div className={cx('flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 py-3', bodyClass)}>{children}</div>
    </section>
  )
}

/** Agent identity row: coloured icon tile, name, persona, live status. */
export function AgentHead({ agent, compact }) {
  const Icon = AGENT_ICON[agent.key] || Database
  const color = agentColor(agent.key)
  return (
    <div className="flex items-start gap-2.5">
      <span className={cx('shrink-0 grid place-items-center rounded-lg text-white', compact ? 'h-8 w-8' : 'h-9 w-9')} style={{ background: color }} aria-hidden>
        <Icon size={compact ? 16 : 18} strokeWidth={2} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-1.5">
          <h3 className="text-[13.5px] font-semibold leading-tight" style={{ color }}>{agent.name}</h3>
          <StatusMark status={agent.status} size={13} />
        </div>
        <p className="text-[11.5px] text-muted leading-snug truncate">
          {[agent.persona, agent.role].filter(Boolean).join(', ') || AGENT_STATUS[agent.status].label}
        </p>
      </div>
    </div>
  )
}

export function ConfBar({ value, color, label = 'Confidence' }) {
  if (value == null) return null
  const v = Math.max(0, Math.min(1, value))
  return (
    <div className="mt-2">
      <div className="flex items-baseline justify-between text-[12px]">
        <span className="font-medium text-ink">{label}: <span className="tabular-nums">{v.toFixed(2)}</span></span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-well overflow-hidden" aria-hidden>
        <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${v * 100}%`, background: color }} />
      </div>
    </div>
  )
}

export function SubHead({ children, tone }) {
  return <h4 className={cx('mt-3 mb-1 text-[12px] font-semibold', tone || 'text-ink')}>{children}</h4>
}

/** Arrow between stages on wide screens. */
export function FlowArrow() {
  return (
    <div className="hidden xl:flex items-center justify-center w-4 shrink-0" aria-hidden>
      <svg width="14" height="14" viewBox="0 0 14 14"><path d="M2 7h9M8 3.5 11.5 7 8 10.5" fill="none" stroke="#8A8170" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
    </div>
  )
}

/** Downward arrow between stacked stages (Agent dashboard workflow column). */
export function FlowArrowDown() {
  return (
    <div className="flex justify-center py-1.5" aria-hidden>
      <svg width="14" height="16" viewBox="0 0 14 16"><path d="M7 2v10M3.5 8.5 7 12l3.5-3.5" fill="none" stroke="#8A8170" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
    </div>
  )
}
