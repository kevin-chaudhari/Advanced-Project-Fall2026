import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Maximize2, Minimize2, MessageSquareText, CheckCircle2, ShieldAlert, AlertTriangle, GitMerge,
  Database, ChevronRight, Clock, Layers, FileCheck2, RotateCcw, Wrench, HelpCircle,
} from 'lucide-react'
import useFlip from '../hooks/useFlip'
import { cx, pct, fmtNum, SourceBadge, DecisionBadge, StatusIcon, Cited, IdChip, Empty } from './ui'
import EvidenceExplorer from './EvidenceExplorer'
import OrchestrationFlow from './OrchestrationFlow'
import { HypothesisPanel, ConfidencePanel, SensorPanel, AuditPanel } from './ReportPanels'

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

function Metric({ icon: Icon, label, value, hint, tone }) {
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2 min-w-0">
      <div className="flex items-center gap-1.5 text-[11px] text-muted"><Icon size={12} />{label}</div>
      <div className={cx('text-[14px] font-semibold truncate mt-0.5', tone || 'text-ink')} title={typeof value === 'string' ? value : undefined}>{value}</div>
      {hint && <div className="text-[10.5px] text-muted truncate" title={hint}>{hint}</div>}
    </div>
  )
}

/** A clickable dashboard panel that can maximise into the focus area. */
function Panel({ id, flip, expanded, onToggle, title, subtitle, accent, children, className, highlighted, onHover }) {
  const isOpen = expanded === id
  return (
    <section
      ref={isOpen ? undefined : flip.register(id)}
      onMouseEnter={onHover ? () => onHover(true) : undefined}
      onMouseLeave={onHover ? () => onHover(false) : undefined}
      onClick={() => onToggle(id)}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(id) } }}
      role="button" tabIndex={0} aria-expanded={isOpen}
      className={cx('group relative rounded-xl border bg-white text-left cursor-pointer transition-[box-shadow,border-color,opacity] duration-200',
        'hover:shadow-lift focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
        isOpen ? 'border-primary-500 ring-2 ring-primary-100 opacity-60' : highlighted ? 'border-primary-500 ring-2 ring-primary-100' : 'border-line shadow-card',
        className)}
    >
      {accent && <span aria-hidden className="absolute left-0 top-3 bottom-3 w-1 rounded-r" style={{ background: accent }} />}
      <header className="flex items-start justify-between gap-2 px-4 pt-3">
        <div className="min-w-0">{title}{subtitle && <div className="text-[11px] text-muted mt-0.5">{subtitle}</div>}</div>
        <span className="shrink-0 text-muted opacity-60 group-hover:opacity-100 transition-opacity" title={isOpen ? 'Shown above' : 'Expand'}>
          {isOpen ? <Layers size={14} /> : <Maximize2 size={14} />}
        </span>
      </header>
      <div className="px-4 pb-3 pt-2">{children}</div>
      {isOpen && <div className="absolute inset-0 rounded-xl flex items-center justify-center text-[12px] font-medium text-primary-700 bg-white/40">Expanded above</div>}
    </section>
  )
}

function AgentTitle({ agent }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="w-7 h-7 shrink-0 rounded-full flex items-center justify-center text-[14px]" style={{ background: `${agent.color}1f`, boxShadow: `inset 0 0 0 1.5px ${agent.color}` }} aria-hidden>{agent.emoji || '•'}</span>
      <div className="min-w-0">
        <div className="text-[13px] font-semibold text-ink truncate">{agent.name}</div>
        <div className="text-[11px] text-muted truncate">{[agent.title, agent.persona].filter(Boolean).join(' · ')}</div>
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
function AgentCompact({ agent, result, model, dense }) {
  const rep = agent.report
  const adv = rep?.extras?.adversarial_review
  const flags = rep?.extras?.flags
  if (dense) {
    return (
      <div className="space-y-1.5">
        <AgentStatusLine agent={agent} />
        <div className="text-[12px] font-semibold text-ink truncate" title={agent.findingLabel || agent.finding}>{agent.findingLabel || agent.finding}</div>
        <ConfBar value={agent.confidence} />
      </div>
    )
  }
  return (
    <div className="space-y-2">
      <AgentStatusLine agent={agent} />
      {agent.column !== 'final' && agent.finding && <div className="text-[13px] font-semibold text-ink leading-snug line-clamp-2">{agent.finding}</div>}

      {agent.column === 'final' ? (
        <>
          <p className="text-[12.5px] text-ink leading-snug line-clamp-5"><Cited text={result.final_diagnosis} /></p>
          {result.recommendation && <p className="text-[12px] text-muted leading-snug line-clamp-3 flex gap-1.5"><Wrench size={12} className="mt-0.5 shrink-0 text-primary-600" />{result.recommendation}</p>}
          {(result.review_decision || model.h.review_decision) && <DecisionBadge decision={result.review_decision || model.h.review_decision} />}
        </>
      ) : adv ? (
        <ul className="space-y-1 text-[11.5px]">
          <li className="flex gap-1.5 text-ink"><CheckCircle2 size={12} className="text-success-600 mt-0.5 shrink-0" />{adv.what_supports_it?.length ?? 0} supporting item(s)</li>
          <li className="flex gap-1.5 text-ink"><AlertTriangle size={12} className={cx('mt-0.5 shrink-0', adv.what_contradicts_it?.length ? 'text-danger-600' : 'text-slate-300')} />{adv.what_contradicts_it?.length ?? 0} contradicting item(s)</li>
          <li className="flex gap-1.5 text-ink"><HelpCircle size={12} className={cx('mt-0.5 shrink-0', adv.what_is_missing?.length ? 'text-warning-500' : 'text-slate-300')} />{adv.what_is_missing?.length ?? 0} missing-evidence item(s)</li>
          {adv.alternative_explanation && <li className="text-muted line-clamp-2">Alternative: {adv.alternative_explanation}</li>}
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
            <div className="rounded-md bg-slate-50 px-2 py-1.5 text-[11px] text-muted line-clamp-2"><span className="font-medium text-ink">Key factor: </span><Cited text={rep.supporting_evidence[0].statement} /></div>
          )}
        </>
      )}

      <ConfBar value={agent.confidence} />
      {agent.evidenceUsed.length > 0 && <div className="text-[10.5px] text-muted">cites {agent.evidenceUsed.length} evidence record(s)</div>}
    </div>
  )
}

function EvidenceCompact({ model, hoverAgent, setHoverEv, dense }) {
  if (dense) {
    const c = model.h.evidence_composition || {}
    return <div className="text-[12px] text-muted">{model.evidence.length} record(s) · REAL {c.real ?? 0} · SYNTHETIC {c.synthetic ?? 0}</div>
  }
  const sensors = (model.h.sensor_view || []).filter((s) => s.value != null || s.status === 'missing')
  const used = hoverAgent ? new Set(model.agents.find((a) => a.key === hoverAgent)?.evidenceUsed || []) : null
  const comp = model.h.evidence_composition || {}
  const targeted = model.evidence.filter((e) => e.retrieval_round > 0).length
  return (
    <div className="space-y-3">
      {sensors.length > 0 && (
        <div>
          <div className="eyebrow mb-1">Reported readings vs reference band</div>
          <div className="space-y-1.5">
            {sensors.map((s) => {
              const lo = s.band_low, hi = s.band_high
              const span = (hi - lo) || 1
              const pos = s.value == null ? null : Math.max(0, Math.min(1, (s.value - (lo - span)) / (3 * span)))
              const off = s.status === 'high' || s.status === 'low'
              return (
                <div key={s.sensor} className="text-[11px]">
                  <div className="flex justify-between"><span className="text-ink">{s.label}</span>
                    <span className={cx('tabular-nums', s.value == null ? 'italic text-warning-700' : off ? 'text-warning-700 font-semibold' : 'text-muted')}>
                      {s.value == null ? 'unavailable' : `${fmtNum(s.value, 3)} ${s.unit === '(norm. index)' ? '' : s.unit}`}{off ? ` · ${s.status}` : ''}
                    </span>
                  </div>
                  <div className="relative h-1.5 rounded bg-slate-100 mt-0.5" title={`reference band ${fmtNum(lo, 2)} – ${fmtNum(hi, 2)}`}>
                    <div className="absolute h-full bg-success-100 rounded" style={{ left: '33.3%', width: '33.3%' }} />
                    {pos != null && <div className="absolute -top-0.5 w-1 h-2.5 rounded-sm" style={{ left: `calc(${pos * 100}% - 2px)`, background: off ? '#B45309' : '#0F172A' }} />}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
      <div>
        <div className="eyebrow mb-1">Top evidence</div>
        {!model.evidence.length ? <Empty>No evidence retrieved.</Empty> : (
          <ul className="space-y-1">
            {model.evidence.slice(0, 6).map((e) => (
              <li key={e.evidence_id}
                onMouseEnter={() => setHoverEv(e.evidence_id)} onMouseLeave={() => setHoverEv(null)}
                className={cx('flex items-center gap-1.5 rounded px-1 py-0.5 text-[11px] transition-colors', used?.has(e.evidence_id) ? 'bg-primary-50 ring-1 ring-primary-200' : used ? 'opacity-50' : 'hover:bg-slate-50')}>
                <span className="mono text-primary-700 shrink-0">{e.evidence_id}</span>
                <SourceBadge source={e.source_type} size="xs" />
                <span className="truncate text-ink flex-1" title={e.label}>{e.label || 'unlabelled'}</span>
                <span className="tabular-nums text-muted">{fmtNum(e.retrieval_score, 2)}</span>
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
    <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
      <div className="grid grid-cols-[minmax(96px,180px)_1fr] gap-x-3 gap-y-1.5 items-center">
        {lanes.map((lane) => (
          <Lane key={lane.id ?? 'harness'} lane={lane} spans={model.spans.filter((s) => (s.agent ?? null) === lane.id)}
            total={model.totalMs} selected={selected} onSelect={onSelect} compact={compact} />
        ))}
        <div />
        <div className="relative h-4 text-[10px] text-muted">
          {ticks.map((t) => <span key={t} className="absolute -translate-x-1/2 tabular-nums" style={{ left: `${t * 100}%` }}>{fmtNum(model.totalMs * t, 0)} ms</span>)}
        </div>
      </div>
    </div>
  )
}

function Lane({ lane, spans, total, selected, onSelect }) {
  return (
    <>
      <div className="flex items-center gap-1.5 text-[11px] text-ink truncate" title={lane.label}>
        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: lane.color }} />{lane.label}
      </div>
      <div className="relative h-5 rounded bg-slate-50 border border-line/70">
        {spans.map((s) => {
          const left = (s.rs / total) * 100
          const width = Math.max(((s.re - s.rs) / total) * 100, 0.8)
          const isSel = selected === s.step
          return (
            <button key={s.step} type="button" onClick={() => onSelect(isSel ? null : s.step)}
              title={`#${s.step} ${s.stage} · ${s.action}\n${fmtNum(s.duration_ms, 1)} ms · ${s.status}${s.reason ? `\n${s.reason}` : ''}`}
              className={cx('absolute top-0.5 bottom-0.5 rounded-sm transition-[box-shadow,transform] hover:scale-y-125', isSel && 'ring-2 ring-offset-1 ring-ink')}
              style={{ left: `${Math.min(left, 99.2)}%`, width: `${width}%`, minWidth: 6, background: s.status === 'error' ? '#DC2626' : lane.color, opacity: s.status === 'loop' ? 0.75 : 1,
                backgroundImage: s.status === 'loop' ? 'repeating-linear-gradient(135deg, rgba(255,255,255,.55) 0 2px, transparent 2px 5px)' : undefined }}
              aria-label={`${s.stage} ${s.action}`} />
          )
        })}
      </div>
    </>
  )
}

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
export default function DecisionExplorer({ result, question }) {
  const model = useMemo(() => buildModel(result), [result])
  const [expanded, setExpanded] = useState(null)
  const [hoverAgent, setHoverAgent] = useState(null)
  const [hoverEv, setHoverEv] = useState(null)
  const [focusEv, setFocusEv] = useState(null)
  const [selectedStep, setSelectedStep] = useState(null)
  const flip = useFlip([expanded])
  const focusRef = useRef(null)
  const h = model.h

  const toggle = (id) => { flip.snapshot(); setExpanded((cur) => (cur === id ? null : id)) }
  const openEvidence = (evId) => { setFocusEv(evId); flip.snapshot(); setExpanded('evidence') }
  const close = () => { flip.snapshot(); setExpanded(null) }

  useEffect(() => {
    if (!expanded) return
    const onKey = (e) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    const el = focusRef.current
    if (el) {
      const r = el.getBoundingClientRect()
      if (r.top < 0 || r.top > window.innerHeight * 0.6) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded])

  if (!result?.harness) return <Empty>This response has no multi-agent state to visualise.</Empty>

  const decision = result.review_decision || h.review_decision
  const auto = decision === 'AUTO_RESOLVE'
  const comp = h.evidence_composition || {}
  const cv = h.claim_validation || {}
  const ambiguityAgent = model.agents.find((a) => a.column === 'ambiguity')
  const ambLevel = ambiguityAgent?.report?.extras?.ambiguity_level
  const conflictCount = model.contradictions.length + (model.distinct.length > 1 ? model.distinct.length - 1 : 0)
  const expandedAgent = expanded?.startsWith('agent:') ? model.agents.find((a) => `agent:${a.key}` === expanded) : null
  const usedByHover = hoverEv ? new Set(model.evidence.find((e) => e.evidence_id === hoverEv)?.used_by || []) : null
  const finished = model.spans.some((s) => s.stage === 'review_gate')

  return (
    <div className="space-y-4">
      {/* Header */}
      <section className="card p-4 sm:p-5">
        <div className="flex flex-wrap items-start gap-4">
          <div className="flex-1 min-w-[240px]">
            <div className="flex flex-wrap items-center gap-2">
              <span className="eyebrow text-primary-700">Multi-agent decision explorer</span>
              {finished && <span className="chip border-success-100 bg-success-50 text-success-700"><CheckCircle2 size={12} />Analysis complete</span>}
              {decision && <DecisionBadge decision={decision} />}
              {h.data_mode && <SourceBadge source={h.data_mode} />}
            </div>
            <div className="mt-2 flex gap-2 rounded-lg bg-primary-50/60 border border-primary-100 px-3 py-2">
              <MessageSquareText size={16} className="text-primary-600 mt-0.5 shrink-0" />
              <div className="min-w-0"><div className="text-[11px] text-muted">User question</div><p className="text-[14px] font-medium text-ink leading-snug break-words">{question || h.query_profile?.raw_query}</p></div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <ConfidenceRing value={result.confidence} />
            <div><div className="eyebrow">Overall confidence</div><div className="text-[12px] text-muted max-w-[160px]">{h.confidence?.factors?.length ? `${h.confidence.factors.length} measured factors` : ''}</div></div>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          {model.verified && <Metric icon={FileCheck2} label="Verified hypothesis" value={model.verified} hint={h.predicted_label && h.predicted_label !== model.verified ? `final: ${h.predicted_label}` : undefined} />}
          {model.initial.length > 0 && model.verified && (
            <Metric icon={GitMerge} label="Agent consensus" value={`${model.agreeing.length}/${model.initial.length} agree`}
              tone={model.agreeing.length === model.initial.length ? 'text-success-700' : 'text-warning-700'}
              hint={h.verification?.agreement_without_evidence ? 'agreement without strong evidence' : model.distinct.length > 1 ? `${model.distinct.length} distinct findings` : 'independent agents agree'} />
          )}
          <Metric icon={AlertTriangle} label="Conflicts" value={conflictCount} tone={conflictCount ? 'text-danger-700' : 'text-ink'} hint={`${model.contradictions.length} contradicting signal(s)`} />
          <Metric icon={Database} label="Evidence" value={`${model.evidence.length} records`} hint={`REAL ${comp.real ?? 0} · SYNTHETIC ${comp.synthetic ?? 0}`} />
          {ambLevel && <Metric icon={HelpCircle} label="Ambiguity" value={ambLevel} tone={ambLevel === 'LOW' ? 'text-success-700' : ambLevel === 'HIGH' ? 'text-danger-700' : 'text-warning-700'} hint={`${ambiguityAgent.report.extras.flags?.length ?? 0} flag(s)`} />}
          <Metric icon={RotateCcw} label="Feedback loop" value={`${h.feedback_rounds ?? 0} round(s)`} hint={`${cv.total_claims ?? 0} claims checked · ${cv.removed ?? 0} removed`} />
        </div>
        {!auto && h.review?.reasons?.length > 0 && (
          <div className="mt-3 flex gap-2 rounded-lg bg-warning-50 border border-warning-100 px-3 py-2 text-[12px] text-warning-700">
            <ShieldAlert size={14} className="mt-0.5 shrink-0" /><span><b>Human review required:</b> {h.review.reasons.join(' · ')}</span>
          </div>
        )}
      </section>

      {/* Focus area: the maximised panel */}
      {expanded && (
        <section ref={(el) => { focusRef.current = el; flip.register(expanded)(el) }}
          className="rounded-xl border-2 border-primary-500 bg-white shadow-lift scroll-mt-4" aria-live="polite">
          <header className="flex items-center justify-between gap-3 px-5 py-3 border-b border-line">
            <div className="min-w-0">
              {expandedAgent ? <AgentTitle agent={expandedAgent} /> : (
                <div className="text-[14px] font-semibold text-ink">{expanded === 'evidence' ? 'Retrieved evidence' : 'Agent execution & interaction timeline'}</div>
              )}
            </div>
            <button type="button" onClick={close} className="btn-ghost border border-line px-2.5 py-1.5" aria-label="Minimize panel" title="Minimize (Esc)">
              <Minimize2 size={14} /> <span className="hidden sm:inline">Minimize</span>
            </button>
          </header>
          <div className="p-5 de-fade-up">
            {expanded === 'evidence' && (
              <div className="space-y-6">
                {(h.sensor_view || []).length > 0 && <SensorPanel harness={h} />}
                <EvidenceExplorer harness={h} focusId={focusEv} />
              </div>
            )}
            {expandedAgent && <AgentDetail agent={expandedAgent} model={model} result={result} onEvidence={openEvidence} />}
            {expanded === 'timeline' && (
              <div className="space-y-6">
                <Timeline model={model} selected={selectedStep} onSelect={setSelectedStep} />
                <OrchestrationFlow harness={h} />
                <AuditPanel harness={h} />
              </div>
            )}
          </div>
        </section>
      )}

      {/* Pipeline grid */}
      <div className={cx('grid gap-4 grid-cols-1 md:grid-cols-2', model.columns.length >= 4 ? 'xl:grid-cols-[1.1fr_repeat(4,minmax(0,1fr))]' : 'xl:grid-cols-[1.1fr_repeat(3,minmax(0,1fr))]')}>
        <div className="min-w-0">
          <div ref={flip.register('hdr:evidence')}><ColumnHeader n={1} title="Retrieved evidence" subtitle="Readings & retrieved records" /></div>
          <Panel id="evidence" flip={flip} expanded={expanded} onToggle={(id) => { setFocusEv(null); toggle(id) }}
            title={<div className="flex items-center gap-1.5 text-[13px] font-semibold text-ink"><Database size={14} className="text-primary-600" />Evidence bundle</div>}
            highlighted={!!(hoverAgent && model.agents.find((a) => a.key === hoverAgent)?.evidenceUsed.length)}>
            <EvidenceCompact model={model} hoverAgent={hoverAgent} setHoverEv={setHoverEv} dense={!!expanded} />
          </Panel>
        </div>

        {model.columns.map((col, ci) => (
          <div key={col.id} className="min-w-0">
            <div ref={flip.register(`hdr:${col.id}`)}><ColumnHeader n={ci + 2} title={COLUMN_TITLES[col.id][0]} subtitle={COLUMN_TITLES[col.id][1]} /></div>
            <div className="space-y-3">
              {col.agents.map((a) => (
                <Panel key={a.key} id={`agent:${a.key}`} flip={flip} expanded={expanded} onToggle={toggle} accent={a.color}
                  title={<AgentTitle agent={a} />} highlighted={usedByHover?.has(a.key) || hoverAgent === a.key}
                  onHover={(on) => setHoverAgent(on ? a.key : null)}>
                  <AgentCompact agent={a} result={result} model={model} dense={!!expanded} />
                </Panel>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Timeline */}
      <Panel id="timeline" flip={flip} expanded={expanded} onToggle={toggle}
        title={<div className="flex items-center gap-1.5 text-[13px] font-semibold text-ink"><Clock size={14} className="text-primary-600" />Agent interaction timeline</div>}
        subtitle={`${model.spans.length} recorded events · ${fmtNum(h.latency_ms ?? model.totalMs, 0)} ms end-to-end · click a bar for details · click the header to expand`}>
        <Timeline model={model} compact selected={selectedStep} onSelect={setSelectedStep} />
        {selectedStep != null && (() => {
          const s = model.spans.find((x) => x.step === selectedStep)
          if (!s) return null
          return (
            <div className="mt-2 rounded-lg border border-line bg-slate-50 p-2 text-[12px]" onClick={(e) => e.stopPropagation()}>
              <span className="mono text-muted">#{s.step}</span> <b className="text-ink">{s.stage}</b> · {s.action} · {fmtNum(s.duration_ms, 1)} ms
              {s.reason && <div className="text-muted mt-0.5">{s.reason}</div>}
              {s.evidence_used?.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{s.evidence_used.map((id) => <IdChip key={id} id={id} onClick={openEvidence} />)}</div>}
            </div>
          )
        })()}
      </Panel>
    </div>
  )
}

function ColumnHeader({ n, title, subtitle }) {
  return (
    <div className="flex items-end justify-between gap-2 mb-2 px-1">
      <div className="min-w-0">
        <div className="text-[13px] font-semibold text-ink truncate">{n}. {title}</div>
        <div className="text-[11px] text-muted truncate">{subtitle}</div>
      </div>
      <ChevronRight size={16} className="text-slate-300 shrink-0 hidden xl:block" aria-hidden />
    </div>
  )
}
