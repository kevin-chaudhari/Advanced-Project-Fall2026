import { useState } from 'react'
import { Link } from 'react-router-dom'
import { MessagesSquare, ArrowRight, CheckCircle2, CircleDot, UserRound, ChevronDown } from 'lucide-react'
import { cx, Cited } from './ui'

/*
 * Agent council panel: the typed messages the six agents exchanged on a hard case
 * (harness.messages) and the council summary (harness.council). Read-only view of
 * what the backend produced; nothing here is computed beyond counting and labelling.
 */

const KIND = {
  QUESTION: { verb: 'asks', cls: 'border-primary-200 bg-primary-50 text-primary-700' },
  CHALLENGE: { verb: 'challenges', cls: 'border-warning-100 bg-warning-50 text-warning-700' },
  EVIDENCE_SHARE: { verb: 'shares evidence', cls: 'border-secondary-100 bg-secondary-50 text-secondary-700' },
  EVIDENCE_REQUEST: { verb: 'requests evidence', cls: 'border-secondary-100 bg-secondary-50 text-secondary-700' },
  CONCESSION: { verb: 'concedes', cls: 'border-success-100 bg-success-50 text-success-700' },
  POSITION_UPDATE: { verb: 'updates position', cls: 'border-success-100 bg-success-50 text-success-700' },
  HOLD: { verb: 'holds position', cls: 'border-slate-200 bg-slate-50 text-slate-700' },
  RISK_FLAG: { verb: 'flags risk', cls: 'border-danger-100 bg-danger-50 text-danger-700' },
  HUMAN_INPUT_REQUEST: { verb: 'needs a person', cls: 'border-warning-100 bg-warning-50 text-warning-700' },
  SYNTHESIS: { verb: 'sums up', cls: 'border-slate-300 bg-white text-ink' },
}
const SHOW = 8
const channel = (c) => String(c).replace(/_/g, ' ')

function Avatar({ agent }) {
  return (
    <span className="w-7 h-7 shrink-0 rounded-full flex items-center justify-center text-[13px]" aria-hidden
      style={agent ? { background: `${agent.color}1f`, boxShadow: `inset 0 0 0 1.5px ${agent.color}` } : undefined}>
      {agent?.emoji || '•'}
    </span>
  )
}

function Delta({ before, after }) {
  if (before == null || after == null) return null
  const d = after - before
  const tone = Math.abs(d) < 0.005 ? 'text-muted' : d > 0 ? 'text-success-700' : 'text-danger-700'
  return (
    <span className="inline-flex items-center gap-1 tabular-nums" title="Measured confidence before and after the council (same factor formula)">
      <span className="text-ink font-semibold">{before.toFixed(2)}</span>
      <ArrowRight size={12} className="text-muted" />
      <span className="text-ink font-semibold">{after.toFixed(2)}</span>
      <span className={cx('text-[11px]', tone)}>({d >= 0 ? '+' : ''}{d.toFixed(2)})</span>
    </span>
  )
}

export default function AgentCouncil({ harness, agents, onEvidence, uid }) {
  const [open, setOpen] = useState(true)
  const [all, setAll] = useState(false)
  const c = harness?.council
  const msgs = harness?.messages || []
  const byKey = Object.fromEntries((agents || []).map((a) => [a.key, a]))
  const name = (k) => (k === 'all' ? 'everyone' : k === 'harness' ? 'retrieval' : byKey[k]?.name || k)
  const bodyId = `${uid}-council`

  if (!c) return null
  if (!c.convened) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-dashed border-line bg-white px-3 py-2 text-[11.5px] text-muted">
        <MessagesSquare size={14} className="text-slate-400 shrink-0" aria-hidden />
        <span><b className="font-medium text-ink">Agent council not convened.</b>{' '}
          {c.reasons?.length ? c.reasons.join('; ') : 'Confidence, margin and first-pass agreement were already sufficient.'}
          {harness?.collaboration?.messages > 0 && <> The agents still worked it out together: {harness.collaboration.messages} messages over {harness.collaboration.rounds} round(s), joint finding {harness.collaboration.joint_label}{harness.collaboration.council_confidence != null ? ` (council confidence ${harness.collaboration.council_confidence.toFixed(2)})` : ''}.</>}</span>
        {harness?.trace_id && <Link to={`/traces/${harness.trace_id}`} className="ml-auto shrink-0 font-medium text-primary-700 underline underline-offset-2">Inspect trace</Link>}
      </div>
    )
  }

  const asks = msgs.filter((m) => ['QUESTION', 'CHALLENGE', 'EVIDENCE_REQUEST'].includes(m.kind))
  const settled = asks.filter((m) => m.resolved).length
  const list = all ? msgs : msgs.slice(0, SHOW)
  const moved = c.position_changes || []

  return (
    <section className="rounded-xl border border-primary-200 bg-white shadow-card" aria-labelledby={`${bodyId}-title`}>
      <header className="flex flex-wrap items-start gap-x-4 gap-y-2 px-3 sm:px-4 pt-3">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="w-7 h-7 shrink-0 rounded-full bg-primary-50 text-primary-700 flex items-center justify-center" aria-hidden><MessagesSquare size={14} /></span>
          <div className="min-w-0">
            <h3 id={`${bodyId}-title`} className="text-[13px] font-semibold text-ink leading-tight">Agent council</h3>
            <p className="text-[11px] text-muted leading-snug">
              {c.rounds} round(s) · {c.messages} messages · convened because {(c.reasons || []).join('; ')}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted">
          <span>Confidence <Delta before={c.confidence_before} after={c.confidence_after} /></span>
          <span><b className="text-ink tabular-nums">{settled}/{asks.length}</b> settled</span>
          <span><b className="text-ink tabular-nums">{moved.length}</b> position change(s)</span>
          {harness?.trace_id && <Link to={`/traces/${harness.trace_id}`} className="font-medium text-primary-700 underline underline-offset-2">Inspect trace</Link>}
        </div>
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls={bodyId}
          className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted hover:bg-slate-100 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
          aria-label={`${open ? 'Collapse' : 'Expand'} agent council`}>
          <ChevronDown size={14} className={cx('transition-transform', !open && '-rotate-90')} />
        </button>
      </header>

      <div id={bodyId} hidden={!open} className="px-3 sm:px-4 pb-3 pt-2 space-y-3">
        {(moved.length > 0 || c.human_inputs?.length > 0 || (c.verified_before && c.verified_after && c.verified_before !== c.verified_after)) && (
          <div className="flex flex-wrap gap-2 text-[11.5px]">
            {c.verified_before && c.verified_after && c.verified_before !== c.verified_after && (
              <span className="chip border-primary-200 bg-primary-50 text-primary-700">Verified: {c.verified_before} → {c.verified_after}</span>
            )}
            {moved.map((p) => (
              <span key={p.message} className="chip border-success-100 bg-success-50 text-success-700">{p.agent_name}: {p.from || 'none'} → {p.to}</span>
            ))}
            {c.human_inputs?.length > 0 && (
              <span className="chip border-warning-100 bg-warning-50 text-warning-700"><UserRound size={11} />Measure on site: {c.human_inputs.map(channel).join(', ')}</span>
            )}
          </div>
        )}

        <ol className="space-y-2" aria-label="Council messages">
          {list.map((m) => {
            const k = KIND[m.kind] || KIND.QUESTION
            const sender = byKey[m.sender]
            const to = (m.recipients || []).filter((r) => r !== 'all' || m.recipients.length === 1)
            return (
              <li key={m.message_id} className={cx('grid grid-cols-[28px_minmax(0,1fr)] gap-x-2.5', m.in_reply_to && 'sm:ml-6')}>
                <Avatar agent={sender} />
                <div className="min-w-0 rounded-lg border border-line bg-slate-50/50 px-2.5 py-1.5">
                  <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px]">
                    <span className="mono text-muted">{m.message_id}</span>
                    <span className="font-semibold text-ink text-[12px]">{name(m.sender)}</span>
                    <span className={cx('chip py-0 text-[10px]', k.cls)}>{k.verb}</span>
                    {to.length > 0 && <span className="text-muted truncate">→ {to.map(name).join(', ')}</span>}
                    {m.in_reply_to && <span className="text-muted">· re {m.in_reply_to}</span>}
                    <span className="ml-auto flex items-center gap-1 text-muted">
                      <span className="tabular-nums">R{m.round}</span>
                      {m.resolved === true && <CheckCircle2 size={12} className="text-success-600" aria-label="settled" />}
                      {m.resolved === false && <CircleDot size={12} className="text-warning-500" aria-label="still open" />}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[12px] leading-relaxed text-ink break-words"><Cited text={m.text} onEvidence={onEvidence} /></p>
                </div>
              </li>
            )
          })}
        </ol>
        {msgs.length > SHOW && (
          <button type="button" onClick={() => setAll((v) => !v)} aria-expanded={all}
            className="text-[11.5px] font-medium text-primary-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 rounded">
            {all ? 'Show fewer messages' : `Show all ${msgs.length} messages`}
          </button>
        )}
        <p className="text-[10.5px] text-muted leading-snug">
          Agents keep their own methods and talk only through these messages. Confidence is recomputed with the same factor
          formula, so it moves only when the discussion produced evidence; agreement alone never raises it.
        </p>
      </div>
    </section>
  )
}
