import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Loader2, RefreshCw, AlertTriangle } from 'lucide-react'
import { cx } from '../components/ui'
import { ConfidenceIndicator, ReviewDecision } from '../components/primitives'
import CommunicationGraph from '../components/trace/CommunicationGraph'
import { AgentDetails, CollaborationPanel, Disagreements, EvidenceFlow, MessageInspector, RawEvents, ScoreChanges, TraceSummary, TraceTimeline } from '../components/trace/TracePanels'
import { useDiagnostics, DATASETS } from '../state/DiagnosticsContext'
import { getTrace, getTraceAgents, getTraceEvidence, getTraceHypotheses, getTraceMessages, getTraceTimeline, getTraceInsights, listTraces, sendQuery, traceReportUrl, traceArchiveUrl, traceExportUrl } from '../services/api'
import { fmtMs } from '../lib/traceVocab'
import RobustnessCheck from '../components/lab/RobustnessCheck'
import { MultiCompare, SignalsPanel, StepBreakdown, TracePicker } from '../components/trace/InsightPanels'
import ReviewPanel from '../components/lab/ReviewPanel'

/*
 * Trace Explorer: how the six agents talked during one diagnosis.
 * Every number and message on this page is read from the persisted AgentTrace via /traces/*;
 * nothing is computed from the chat state or invented for display.
 */

const STATUS_TONE = { COMPLETED: 'text-success-700', COMPLETED_WITH_ERRORS: 'text-warning-700', FAILED: 'text-danger-700', RUNNING: 'text-muted' }
const STATUS_TEXT = { COMPLETED: 'Completed', COMPLETED_WITH_ERRORS: 'Completed, an agent failed', FAILED: 'Failed', RUNNING: 'Incomplete' }
const TABS = [['steps', 'Step breakdown'], ['signals', 'Signals'], ['compare', 'Compare traces'], ['collaboration', 'How they agreed'], ['timeline', 'Timeline'], ['agents', 'Agents'], ['evidence', 'Evidence flow'], ['scores', 'Score changes'], ['disagreements', 'Disagreements'], ['events', 'Raw events']]

function TraceList({ traces, total, selected, onSelect, loading, onRefresh, error, origin, setOrigin }) {
  const ds = (id) => DATASETS.find((d) => d.id === id)?.label || id
  return (
    <aside className="flex min-h-0 flex-col border-b md:border-b-0 md:border-r border-line bg-canvas" aria-label="Diagnostic traces">
      <div className="flex items-center gap-2 px-4 py-3">
        <h2 className="text-[13px] font-semibold text-ink">Traces</h2>
        <span className="text-[12px] text-muted tabular-nums">{total}</span>
        <a href={traceArchiveUrl(20)} download className="ml-auto text-[11.5px] font-medium text-primary-700 underline underline-offset-2 focus-ring rounded" title="The 20 newest traces as a .zip (JSON, conversation, messages CSV)">Download recent</a>
        <button type="button" onClick={onRefresh} className="btn-ghost p-1 rounded-md" aria-label="Refresh traces" title="Refresh">
          {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
        </button>
      </div>
      <label className="flex items-center gap-1.5 px-4 pb-2 text-[11.5px] text-muted cursor-pointer">
        <input type="checkbox" className="accent-primary-700" checked={origin === 'all'} onChange={(e) => setOrigin(e.target.checked ? 'all' : 'live')} />
        Include experiment runs (hypothetical inputs)
      </label>
      {error && <p className="px-4 pb-3 text-[12px] text-danger-700">{error}</p>}
      <ol className="min-h-0 flex-1 overflow-y-auto max-h-[220px] md:max-h-none">
        {traces.map((t) => (
          <li key={t.trace_id}>
            <button type="button" onClick={() => onSelect(t.trace_id)} aria-current={t.trace_id === selected ? 'true' : undefined}
              className={cx('w-full border-l-2 px-4 py-2.5 text-left focus-ring', t.trace_id === selected ? 'border-ink bg-surface' : 'border-transparent hover:bg-well')}>
              <p className="text-[12.5px] leading-snug text-ink line-clamp-2">{t.query}</p>
              <p className="mt-1 flex flex-wrap gap-x-2 text-[11.5px] text-muted">
                <span className="font-medium text-ink">{t.final_label || '—'}</span>
                <span>{ds(t.dataset_type)}, {t.data_mode}</span>
                <span className="tabular-nums">{t.total_messages ?? 0} msgs</span>
                {t.is_experiment && <span className="text-warning-700">experiment run</span>}
                {t.status !== 'COMPLETED' && <span className={STATUS_TONE[t.status]}>{STATUS_TEXT[t.status]}</span>}
              </p>
            </button>
          </li>
        ))}
      </ol>
    </aside>
  )
}

export default function TraceExplorerPage() {
  const { traceId } = useParams()
  const nav = useNavigate()
  const { latest } = useDiagnostics()
  const [list, setList] = useState({ traces: [], total: 0, loading: true })
  const [origin, setOrigin] = useState('live')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('steps')
  const [insights, setInsights] = useState(undefined)   // undefined = loading, null = no snapshot
  const [focusStep, setFocusStep] = useState(null)
  const [compareIds, setCompareIds] = useState(null)
  const [rerunning, setRerunning] = useState(false)
  const [selectedMsg, setSelectedMsg] = useState(null)
  const [selectedAgent, setSelectedAgent] = useState(null)
  const [selectedEdge, setSelectedEdge] = useState(null)

  const refreshList = useCallback(() => {
    setList((l) => ({ ...l, loading: true }))
    listTraces({ limit: 100, origin }).then((r) => setList({ traces: r.traces, total: r.total, loading: false }))
      .catch((e) => setList({ traces: [], total: 0, loading: false, error: e.code === 'ERR_NETWORK' ? 'Cannot reach the backend.' : e.message }))
  }, [origin])
  useEffect(() => { refreshList() }, [refreshList])

  // default: the trace of the latest diagnosis in this session, else the newest stored trace
  const fallback = latest?.result?.harness?.trace_id || list.traces[0]?.trace_id
  const active = traceId || fallback
  useEffect(() => { if (!traceId && fallback) nav(`/traces/${fallback}`, { replace: true }) }, [traceId, fallback, nav])

  useEffect(() => {
    if (!active) return
    let live = true
    setInsights(undefined); setCompareIds(null); setFocusStep(null)
    getTraceInsights(active).then((d) => live && setInsights(d)).catch(() => live && setInsights(null))
    setLoading(true); setError(null); setSelectedMsg(null); setSelectedEdge(null); setSelectedAgent(null)
    Promise.all([getTrace(active), getTraceMessages(active), getTraceTimeline(active), getTraceEvidence(active), getTraceHypotheses(active), getTraceAgents(active)])
      .then(([trace, msgs, timeline, evidence, hyps, agents]) => {
        if (!live) return
        setData({ ...trace, messages: msgs.messages, timeline, evidence: evidence.evidence, hypotheses: hyps.states, agentDetails: agents })
        const firstDispute = trace.disagreements?.[0]?.message_id
        setSelectedMsg(firstDispute || msgs.messages[0]?.message_id || null)
      })
      .catch((e) => live && setError(e.response?.status === 404 ? `Trace ${active} was not found.` : e.code === 'ERR_NETWORK' ? 'Cannot reach the backend.' : e.message))
      .finally(() => live && setLoading(false))
    return () => { live = false }
  }, [active])

  const message = useMemo(() => data?.messages.find((m) => m.message_id === selectedMsg), [data, selectedMsg])
  const selectMessage = (id) => { setSelectedMsg(id); setTab('timeline') }

  if (!list.loading && !list.traces.length && !traceId) {
    return (
      <div className="h-full grid place-items-center p-6">
        <div className="max-w-md text-center">
          <h1 className="text-[20px] font-semibold text-ink">No traces yet</h1>
          <p className="mt-2 text-[13.5px] text-muted">{list.error || 'Every diagnosis is recorded as a trace. Ask a question in the diagnostic chat and its agent conversation will appear here.'}</p>
          <button type="button" onClick={() => nav('/chat')} className="btn-primary mt-5">Open diagnostic chat</button>
        </div>
      </div>
    )
  }

  const t = data?.trace
  const s = data?.summary
  return (
    <div className="h-full grid md:grid-cols-[280px_minmax(0,1fr)] min-h-0">
      <TraceList traces={list.traces} total={list.total} selected={active} onSelect={(id) => nav(`/traces/${id}`)}
        loading={list.loading} onRefresh={refreshList} error={list.error} origin={origin} setOrigin={setOrigin} />

      <div className="min-h-0 overflow-y-auto">
        {error && (
          <div role="alert" className="m-6 flex items-center gap-2 rounded-lg border border-danger-100 bg-danger-50 px-4 py-2.5 text-[13px] text-danger-700">
            <AlertTriangle size={15} aria-hidden />{error}
          </div>
        )}
        {loading && !data && <p className="p-6 text-[13px] text-muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" />Loading trace…</p>}
        {data && t && (
          <div className={cx('mx-auto max-w-[1280px] px-4 sm:px-6 py-5 space-y-6', loading && 'opacity-60')}>
            {t.config?.experiment && (
              <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warning-100 bg-warning-50 px-3 py-2 text-[12.5px]">
                <button type="button" onClick={() => (window.history.state?.idx > 0 ? nav(-1) : nav(`/lab/${t.config.experiment.experiment_id}`))}
                  className="btn-primary py-1 text-[12.5px]">← Back to experiment</button>
                <span className="text-ink">This trace is run “{t.config.experiment.label}” of experiment <span className="mono">{t.config.experiment.experiment_id}</span> — a hypothetical input, not a real diagnosis.</span>
              </div>
            )}
            <header className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px] items-start">
              <div className="min-w-0">
                <p className="mono text-[11.5px] text-muted">{t.trace_id}{t.analysis_id ? `, analysis ${t.analysis_id}` : ''}</p>
                <h1 className="mt-1 text-[17px] font-semibold leading-snug text-ink">{t.query}</h1>
                <p className="mt-1.5 text-[12.5px] text-muted">
                  {DATASETS.find((d) => d.id === t.dataset_type)?.long || t.dataset_type}, {t.data_mode.toUpperCase()} data,{' '}
                  {t.llm_mode === 'deterministic' ? 'deterministic agents' : `${t.llm_provider || 'LLM'} ${t.llm_model || ''} with deterministic checks`},{' '}
                  {fmtMs(t.duration_ms)}. <span className={STATUS_TONE[t.status]}>{STATUS_TEXT[t.status]}</span>
                  {t.error && <span className="text-danger-700">: {t.error}</span>}
                </p>
                <p className="mt-1 text-[11.5px] text-muted">
                  Code version:{' '}
                  {t.code_version
                    ? <span className="mono text-ink" title={JSON.stringify(t.code_version, null, 1)}>{t.code_version.id}</span>
                    : <span>not recorded (trace made before schema 1.1)</span>}
                  {t.code_version?.git?.branch && <span>, branch {t.code_version.git.branch}</span>}
                  {t.code_version?.git?.dirty && <span className="text-warning-700">, uncommitted changes ({t.code_version.git.changed_files_count} file{t.code_version.git.changed_files_count === 1 ? '' : 's'})</span>}
                </p>
                <div className="mt-2">{t.config?.experiment ? (
                  <p className="rounded-md border border-warning-100 bg-warning-50 px-2.5 py-1.5 text-[12px] text-ink">Experiment run (a hypothetical input, not a real diagnosis): “{t.config.experiment.label}” of{' '}
                    <a href={`/lab/${t.config.experiment.experiment_id}`} className="font-medium text-primary-700 underline underline-offset-2">{t.config.experiment.experiment_id}</a>.</p>
                ) : <RobustnessCheck key={t.trace_id} question={t.query} dataset={t.dataset_type} traceId={t.trace_id} dataMode={t.data_mode} topK={t.config?.top_k} />}</div>
                <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[12px]">
                  <a href={traceReportUrl(t.trace_id)} target="_blank" rel="noreferrer" className="rounded-md border border-ink bg-ink px-2 py-1 font-medium text-surface hover:opacity-90 focus-ring">Run report (print / PDF)</a>
                  <span className="text-muted">Download this trace:</span>
                  {[['json', 'Full JSON'], ['transcript', 'Conversation (.md)'], ['messages_csv', 'Messages CSV'], ['events_csv', 'Events CSV'],
                    ['executions_csv', 'Agent runs CSV'], ['evidence_csv', 'Evidence CSV'], ['llm_calls_csv', 'Model calls CSV'],
                    ['scores_csv', 'Score changes CSV']].map(([f, l]) => (
                    <a key={f} href={traceExportUrl(t.trace_id, f)} download
                      className="rounded-md border border-line bg-surface px-2 py-1 font-medium text-ink hover:bg-well focus-ring">{l}</a>
                  ))}
                </div>
              </div>
              <div className="rounded-xl border border-line bg-surface p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-[11.5px] text-muted">Final decision</p>
                    <p className="text-[15px] font-semibold text-ink">{t.final_label || 'No decision recorded'}</p>
                  </div>
                  {t.review_decision && <ReviewDecision decision={t.review_decision} variant="inline" />}
                </div>
                {t.final_confidence != null && <div className="mt-3"><ConfidenceIndicator value={t.final_confidence} threshold={0.65} /></div>}
                {!t.config?.experiment && <div className="mt-3 -mx-1"><ReviewPanel key={t.trace_id} traceId={t.trace_id} diagnosis={t.final_label} alternatives={[...new Set((data.hypotheses || []).map((h) => h.label))]} compact /></div>}
                {s.confidence_progression?.length > 1 && (
                  <p className="mt-2 text-[11.5px] text-muted">Confidence over the run: {s.confidence_progression.map((c) => c.confidence?.toFixed(2)).join(' → ')}</p>
                )}
              </div>
            </header>

            <section aria-label="Trace summary" className="border-y border-line py-4"><TraceSummary summary={s} /></section>

            <section className="grid gap-6 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
              <div className="min-w-0">
                <h2 className="text-[13px] font-semibold text-ink mb-2">Who talked to whom</h2>
                <CommunicationGraph graph={data.graph} selectedAgent={selectedAgent} onSelectAgent={(a) => { setSelectedAgent(a); setSelectedEdge(null) }}
                  selectedEdge={selectedEdge} onSelectEdge={(e) => { setSelectedEdge(e); setSelectedAgent(null); setTab('timeline') }} />
              </div>
              <div className="min-w-0 xl:sticky xl:top-4 self-start rounded-xl border border-line bg-surface p-4">
                <h2 className="text-[13px] font-semibold text-ink mb-2">Message</h2>
                <MessageInspector message={message} messages={data.messages} hypotheses={data.hypotheses} onSelect={selectMessage} />
              </div>
            </section>

            <section>
              <div role="tablist" aria-label="Trace views" className="flex flex-wrap gap-x-5 border-b border-line">
                {TABS.map(([id, label]) => (
                  <button key={id} role="tab" type="button" aria-selected={tab === id} onClick={() => setTab(id)}
                    className={cx('relative whitespace-nowrap py-2 text-[13px] focus-ring rounded-sm', tab === id ? 'font-semibold text-ink after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:bg-ink' : 'text-muted hover:text-ink')}>
                    {label}
                    {id === 'signals' && insights?.signals?.length > 0 && <span className={cx('ml-1.5 text-[11px] tabular-nums', insights.signals.some((x) => x.severity === 'high') ? 'text-danger-700 font-semibold' : 'text-muted')}>{insights.signals.length}</span>}
                    {id === 'disagreements' && data.disagreements.length > 0 && <span className="ml-1.5 text-[11px] text-muted tabular-nums">{data.disagreements.length}</span>}
                  </button>
                ))}
              </div>
              <div className="pt-4" role="tabpanel">
                {['steps', 'signals', 'compare'].includes(tab) && insights === undefined && <p className="flex items-center gap-2 text-[13px] text-muted"><Loader2 size={14} className="animate-spin" />Loading…</p>}
                {['steps', 'signals'].includes(tab) && insights === null && (
                  <div className="rounded-lg border border-dashed border-line p-4 text-[12.5px] text-muted">
                    This trace was recorded before step recording was added, so it has no step breakdown or signals.{' '}
                    <button type="button" disabled={rerunning} className="font-medium text-primary-700 underline underline-offset-2"
                      onClick={async () => { setRerunning(true); try { const r = await sendQuery(t.query, t.dataset_type, t.data_mode, t.config?.top_k || 8); nav(`/traces/${r.harness.trace_id}`) } finally { setRerunning(false) } }}>
                      {rerunning ? 'Re-running…' : 'Re-run this question now'}</button> to get a new trace with it.
                  </div>
                )}
                {tab === 'steps' && insights && <StepBreakdown data={insights} focus={focusStep} />}
                {tab === 'signals' && insights && <SignalsPanel signals={insights.signals} steps={insights.steps} onGoToStep={(k) => { setFocusStep(k); setTab('steps') }} />}
                {tab === 'compare' && insights !== undefined && (
                  <div className="space-y-4">
                    <TracePicker current={t} onCompare={setCompareIds} />
                    {compareIds && <MultiCompare ids={compareIds} />}
                  </div>
                )}
                {tab === 'collaboration' && <CollaborationPanel positions={data.positions} summary={s} onSelect={selectMessage} />}
                {tab === 'timeline' && <TraceTimeline timeline={data.timeline} selectedId={selectedMsg} onSelect={setSelectedMsg}
                  agentFilter={selectedAgent} edgeFilter={selectedEdge} onClearFilters={() => { setSelectedAgent(null); setSelectedEdge(null) }} />}
                {tab === 'agents' && <AgentDetails traceId={t.trace_id} agents={data.agentDetails.agents} agentOrder={data.agentDetails.agent_order}
                  selectedAgent={selectedAgent} onSelectAgent={setSelectedAgent} />}
                {tab === 'evidence' && <EvidenceFlow evidence={data.evidence} />}
                {tab === 'scores' && <ScoreChanges traceId={t.trace_id} />}
                {tab === 'disagreements' && <Disagreements items={data.disagreements} onSelect={selectMessage} />}
                {tab === 'events' && <RawEvents traceId={t.trace_id} />}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
