import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  Maximize2, Minimize2, MessageSquareText, CheckCircle2, ShieldAlert, AlertTriangle, GitMerge,
  Database, Clock, FileCheck2, RotateCcw, Wrench, HelpCircle, ChevronDown, ArrowDown,
  PanelLeftClose, PanelLeftOpen, ListChecks, Gauge, BarChart3,
} from 'lucide-react'
import { cx, pct, fmtNum, SourceBadge, DecisionBadge, StatusIcon, Cited, IdChip, Empty } from './ui'
import EvidenceExplorer from './EvidenceExplorer'
import OrchestrationFlow from './OrchestrationFlow'
import { HypothesisPanel, ConfidencePanel, SensorPanel, AuditPanel } from './ReportPanels'
import { SensorHealthChart, HypothesisComparisonChart } from './DiagnosticCharts'

/* Categorical palette in fixed order (validated data-viz palette); assigned to
   agents in the order the backend returns them — never by name. */
const AGENT_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948']
const NEUTRAL = '#94A3B8'

/* Pipeline column per execution_mode reported by the backend for each agent. */
const COLUMN_FOR_MODE = { parallel: 'initial', review: 'verification', calibration: 'ambiguity', synthesis: 'final' }
const COLUMN_TITLES = {
  initial: ['Initial agent analysis', 'Independent perspectives'],
  verification: ['Verification', 'Cross-check against evidence'],
  ambiguity: ['Ambiguity assessment', 'Unresolved issues & alternatives'],
  final: ['Final recommendation', 'Coordinated output & review gate'],
}
const HIDDEN_EXTRAS = new Set(['adversarial_review', 'candidate_reviews', 'reasoning', 'direct_answer', 'first_pass_findings'])

const worstStatus = (events) =>
  events.some((e) => e.status === 'error') ? 'error'
    : events.some((e) => e.status === 'warning') ? 'warning'
      : events.some((e) => e.status === 'loop') ? 'loop' : events.length ? 'ok' : null

const STATUS_TEXT = { ok: 'Completed', loop: 'Re-run (feedback loop)', warning: 'Completed, warnings', error: 'Failed' }
const humanize = (k) => String(k).replaceAll('_', ' ')

/* ── data model built only from the existing response ─────────────────────── */
function buildModel(result) {
  const h = result?.harness || {}
  const reports = h.agents || {}
  const keys = Object.keys(reports)
  const outputs = result?.agent_outputs || []
  const timeline = h.timeline || []
  const evidence = h.evidence || []

  const agents = outputs.map((o, i) => {
    const key = keys.find((k) => reports[k]?.display_name === o.agent_name) ?? keys[i] ?? `agent_${i}`
    const report = reports[key] || null
    const events = timeline.filter((e) => e.agent === key)
    return {
      key, name: o.agent_name || report?.display_name || key, persona: o.agent_persona, emoji: o.agent_emoji,
      title: o.persona_title, mode: o.execution_mode || 'parallel', description: o.persona_description,
      column: COLUMN_FOR_MODE[o.execution_mode] || 'initial', color: AGENT_COLORS[i % AGENT_COLORS.length],
      report, events, status: worstStatus(events), passes: events.length,
      durationMs: events.reduce((s, e) => s + (e.duration_ms || 0), 0),
      confidence: report?.confidence ?? o.agent_confidence,
      finding: report?.finding ?? o.diagnosis, findingLabel: report?.finding_label,
      evidenceUsed: evidence.filter((e) => e.used_by?.includes(key)).map((e) => e.evidence_id),
    }
  })

  const columns = ['initial', 'verification', 'ambiguity', 'final']
    .map((c) => ({ id: c, agents: agents.filter((a) => a.column === c) }))
    .filter((c) => c.agents.length)

  // consensus: independent agents' labelled findings vs the verified hypothesis
  const initial = agents.filter((a) => a.column === 'initial' && a.findingLabel)
  const verifier = agents.find((a) => a.column === 'verification')
  const verified = verifier?.findingLabel || h.verification?.verified_label || h.predicted_label || null
  const agreeing = verified ? initial.filter((a) => a.findingLabel === verified) : []
  const distinct = [...new Set(initial.map((a) => a.findingLabel))]
  const contradictions = h.verification?.adversarial_review?.what_contradicts_it || []

  // timeline: agent events are logged when the agent finishes; harness stages when they start
  const spans = timeline.map((e) => {
    const end = e.agent ? e.timestamp * 1000 : e.timestamp * 1000 + (e.duration_ms || 0)
    return { ...e, start: end - (e.duration_ms || 0), end }
  })
  const t0 = spans.length ? Math.min(...spans.map((s) => s.start)) : 0
  const t1 = spans.length ? Math.max(...spans.map((s) => s.end)) : 0

  return {
    h, agents, columns, evidence, verified, agreeing, initial, distinct, contradictions,
    spans: spans.map((s) => ({ ...s, rs: s.start - t0, re: s.end - t0 })), totalMs: Math.max(1, t1 - t0),
  }
}

/* ── small building blocks ───────────────────────────────────────────────── */
function ConfidenceRing({ value, size = 64 }) {
  if (value == null) return null
  const r = (size - 8) / 2
  const c = 2 * Math.PI * r
  const v = Math.max(0, Math.min(1, value))
  const color = v >= 0.65 ? '#16A34A' : v >= 0.45 ? '#F59E0B' : '#DC2626'
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`confidence ${pct(v)}`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#E2E8F0" strokeWidth="6" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round"
        strokeDasharray={`${c * v} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} style={{ transition: 'stroke-dasharray .6s ease' }} />
      <text x="50%" y="52%" textAnchor="middle" dominantBaseline="middle" className="fill-ink" style={{ fontSize: size * 0.24, fontWeight: 600 }}>
        {Math.round(v * 100)}%
      </text>
    </svg>
  )
}

function ConfBar({ value, label = 'Confidence' }) {
  if (value == null) return null
  const v = Math.max(0, Math.min(1, value))
  const color = v >= 0.65 ? 'bg-success-600' : v >= 0.45 ? 'bg-warning-500' : 'bg-danger-600'
  return (
    <div>
      <div className="flex justify-between text-[11px] text-muted"><span>{label}</span><span className="tabular-nums text-ink font-medium">{v.toFixed(2)}</span></div>
      <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden mt-0.5"><div className={cx('h-full rounded-full transition-all duration-500', color)} style={{ width: `${v * 100}%` }} /></div>
    </div>
  )
}

/* ── controls ────────────────────────────────────────────────────────────── */
function IconBtn({ label, onClick, children, className, ...rest }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label}
      className={cx('inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted transition-colors',
        'hover:bg-slate-100 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500', className)}
      {...rest}>
      {children}
    </button>
  )
}

function CollapseBtn({ collapsed, onToggle, label, controls }) {
  return (
    <IconBtn label={`${collapsed ? 'Expand' : 'Collapse'} ${label}`} onClick={onToggle} aria-expanded={!collapsed} aria-controls={controls}>
      <ChevronDown size={14} className={cx('transition-transform duration-200', collapsed && '-rotate-90')} />
    </IconBtn>
  )
}

function MaximizeBtn({ label, onClick }) {
  return <IconBtn label={`Maximize ${label}`} onClick={onClick} aria-haspopup="dialog"><Maximize2 size={13} /></IconBtn>
}

function StageNum({ n }) {
  return <span className="w-5 h-5 shrink-0 rounded-full bg-slate-100 text-slate-700 text-[11px] font-semibold flex items-center justify-center tabular-nums" aria-hidden>{n}</span>
}

/** Visual connector between workflow stages (presentation only). */
function Connector() {
  return (
    <div className="flex justify-center py-1" aria-hidden>
      <div className="flex flex-col items-center text-slate-300"><span className="w-px h-2 bg-slate-300" /><ArrowDown size={12} className="-mt-0.5" /></div>
    </div>
  )
}

/** Modal used for the maximised view of a panel. Esc / backdrop / Minimize close it; focus is trapped and restored. */
function Dialog({ title, contentKey, onClose, children }) {
  const titleId = useId()
  const panelRef = useRef(null)
  const closeRef = useRef(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    const previouslyFocused = document.activeElement
    closeRef.current?.focus()
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); onCloseRef.current() }
      if (e.key !== 'Tab' || !panelRef.current) return
      const f = panelRef.current.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
      if (!f.length) return
      const first = f[0], last = f[f.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); previouslyFocused?.focus?.({ preventScroll: true }) }
  }, [])

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/40 p-2 sm:p-6 de-fade"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={panelRef} role="dialog" aria-modal="true" aria-labelledby={titleId}
        className="flex w-full max-w-6xl max-h-full flex-col rounded-xl border border-line bg-white shadow-lift">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
          <div id={titleId} className="min-w-0">{title}</div>
          <button ref={closeRef} type="button" onClick={onClose} className="btn-ghost border border-line px-2.5 py-1.5" aria-label="Minimize panel" title="Minimize (Esc)">
            <Minimize2 size={14} /> <span className="hidden sm:inline">Minimize</span>
          </button>
        </header>
        {/* keyed so switching content (e.g. agent → evidence) starts at the top */}
        <div key={contentKey} className="overflow-y-auto p-4 sm:p-5 de-fade-up">{children}</div>
      </div>
    </div>,
    document.body,
  )
}

/* ── agent cards ─────────────────────────────────────────────────────────── */
function AgentTitle({ agent }) {
  const sub = [agent.title, agent.persona].filter(Boolean).join(' · ')
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="w-7 h-7 shrink-0 rounded-full flex items-center justify-center text-[14px]" style={{ background: `${agent.color}1f`, boxShadow: `inset 0 0 0 1.5px ${agent.color}` }} aria-hidden>{agent.emoji || '•'}</span>
      <div className="min-w-0">
        <div className="text-[13px] font-semibold text-ink leading-tight break-words">{agent.name}</div>
        {sub && <div className="text-[11px] text-muted truncate" title={sub}>{sub}</div>}
      </div>
    </div>
  )
}

function AgentStatusLine({ agent }) {
  if (!agent.status) return null
  return (
    <div className="flex items-center gap-1.5 text-[11px] text-muted min-w-0" title={`${STATUS_TEXT[agent.status]} · ${fmtNum(agent.durationMs, 1)} ms`}>
      <StatusIcon status={agent.status} size={12} />
      <span className="truncate">{STATUS_TEXT[agent.status]}</span>
      {agent.passes > 1 && <span className="ml-auto shrink-0 chip border-secondary-100 bg-secondary-50 text-secondary-700 text-[10px] py-0 whitespace-nowrap">{agent.passes} passes</span>}
    </div>
  )
}

/* ── compact bodies ──────────────────────────────────────────────────────── */
function AgentCompact({ agent, result, model, dense, wide, onEvidence }) {
  const rep = agent.report
  const adv = rep?.extras?.adversarial_review
  const flags = rep?.extras?.flags
  const isFinal = agent.column === 'final'
  const decision = result.review_decision || model.h.review_decision
  const headline = agent.findingLabel || agent.finding

  if (dense) {
    return (
      <div className="space-y-1.5">
        <AgentStatusLine agent={agent} />
        {headline && <div className="text-[12px] font-semibold text-ink truncate" title={headline}>{headline}</div>}
        <ConfBar value={agent.confidence} />
      </div>
    )
  }

  const main = (
    <>
      {!isFinal && agent.finding && <div className={cx('text-[13px] font-semibold text-ink leading-snug', !wide && 'line-clamp-2')}>{agent.finding}</div>}
      {isFinal ? (
        <>
          <p className={cx('text-[12.5px] text-ink leading-relaxed', wide ? 'line-clamp-4' : 'line-clamp-5')}><Cited text={result.final_diagnosis} onEvidence={onEvidence} /></p>
          {result.recommendation && <p className="text-[12px] text-muted leading-snug line-clamp-3 flex gap-1.5"><Wrench size={12} className="mt-0.5 shrink-0 text-primary-600" /><span>{result.recommendation}</span></p>}
          {!wide && decision && <DecisionBadge decision={decision} />}
        </>
      ) : adv ? (
        <ul className={cx('text-[11.5px]', wide ? 'flex flex-wrap gap-x-5 gap-y-1' : 'space-y-1')}>
          <li className="flex gap-1.5 text-ink"><CheckCircle2 size={12} className="text-success-600 mt-0.5 shrink-0" />{adv.what_supports_it?.length ?? 0} supporting item(s)</li>
          <li className="flex gap-1.5 text-ink"><AlertTriangle size={12} className={cx('mt-0.5 shrink-0', adv.what_contradicts_it?.length ? 'text-danger-600' : 'text-slate-300')} />{adv.what_contradicts_it?.length ?? 0} contradicting item(s)</li>
          <li className="flex gap-1.5 text-ink"><HelpCircle size={12} className={cx('mt-0.5 shrink-0', adv.what_is_missing?.length ? 'text-warning-500' : 'text-slate-300')} />{adv.what_is_missing?.length ?? 0} missing-evidence item(s)</li>
          {adv.alternative_explanation && <li className={cx('text-muted line-clamp-2', wide && 'basis-full')}>Alternative: {adv.alternative_explanation}</li>}
        </ul>
      ) : flags ? (
        flags.length ? (
          <ul className="space-y-1 text-[11.5px]">
            {flags.slice(0, 4).map((f, i) => {
              const [code, ...rest] = String(f).split(':')
              return <li key={i} className="flex gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-warning-500 mt-1.5 shrink-0" /><span><b className="font-medium text-ink">{humanize(code).toLowerCase()}</b>{rest.length ? <span className="text-muted">:{rest.join(':')}</span> : null}</span></li>
            })}
            {flags.length > 4 && <li className="text-muted">+{flags.length - 4} more</li>}
          </ul>
        ) : <p className="text-[12px] text-muted">No uncertainty source flagged.</p>
      ) : (
        <>
          {rep?.narrative && <p className="text-[12px] text-muted leading-snug line-clamp-3">{rep.narrative}</p>}
          {rep?.supporting_evidence?.length > 0 && (
            /* clamp the inner paragraph, not the padded box, so clipped lines/chips never peek out */
            <div className="rounded-md bg-slate-50 px-2 py-1.5 text-[11px] text-muted">
              <p className="line-clamp-2 leading-[18px]"><span className="font-medium text-ink">Key factor: </span><Cited text={rep.supporting_evidence[0].statement} onEvidence={onEvidence} /></p>
            </div>
          )}
        </>
      )}
    </>
  )

  const meta = (
    <div className="space-y-1.5">
      {wide && isFinal && decision && <DecisionBadge decision={decision} />}
      <ConfBar value={agent.confidence} />
      {agent.evidenceUsed.length > 0 && <div className="text-[10.5px] text-muted">cites {agent.evidenceUsed.length} evidence record(s)</div>}
    </div>
  )

  if (wide) {
    return (
      <div className="grid gap-x-5 gap-y-2.5 sm:grid-cols-[minmax(0,1fr)_200px]">
        <div className="min-w-0 space-y-2"><AgentStatusLine agent={agent} />{main}</div>
        <div className="sm:border-l sm:border-line sm:pl-4">{meta}</div>
      </div>
    )
  }
  return (
    <div className="flex flex-1 flex-col gap-2">
      <AgentStatusLine agent={agent} />
      {main}
      <div className="mt-auto pt-1">{meta}</div>
    </div>
  )
}

function AgentCard({ agent, result, model, collapsed, onToggleCollapse, onMaximize, onEvidence, highlighted, onHover, stage, wide, uid }) {
  const bodyId = `${uid}-agent-${agent.key}`
  const isFinal = agent.column === 'final'
  const auto = (result.review_decision || model.h.review_decision) === 'AUTO_RESOLVE'
  return (
    <article
      onMouseEnter={() => onHover(true)} onMouseLeave={() => onHover(false)}
      aria-label={stage ? `${stage.n}. ${stage.label}: ${agent.name}` : agent.name}
      className={cx('relative flex min-w-0 flex-col rounded-xl border bg-white transition-[box-shadow,border-color] duration-200',
        highlighted ? 'border-primary-500 ring-2 ring-primary-100' : isFinal ? (auto ? 'border-success-100 shadow-card' : 'border-warning-100 shadow-card') : 'border-line shadow-card',
        isFinal && !highlighted && (auto ? 'bg-gradient-to-r from-success-50/60 to-white' : 'bg-gradient-to-r from-warning-50/60 to-white'))}>
      <span aria-hidden className="absolute left-0 top-3 bottom-3 w-1 rounded-r" style={{ background: agent.color }} />
      <header className="flex items-start gap-2 pl-4 pr-2 pt-2.5">
        {stage && <span className="pt-1"><StageNum n={stage.n} /></span>}
        <div className="min-w-0 flex-1"><AgentTitle agent={agent} /></div>
        {stage && <span className="hidden md:block self-center whitespace-nowrap text-[10.5px] font-semibold uppercase tracking-[0.08em] text-muted">{stage.label}</span>}
        <div className="flex items-center gap-0.5">
          <CollapseBtn collapsed={collapsed} onToggle={onToggleCollapse} label={agent.name} controls={bodyId} />
          <MaximizeBtn label={`${agent.name} details`} onClick={onMaximize} />
        </div>
      </header>
      <div id={bodyId} className="flex flex-1 flex-col pl-4 pr-3 pb-3 pt-2">
        <AgentCompact agent={agent} result={result} model={model} dense={collapsed} wide={wide} onEvidence={onEvidence} />
      </div>
    </article>
  )
}

function InitialGroup({ n, title, subtitle, agents, model, collapsed, onToggle, renderCard, uid }) {
  const bodyId = `${uid}-initial`
  const agreeText = model.verified && model.initial.length
    ? `${model.agreeing.length}/${model.initial.length} agree on ${model.verified}` : null
  return (
    <section className="rounded-xl border border-line bg-slate-50/70 shadow-card" aria-labelledby={`${bodyId}-title`}>
      <header className={cx('flex items-center gap-2 px-3 py-2', !collapsed && 'border-b border-line')}>
        <StageNum n={n} />
        <div className="min-w-0 flex-1">
          <h3 id={`${bodyId}-title`} className="text-[13px] font-semibold text-ink">{title}</h3>
          <p className="text-[11px] text-muted truncate">{subtitle} · {agents.length} agent{agents.length === 1 ? '' : 's'}{agreeText ? ` · ${agreeText}` : ''}</p>
        </div>
        <CollapseBtn collapsed={collapsed} onToggle={onToggle} label={title.toLowerCase()} controls={bodyId} />
      </header>
      <div id={bodyId}>
        {collapsed ? (
          <ul className="divide-y divide-line px-3 py-1">
            {agents.map((a) => (
              <li key={a.key} className="flex items-center gap-2 py-1.5 text-[12px] min-w-0">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ background: a.color }} aria-hidden />
                <span className="font-medium text-ink truncate min-w-0 flex-1" title={a.name}>{a.name}</span>
                {a.status && <StatusIcon status={a.status} size={12} />}
                <span className="truncate max-w-[40%] text-muted" title={a.findingLabel || a.finding}>{a.findingLabel || a.finding}</span>
                <span className="w-9 text-right tabular-nums text-ink font-medium">{a.confidence == null ? '—' : a.confidence.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="grid gap-3 p-3 grid-cols-[repeat(auto-fit,minmax(196px,1fr))]">
            {agents.map(renderCard)}
          </div>
        )}
      </div>
    </section>
  )
}

/* ── sidebar ─────────────────────────────────────────────────────────────── */
function SidebarSection({ id, title, icon: Icon, collapsed, onToggle, actions, highlighted, children }) {
  return (
    <section className={cx('rounded-xl border bg-white transition-[box-shadow,border-color] duration-200',
      highlighted ? 'border-primary-500 ring-2 ring-primary-100' : 'border-line shadow-card')} aria-labelledby={`${id}-title`}>
      <header className="flex items-center gap-1.5 pl-3 pr-2 py-2">
        <Icon size={13} className="text-primary-600 shrink-0" aria-hidden />
        <h3 id={`${id}-title`} className="flex-1 min-w-0 truncate text-[12.5px] font-semibold text-ink">{title}</h3>
        {actions}
        <CollapseBtn collapsed={collapsed} onToggle={onToggle} label={title.toLowerCase()} controls={id} />
      </header>
      <div id={id} hidden={collapsed} className="px-3 pb-3">{children}</div>
    </section>
  )
}

function SummaryRow({ icon: Icon, label, value, hint, tone }) {
  return (
    <div className="flex items-start gap-2 py-1.5">
      <Icon size={13} className="mt-0.5 shrink-0 text-muted" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="text-[11.5px] text-muted leading-tight">{label}</div>
        {hint && <div className="text-[10.5px] text-muted leading-tight truncate mt-0.5" title={hint}>{hint}</div>}
      </div>
      <div className={cx('max-w-[55%] text-right text-[12.5px] font-semibold leading-tight break-words', tone || 'text-ink')}>{value}</div>
    </div>
  )
}

const TOP_EVIDENCE = 6

function EvidenceCompact({ model, hoverAgent, setHoverEv, showAll, setShowAll, onEvidence, listId }) {
  const used = hoverAgent ? new Set(model.agents.find((a) => a.key === hoverAgent)?.evidenceUsed || []) : null
  const comp = model.h.evidence_composition || {}
  const targeted = model.evidence.filter((e) => e.retrieval_round > 0).length
  const list = showAll ? model.evidence : model.evidence.slice(0, TOP_EVIDENCE)
  return (
    <div className="space-y-3">
      {/* reported readings now live in the Sensor health overview chart (DiagnosticCharts) */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="eyebrow text-[10px]">{showAll ? 'All evidence' : 'Top evidence'}</span>
          {model.evidence.length > TOP_EVIDENCE && (
            <button type="button" onClick={() => setShowAll(!showAll)} aria-expanded={showAll} aria-controls={listId}
              className="rounded text-[11px] font-medium text-primary-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500">
              {showAll ? 'Show less' : `Show all ${model.evidence.length}`}
            </button>
          )}
        </div>
        {!model.evidence.length ? <Empty>No evidence retrieved.</Empty> : (
          <ul id={listId} className={cx('space-y-0.5', showAll && 'max-h-64 overflow-y-auto pr-1')}>
            {list.map((e) => (
              <li key={e.evidence_id}>
                <button type="button" onClick={() => onEvidence(e.evidence_id)}
                  onMouseEnter={() => setHoverEv(e.evidence_id)} onMouseLeave={() => setHoverEv(null)}
                  onFocus={() => setHoverEv(e.evidence_id)} onBlur={() => setHoverEv(null)}
                  title={`Inspect ${e.evidence_id}`}
                  className={cx('flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
                    used?.has(e.evidence_id) ? 'bg-primary-50 ring-1 ring-primary-200' : used ? 'opacity-50' : 'hover:bg-slate-50')}>
                  <span className="mono shrink-0 text-primary-700">{e.evidence_id}</span>
                  <span className="shrink-0"><SourceBadge source={e.source_type} size="xs" /></span>
                  <span className="min-w-0 flex-1 truncate text-ink" title={e.label}>{e.label || 'unlabelled'}</span>
                  <span className="shrink-0 tabular-nums text-muted">{fmtNum(e.retrieval_score, 2)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="text-[10.5px] text-muted">{model.evidence.length} record(s) · REAL {comp.real ?? 0} · SYNTHETIC {comp.synthetic ?? 0}{targeted ? ` · ${targeted} from targeted re-RAG` : ''}</div>
    </div>
  )
}

/* ── timeline ────────────────────────────────────────────────────────────── */
function Timeline({ model, compact, selected, onSelect }) {
  const lanes = [
    ...model.agents.filter((a) => a.events.length).map((a) => ({ id: a.key, label: a.name, color: a.color })),
    { id: null, label: 'Harness stages', color: NEUTRAL },
  ]
  if (!model.spans.length) return <Empty>No execution events recorded.</Empty>
  const ticks = [0, 0.25, 0.5, 0.75, 1]
  return (
    <div className={cx('grid items-center', compact ? 'grid-cols-[minmax(72px,128px)_1fr] gap-x-2 gap-y-[3px]' : 'grid-cols-[minmax(96px,180px)_1fr] gap-x-3 gap-y-1.5')}>
      {lanes.map((lane) => (
        <Lane key={lane.id ?? 'harness'} lane={lane} spans={model.spans.filter((s) => (s.agent ?? null) === lane.id)}
          total={model.totalMs} selected={selected} onSelect={onSelect} compact={compact} />
      ))}
      <div />
      <div className={cx('relative text-muted', compact ? 'h-3 text-[9.5px] leading-3' : 'h-4 text-[10px]')}>
        {/* first/last labels are anchored inside the track so they never overflow or wrap */}
        {ticks.map((t) => (
          <span key={t} className={cx('absolute whitespace-nowrap tabular-nums', t === 0 ? '' : t === 1 ? '-translate-x-full' : '-translate-x-1/2')} style={{ left: `${t * 100}%` }}>
            {fmtNum(model.totalMs * t, 0)} ms
          </span>
        ))}
      </div>
    </div>
  )
}

function Lane({ lane, spans, total, selected, onSelect, compact }) {
  return (
    <>
      <div className={cx('flex min-w-0 items-center gap-1.5 text-ink', compact ? 'text-[10px] leading-3' : 'text-[11px]')} title={lane.label}>
        <span className={cx('rounded-full shrink-0', compact ? 'w-1.5 h-1.5' : 'w-2 h-2')} style={{ background: lane.color }} /><span className="truncate">{lane.label}</span>
      </div>
      <div className={cx('relative rounded-sm bg-slate-50 border border-line/70', compact ? 'h-2.5' : 'h-5')}>
        {spans.map((s) => {
          const left = (s.rs / total) * 100
          const width = Math.max(((s.re - s.rs) / total) * 100, 0.8)
          const isSel = selected === s.step
          return (
            <button key={s.step} type="button" onClick={() => onSelect(isSel ? null : s.step)} aria-pressed={isSel}
              title={`#${s.step} ${s.stage} · ${s.action}\n${fmtNum(s.duration_ms, 1)} ms · ${s.status}${s.reason ? `\n${s.reason}` : ''}`}
              className={cx('absolute rounded-sm transition-[box-shadow,transform] hover:scale-y-125 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
                compact ? 'top-0 bottom-0' : 'top-0.5 bottom-0.5', isSel && 'ring-2 ring-offset-1 ring-ink')}
              style={{ left: `${Math.min(left, 99.2)}%`, width: `${width}%`, minWidth: compact ? 5 : 6, background: s.status === 'error' ? '#DC2626' : lane.color, opacity: s.status === 'loop' ? 0.75 : 1,
                backgroundImage: s.status === 'loop' ? 'repeating-linear-gradient(135deg, rgba(255,255,255,.55) 0 2px, transparent 2px 5px)' : undefined }}
              aria-label={`Step ${s.step}: ${s.stage} ${s.action}`} />
          )
        })}
      </div>
    </>
  )
}

function SelectedStep({ model, step, onEvidence }) {
  const s = model.spans.find((x) => x.step === step)
  if (!s) return null
  return (
    <div className="rounded-lg border border-line bg-slate-50 px-2 py-1.5 text-[11.5px]" aria-live="polite">
      <span className="mono text-muted">#{s.step}</span> <b className="text-ink">{s.stage}</b> · {s.action} · {fmtNum(s.duration_ms, 1)} ms
      {s.reason && <div className="text-muted mt-0.5">{s.reason}</div>}
      {s.evidence_used?.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{s.evidence_used.map((id) => <IdChip key={id} id={id} onClick={onEvidence} />)}</div>}
    </div>
  )
}

const RECENT_EVENTS = 2

function TimelinePanel({ model, latency, collapsed, onToggle, onMaximize, selected, onSelect, showAll, setShowAll, onEvidence, uid }) {
  const bodyId = `${uid}-timeline`
  const events = model.spans
  const visible = showAll ? events : events.slice(-RECENT_EVENTS)
  const nameOf = Object.fromEntries(model.agents.map((a) => [a.key, a]))
  return (
    <section className="rounded-xl border border-line bg-white shadow-card" aria-labelledby={`${bodyId}-title`}>
      <header className="flex items-center gap-2 pl-3 pr-2 py-1">
        <Clock size={13} className="shrink-0 text-primary-600" aria-hidden />
        <h3 id={`${bodyId}-title`} className="whitespace-nowrap text-[12.5px] font-semibold text-ink">Agent interaction timeline</h3>
        <span className="min-w-0 truncate text-[11px] text-muted">{events.length} events · {fmtNum(latency, 0)} ms end-to-end</span>
        <div className="ml-auto flex items-center gap-0.5">
          <CollapseBtn collapsed={collapsed} onToggle={onToggle} label="agent interaction timeline" controls={bodyId} />
          <MaximizeBtn label="agent interaction timeline" onClick={onMaximize} />
        </div>
      </header>
      <div id={bodyId} hidden={collapsed} className="space-y-1.5 px-3 pb-2">
        <Timeline model={model} compact selected={selected} onSelect={onSelect} />
        {selected != null && <SelectedStep model={model} step={selected} onEvidence={onEvidence} />}
        {events.length > 0 && (
          <div>
            <div className="flex items-center justify-between">
              <span className="eyebrow text-[10px]">{showAll ? `All ${events.length} events` : 'Latest events'}</span>
              {events.length > RECENT_EVENTS && (
                <button type="button" onClick={() => setShowAll(!showAll)} aria-expanded={showAll} aria-controls={`${bodyId}-events`}
                  className="rounded text-[11px] font-medium text-primary-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500">
                  {showAll ? 'Show less' : `Show all ${events.length}`}
                </button>
              )}
            </div>
            <ol id={`${bodyId}-events`} className={cx('mt-0.5 divide-y divide-line/70', showAll && 'max-h-48 overflow-y-auto pr-1')}>
              {visible.map((s) => {
                const a = s.agent ? nameOf[s.agent] : null
                const isSel = selected === s.step
                return (
                  <li key={s.step}>
                    <button type="button" onClick={() => onSelect(isSel ? null : s.step)} aria-pressed={isSel}
                      className={cx('grid w-full items-center gap-2 rounded px-1 py-0.5 text-left text-[11px] leading-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
                        'grid-cols-[28px_minmax(0,1fr)_auto] sm:grid-cols-[28px_minmax(0,150px)_minmax(0,1fr)_56px_auto]', isSel ? 'bg-primary-50' : 'hover:bg-slate-50')}>
                      <span className="mono text-[10.5px] text-muted">#{s.step}</span>
                      <span className="hidden sm:flex min-w-0 items-center gap-1.5 text-ink">
                        <span className="w-1.5 h-1.5 shrink-0 rounded-full" style={{ background: a?.color || NEUTRAL }} />
                        <span className="truncate">{a?.name || 'Harness'}</span>
                      </span>
                      <span className="truncate text-muted" title={`${s.stage} · ${s.action}`}><span className="sm:hidden text-ink">{a?.name || 'Harness'} · </span>{s.stage} · {s.action}</span>
                      <span className="hidden sm:block text-right tabular-nums text-[10.5px] text-muted" title="start offset">+{fmtNum(s.rs, 1)} ms</span>
                      <span className="flex items-center justify-end gap-1 whitespace-nowrap tabular-nums text-muted"><StatusIcon status={s.status} size={11} />{fmtNum(s.duration_ms, 1)} ms</span>
                    </button>
                  </li>
                )
              })}
            </ol>
          </div>
        )}
      </div>
    </section>
  )
}

/* ── expanded detail views ───────────────────────────────────────────────── */
/* ── expanded detail views ───────────────────────────────────────────────── */
function ExtrasView({ extras }) {
  const entries = Object.entries(extras || {}).filter(([k, v]) => !HIDDEN_EXTRAS.has(k) && v != null && !(Array.isArray(v) && !v.length))
  if (!entries.length) return null
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {entries.map(([k, v]) => {
        let body = null
        if (typeof v !== 'object') body = <span className="text-ink font-medium">{typeof v === 'number' ? fmtNum(v, 3) : String(v)}</span>
        else if (Array.isArray(v) && v.every((x) => typeof x !== 'object')) body = <div className="flex flex-wrap gap-1">{v.map((x, i) => /^(EV|D)-\d+$/.test(String(x)) ? <IdChip key={i} id={String(x)} /> : <span key={i} className="chip border-line bg-slate-50 text-slate-700">{String(x)}</span>)}</div>
        else if (!Array.isArray(v) && Object.values(v).every((x) => typeof x === 'number')) {
          const max = Math.max(...Object.values(v), 1e-9)
          body = <div className="space-y-1">{Object.entries(v).sort((a, b) => b[1] - a[1]).map(([lk, lv]) => (
            <div key={lk} className="flex items-center gap-2 text-[11px]"><span className="w-36 truncate text-ink" title={lk}>{lk}</span>
              <div className="flex-1 h-1.5 bg-slate-100 rounded-r"><div className="h-full rounded-r bg-primary-600" style={{ width: `${(lv / max) * 100}%` }} /></div>
              <span className="w-12 text-right tabular-nums text-muted">{fmtNum(lv, 3)}</span></div>))}</div>
        } else if (!Array.isArray(v) && Object.values(v).every((x) => typeof x !== 'object')) {
          body = <div className="flex flex-wrap gap-1">{Object.entries(v).map(([a, b]) => <span key={a} className="chip border-line bg-slate-50 text-slate-700">{a}: {String(b)}</span>)}</div>
        } else if (Array.isArray(v)) body = <span className="text-muted">{v.length} item(s)</span>
        if (!body) return null
        return <div key={k} className="rounded-lg border border-line p-2.5"><div className="eyebrow mb-1">{humanize(k)}</div><div className="text-[12px]">{body}</div></div>
      })}
    </div>
  )
}

function StatementList({ items, tone, onEvidence }) {
  if (!items?.length) return null
  const mark = { support: ['+', 'text-success-600'], contra: ['−', 'text-danger-600'], missing: ['?', 'text-warning-700'] }[tone]
  return (
    <ul className="space-y-1 text-[12px]">
      {items.map((s, i) => <li key={i} className="flex gap-1.5"><span className={cx('font-semibold', mark[1])}>{mark[0]}</span><Cited text={typeof s === 'string' ? s : s.statement} onEvidence={onEvidence} /></li>)}
    </ul>
  )
}

function AgentDetail({ agent, model, result, onEvidence }) {
  const rep = agent.report
  const h = model.h
  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-[1fr_220px]">
        <div className="space-y-2">
          {agent.description && <p className="text-[12px] text-muted">{agent.description}</p>}
          <div className="text-[15px] font-semibold text-ink"><Cited text={agent.column === 'final' ? result.final_diagnosis : agent.finding} onEvidence={onEvidence} /></div>
          {rep?.narrative && rep.narrative !== agent.finding && <p className="text-[13px] text-muted leading-relaxed"><Cited text={rep.narrative} onEvidence={onEvidence} /></p>}
          {agent.column === 'final' && result.recommendation && <p className="text-[13px] text-ink flex gap-2"><Wrench size={15} className="text-primary-600 mt-0.5 shrink-0" />{result.recommendation}</p>}
        </div>
        <div className="space-y-2 rounded-lg border border-line p-3">
          <ConfBar value={agent.confidence} />
          <div className="text-[11px] text-muted space-y-0.5">
            <div>Mode: <b className="text-ink font-medium">{agent.mode}</b></div>
            {rep?.mode && <div>Reasoning: <b className="text-ink font-medium">{rep.mode}</b></div>}
            <div>Passes: <b className="text-ink font-medium">{agent.passes}</b> · {fmtNum(agent.durationMs, 1)} ms</div>
            {rep?.claims_removed > 0 && <div className="text-warning-700">{rep.claims_removed} unsupported claim(s) removed</div>}
          </div>
          {agent.column === 'final' && (result.review_decision || h.review_decision) && <DecisionBadge decision={result.review_decision || h.review_decision} />}
        </div>
      </div>

      {(rep?.supporting_evidence?.length || rep?.contradicting_evidence?.length || rep?.missing_information?.length) ? (
        <div className="grid gap-4 md:grid-cols-3">
          <div><div className="eyebrow mb-1.5">Supporting</div>{rep.supporting_evidence?.length ? <StatementList items={rep.supporting_evidence} tone="support" onEvidence={onEvidence} /> : <Empty>none</Empty>}</div>
          <div><div className="eyebrow mb-1.5">Contradicting</div>{rep.contradicting_evidence?.length ? <StatementList items={rep.contradicting_evidence} tone="contra" onEvidence={onEvidence} /> : <Empty>none</Empty>}</div>
          <div><div className="eyebrow mb-1.5">Missing information</div>{rep.missing_information?.length ? <StatementList items={rep.missing_information} tone="missing" /> : <Empty>none</Empty>}</div>
        </div>
      ) : null}

      {rep?.extras?.adversarial_review && <div className="border-t border-line pt-4"><HypothesisPanel harness={h} onEvidence={onEvidence} /></div>}
      {agent.column === 'ambiguity' && h.confidence && <div className="border-t border-line pt-4"><ConfidencePanel harness={h} /></div>}
      {agent.column === 'final' && (
        <div className="border-t border-line pt-4 grid gap-4 lg:grid-cols-2">
          {h.review?.criteria?.length > 0 && (
            <div>
              <div className="eyebrow mb-1.5">Review gate criteria</div>
              <ul className="space-y-1 text-[12px]">{h.review.criteria.map((g) => (
                <li key={g.criterion_id} className="flex gap-1.5"><StatusIcon status={g.passed ? 'ok' : 'error'} size={13} /><span><span className="mono text-muted">{g.criterion_id}</span> {g.description} <span className="text-muted">— {g.observed}</span></span></li>))}</ul>
            </div>
          )}
          {result.reasoning?.length > 0 && (
            <div><div className="eyebrow mb-1.5">Reasoning trace</div>
              <ol className="space-y-1 text-[12px] text-ink">{result.reasoning.map((r, i) => <li key={i}><Cited text={r} onEvidence={onEvidence} /></li>)}</ol></div>
          )}
        </div>
      )}

      {rep?.hypotheses?.length > 0 && !rep?.extras?.adversarial_review && (
        <div className="border-t border-line pt-4">
          <div className="eyebrow mb-1.5">Hypotheses considered</div>
          <div className="space-y-1">{rep.hypotheses.map((hy) => (
            <div key={hy.label} className="flex items-center gap-2 text-[12px]"><span className="w-44 truncate text-ink" title={hy.label}>{hy.label}</span>
              <div className="flex-1 h-1.5 bg-slate-100 rounded-r"><div className="h-full rounded-r" style={{ width: `${Math.min(1, hy.score) * 100}%`, background: agent.color }} /></div>
              <span className="w-12 text-right tabular-nums text-muted">{fmtNum(hy.score, 3)}</span>
              <span className="w-28 text-[11px] text-muted text-right">{hy.supporting.length}+ / {hy.contradicting.length}− / {hy.missing.length}?</span></div>))}</div>
        </div>
      )}

      <div className="border-t border-line pt-4"><ExtrasView extras={rep?.extras} /></div>

      {agent.evidenceUsed.length > 0 && (
        <div><div className="eyebrow mb-1.5">Evidence cited by this agent</div>
          <div className="flex flex-wrap gap-1">{agent.evidenceUsed.map((id) => <IdChip key={id} id={id} onClick={onEvidence} />)}</div></div>
      )}
      {agent.events.length > 0 && (
        <div><div className="eyebrow mb-1.5">Execution events</div>
          <ul className="space-y-1 text-[12px]">{agent.events.map((e) => (
            <li key={e.step} className="flex gap-2"><StatusIcon status={e.status} size={13} /><span className="mono text-muted">#{e.step}</span><span className="text-ink">{e.stage}</span><span className="text-muted truncate">{e.action}</span><span className="ml-auto tabular-nums text-muted">{fmtNum(e.duration_ms, 1)} ms</span></li>))}</ul></div>
      )}
    </div>
  )
}

/* ── main component ──────────────────────────────────────────────────────── */
const isDesktop = () => typeof window === 'undefined' || !window.matchMedia || window.matchMedia('(min-width: 1280px)').matches

export default function DecisionExplorer({ result, question }) {
  const model = useMemo(() => buildModel(result), [result])
  const uid = useId().replace(/:/g, '')
  // `dialog` is the maximised panel (was the inline focus area): 'evidence' | 'timeline' | 'agent:<key>' | null
  const [dialog, setDialog] = useState(null)
  // collapse state lives here (not inside the cards) so it survives the parent group collapsing/expanding
  const [collapsed, setCollapsed] = useState({})
  const [sidebarOpen, setSidebarOpen] = useState(isDesktop)
  const [showAllEvidence, setShowAllEvidence] = useState(false)
  const [showAllEvents, setShowAllEvents] = useState(false)
  const [hoverAgent, setHoverAgent] = useState(null)
  const [hoverEv, setHoverEv] = useState(null)
  const [focusEv, setFocusEv] = useState(null)
  const [selectedStep, setSelectedStep] = useState(null)
  const h = model.h

  const isCollapsed = (id) => !!collapsed[id]
  const toggleCollapsed = (id) => setCollapsed((c) => ({ ...c, [id]: !c[id] }))
  const openDialog = (id) => { if (id === 'evidence') setFocusEv(null); setDialog(id) }
  const openEvidence = (evId) => { setFocusEv(evId); setDialog('evidence') }
  const closeDialog = () => setDialog(null)

  if (!result?.harness) return <Empty>This response has no multi-agent state to visualise.</Empty>

  const decision = result.review_decision || h.review_decision
  const auto = decision === 'AUTO_RESOLVE'
  const comp = h.evidence_composition || {}
  const cv = h.claim_validation || {}
  const ambiguityAgent = model.agents.find((a) => a.column === 'ambiguity')
  const ambLevel = ambiguityAgent?.report?.extras?.ambiguity_level
  const conflictCount = model.contradictions.length + (model.distinct.length > 1 ? model.distinct.length - 1 : 0)
  const dialogAgent = dialog?.startsWith('agent:') ? model.agents.find((a) => `agent:${a.key}` === dialog) : null
  const usedByHover = hoverEv ? new Set(model.evidence.find((e) => e.evidence_id === hoverEv)?.used_by || []) : null
  const finished = model.spans.some((s) => s.stage === 'review_gate')
  const sidebarId = `${uid}-sidebar`

  const renderAgent = (a, extra = {}) => (
    <AgentCard key={a.key} agent={a} result={result} model={model} uid={uid}
      collapsed={isCollapsed(`agent:${a.key}`)} onToggleCollapse={() => toggleCollapsed(`agent:${a.key}`)}
      onMaximize={() => openDialog(`agent:${a.key}`)} onEvidence={openEvidence}
      highlighted={usedByHover?.has(a.key) || hoverAgent === a.key}
      onHover={(on) => setHoverAgent(on ? a.key : null)} {...extra} />
  )

  return (
    <div className="space-y-3">
      {/* Header: question + global status */}
      <section className="card p-3 sm:p-4">
        <div className="flex flex-wrap items-start gap-3">
          <div className="flex-1 min-w-[240px]">
            <div className="flex flex-wrap items-center gap-2">
              <span className="eyebrow text-primary-700">Multi-agent decision explorer</span>
              {finished && <span className="chip border-success-100 bg-success-50 text-success-700"><CheckCircle2 size={12} />Analysis complete</span>}
              {decision && <DecisionBadge decision={decision} />}
              {h.data_mode && <SourceBadge source={h.data_mode} />}
            </div>
            <div className="mt-2 flex gap-2 rounded-lg bg-primary-50/60 border border-primary-100 px-3 py-2">
              <MessageSquareText size={16} className="text-primary-600 mt-0.5 shrink-0" aria-hidden />
              <div className="min-w-0"><div className="text-[11px] text-muted">User question</div><p className="text-[13.5px] font-medium text-ink leading-snug break-words">{question || h.query_profile?.raw_query}</p></div>
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="flex items-center gap-3">
              <ConfidenceRing value={result.confidence} size={56} />
              <div><div className="eyebrow">Overall confidence</div><div className="text-[12px] text-muted max-w-[160px]">{h.confidence?.factors?.length ? `${h.confidence.factors.length} measured factors` : ''}</div></div>
            </div>
            <button type="button" onClick={() => setSidebarOpen((o) => !o)} aria-expanded={sidebarOpen} aria-controls={sidebarId}
              className="btn-ghost border border-line px-2 py-1 text-[12px]">
              {sidebarOpen ? <PanelLeftClose size={14} /> : <PanelLeftOpen size={14} />}
              {sidebarOpen ? 'Hide summary & evidence' : 'Show summary & evidence'}
            </button>
          </div>
        </div>
        {!auto && h.review?.reasons?.length > 0 && (
          <div className="mt-3 flex gap-2 rounded-lg bg-warning-50 border border-warning-100 px-3 py-2 text-[12px] text-warning-700">
            <ShieldAlert size={14} className="mt-0.5 shrink-0" /><span><b>Human review required:</b> {h.review.reasons.join(' · ')}</span>
          </div>
        )}
      </section>

      <div className={cx('grid items-start gap-4', sidebarOpen && 'xl:grid-cols-[288px_minmax(0,1fr)] 2xl:grid-cols-[320px_minmax(0,1fr)]')}>
        {/* LEFT: workflow summary + retrieved evidence (kept mounted when hidden so nothing is lost) */}
        {/* below xl the column stacks above the workflow, so its sections pair up two-across instead of forming a tall strip */}
        <aside id={sidebarId} hidden={!sidebarOpen}
          className={cx('min-w-0', sidebarOpen ? 'grid content-start items-start gap-3 md:grid-cols-2 xl:grid-cols-1' : 'hidden')}
          aria-label="Workflow summary, retrieved evidence and diagnostic charts">
          <SidebarSection id={`${uid}-summary`} title="Workflow summary" icon={ListChecks}
            collapsed={isCollapsed('sidebar:summary')} onToggle={() => toggleCollapsed('sidebar:summary')}>
            <div className="divide-y divide-line">
              {model.verified && <SummaryRow icon={FileCheck2} label="Verified hypothesis" value={model.verified} hint={h.predicted_label && h.predicted_label !== model.verified ? `final: ${h.predicted_label}` : undefined} />}
              {model.initial.length > 0 && model.verified && (
                <SummaryRow icon={GitMerge} label="Agent consensus" value={`${model.agreeing.length}/${model.initial.length} agree`}
                  tone={model.agreeing.length === model.initial.length ? 'text-success-700' : 'text-warning-700'}
                  hint={h.verification?.agreement_without_evidence ? 'agreement without strong evidence' : model.distinct.length > 1 ? `${model.distinct.length} distinct findings` : 'independent agents agree'} />
              )}
              <SummaryRow icon={AlertTriangle} label="Conflicts" value={conflictCount} tone={conflictCount ? 'text-danger-700' : 'text-ink'} hint={`${model.contradictions.length} contradicting signal(s)`} />
              <SummaryRow icon={Database} label="Evidence" value={`${model.evidence.length} records`} hint={`REAL ${comp.real ?? 0} · SYNTHETIC ${comp.synthetic ?? 0}`} />
              {ambLevel && <SummaryRow icon={HelpCircle} label="Ambiguity" value={ambLevel} tone={ambLevel === 'LOW' ? 'text-success-700' : ambLevel === 'HIGH' ? 'text-danger-700' : 'text-warning-700'} hint={`${ambiguityAgent.report.extras.flags?.length ?? 0} flag(s)`} />}
              <SummaryRow icon={RotateCcw} label="Feedback loop" value={`${h.feedback_rounds ?? 0} round(s)`} hint={`${cv.total_claims ?? 0} claims checked · ${cv.removed ?? 0} removed`} />
            </div>
          </SidebarSection>

          <SidebarSection id={`${uid}-sensors`} title="Sensor health overview" icon={Gauge}
            collapsed={isCollapsed('sidebar:sensors')} onToggle={() => toggleCollapsed('sidebar:sensors')}>
            <SensorHealthChart harness={h} />
          </SidebarSection>

          <SidebarSection id={`${uid}-evidence`} title="Retrieved evidence bundle" icon={Database}
            collapsed={isCollapsed('sidebar:evidence')} onToggle={() => toggleCollapsed('sidebar:evidence')}
            highlighted={!!(hoverAgent && model.agents.find((a) => a.key === hoverAgent)?.evidenceUsed.length)}
            actions={<MaximizeBtn label="retrieved evidence" onClick={() => openDialog('evidence')} />}>
            <EvidenceCompact model={model} hoverAgent={hoverAgent} setHoverEv={setHoverEv} onEvidence={openEvidence}
              showAll={showAllEvidence} setShowAll={setShowAllEvidence} listId={`${uid}-evlist`} />
          </SidebarSection>

          <SidebarSection id={`${uid}-hyps`} title="Fault hypothesis comparison" icon={BarChart3}
            collapsed={isCollapsed('sidebar:hyps')} onToggle={() => toggleCollapsed('sidebar:hyps')}>
            <HypothesisComparisonChart harness={h} decision={decision} />
          </SidebarSection>
        </aside>

        {/* RIGHT: workflow stages, top to bottom */}
        <div className="min-w-0">
          {model.columns.map((col, ci) => {
            const n = ci + 1
            const [title, subtitle] = COLUMN_TITLES[col.id]
            return (
              <div key={col.id}>
                {ci > 0 && <Connector />}
                {col.id === 'initial' ? (
                  <InitialGroup n={n} title={title} subtitle={subtitle} agents={col.agents} model={model} uid={uid}
                    collapsed={isCollapsed('group:initial')} onToggle={() => toggleCollapsed('group:initial')}
                    renderCard={(a) => renderAgent(a)} />
                ) : (
                  <div className="space-y-2">{col.agents.map((a) => renderAgent(a, { wide: true, stage: { n, label: title } }))}</div>
                )}
              </div>
            )
          })}

          <div className="pt-4">
            <TimelinePanel model={model} latency={h.latency_ms ?? model.totalMs} uid={uid}
              collapsed={isCollapsed('timeline')} onToggle={() => toggleCollapsed('timeline')} onMaximize={() => openDialog('timeline')}
              selected={selectedStep} onSelect={setSelectedStep} showAll={showAllEvents} setShowAll={setShowAllEvents} onEvidence={openEvidence} />
          </div>
        </div>
      </div>

      {dialog && (
        <Dialog contentKey={dialog} onClose={closeDialog}
          title={dialogAgent ? <AgentTitle agent={dialogAgent} /> : (
            <div className="text-[14px] font-semibold text-ink">{dialog === 'evidence' ? 'Retrieved evidence' : 'Agent execution & interaction timeline'}</div>
          )}>
          {dialog === 'evidence' && (
            <div className="space-y-6">
              {(h.sensor_view || []).length > 0 && <SensorPanel harness={h} />}
              <EvidenceExplorer harness={h} focusId={focusEv} />
            </div>
          )}
          {dialogAgent && <AgentDetail agent={dialogAgent} model={model} result={result} onEvidence={openEvidence} />}
          {dialog === 'timeline' && (
            <div className="space-y-6">
              <Timeline model={model} selected={selectedStep} onSelect={setSelectedStep} />
              {selectedStep != null && <SelectedStep model={model} step={selectedStep} onEvidence={openEvidence} />}
              <OrchestrationFlow harness={h} />
              <AuditPanel harness={h} />
            </div>
          )}
        </Dialog>
      )}
    </div>
  )
}
