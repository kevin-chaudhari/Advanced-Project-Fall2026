import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, FlaskConical, CheckCircle2, AlertTriangle, XCircle, TrendingUp, Award, Zap } from 'lucide-react'

// ── helpers ──────────────────────────────────────────────────────────────────

const PHASE_COLORS = {
  1: { accent: '#7c9fff', glow: 'rgba(91,127,255,0.18)', label: 'Phase 1' },
  2: { accent: '#6ee7b7', glow: 'rgba(52,211,153,0.16)', label: 'Phase 2' },
  3: { accent: '#ffd93d', glow: 'rgba(255,217,61,0.16)', label: 'Phase 3' },
  4: { accent: '#f472b6', glow: 'rgba(244,114,182,0.16)', label: 'Phase 4' },
}

const AGENT_ACCENT = [
  '#7c9fff', '#a78bfa', '#ff9f1c', '#f472b6', '#6ee7b7', '#ffd93d',
]

function verdictIcon(verdict, size = 14) {
  if (!verdict) return null
  if (verdict.includes('PASS')) return <CheckCircle2 size={size} className="text-emerald-400 flex-shrink-0" />
  if (verdict.includes('PARTIAL')) return <AlertTriangle size={size} className="text-yellow-400 flex-shrink-0" />
  return <XCircle size={size} className="text-rose-400 flex-shrink-0" />
}

function verdictStyle(verdict) {
  if (!verdict) return {}
  if (verdict.includes('PASS'))    return { background: 'rgba(52,211,153,0.12)', border: '1px solid rgba(52,211,153,0.35)', color: '#6ee7b7' }
  if (verdict.includes('PARTIAL')) return { background: 'rgba(255,217,61,0.12)', border: '1px solid rgba(255,217,61,0.35)', color: '#ffd93d' }
  return { background: 'rgba(244,114,182,0.12)', border: '1px solid rgba(244,114,182,0.35)', color: '#f9a8d4' }
}

function ScorePill({ value, label }) {
  const pct = Math.round((value || 0) * 100)
  const color = pct >= 78 ? '#6ee7b7' : pct >= 60 ? '#ffd93d' : '#f472b6'
  return (
    <div className="flex flex-col items-center gap-0.5 min-w-[56px]">
      <span className="text-base font-bold" style={{ color }}>{pct}%</span>
      <span className="text-[9px] text-[var(--text-muted)] uppercase tracking-wide text-center leading-tight">{label}</span>
    </div>
  )
}

function MetricBar({ label, value }) {
  const pct = Math.round((value || 0) * 100)
  const color = pct >= 78 ? '#6ee7b7' : pct >= 60 ? '#ffd93d' : '#f472b6'
  return (
    <div className="space-y-1">
      <div className="flex justify-between items-center">
        <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">{label}</span>
        <span className="text-[10px] font-bold" style={{ color }}>{pct}%</span>
      </div>
      <div className="h-1.5 rounded-full" style={{ background: 'rgba(255,255,255,0.08)' }}>
        <motion.div
          className="h-full rounded-full"
          style={{ background: color, boxShadow: `0 0 6px ${color}60` }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.7, ease: 'easeOut' }}
        />
      </div>
    </div>
  )
}

// ── Agent card inside a phase ─────────────────────────────────────────────────

function AgentEvalCard({ evalData, accentColor }) {
  const [open, setOpen] = useState(false)
  const metrics = [
    { label: 'Faithfulness', value: evalData.faithfulness_score },
    { label: 'Reasoning',    value: evalData.reasoning_score },
    { label: 'Agreement',    value: evalData.agreement_score },
    { label: 'Coverage',     value: evalData.coverage_score },
    { label: 'Reliability',  value: evalData.reliability_score },
  ]
  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ border: `1px solid ${accentColor}28`, background: `radial-gradient(circle at top left, ${accentColor}12 0%, rgba(10,12,30,0.85) 70%)` }}
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-3 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-bold text-white">{evalData.agent_name}</span>
          <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-semibold" style={verdictStyle(evalData.verdict)}>
            {verdictIcon(evalData.verdict, 11)} {evalData.verdict}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold" style={{ color: accentColor }}>{Math.round((evalData.overall_score || 0) * 100)}%</span>
          <motion.div animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
            <ChevronDown size={14} className="text-[var(--text-muted)]" />
          </motion.div>
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="agent-detail"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 space-y-3 border-t" style={{ borderColor: `${accentColor}20` }}>
              {/* Metrics */}
              <div className="pt-3 space-y-1.5">
                {metrics.map(m => <MetricBar key={m.label} label={m.label} value={m.value} />)}
              </div>

              {/* Diagnosis excerpt */}
              {evalData.diagnosis_excerpt && (
                <div className="rounded-lg p-2.5" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
                  <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">Diagnosis</p>
                  <p className="text-xs text-white/85 leading-relaxed">{evalData.diagnosis_excerpt}</p>
                </div>
              )}

              {/* Strengths + Risks */}
              <div className="grid grid-cols-2 gap-2">
                {evalData.strengths?.length > 0 && (
                  <div className="rounded-lg p-2" style={{ background: 'rgba(52,211,153,0.07)', border: '1px solid rgba(52,211,153,0.20)' }}>
                    <p className="text-[9px] uppercase tracking-wider text-emerald-400 mb-1.5">Strengths</p>
                    {evalData.strengths.slice(0, 2).map((s, i) => (
                      <p key={i} className="text-[10px] text-white/80 leading-snug mb-0.5">• {s}</p>
                    ))}
                  </div>
                )}
                {evalData.risks?.length > 0 && (
                  <div className="rounded-lg p-2" style={{ background: 'rgba(244,114,182,0.07)', border: '1px solid rgba(244,114,182,0.20)' }}>
                    <p className="text-[9px] uppercase tracking-wider text-rose-400 mb-1.5">Risks</p>
                    {evalData.risks.slice(0, 2).map((r, i) => (
                      <p key={i} className="text-[10px] text-white/80 leading-snug mb-0.5">• {r}</p>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ── Phase block ───────────────────────────────────────────────────────────────

function PhaseBlock({ phase }) {
  const [open, setOpen] = useState(phase.phase === 1)
  const colors = PHASE_COLORS[phase.phase] || PHASE_COLORS[1]
  const phasePct = Math.round((phase.phase_score || 0) * 100)

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{ border: `1px solid ${colors.accent}30`, background: `radial-gradient(circle at top left, ${colors.glow} 0%, rgba(8,10,28,0.92) 65%)` }}
    >
      {/* Phase header */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div
            className="w-9 h-9 rounded-xl flex items-center justify-center text-xs font-black flex-shrink-0"
            style={{ background: `${colors.accent}20`, border: `1px solid ${colors.accent}40`, color: colors.accent }}
          >
            P{phase.phase}
          </div>
          <div className="text-left">
            <p className="text-sm font-bold text-white">{phase.phase_name}</p>
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{phase.phase_description}</p>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <div className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full" style={verdictStyle(phase.phase_verdict)}>
            {verdictIcon(phase.phase_verdict)} {phase.phase_verdict}
          </div>
          <span className="text-base font-bold" style={{ color: colors.accent }}>{phasePct}%</span>
          <motion.div animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
            <ChevronDown size={16} className="text-[var(--text-muted)]" />
          </motion.div>
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="phase-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-5 space-y-4 border-t" style={{ borderColor: `${colors.accent}20` }}>
              {/* Phase meta stats */}
              <div className="pt-4 flex flex-wrap gap-3">
                <ScorePill value={phase.phase_score} label="Phase Score" />
                {phase.improvement_over_phase1 != null && (
                  <ScorePill value={Math.abs(phase.improvement_over_phase1)} label={phase.improvement_over_phase1 >= 0 ? 'Improvement' : 'Drop'} />
                )}
                {phase.confidence_calibrated != null && (
                  <ScorePill value={phase.confidence_calibrated} label="Calibrated Conf." />
                )}
                {phase.contradictions_resolved != null && (
                  <div className="flex flex-col items-center gap-0.5 min-w-[56px]">
                    <span className="text-base font-bold text-[#6ee7b7]">{phase.contradictions_resolved}</span>
                    <span className="text-[9px] text-[var(--text-muted)] uppercase tracking-wide text-center">Resolved</span>
                  </div>
                )}
                {phase.risk_level && (
                  <div className="flex flex-col items-center gap-0.5 min-w-[56px]">
                    <span className="text-sm font-bold" style={{ color: phase.risk_level === 'HIGH' || phase.risk_level === 'CRITICAL' ? '#f472b6' : phase.risk_level === 'MEDIUM' ? '#ffd93d' : '#6ee7b7' }}>
                      {phase.risk_level}
                    </span>
                    <span className="text-[9px] text-[var(--text-muted)] uppercase tracking-wide">Risk</span>
                  </div>
                )}
              </div>

              {/* Agent eval cards */}
              <div className="space-y-2">
                <p className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-muted)]">Agent Test Results</p>
                {(phase.agent_evaluations || []).map((ev, i) => (
                  <AgentEvalCard key={ev.agent_key || i} evalData={ev} accentColor={AGENT_ACCENT[i % AGENT_ACCENT.length]} />
                ))}
              </div>

              {/* Recommendations for next phase */}
              {phase.recommendations_for_next_phase?.length > 0 && (
                <div className="rounded-xl p-3" style={{ background: `${colors.accent}10`, border: `1px solid ${colors.accent}25` }}>
                  <p className="text-[10px] uppercase tracking-wider mb-2 font-semibold" style={{ color: colors.accent }}>
                    → Guidance for Next Phase
                  </p>
                  {phase.recommendations_for_next_phase.map((r, i) => (
                    <p key={i} className="text-xs text-white/80 leading-relaxed mb-0.5">• {r}</p>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ── Pipeline summary bar ──────────────────────────────────────────────────────

function PipelineSummary({ summary }) {
  const pct = Math.round((summary.pipeline_score || 0) * 100)
  return (
    <div
      className="rounded-2xl p-5"
      style={{ border: '1px solid rgba(91,127,255,0.30)', background: 'rgba(91,127,255,0.07)' }}
    >
      <div className="flex items-center gap-3 mb-4">
        <Award size={18} style={{ color: '#7c9fff' }} />
        <h3 className="text-sm font-bold text-white">Pipeline Test Summary</h3>
        <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-semibold ml-auto" style={verdictStyle(summary.overall_verdict)}>
          {verdictIcon(summary.overall_verdict)} {summary.overall_verdict}
        </span>
      </div>

      {/* Score bar */}
      <div className="mb-4">
        <div className="flex justify-between mb-1">
          <span className="text-xs text-[var(--text-muted)]">Overall Pipeline Score</span>
          <span className="text-sm font-bold" style={{ color: pct >= 75 ? '#6ee7b7' : pct >= 58 ? '#ffd93d' : '#f472b6' }}>{pct}%</span>
        </div>
        <div className="h-2 rounded-full" style={{ background: 'rgba(255,255,255,0.08)' }}>
          <motion.div
            className="h-full rounded-full"
            style={{ background: 'linear-gradient(90deg,#5b7fff,#f472b6)', boxShadow: '0 0 10px rgba(91,127,255,0.5)' }}
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 1.0, ease: 'easeOut' }}
          />
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <div className="text-center">
          <p className="text-base font-bold text-[#7c9fff]">{summary.agents_passed}<span className="text-[var(--text-muted)]">/{summary.total_agents_tested}</span></p>
          <p className="text-[10px] text-[var(--text-muted)]">Agents Passed</p>
        </div>
        <div className="text-center">
          <p className="text-sm font-bold text-[#6ee7b7]">{summary.best_agent}</p>
          <p className="text-[10px] text-[var(--text-muted)]">Best Agent</p>
        </div>
        <div className="text-center">
          <p className="text-sm font-bold" style={{ color: Math.round((summary.best_agent_score || 0) * 100) >= 75 ? '#6ee7b7' : '#ffd93d' }}>
            {Math.round((summary.best_agent_score || 0) * 100)}%
          </p>
          <p className="text-[10px] text-[var(--text-muted)]">Best Score</p>
        </div>
        <div className="text-center">
          <p className="text-sm font-bold text-rose-400">{summary.worst_agent}</p>
          <p className="text-[10px] text-[var(--text-muted)]">Needs Improvement</p>
        </div>
      </div>

      {/* Phase mini-pills */}
      <div className="flex flex-wrap gap-2">
        {(summary.phase_summaries || []).map(ps => {
          const c = PHASE_COLORS[ps.phase] || PHASE_COLORS[1]
          return (
            <div key={ps.phase} className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-semibold" style={{ background: `${c.accent}15`, border: `1px solid ${c.accent}30`, color: c.accent }}>
              {verdictIcon(ps.verdict, 11)} P{ps.phase}: {Math.round((ps.score || 0) * 100)}%
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export default function PhaseTestPanel({ phaseTestResults }) {
  const [open, setOpen] = useState(true)

  if (!phaseTestResults) return null
  const { phases = [], pipeline_summary } = phaseTestResults

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{ border: '1px solid rgba(255,217,61,0.25)', background: 'rgba(10,12,30,0.70)' }}
    >
      {/* Panel header */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-5 hover:bg-white/5 transition-colors"
        id="phase-test-panel-toggle"
      >
        <div className="flex items-center gap-2.5">
          <FlaskConical size={16} style={{ color: '#ffd93d', filter: 'drop-shadow(0 0 5px #ffd93d80)' }} />
          <span className="text-sm font-bold" style={{
            background: 'linear-gradient(135deg,#ffd93d,#f472b6)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text'
          }}>
            Phase-Wise Agent Testing
          </span>
          <span className="text-xs text-[var(--text-muted)]">({phases.length} phases evaluated)</span>
        </div>
        <div className="flex items-center gap-3">
          {pipeline_summary && (
            <span className="text-xs font-semibold px-2.5 py-1 rounded-full" style={verdictStyle(pipeline_summary.overall_verdict)}>
              {Math.round((pipeline_summary.pipeline_score || 0) * 100)}% overall
            </span>
          )}
          <motion.div animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
            <ChevronDown size={18} className="text-[var(--text-muted)]" />
          </motion.div>
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="test-panel-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.35 }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-5 space-y-4 border-t" style={{ borderColor: 'rgba(255,217,61,0.15)' }}>
              {/* Pipeline summary at top */}
              {pipeline_summary && (
                <div className="pt-4">
                  <PipelineSummary summary={pipeline_summary} />
                </div>
              )}

              {/* Phase blocks */}
              {phases.map(phase => (
                <PhaseBlock key={phase.phase} phase={phase} />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
