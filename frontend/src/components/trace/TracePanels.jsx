import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, CircleDot, Eye, EyeOff, ChevronRight, Loader2 } from 'lucide-react'
import { cx, Cited } from '../ui'
import { agentColor, AGENT_SHORT } from '../../lib/agentColors'
import { FAMILY, MSG, familyOf, typeLabel, RESOLUTION, HYP_STATUS, SEGMENT_HINT, fmtMs, fmtClock } from '../../lib/traceVocab'
import { getTraceAgents, getTraceEvents, getTraceLlmCalls, getTraceScores } from '../../services/api'

const NAME = { ...AGENT_SHORT, harness: 'Retrieval', all: 'everyone' }
const name = (k) => NAME[k] || k

export function AgentDot({ id, size = 8 }) {
  return <span className="inline-block shrink-0 rounded-full" style={{ width: size, height: size, background: agentColor(id) }} aria-hidden />
}

export function TypeChip({ type }) {
  return <span className={cx('chip py-0 text-[10.5px] font-medium', FAMILY[familyOf(type)].chip)}>{typeLabel(type)}</span>
}

function Resolution({ status, challenge }) {
  if (challenge && challenge !== 'NOT_APPLICABLE' && !RESOLUTION[status]) return null
  const r = RESOLUTION[status]
  if (!r) return null
  const Icon = status === 'RESOLVED' ? CheckCircle2 : CircleDot
  return <span className={cx('inline-flex items-center gap-1 text-[11px]', r.cls)}><Icon size={12} aria-hidden />{r.label}</span>
}

/* ── B. communication timeline ─────────────────────────────────────────── */
export function TraceTimeline({ timeline, selectedId, onSelect, agentFilter, edgeFilter, onClearFilters }) {
  const keep = (m) => {
    if (agentFilter && m.sender !== agentFilter && !m.receivers.includes(agentFilter) && !m.readers.includes(agentFilter)) return false
    if (edgeFilter) {
      const [s, t] = edgeFilter.split('>')
      if (m.sender !== s || !(m.receivers.includes(t) || (m.receivers.includes('all') && m.readers.includes(t)))) return false
    }
    return true
  }
  const segments = (timeline?.segments || []).map((s) => ({ ...s, messages: s.messages.filter(keep) })).filter((s) => s.messages.length)
  const total = (timeline?.segments || []).reduce((n, s) => n + s.messages.length, 0)
  const shown = segments.reduce((n, s) => n + s.messages.length, 0)
  if (!total) return <p className="text-[13px] text-muted">No agent messages were recorded in this trace.</p>
  return (
    <div>
      {(agentFilter || edgeFilter) && (
        <div className="mb-3 flex items-center gap-2 text-[12px] text-muted">
          <span>Showing {shown} of {total} messages{agentFilter ? ` involving ${name(agentFilter)}` : ''}{edgeFilter ? ` from ${edgeFilter.split('>').map(name).join(' to ')}` : ''}.</span>
          <button type="button" onClick={onClearFilters} className="font-medium text-primary-700 underline underline-offset-2 focus-ring rounded">Show all</button>
        </div>
      )}
      <ol className="space-y-5">
        {segments.map((seg, i) => (
          <li key={`${seg.label}-${i}`}>
            <div className="flex items-baseline gap-3 border-b border-line pb-1.5 mb-2">
              <h4 className="text-[13px] font-semibold text-ink">{seg.label}</h4>
              <span className="text-[11.5px] text-muted">{SEGMENT_HINT[seg.phase] || `${seg.messages.length} message(s)`}</span>
            </div>
            <ol className="space-y-0.5">
              {seg.messages.map((m) => {
                const sel = m.message_id === selectedId
                const unread = m.receivers.filter((r) => r !== 'all' && r !== 'harness' && !m.readers.includes(r))
                return (
                  <li key={m.message_id}>
                    <button type="button" onClick={() => onSelect(m.message_id)} aria-pressed={sel}
                      className={cx('grid w-full grid-cols-[46px_minmax(0,1fr)_auto] items-center gap-x-3 rounded-md px-2 py-1.5 text-left focus-ring',
                        sel ? 'bg-primary-50 ring-1 ring-primary-200' : 'hover:bg-well', m.response_to && 'pl-6')}>
                      <span className="mono text-[11px] text-muted tabular-nums">{m.message_id}</span>
                      <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[12.5px]">
                        <AgentDot id={m.sender} />
                        <span className="font-medium text-ink">{name(m.sender)}</span>
                        <span className="text-muted" aria-hidden>→</span>
                        <span className="text-ink">{m.receivers.map(name).join(', ')}</span>
                        <TypeChip type={m.message_type} />
                        {m.voice === 'llm' && <span className="chip py-0 text-[10px] font-medium border-slate-300 bg-surface text-muted" title="Worded by the council LLM, checked against the method's facts">GPT-voiced</span>}
                        {m.topic && <span className="truncate text-muted max-w-[260px]">{m.topic}</span>}
                      </span>
                      <span className="flex items-center gap-2 justify-self-end">
                        <Resolution status={m.resolution_status} />
                        {unread.length > 0 && <span title={`Not read by ${unread.map(name).join(', ')}`} className="text-muted"><EyeOff size={13} aria-label="not read by every addressee" /></span>}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ol>
          </li>
        ))}
      </ol>
    </div>
  )
}

/* ── C. conversation inspector ─────────────────────────────────────────── */
export function MessageInspector({ message, messages, hypotheses, onSelect }) {
  if (!message) return <p className="text-[13px] text-muted">Select a message in the timeline to inspect it.</p>
  const m = message
  const replies = messages.filter((x) => x.response_to_message_id === m.message_id)
  const parent = messages.find((x) => x.message_id === m.response_to_message_id)
  const transitions = hypotheses.filter((h) => h.message_id === m.message_id)
  const readers = [...new Map(m.deliveries.map((d) => [`${d.receiver}:${d.via}`, d])).values()]
  const Row = ({ label, children }) => (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-3 py-1.5 border-b border-line last:border-0">
      <dt className="text-[11.5px] text-muted">{label}</dt><dd className="text-[12.5px] text-ink min-w-0">{children}</dd>
    </div>
  )
  const Link = ({ id }) => (
    <button type="button" onClick={() => onSelect(id)} className="mono text-[12px] text-primary-700 underline underline-offset-2 focus-ring rounded">{id}</button>
  )
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="mono text-[12px] text-muted">{m.message_id}</span>
        <TypeChip type={m.message_type} />
        <span className="text-[12px] text-muted">{MSG[m.message_type]?.verb}</span>
        <span className="ml-auto text-[11.5px] text-muted">{typeLabel(m.stage || 'message')}, round {m.round_id}, sequence {m.seq}</span>
      </div>
      <p className="mt-2 text-[13px] leading-relaxed text-ink break-words"><Cited text={m.message_content} /></p>
      <dl className="mt-3">
        <Row label="From"><span className="inline-flex items-center gap-1.5"><AgentDot id={m.sender_agent_id} />{name(m.sender_agent_id)}</span>{m.sender_execution_id && <span className="mono text-[11px] text-muted ml-2">{m.sender_execution_id}</span>}</Row>
        <Row label="Addressed to">{m.receiver_agent_ids.map(name).join(', ')}</Row>
        <Row label="Read by">
          {readers.length ? readers.map((d) => (
            <span key={`${d.receiver}${d.via}`} className="mr-2 inline-flex items-center gap-1"><Eye size={11} className="text-muted" aria-hidden />{name(d.receiver)}
              <span className="text-[11px] text-muted">({d.via.replace('_', ' ')})</span></span>
          )) : <span className="text-muted">Nobody read this message</span>}
        </Row>
        <Row label="Sent at">{fmtClock(m.timestamp)}</Row>
        {m.payload?.position && (
          <Row label="Position">
            <span className="flex flex-wrap gap-x-3">{Object.entries(m.payload.position).map(([l, v]) => <span key={l} className="whitespace-nowrap">{l} <b className="tabular-nums font-semibold">{Math.round(v * 100)}%</b></span>)}</span>
            {m.payload.old_position && <div className="text-[11.5px] text-muted">was {Object.entries(m.payload.old_position).slice(0, 3).map(([l, v]) => `${l} ${Math.round(v * 100)}%`).join(', ')}</div>}
            {m.payload.read_positions_from?.length > 0 && <div className="text-[11.5px] text-muted">read positions from {m.payload.read_positions_from.map(name).join(', ')} (openness {m.payload.openness})</div>}
          </Row>
        )}
        {m.payload?.voice && (
          <Row label="Wording">
            {m.payload.voice === 'llm' ? <>Voiced by {m.payload.voice_model}; the method's own text was:<div className="mt-0.5 text-[12px] text-muted">{m.payload.method_text}</div></>
              : <>The agent's method text{m.payload.voice_rejected ? <span className="text-muted"> (LLM wording rejected: {m.payload.voice_rejected})</span> : ''}</>}
          </Row>
        )}
        {m.related_hypothesis_ids.length > 0 && <Row label="Hypotheses">{m.related_hypothesis_ids.join(', ')}</Row>}
        <Row label="Evidence">{m.evidence_ids.length ? <Cited text={m.evidence_ids.join(' ')} /> : <span className="text-muted">None cited</span>}
          {m.payload?._trace_unknown_evidence_ids?.length > 0 && <div className="text-[11.5px] text-danger-700 mt-0.5">Not in this run: {m.payload._trace_unknown_evidence_ids.join(', ')}</div>}
        </Row>
        {parent && <Row label="In reply to"><Link id={parent.message_id} /> <span className="text-muted">{typeLabel(parent.message_type).toLowerCase()} from {name(parent.sender_agent_id)}</span></Row>}
        {replies.length > 0 && <Row label="Replies">{replies.map((r) => <span key={r.message_id} className="mr-3"><Link id={r.message_id} /> <span className="text-muted">{typeLabel(r.message_type).toLowerCase()}</span></span>)}</Row>}
        {m.challenge_status !== 'NOT_APPLICABLE' && <Row label="Challenge">{typeLabel(m.challenge_status)}</Row>}
        {m.resolution_status !== 'NOT_APPLICABLE' && <Row label="Resolution"><Resolution status={m.resolution_status} />{m.payload?.outcome && <div className="text-[12px] text-muted mt-0.5">{m.payload.outcome}</div>}</Row>}
        {m.payload?.results && (
          <Row label="Claims checked">
            <ul className="space-y-0.5">{m.payload.results.map((r) => (
              <li key={r.claim_id} className="text-[12px]"><span className={cx('font-medium', r.status === 'UNSUPPORTED' ? 'text-danger-700' : 'text-success-700')}>{typeLabel(r.status)}</span>
                <span className="mono text-[11px] text-muted ml-1.5">{r.claim_id}</span>{r.reasons?.[0] && <span className="text-muted">: {r.reasons[0]}</span>}</li>
            ))}</ul>
          </Row>
        )}
        <Row label="Resulting state">
          {transitions.length ? transitions.map((h) => (
            <span key={h.seq} className="mr-2 inline-flex items-center gap-1"><AgentDot id={h.agent_id} size={7} />
              <span className={cx('chip py-0 text-[10.5px] font-medium', HYP_STATUS[h.status])}>{typeLabel(h.status)}</span>
              <span className="text-[12px]">{h.label}</span></span>
          )) : <span className="text-muted">No hypothesis changed state on this message</span>}
        </Row>
      </dl>
    </div>
  )
}

/* ── D. agent execution details ────────────────────────────────────────── */
export function AgentDetails({ traceId, agents, agentOrder, selectedAgent, onSelectAgent }) {
  const [prompts, setPrompts] = useState(null)
  const [responses, setResponses] = useState(null)
  const [loadingPrompts, setLoadingPrompts] = useState(false)
  const key = selectedAgent || agentOrder?.[0]
  const a = agents?.[key]
  useEffect(() => { setPrompts(null); setResponses(null) }, [traceId])
  if (!a) return <p className="text-[13px] text-muted">No agent executions recorded.</p>
  const execs = a.execution_records || []
  const llm = execs.some((x) => x.llm_calls?.length)
  const loadPrompts = async () => {
    setLoadingPrompts(true)
    try {
      const [ag, calls] = await Promise.all([getTraceAgents(traceId, true), getTraceLlmCalls(traceId, true)])
      setPrompts(ag.agents); setResponses(calls.calls)
    } finally { setLoadingPrompts(false) }
  }
  const promptOf = (xid) => prompts?.[key]?.execution_records?.find((x) => x.execution_id === xid)?.rendered_input
  const responsesOf = (xid) => (responses || []).filter((c) => c.execution_id === xid)
  const tokens = (calls) => calls.reduce((n, c) => n + (c.total_tokens || 0), 0)
  return (
    <div className="grid gap-5 lg:grid-cols-[180px_minmax(0,1fr)]">
      <ul className="flex lg:flex-col gap-1 overflow-x-auto" aria-label="Agents">
        {agentOrder.map((k) => (
          <li key={k}>
            <button type="button" onClick={() => onSelectAgent(k)} aria-pressed={k === key}
              className={cx('flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12.5px] whitespace-nowrap focus-ring',
                k === key ? 'bg-ink text-surface' : 'text-ink hover:bg-well')}>
              <AgentDot id={k} />{name(k)}
              {agents[k].failed > 0 && <span className="ml-auto text-[10.5px] text-danger-500">failed</span>}
            </button>
          </li>
        ))}
      </ul>
      <div className="min-w-0 space-y-4">
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-[12.5px]">
          {[['Executions', a.executions], ['Sent', a.messages_sent], ['Read', a.messages_received], ['Challenges sent', a.challenges_sent],
            ['Challenged', a.challenges_received], ['Replies', a.responses], ['Model calls', a.llm_calls]].map(([l, v]) => (
            <div key={l}><div className="text-[11.5px] text-muted">{l}</div><div className="font-semibold tabular-nums text-ink">{v}</div></div>
          ))}
          <div><div className="text-[11.5px] text-muted">Final finding</div><div className="font-semibold text-ink">{a.final_label || '—'}</div></div>
        </div>

        {a.hypothesis_states.length > 0 && (
          <div>
            <h5 className="text-[12px] font-semibold text-ink mb-1.5">Hypothesis evolution</h5>
            <ol className="flex flex-wrap items-center gap-1.5">
              {a.hypothesis_states.map((h, i) => (
                <li key={h.seq} className="flex items-center gap-1.5">
                  {i > 0 && <ChevronRight size={12} className="text-slate-400" aria-hidden />}
                  <span className={cx('chip font-medium', HYP_STATUS[h.status])} title={`#${h.seq} ${h.reason || ''}`}>{typeLabel(h.status)}: {h.label}</span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {a.confidence_progression.length > 0 && (
          <p className="text-[12.5px] text-muted">Confidence by execution:{' '}
            {a.confidence_progression.map((c, i) => <span key={c.execution_id} className="text-ink tabular-nums">{i > 0 && ' → '}{c.confidence.toFixed(2)}<span className="text-muted text-[11px]"> ({c.stage})</span></span>)}
          </p>
        )}

        <div>
          <div className="flex items-center gap-3 mb-1.5">
            <h5 className="text-[12px] font-semibold text-ink">Executions</h5>
            {llm && !prompts && (
              <button type="button" onClick={loadPrompts} disabled={loadingPrompts} className="text-[12px] font-medium text-primary-700 underline underline-offset-2 focus-ring rounded">
                {loadingPrompts ? 'Loading model inputs and responses…' : 'Load model inputs and full responses'}
              </button>
            )}
          </div>
          <ol className="space-y-2">
            {execs.map((x) => (
              <li key={x.execution_id} className="rounded-lg border border-line bg-surface px-3 py-2">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
                  <span className="mono text-[11px] text-muted">{x.execution_id}</span>
                  <span className="font-medium text-ink">{x.kind === 'analyze' ? 'Analysis' : typeLabel(x.kind)}</span>
                  <span className="text-muted">{x.stage}{x.pass_number ? `, pass ${x.pass_number}` : ''}{x.round_id ? `, round ${x.round_id}` : ''}</span>
                  <span className={cx('font-medium', x.status === 'COMPLETED' ? 'text-success-700' : x.status === 'FAILED' ? 'text-danger-700' : 'text-warning-700')}>{typeLabel(x.status)}</span>
                  <span className="ml-auto text-muted tabular-nums">{fmtMs(x.duration_ms)}</span>
                </div>
                {x.kind === 'analyze' && (
                  <div className="mt-1 text-[12px] text-muted">
                    Input: {x.evidence_in_input?.length || 0} evidence item(s) in state
                    {x.input?.messages_on_board != null && `, ${x.input.messages_on_board} message(s) on the board`}
                    {x.llm_calls?.length ? `; ${x.llm_calls.length} model call(s), ${x.llm_calls.reduce((n, c) => n + c.input_chars, 0).toLocaleString()} characters rendered` : '; no model call (deterministic)'}
                  </div>
                )}
                {x.llm_calls?.length > 0 && x.llm_calls.some((c) => c.total_tokens != null) && (
                  <p className="text-[11.5px] text-muted tabular-nums">
                    Tokens: {x.llm_calls.reduce((n, c) => n + (c.prompt_tokens || 0), 0).toLocaleString()} prompt + {x.llm_calls.reduce((n, c) => n + (c.completion_tokens || 0), 0).toLocaleString()} completion
                    {' '}({tokens(x.llm_calls).toLocaleString()} total){x.llm_calls[0].response_model ? `, ${x.llm_calls[0].response_model}` : ''}
                  </p>
                )}
                {x.output?.finding && <p className="mt-1 text-[12.5px] text-ink"><Cited text={x.output.finding} /></p>}
                {x.claims?.length > 0 && <p className="text-[11.5px] text-muted">{x.claims.length} claim(s); confidence {x.confidence?.toFixed(2)}</p>}
                {(x.messages_sent?.length > 0 || x.messages_received?.length > 0) && (
                  <p className="text-[11.5px] text-muted">Sent {x.messages_sent.join(', ') || 'none'}; read {x.messages_received.join(', ') || 'none'}</p>
                )}
                {x.tool_calls?.length > 0 && <p className="text-[11.5px] text-muted">Tools: {x.tool_calls.map((t) => t.tool).join(', ')}</p>}
                {x.error && <p className="text-[12px] text-danger-700">{x.error}</p>}
                {promptOf(x.execution_id) && (
                  <details className="mt-1.5">
                    <summary className="cursor-pointer text-[12px] text-primary-700">Rendered model input</summary>
                    <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded bg-well p-2 text-[11px] leading-snug">{promptOf(x.execution_id)}</pre>
                  </details>
                )}
                {responsesOf(x.execution_id).map((c) => (
                  <details key={c.call_index} className="mt-1.5">
                    <summary className="cursor-pointer text-[12px] text-primary-700">
                      Raw model response {c.call_index}{' '}
                      <span className="text-muted">({c.response_chars?.toLocaleString() ?? 0} chars, {c.total_tokens ?? '?'} tokens, {c.finish_reason || (c.ok ? 'ok' : 'failed')})</span>
                    </summary>
                    {c.error && <p className="mt-1 text-[11.5px] text-danger-700 whitespace-pre-wrap">{c.error}</p>}
                    {c.response_raw != null && <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded bg-well p-2 text-[11px] leading-snug">{c.response_raw}</pre>}
                    <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-well/60 p-2 text-[10.5px] leading-snug text-muted">{JSON.stringify({ usage: c.usage, request: c.request, response: c.response_meta }, null, 1)}</pre>
                  </details>
                ))}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  )
}

/* ── E. evidence flow ──────────────────────────────────────────────────── */
const RENDERED = { TRUE: 'In prompt', FALSE: 'Not in prompt', NOT_APPLICABLE: 'No model call' }
export function EvidenceFlow({ evidence }) {
  const [open, setOpen] = useState(null)
  const [kind, setKind] = useState('record')
  const rows = (evidence || []).filter((e) => kind === 'all' || e.kind === kind)
  if (!evidence?.length) return <p className="text-[13px] text-muted">No evidence was recorded for this trace.</p>
  return (
    <div>
      <div className="mb-2 flex items-center gap-3 text-[12px]" role="radiogroup" aria-label="Evidence kind">
        {[['record', 'Retrieved records'], ['derived', 'Derived values'], ['all', 'All']].map(([k, l]) => (
          <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => setKind(k)}
            className={cx('rounded-md px-2 py-1 focus-ring', kind === k ? 'bg-ink text-surface' : 'text-muted hover:text-ink')}>{l}</button>
        ))}
        <span className="ml-auto text-muted">Received means present in the agent's input; it does not mean the agent used it.</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-[12.5px]">
          <thead>
            <tr className="text-left text-[11.5px] text-muted border-b border-line">
              <th className="py-1.5 pr-3 font-medium">Evidence</th><th className="pr-3 font-medium">Origin</th>
              <th className="pr-3 font-medium">Received by</th><th className="pr-3 font-medium">Rendered</th>
              <th className="pr-3 font-medium">Cited by</th><th className="pr-3 font-medium">Claims</th>
              <th className="pr-3 font-medium">Messages</th><th className="font-medium">Verification</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <FlowRow key={e.evidence_id} e={e} open={open === e.evidence_id} onToggle={() => setOpen(open === e.evidence_id ? null : e.evidence_id)} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Dots({ ids }) {
  if (!ids?.length) return <span className="text-muted">—</span>
  return <span className="inline-flex items-center gap-1" title={ids.map(name).join(', ')}>{ids.map((a) => <AgentDot key={a} id={a} />)}<span className="ml-1 text-[11px] text-muted">{ids.length}</span></span>
}

function FlowRow({ e, open, onToggle }) {
  const prov = e.provenance === 'REAL' ? 'text-primary-700' : e.provenance === 'SYNTHETIC' ? 'text-secondary-700' : 'text-muted'
  const ver = { VERIFIED: 'text-success-700', UNSUPPORTED: 'text-danger-700', NOT_CHECKED: 'text-muted' }[e.verification_status]
  return (
    <>
      <tr className="border-b border-line align-top">
        <td className="py-1.5 pr-3">
          <button type="button" onClick={onToggle} aria-expanded={open} className="inline-flex items-center gap-1 focus-ring rounded">
            <ChevronRight size={12} className={cx('text-muted transition-transform', open && 'rotate-90')} aria-hidden />
            <span className="mono text-[12px] text-ink">{e.evidence_id}</span>
          </button>
          <div className={cx('pl-4 text-[11px] font-medium', prov)}>{e.provenance}{e.label ? <span className="font-normal text-muted"> · {e.label}</span> : null}</div>
        </td>
        <td className="pr-3 text-muted">{e.kind === 'derived' ? 'harness computation' : <>{e.retrieval_action}<div className="text-[11px]">{e.retrieval_method}, round {e.retrieval_round}</div></>}</td>
        <td className="pr-3"><Dots ids={e.received_by} /></td>
        <td className="pr-3 text-muted">{RENDERED[e.rendered_status]}{e.in_rendered_input?.length > 0 && <div><Dots ids={e.in_rendered_input} /></div>}</td>
        <td className="pr-3"><Dots ids={e.cited_by} /></td>
        <td className="pr-3 tabular-nums">{e.claims.length || <span className="text-muted">—</span>}</td>
        <td className="pr-3 tabular-nums">{e.messages.length || <span className="text-muted">—</span>}</td>
        <td className={cx('font-medium', ver)}>{typeLabel(e.verification_status)}</td>
      </tr>
      {open && (
        <tr className="border-b border-line bg-well/50">
          <td colSpan={8} className="px-4 py-2 text-[12px]">
            {e.description && <p className="text-muted mb-1">{e.description}</p>}
            {e.content_text && (
              <details className="mb-1">
                <summary className="cursor-pointer text-primary-700">Record text <span className="text-muted">({e.content_text.length.toLocaleString()} chars)</span></summary>
                <p className="mt-1 text-ink whitespace-pre-wrap">{e.content_text}</p>
              </details>
            )}
            {e.content && (
              <details className="mb-1">
                <summary className="cursor-pointer text-primary-700">Full record content</summary>
                <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-surface p-2 text-[11px] leading-snug">{JSON.stringify(e.content, null, 1)}</pre>
              </details>
            )}
            {e.claims.length > 0 && <ul className="space-y-0.5 mb-1">{e.claims.map((c) => <li key={c.claim_id + c.agent}><AgentDot id={c.agent} size={6} /> <span className="text-muted">{c.polarity}:</span> <Cited text={c.statement} /></li>)}</ul>}
            {e.messages.length > 0 && <p className="text-muted">Cited in {e.messages.map((m) => `${m.message_id} (${typeLabel(m.message_type || '').toLowerCase()} from ${name(m.sender)})`).join(', ')}</p>}
            {e.verification.length > 0 && <p className="text-muted">Verification: {e.verification.map((v) => `${v.claim_id} ${typeLabel(v.status).toLowerCase()} (${v.message_id})`).join('; ')}</p>}
            {e.not_in_rendered_input?.length > 0 && <p className="text-muted">In the input state but absent from the rendered prompt of: {e.not_in_rendered_input.map(name).join(', ')}</p>}
          </td>
        </tr>
      )}
    </>
  )
}

/* ── F. summary + disagreements ────────────────────────────────────────── */
export function TraceSummary({ summary }) {
  const s = summary
  const items = [
    ['Agents', s.total_agents], ['Messages', s.total_messages], ['Rounds', s.total_rounds],
    ['Evidence references', s.total_evidence_references], ['Challenges', s.challenges],
    ['Resolved', s.resolved_disagreements], ['Unresolved', s.unresolved_disagreements], ['Events', s.total_events],
    ...(s.llm_usage?.total_tokens ? [['Model tokens', s.llm_usage.total_tokens.toLocaleString()]] : []),
    ...(s.score_changes ? [['Score changes', s.score_changes.length]] : []),
  ]
  return (
    <dl className="grid grid-cols-4 sm:grid-cols-5 lg:grid-cols-10 gap-x-4 gap-y-3">
      {items.map(([l, v]) => (
        <div key={l} className="min-w-0">
          <dt className="text-[11.5px] text-muted truncate">{l}</dt>
          <dd className={cx('text-[20px] font-semibold tabular-nums leading-tight', l === 'Unresolved' && v ? 'text-danger-700' : 'text-ink')}>{v ?? '—'}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Disagreements({ items, onSelect }) {
  if (!items?.length) return <p className="text-[13px] text-muted">No agent challenged another agent in this trace.</p>
  return (
    <ol className="space-y-2">
      {items.map((d) => (
        <li key={d.message_id} className="rounded-lg border border-line bg-surface px-3 py-2 text-[12.5px]">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <AgentDot id={d.challenger} /><b className="font-medium">{name(d.challenger)}</b>
            <span className="text-muted">{MSG[d.type]?.verb}</span>
            <AgentDot id={d.challenged[0]} /><b className="font-medium">{name(d.challenged[0])}</b>
            <span className="text-muted">on {d.challenged_label}{d.challenger_label ? ` (proposes ${d.challenger_label})` : ''}</span>
            <span className="ml-auto"><Resolution status={d.resolution_status} /></span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
            {d.original_assertion && <><button type="button" onClick={() => onSelect(d.original_assertion)} className="mono text-primary-700 underline underline-offset-2 focus-ring rounded">{d.original_assertion}</button><span>assertion</span><ChevronRight size={11} aria-hidden /></>}
            <button type="button" onClick={() => onSelect(d.message_id)} className="mono text-primary-700 underline underline-offset-2 focus-ring rounded">{d.message_id}</button><span>{typeLabel(d.type).toLowerCase()}</span>
            {d.replies.map((r) => <span key={r.message_id} className="inline-flex items-center gap-1.5"><ChevronRight size={11} aria-hidden /><button type="button" onClick={() => onSelect(r.message_id)} className="mono text-primary-700 underline underline-offset-2 focus-ring rounded">{r.message_id}</button>{typeLabel(r.type).toLowerCase()}{r.stance ? ` (${r.stance})` : ''}</span>)}
          </div>
          {d.outcome && <p className="mt-1 text-[12px] text-ink">{d.outcome}</p>}
        </li>
      ))}
    </ol>
  )
}

/* ── raw event log (audit) ─────────────────────────────────────────────── */
export function RawEvents({ traceId }) {
  const [state, setState] = useState({ loading: true, events: [], total: 0 })
  const [type, setType] = useState('')
  const [offset, setOffset] = useState(0)
  const LIMIT = 200
  useEffect(() => { setOffset(0) }, [traceId, type])
  useEffect(() => {
    let live = true
    setState((s) => ({ ...s, loading: true }))
    getTraceEvents(traceId, { limit: LIMIT, offset, eventType: type || null })
      .then((r) => live && setState({ loading: false, events: r.events, total: r.total }))
      .catch((e) => live && setState({ loading: false, events: [], total: 0, error: e.message }))
    return () => { live = false }
  }, [traceId, type, offset])
  const types = useMemo(() => ['TRACE_STARTED', 'QUERY_PREPARED', 'EVIDENCE_RETRIEVED', 'AGENT_STARTED', 'AGENT_OUTPUT_GENERATED', 'AGENT_FAILED',
    'AGENT_REEXECUTED', 'LLM_CALL_COMPLETED', 'MESSAGE_SENT', 'MESSAGE_RECEIVED', 'HYPOTHESIS_CHALLENGED', 'HYPOTHESIS_UPDATED', 'EVIDENCE_VERIFIED',
    'FEEDBACK_LOOP_TRIGGERED', 'TARGETED_RETRIEVAL_STARTED', 'COUNCIL_ROUND_STARTED', 'COUNCIL_ROUND_COMPLETED', 'CONFIDENCE_RECALCULATED',
    'CLAIM_VALIDATED', 'HUMAN_REVIEW_TRIGGERED', 'FINAL_SYNTHESIS_GENERATED', 'TRACE_COMPLETED', 'TRACE_FAILED'], [])
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-3 text-[12px]">
        <label className="flex items-center gap-1.5 text-muted">Event type
          <select value={type} onChange={(e) => setType(e.target.value)} className="rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink focus-ring">
            <option value="">All</option>{types.map((t) => <option key={t} value={t}>{typeLabel(t)}</option>)}
          </select>
        </label>
        <span className="text-muted tabular-nums">{state.total} event(s), ordered by sequence number</span>
        {state.loading && <Loader2 size={13} className="animate-spin text-muted" aria-label="loading" />}
        <span className="ml-auto flex gap-2">
          <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))} className="btn-ghost px-2 py-1 text-[12px]">Previous</button>
          <button type="button" disabled={offset + LIMIT >= state.total} onClick={() => setOffset(offset + LIMIT)} className="btn-ghost px-2 py-1 text-[12px]">Next</button>
        </span>
      </div>
      {state.error && <p className="text-[12.5px] text-danger-700">Could not load events: {state.error}</p>}
      <div className="max-h-[480px] overflow-auto rounded-lg border border-line">
        <table className="w-full text-[12px]">
          <tbody>
            {state.events.map((e) => (
              <tr key={e.event_id} className="border-b border-line align-top">
                <td className="px-2 py-1 mono text-[11px] text-muted tabular-nums">#{e.seq}</td>
                <td className="px-2 py-1 whitespace-nowrap font-medium text-ink">{typeLabel(e.event_type)}</td>
                <td className="px-2 py-1 whitespace-nowrap">{e.actor && <span className="inline-flex items-center gap-1"><AgentDot id={e.actor} size={6} />{name(e.actor)}</span>}</td>
                <td className="px-2 py-1 text-muted">{[e.message_id, e.execution_id, e.payload?.stage].filter(Boolean).join(', ')}{e.evidence_ids?.length ? `; ${e.evidence_ids.slice(0, 6).join(' ')}${e.evidence_ids.length > 6 ? ` +${e.evidence_ids.length - 6}` : ''}` : ''}</td>
                <td className="px-2 py-1 text-muted whitespace-nowrap">{fmtClock(e.timestamp)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ── collaboration: how each agent's position moved, round by round ───── */
const LABEL_TONES = ['#3F6690', '#A9594E', '#557A47', '#A27A12', '#76569A', '#6B6457']
const PHASE_SHORT = { collaboration: 'Collab', resync: 'Re-sync', council: 'Council' }
const PARTICIPANTS = ['diagnostic_expert', 'pattern_agent', 'aggressive_agent', 'verification']

export function CollaborationPanel({ positions, summary, onSelect }) {
  const cols = positions?.columns || []
  const joint = positions?.joint || []
  if (!cols.length) return <p className="text-[13px] text-muted">The agents did not collaborate in this trace (collaboration was off or there was only one candidate).</p>
  const lastJoint = joint[joint.length - 1]
  const order = Object.keys(lastJoint?.joint || {})
  const tone = (l) => LABEL_TONES[Math.max(0, order.indexOf(l)) % LABEL_TONES.length] || LABEL_TONES[5]
  const cell = (agent, c) => (positions.agents[agent] || []).filter((x) => x.phase === c.phase && x.round_id === c.round_id && !!x.draft === !!c.draft).pop()
  const phaseIdx = {}
  const colLabel = cols.map((c) => { if (c.draft) return c.phase === 'resync' ? 'After new evidence' : 'Private draft'; phaseIdx[c.phase] = (phaseIdx[c.phase] || 0) + 1; return `${PHASE_SHORT[c.phase] || c.phase} ${phaseIdx[c.phase]}` })
  const conf = summary?.confidence_progression?.filter((c) => c.council_confidence != null).pop()
  return (
    <div className="space-y-5">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-separate border-spacing-x-1 border-spacing-y-1 text-[12px]">
          <thead>
            <tr><th className="w-40" />{colLabel.map((l, i) => <th key={i} className="text-left font-medium text-muted px-1">{l}</th>)}</tr>
          </thead>
          <tbody>
            {PARTICIPANTS.map((a) => {
              let prev = null
              return (
                <tr key={a}>
                  <th scope="row" className="text-left font-medium text-ink whitespace-nowrap pr-2"><span className="inline-flex items-center gap-1.5"><AgentDot id={a} />{name(a)}</span></th>
                  {cols.map((c, i) => {
                    const x = cell(a, c)
                    if (!x) return <td key={i} className="text-muted text-center">·</td>
                    const changed = prev && x.label && prev !== x.label
                    prev = x.label || prev
                    if (x.abstain) return <td key={i} className="rounded-md bg-well px-2 py-1.5 text-muted italic">abstains</td>
                    return (
                      <td key={i} className="p-0">
                        <button type="button" onClick={() => onSelect(x.message_id)} title={`${x.message_id} ${typeLabel(x.message_type)}${x.moved_by?.length ? `; moved by ${x.moved_by.map(name).join(', ')}` : ''}`}
                          className={cx('w-full rounded-md border px-2 py-1.5 text-left focus-ring bg-surface hover:bg-well', changed ? 'border-ink' : 'border-line')}>
                          <span className="flex items-center gap-1.5 font-medium text-ink truncate"><span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: tone(x.label) }} aria-hidden />{x.label}</span>
                          <span className="mt-1 block h-1 rounded-full bg-well"><span className="block h-1 rounded-full" style={{ width: `${Math.round((x.confidence || 0) * 100)}%`, background: tone(x.label) }} /></span>
                          <span className="mt-0.5 block text-[11px] text-muted tabular-nums">{Math.round((x.confidence || 0) * 100)}%{changed ? ', changed' : ''}</span>
                        </button>
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
        <p className="mt-1 text-[11.5px] text-muted">The first column is each agent's private draft, written before it saw anyone else's view. Each later cell is the position it stated in that round (its leading hypothesis and how strongly it holds it). A dark border marks a change of mind. Click a cell to read the message.</p>
      </div>

      {lastJoint && (
        <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_260px]">
          <div>
            <h5 className="text-[12px] font-semibold text-ink mb-2">Joint ranking the council handed to Verification</h5>
            <ul className="space-y-1.5">
              {Object.entries(lastJoint.joint).map(([l, v]) => (
                <li key={l} className="grid grid-cols-[150px_minmax(0,1fr)_44px] items-center gap-2 text-[12.5px]">
                  <span className="truncate text-ink">{l}</span>
                  <span className="h-2 rounded-full bg-well"><span className="block h-2 rounded-full" style={{ width: `${v * 100}%`, background: tone(l) }} /></span>
                  <span className="text-right tabular-nums text-muted">{Math.round(v * 100)}%</span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[12px] text-muted">
              {lastJoint.converged ? 'The agents converged.' : 'The agents did not fully converge.'}
              {lastJoint.dissent?.length ? ` Still dissenting: ${lastJoint.dissent.map(name).join(', ')}.` : ''}{' '}
              <button type="button" onClick={() => onSelect(lastJoint.message_id)} className="font-medium text-primary-700 underline underline-offset-2 focus-ring rounded">Read the joint finding</button>
            </p>
          </div>
          <div className="rounded-lg border border-line bg-surface p-3 text-[12.5px]">
            <h5 className="font-semibold text-ink">Confidence</h5>
            {conf ? (
              <dl className="mt-2 space-y-1.5">
                <div className="flex justify-between"><dt className="text-muted">Evidence factors</dt><dd className="tabular-nums text-ink">{conf.evidence_confidence?.toFixed(2)}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Agents' agreed confidence</dt><dd className="tabular-nums text-ink">{conf.council_confidence?.toFixed(2)}</dd></div>
                <div className="flex justify-between border-t border-line pt-1.5"><dt className="font-medium text-ink">Final (capped by evidence)</dt><dd className="tabular-nums font-semibold text-ink">{conf.confidence?.toFixed(2)}</dd></div>
              </dl>
            ) : <p className="mt-1 text-muted">No council confidence was recorded.</p>}
          </div>
        </div>
      )}
    </div>
  )
}


/* ── G. score changes: before / after every blend and re-score ─────────── */
const OPERATION = {
  initial_scoring: ['Initial scoring', 'Hypotheses scored from the retrieved evidence (signature fit + case vote).'],
  targeted_evidence_rescore: ['Re-scored after targeted retrieval', 'New evidence replaced the scores (including any council blend).'],
  conflict_rescore: ['Conflict re-score', 'Diagnostic Expert re-weighted the contested pair on the discriminating channels.'],
  council_blend: ['Council blend', "The agents' joint position was blended into the hypothesis scores."],
  council_blend_reverted: ['Council blend undone', 'A new collaboration pass restored the evidence scores first.'],
  council_pair_rescore: ['Council pair re-score', 'The escalation council re-weighted a contested pair from the shares agents posted.'],
  council_confidence_blend: ['Confidence blend', 'Evidence confidence blended with council confidence, capped by the evidence.'],
}
const fmtD = (d) => (d > 0 ? '+' : d < 0 ? '−' : '±') + Math.abs(d).toFixed(4)

export function ScoreChanges({ traceId }) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    let live = true
    setRows(null); setErr(null)
    getTraceScores(traceId).then((d) => live && setRows(d.changes)).catch((e) => live && setErr(e.message))
    return () => { live = false }
  }, [traceId])
  if (err) return <p className="text-[13px] text-danger-700">{err}</p>
  if (!rows) return <p className="text-[13px] text-muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" />Loading score changes…</p>
  if (!rows.length) return <p className="text-[13px] text-muted">No score changes recorded. Traces made before schema 1.1 do not have them.</p>
  return (
    <div className="space-y-3">
      <p className="text-[12.5px] text-muted">Scores immediately before and after every operation that changed them, in the order they happened. Δ = after − before.</p>
      {rows.map((c) => {
        const [title, hint] = OPERATION[c.operation] || [typeLabel(c.operation), '']
        const labels = [...new Set([...Object.keys(c.after), ...Object.keys(c.before)])].sort((a, b) => (c.after[b] ?? 0) - (c.after[a] ?? 0))
        const scale = Math.max(...labels.map((l) => Math.abs(c.delta[l] || 0)), 1e-9)
        return (
          <details key={c.change_id} className="rounded-lg border border-line bg-surface px-3 py-2" open={c.operation !== 'initial_scoring'}>
            <summary className="cursor-pointer flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[12.5px]">
              <span className="mono text-[11px] text-muted">{c.change_id}</span>
              <span className="font-semibold text-ink">{title}</span>
              <span className="text-muted">{[c.stage, c.phase && `phase ${c.phase}`, c.round_id != null && `round ${c.round_id}`, c.actor && (c.actor === 'harness' ? 'harness' : name(c.actor))].filter(Boolean).join(' · ')}</span>
              {c.top_before !== c.top_after && c.top_before && <span className="font-medium text-warning-700">top: {c.top_before} → {c.top_after}</span>}
              <span className="ml-auto tabular-nums text-muted">max |Δ| {c.max_abs_delta?.toFixed(4)}</span>
            </summary>
            {hint && <p className="mt-1 text-[11.5px] text-muted">{hint}{c.parameters?.formula ? ` ${c.parameters.formula}.` : ''}</p>}
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[520px] text-[12px] tabular-nums">
                <thead><tr className="text-left text-[11px] text-muted border-b border-line">
                  <th className="py-1 pr-3 font-medium">{c.quantity === 'confidence' ? 'Quantity' : 'Hypothesis'}</th>
                  <th className="pr-3 font-medium text-right">Before</th><th className="pr-3 font-medium text-right">After</th>
                  <th className="pr-3 font-medium text-right">Δ</th><th className="font-medium w-40" aria-label="change bar" />
                </tr></thead>
                <tbody>
                  {labels.map((l) => {
                    const d = c.delta[l] || 0
                    return (
                      <tr key={l} className="border-b border-line/60">
                        <td className="py-1 pr-3 text-ink">{l}</td>
                        <td className="pr-3 text-right text-muted">{c.before[l] != null ? c.before[l].toFixed(4) : '—'}</td>
                        <td className="pr-3 text-right text-ink">{c.after[l] != null ? c.after[l].toFixed(4) : '—'}</td>
                        <td className={cx('pr-3 text-right font-medium', d > 0 ? 'text-success-700' : d < 0 ? 'text-danger-700' : 'text-muted')}>{fmtD(d)}</td>
                        <td><div className="relative h-2 rounded bg-well"><div className={cx('absolute top-0 h-2 rounded', d >= 0 ? 'left-1/2 bg-success-500' : 'right-1/2 bg-danger-500')}
                          style={{ width: `${(Math.abs(d) / scale) * 50}%` }} /></div></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </details>
        )
      })}
    </div>
  )
}
