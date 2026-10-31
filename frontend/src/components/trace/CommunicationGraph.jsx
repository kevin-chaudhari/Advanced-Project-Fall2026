import { useMemo, useState } from 'react'
import { agentColor, AGENT_SHORT } from '../../lib/agentColors'
import { FAMILY, edgeFamily, typeLabel } from '../../lib/traceVocab'
import { cx } from '../ui'

/*
 * Agent communication graph. Nodes sit in pipeline order (first pass on top, review in the
 * middle, the coordinator at the bottom) so the picture reads like the architecture.
 * Edge weight = messages sent along it; colour = dominant message family; a dashed edge
 * means some addressed messages were never observably read by the receiver.
 * Everything comes from GET /traces/{id} → graph (computed from persisted messages).
 */

const W = 640, H = 450, R = 30
// first pass on a shallow arc (so Diagnostic Expert ↔ Rapid Triage edges pass under Pattern Recognition),
// review in the middle, the coordinator at the bottom — the architecture read top to bottom
const POS = {
  diagnostic_expert: [95, 120], pattern_agent: [320, 48], aggressive_agent: [545, 120],
  verification: [200, 268], ambiguity: [440, 268], human_review_coordinator: [320, 388], harness: [575, 395],
}
const SHORT = { ...AGENT_SHORT, harness: 'Retrieval' }

function curve(a, b) {
  const [x1, y1] = POS[a], [x2, y2] = POS[b]
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1
  const nx = -dy / len, ny = dx / len                       // left-hand normal: A→B and B→A bow apart
  const bend = 26
  const cx_ = (x1 + x2) / 2 + nx * bend, cy_ = (y1 + y2) / 2 + ny * bend
  const trim = (px, py, qx, qy, d) => { const l = Math.hypot(qx - px, qy - py) || 1; return [px + ((qx - px) / l) * d, py + ((qy - py) / l) * d] }
  const [sx, sy] = trim(x1, y1, cx_, cy_, R + 3)
  const [ex, ey] = trim(x2, y2, cx_, cy_, R + 9)
  return { d: `M${sx},${sy} Q${cx_},${cy_} ${ex},${ey}`, mid: [(sx + 2 * cx_ + ex) / 4, (sy + 2 * cy_ + ey) / 4] }
}

export default function CommunicationGraph({ graph, selectedAgent, onSelectAgent, selectedEdge, onSelectEdge }) {
  const [hover, setHover] = useState(null)
  const nodes = (graph?.nodes || []).filter((n) => POS[n.id])
  const edges = useMemo(() => (graph?.edges || []).filter((e) => POS[e.source] && POS[e.target]), [graph])
  const maxN = Math.max(1, ...edges.map((e) => e.count))
  const width = (n) => 1.2 + 4.8 * Math.sqrt(n / maxN)
  const active = (e) => (!selectedAgent || e.source === selectedAgent || e.target === selectedAgent)
  const edgeKey = (e) => `${e.source}>${e.target}`
  const info = hover || (selectedEdge && edges.find((e) => edgeKey(e) === selectedEdge))

  if (!nodes.length) return <p className="text-[13px] text-muted">No agents were recorded for this trace.</p>

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto select-none" role="img"
        aria-label={`Communication graph: ${edges.length} directed connections between ${nodes.length} agents`}>
        <defs>
          {Object.entries(FAMILY).map(([k, f]) => (
            <marker key={k} id={`arrow-${k}`} viewBox="0 0 10 10" refX="7" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill={f.stroke} />
            </marker>
          ))}
        </defs>

        {edges.map((e) => {
          const fam = edgeFamily(e.types)
          const { d } = curve(e.source, e.target)
          const on = active(e)
          const sel = selectedEdge === edgeKey(e)
          const undelivered = e.addressed > e.delivered
          return (
            <g key={edgeKey(e)} className="cursor-pointer" onMouseEnter={() => setHover(e)} onMouseLeave={() => setHover(null)}
              onClick={() => onSelectEdge?.(sel ? null : edgeKey(e))}>
              <path d={d} fill="none" stroke="transparent" strokeWidth={14} />
              <path d={d} fill="none" stroke={FAMILY[fam].stroke} strokeWidth={width(e.count) + (sel ? 1.5 : 0)}
                strokeOpacity={on ? (sel ? 1 : 0.72) : 0.12} strokeDasharray={undelivered ? '5 4' : undefined}
                markerEnd={`url(#arrow-${fam})`} style={{ transition: 'stroke-opacity .15s' }} />
            </g>
          )
        })}

        {nodes.map((n) => {
          const [x, y] = POS[n.id]
          const sel = selectedAgent === n.id
          const dim = selectedAgent && !sel && !edges.some((e) => (e.source === selectedAgent && e.target === n.id) || (e.target === selectedAgent && e.source === n.id))
          const c = n.id === 'harness' ? '#6B6457' : agentColor(n.id)
          return (
            <g key={n.id} transform={`translate(${x},${y})`} className="cursor-pointer" opacity={dim ? 0.35 : 1}
              onClick={() => onSelectAgent?.(sel ? null : n.id)} role="button" tabIndex={0}
              aria-label={`${n.name}: sent ${n.sent}, read ${n.received}`} aria-pressed={sel}
              onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onSelectAgent?.(sel ? null : n.id) } }}>
              <circle r={R} fill="#FFFCF5" stroke={c} strokeWidth={sel ? 4 : 2} />
              <circle r={R - 7} fill={c} fillOpacity={0.12} />
              <text textAnchor="middle" dy="-2" fontSize="15" fontWeight="600" fill="#17140F" className="tabular-nums">{n.sent}</text>
              <text textAnchor="middle" dy="12" fontSize="8.5" fill="#4A453D">sent</text>
              <text textAnchor="middle" y={R + 15} fontSize="12" fontWeight="600" fill="#17140F" stroke="#F7F4EC" strokeWidth="4" paintOrder="stroke" strokeLinejoin="round">{SHORT[n.id] || n.name}</text>
              <text textAnchor="middle" y={R + 28} fontSize="10" fill="#4A453D" stroke="#F7F4EC" strokeWidth="4" paintOrder="stroke" strokeLinejoin="round">read {n.received}</text>
            </g>
          )
        })}
      </svg>

      <div className="mt-1 min-h-[38px] rounded-md bg-well px-3 py-2 text-[12px] text-muted" aria-live="polite">
        {info ? (
          <span>
            <b className="text-ink">{SHORT[info.source]} → {SHORT[info.target]}</b>: {info.count} message(s)
            {' '}({Object.entries(info.types).map(([t, n]) => `${n} ${typeLabel(t).toLowerCase()}`).join(', ')}),
            {' '}read {info.delivered} of {info.addressed} addressed; first at #{info.first_seq}
            {info.rounds?.length ? `, rounds ${info.rounds.join(', ')}` : ''}.
          </span>
        ) : (
          <span>Select an agent to isolate its conversations, or an arrow to filter the timeline. Dashed: some addressed messages were never read.</span>
        )}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-muted" aria-label="Legend">
        {Object.entries(FAMILY).map(([k, f]) => (
          <li key={k} className="flex items-center gap-1.5">
            <span className="h-[3px] w-5 rounded-full" style={{ background: f.stroke }} aria-hidden />{f.label}
          </li>
        ))}
        <li className={cx('flex items-center gap-1.5')}><span className="w-5 border-t-2 border-dashed border-slate-500" aria-hidden />Not read by receiver</li>
      </ul>
    </div>
  )
}
