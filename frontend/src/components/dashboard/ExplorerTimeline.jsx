import { useId, useMemo, useState } from 'react'
import { buildModel, Timeline, SelectedStep, TimelinePanel } from '../DecisionExplorer'
import OrchestrationFlow from '../OrchestrationFlow'
import { AuditPanel } from '../ReportPanels'
import FullscreenPanel from '../FullscreenPanel'

/**
 * The Decision Explorer's agent interaction timeline (one lane per agent, measured
 * durations, latest events), reused unchanged on the Agent dashboard.
 */
export default function ExplorerTimeline({ result, question }) {
  const model = useMemo(() => buildModel(result), [result])
  const uid = useId().replace(/:/g, '')
  const [collapsed, setCollapsed] = useState(false)
  const [selected, setSelected] = useState(null)
  const [showAll, setShowAll] = useState(false)
  const [max, setMax] = useState(false)
  const h = result?.harness || {}
  return (
    <>
      <TimelinePanel model={model} latency={h.latency_ms ?? model.totalMs} uid={uid}
        collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} onMaximize={() => setMax(true)}
        selected={selected} onSelect={setSelected} showAll={showAll} setShowAll={setShowAll} />
      {max && (
        <FullscreenPanel title="Agent execution & interaction timeline" subtitle={question} onClose={() => setMax(false)}>
          <div className="space-y-6">
            <div className="card p-5">
              <Timeline model={model} selected={selected} onSelect={setSelected} />
              {selected != null && <div className="mt-3"><SelectedStep model={model} step={selected} /></div>}
            </div>
            <div className="card p-5"><OrchestrationFlow harness={h} /></div>
            <div className="card p-5"><AuditPanel harness={h} /></div>
          </div>
        </FullscreenPanel>
      )}
    </>
  )
}
