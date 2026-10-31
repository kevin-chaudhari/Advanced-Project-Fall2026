import { useEffect, useState } from 'react'
import AgentCard from '../agents/AgentCard'

/** The six cooperating agents of the latest run, with their recorded execution status. */
export default function AgentOverview({ agents, runId }) {
  const [open, setOpen] = useState(() => new Set())
  useEffect(() => { setOpen(new Set()) }, [runId])
  const all = agents.length > 0 && open.size === agents.length
  const toggle = (k) => setOpen((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })
  const done = agents.filter((a) => a.status !== 'idle' && a.status !== 'failed').length

  return (
    <section aria-labelledby="agents-title" className="card flex flex-col min-h-0">
      <header className="flex items-center justify-between gap-3 px-5 pt-4 pb-3">
        <div className="flex items-baseline gap-2">
          <h2 id="agents-title" className="section-title">Agent activity</h2>
          <span className="text-[12px] text-muted tabular-nums">{done} of {agents.length} completed</span>
        </div>
        {agents.length > 0 && (
          <button type="button" onClick={() => setOpen(all ? new Set() : new Set(agents.map((a) => a.key)))}
            className="text-[12px] text-muted hover:text-ink rounded px-1.5 py-0.5 focus-ring">
            {all ? 'Collapse all' : 'Expand all'}
          </button>
        )}
      </header>
      <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-5 pb-5">
        {agents.length ? (
          <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3 items-start">
            {agents.map((a) => <AgentCard key={a.key} agent={a} expanded={open.has(a.key)} onToggle={() => toggle(a.key)} />)}
          </div>
        ) : <p className="text-[13px] text-muted">The response did not include per-agent results.</p>}
      </div>
    </section>
  )
}
