import { useEffect, useRef, useState } from 'react'
import { ArrowRight } from 'lucide-react'
import { cx } from '../ui'
import FullscreenPanel from '../FullscreenPanel'
import { agentColor, AGENT_SHORT, HARNESS_COLOR } from '../../lib/agentColors'

const STAGE_LABEL = {
  query_prep: 'Query prepared', initial_rag: 'Evidence retrieved', numerical_analysis: 'Hypotheses scored', phase1: 'Initial analyses',
  verification: 'Cross-check', evidence_check: 'Evidence check', targeted_rag: 'Targeted retrieval', targeted_rerun: 'Agent re-run',
  ambiguity: 'Uncertainty', council: 'Agent council', final_coordinator: 'Synthesis', claim_validation: 'Claim validation', review_gate: 'Review gate',
}
const stageLabel = (s) => STAGE_LABEL[s] || String(s).replaceAll('_', ' ')
const STATUS_TONE = { ok: 'text-success-700', loop: 'text-warning-700', warning: 'text-warning-700', error: 'text-danger-700' }

/** Consecutive events of the same stage become one labelled group on the track. */
function groups(events) {
  const out = []
  events.forEach((e, i) => {
    const last = out[out.length - 1]
    if (last && last.stage === e.stage) last.end = i
    else out.push({ stage: e.stage, start: i, end: i })
  })
  return out
}

function StepTable({ events }) {
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-[12.5px]">
        <thead className="text-left text-muted border-b border-line">
          <tr><th className="px-4 py-2 font-medium">#</th><th className="px-2 py-2 font-medium">Stage</th><th className="px-2 py-2 font-medium">Agent</th><th className="px-2 py-2 font-medium">Action</th><th className="px-2 py-2 font-medium">Status</th><th className="px-2 py-2 font-medium text-right">ms</th><th className="px-4 py-2 font-medium">Outcome</th></tr>
        </thead>
        <tbody className="divide-y divide-line">
          {events.map((e) => (
            <tr key={e.step} className="align-top">
              <td className="px-4 py-2 tabular-nums text-muted">{e.step}</td>
              <td className="px-2 py-2 whitespace-nowrap">{stageLabel(e.stage)}</td>
              <td className="px-2 py-2 whitespace-nowrap">{e.agent ? <span className="inline-flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{ background: agentColor(e.agent) }} />{AGENT_SHORT[e.agent] || e.agent}</span> : <span className="text-muted">harness</span>}</td>
              <td className="px-2 py-2 font-mono text-[11.5px]">{e.action}</td>
              <td className={cx('px-2 py-2 font-medium', STATUS_TONE[e.status])}>{e.status}</td>
              <td className="px-2 py-2 tabular-nums text-right text-muted">{e.duration_ms != null ? e.duration_ms.toFixed(1) : '—'}</td>
              <td className="px-4 py-2 text-ink">{e.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Order in which the agents and harness stages actually ran, from the response timeline. */
export default function InteractionTimeline({ result, runId }) {
  const events = result?.harness?.timeline || []
  const [sel, setSel] = useState(null)
  const [max, setMax] = useState(false)
  const track = useRef(null)
  const [tw, setTw] = useState(800)
  useEffect(() => { setSel(null) }, [runId])
  useEffect(() => {
    if (!track.current) return
    const ro = new ResizeObserver(([e]) => setTw(e.contentRect.width))
    ro.observe(track.current)
    return () => ro.disconnect()
  }, [])
  if (!events.length) return null
  const n = events.length
  const x = (i) => (n === 1 ? 50 : 1.5 + (i / (n - 1)) * 97)
  // place stage labels on two rows (above / below the line); a label that would overlap is dropped
  // (every step still has its own tooltip and appears in View details)
  const placed = []
  const lastEnd = [-Infinity, -Infinity]
  groups(events).forEach((g) => {
    const mid = (x(g.start) + x(g.end)) / 2
    const w = (stageLabel(g.stage).length * 6.2 + 10) / Math.max(tw, 1) * 100
    const left = Math.min(Math.max(mid - w / 2, 0), 100 - w)
    const row = left >= lastEnd[0] ? 0 : left >= lastEnd[1] ? 1 : -1
    if (row < 0) return
    lastEnd[row] = left + w
    placed.push({ ...g, left, row })
  })
  const agentsSeen = [...new Set(events.map((e) => e.agent).filter(Boolean))]
  const cur = sel != null ? events[sel] : null
  const latency = result.harness?.latency_ms

  return (
    <section aria-labelledby="tl-title" className="card shrink-0 px-4 sm:px-5 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <h2 id="tl-title" className="text-[13.5px] font-semibold text-ink">Agent interaction timeline</h2>
        <span className="text-[12px] text-muted">{n} steps in execution order{latency != null ? `, ${Math.round(latency)} ms total` : ''}</span>
        <button type="button" onClick={() => setMax(true)} className="ml-auto inline-flex items-center gap-1 text-[12.5px] font-medium text-primary-700 hover:text-ink rounded focus-ring">
          View details <ArrowRight size={13} aria-hidden />
        </button>
      </div>
      <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px]" aria-label="Legend">
        {agentsSeen.map((k) => <li key={k} className="flex items-center gap-1.5 text-ink"><span className="w-2 h-2 rounded-full" style={{ background: agentColor(k) }} />{AGENT_SHORT[k] || k}</li>)}
        <li className="flex items-center gap-1.5 text-muted"><span className="w-2 h-2 rounded-full" style={{ background: HARNESS_COLOR }} />Harness step</li>
      </ul>
      <div className="mt-1">
        <div className="min-w-0">
          <div ref={track} className="relative h-[58px]">
            {/* stage labels alternate above/below the line so neighbours don't collide */}
            {placed.map((g) => (
              <span key={g.start} className={cx('absolute whitespace-nowrap text-[11px] leading-none text-muted', g.row ? 'top-[44px]' : 'top-0')}
                style={{ left: `${g.left}%` }}>{stageLabel(g.stage)}</span>
            ))}
            <div className="absolute left-0 right-0 top-[30px] h-px bg-slate-300" aria-hidden />
            {events.map((e, i) => (
              <button key={e.step} type="button" onClick={() => setSel(sel === i ? null : i)} aria-pressed={sel === i}
                title={`#${e.step} ${stageLabel(e.stage)}${e.agent ? ` · ${AGENT_SHORT[e.agent] || e.agent}` : ''} · ${e.status}\n${e.reason || ''}`}
                aria-label={`Step ${e.step}: ${stageLabel(e.stage)}${e.agent ? `, ${AGENT_SHORT[e.agent] || e.agent}` : ''}, ${e.status}`}
                className={cx('absolute top-[24px] -translate-x-1/2 h-3 w-3 rounded-full border-2 border-surface focus-ring transition-transform hover:scale-125', sel === i && 'scale-150 ring-2 ring-ink')}
                style={{ left: `${x(i)}%`, background: e.agent ? agentColor(e.agent) : HARNESS_COLOR, opacity: e.status === 'loop' ? 0.75 : 1 }} />
            ))}
          </div>
          <p className="min-h-[18px] text-[12px] text-ink truncate">
            {cur ? <><b className="font-semibold">Step {cur.step}</b> · {stageLabel(cur.stage)}{cur.agent && ` · ${AGENT_SHORT[cur.agent] || cur.agent}`} · <span className={STATUS_TONE[cur.status]}>{cur.status}</span> — {cur.reason}</>
              : <span className="text-muted">Select a point to see what happened at that step.</span>}
          </p>
        </div>
      </div>
      {max && (
        <FullscreenPanel title="Agent interaction timeline" subtitle={`${n} steps, in the order the harness recorded them`} onClose={() => setMax(false)}>
          <StepTable events={events} />
        </FullscreenPanel>
      )}
    </section>
  )
}
