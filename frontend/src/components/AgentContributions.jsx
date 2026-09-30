import { useState } from 'react'
import { ChevronDown, Users } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

const AGENT_META = {
  diagnostic_expert: { label: 'Diagnostic Expert',       emoji: '🧠', border: 'rgba(191,95,255,0.35)',  bg: 'rgba(191,95,255,0.08)'  },
  pattern_agent:     { label: 'Pattern Recognition',     emoji: '🔍', border: 'rgba(91,127,255,0.35)',  bg: 'rgba(91,127,255,0.08)'  },
  aggressive_agent:  { label: 'Aggressive Decision',     emoji: '⚡', border: 'rgba(255,159,28,0.35)',  bg: 'rgba(255,159,28,0.08)'  },
  verification:      { label: 'Verification Analyst',    emoji: '✅', border: 'rgba(52,211,153,0.35)',  bg: 'rgba(52,211,153,0.08)'  },
  ambiguity:         { label: 'Ambiguity Detection',     emoji: '🎯', border: 'rgba(244,114,182,0.35)', bg: 'rgba(244,114,182,0.08)' },
  final_decision:    { label: 'Human Review Coordinator',emoji: '🏁', border: 'rgba(255,217,61,0.35)',  bg: 'rgba(255,217,61,0.08)'  },
}

export default function AgentContributions({ contributions }) {
  const [open, setOpen] = useState(false)
  const entries = Object.entries(contributions || {}).filter(([, value]) => value)

  if (!entries.length) return null

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{ border: '1px solid rgba(91,127,255,0.22)', background: 'rgba(10,12,30,0.75)' }}
    >
      <button
        id="agents-accordion-toggle"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-5 hover:bg-white/5 transition-colors"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2.5">
          <Users size={16} style={{ color: '#7c9fff', filter: 'drop-shadow(0 0 5px #5b7fff)' }} />
          <span className="text-sm font-bold text-white">Quick Contribution Summary</span>
          <span className="text-xs text-[var(--text-muted)]">({entries.length} summaries)</span>
        </div>
        <motion.div animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
          <ChevronDown size={18} className="text-[var(--text-muted)]" />
        </motion.div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="agents"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="overflow-hidden"
          >
            <div
              className="px-5 pb-5 grid grid-cols-1 sm:grid-cols-2 gap-3 border-t pt-4"
              style={{ borderColor: 'rgba(91,127,255,0.15)' }}
            >
              {entries.map(([key, value]) => {
                const meta = AGENT_META[key] || {
                  label: key, emoji: '🤖',
                  border: 'rgba(255,255,255,0.12)', bg: 'rgba(255,255,255,0.04)'
                }
                return (
                  <div
                    key={key}
                    id={`agent-${key}`}
                    className="rounded-xl p-4"
                    style={{ border: `1px solid ${meta.border}`, background: meta.bg }}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-base">{meta.emoji}</span>
                      <span className="text-xs font-bold text-white">{meta.label}</span>
                    </div>
                    <p className="text-xs text-[var(--text-muted)] leading-relaxed">{value}</p>
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
