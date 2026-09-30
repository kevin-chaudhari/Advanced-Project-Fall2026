import { useState } from 'react'
import { ChevronDown, ShieldCheck } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

// Each agent gets its own accent color
const AGENT_ACCENT = [
  { color: '#7c9fff', glow: 'rgba(91,127,255,0.20)'  },
  { color: '#a78bfa', glow: 'rgba(167,139,250,0.20)' },
  { color: '#ff9f1c', glow: 'rgba(255,159,28,0.20)'  },
  { color: '#f472b6', glow: 'rgba(244,114,182,0.20)' },
  { color: '#6ee7b7', glow: 'rgba(52,211,153,0.20)'  },
  { color: '#ffd93d', glow: 'rgba(255,217,61,0.20)'  },
]

function confidenceTone(confidence) {
  const pct = Math.round((confidence || 0) * 100)
  if (pct >= 80) return { background: 'rgba(52,211,153,0.15)', border: '1px solid rgba(52,211,153,0.35)', color: '#6ee7b7' }
  if (pct >= 60) return { background: 'rgba(255,217,61,0.12)', border: '1px solid rgba(255,217,61,0.35)', color: '#ffd93d' }
  return { background: 'rgba(244,114,182,0.12)', border: '1px solid rgba(244,114,182,0.35)', color: '#f9a8d4' }
}

function executionTone(mode) {
  if (mode === 'parallel')    return { background: 'rgba(91,127,255,0.14)', border: '1px solid rgba(91,127,255,0.35)', color: '#7c9fff' }
  if (mode === 'review')      return { background: 'rgba(52,211,153,0.12)', border: '1px solid rgba(52,211,153,0.30)', color: '#6ee7b7' }
  if (mode === 'calibration') return { background: 'rgba(255,217,61,0.12)', border: '1px solid rgba(255,217,61,0.35)', color: '#ffd93d' }
  return { background: 'rgba(191,95,255,0.12)', border: '1px solid rgba(191,95,255,0.30)', color: '#d8b4fe' }
}

export default function PersonaOutputs({ agentOutputs = [] }) {
  const [open, setOpen] = useState(true)

  if (!agentOutputs.length) return null

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{ border: '1px solid rgba(91,127,255,0.25)', background: 'rgba(10,12,30,0.70)' }}
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-5 hover:bg-white/5 transition-colors"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2.5">
          <ShieldCheck size={16} style={{ color: '#7c9fff', filter: 'drop-shadow(0 0 5px #5b7fff)' }} />
          <span className="text-sm font-bold" style={{
            background: 'linear-gradient(135deg,#7c9fff,#f472b6)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text'
          }}>
            Six Persona Views
          </span>
          <span className="text-xs text-[var(--text-muted)]">({agentOutputs.length} active perspectives)</span>
        </div>
        <motion.div animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
          <ChevronDown size={18} className="text-[var(--text-muted)]" />
        </motion.div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="persona-grid"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="overflow-hidden"
          >
            <div
              className="border-t px-5 py-5 grid grid-cols-1 xl:grid-cols-2 gap-4"
              style={{ borderColor: 'rgba(91,127,255,0.15)' }}
            >
              {agentOutputs.map((agent, index) => {
                const accent = AGENT_ACCENT[index % AGENT_ACCENT.length]
                return (
                  <div
                    key={`${agent.agent_name}-${index}`}
                    className="rounded-2xl p-4 space-y-4 transition-all hover:scale-[1.01] duration-200"
                    style={{
                      border: `1px solid ${accent.color}30`,
                      background: `radial-gradient(circle at top left, ${accent.glow} 0%, rgba(10,12,30,0.85) 60%)`,
                    }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xl">{agent.agent_emoji || '🤖'}</span>
                          <h4 className="text-sm font-bold text-white">{agent.agent_name}</h4>
                        </div>
                        <p className="text-xs font-semibold mt-1" style={{ color: accent.color }}>{agent.agent_persona}</p>
                        {agent.persona_title && (
                          <p className="text-[10px] text-[var(--text-muted)] mt-0.5 italic">{agent.persona_title}</p>
                        )}
                      </div>
                      <div className="text-right space-y-1.5 flex-shrink-0">
                        <div
                          className="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold"
                          style={confidenceTone(agent.agent_confidence)}
                        >
                          {Math.round((agent.agent_confidence || 0) * 100)}% confidence
                        </div>
                        {agent.execution_mode && (
                          <div
                            className="inline-flex items-center rounded-full px-2.5 py-1 text-[10px] uppercase tracking-wide font-bold"
                            style={executionTone(agent.execution_mode)}
                          >
                            {agent.execution_mode}
                          </div>
                        )}
                      </div>
                    </div>

                    {agent.persona_description && (
                      <p className="text-xs leading-relaxed text-[var(--text-muted)]">{agent.persona_description}</p>
                    )}

                    <div className="space-y-1">
                      <p className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-muted)]">Answer</p>
                      <p className="text-sm text-white leading-relaxed">{agent.diagnosis}</p>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {agent.specialty && (
                        <div className="rounded-xl p-3" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
                          <p className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-muted)] mb-1">Specialty</p>
                          <p className="text-xs text-white/90 leading-relaxed">{agent.specialty}</p>
                        </div>
                      )}
                      {agent.decision_style && (
                        <div className="rounded-xl p-3" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
                          <p className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-muted)] mb-1">Decision Style</p>
                          <p className="text-xs text-white/90 leading-relaxed">{agent.decision_style}</p>
                        </div>
                      )}
                    </div>

                    {agent.key_findings?.length > 0 && (
                      <div className="space-y-2">
                        <p className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-muted)]">Key Findings</p>
                        <ul className="space-y-1.5">
                          {agent.key_findings.slice(0, 4).map((finding, findingIndex) => (
                            <li key={findingIndex} className="flex items-start gap-2 text-xs text-white/85">
                              <span className="font-bold mt-0.5 text-[10px]" style={{ color: accent.color }}>{findingIndex + 1}.</span>
                              <span className="leading-relaxed">{finding}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {agent.reasoning && (
                      <div className="space-y-1">
                        <p className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-muted)]">Reasoning</p>
                        <p className="text-xs text-[var(--text-muted)] leading-relaxed">{agent.reasoning}</p>
                      </div>
                    )}

                    {agent.recommendation && (
                      <div
                        className="rounded-xl p-3"
                        style={{ background: `${accent.glow}`, border: `1px solid ${accent.color}30` }}
                      >
                        <p className="text-[10px] uppercase tracking-[0.2em] mb-1" style={{ color: accent.color }}>Recommendation</p>
                        <p className="text-xs text-white/90 leading-relaxed">{agent.recommendation}</p>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
