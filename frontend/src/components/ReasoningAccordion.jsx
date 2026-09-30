import { useState } from 'react'
import { ChevronDown, ListOrdered } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

// Step number accent colors cycling through the neon palette
const STEP_COLORS = ['#7c9fff', '#f472b6', '#00f5ff', '#ffd93d', '#39ff14', '#bf5fff']

export default function ReasoningAccordion({ steps }) {
  const [open, setOpen] = useState(false)

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{ border: '1px solid rgba(91,127,255,0.22)', background: 'rgba(10,12,30,0.75)' }}
    >
      <button
        id="reasoning-accordion-toggle"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-5 hover:bg-white/5 transition-colors"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2.5">
          <ListOrdered size={16} style={{ color: '#7c9fff', filter: 'drop-shadow(0 0 5px #5b7fff)' }} />
          <span className="text-sm font-bold text-white">Step-by-Step Reasoning</span>
          <span className="text-xs text-[var(--text-muted)]">({steps.length} steps)</span>
        </div>
        <motion.div animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
          <ChevronDown size={18} className="text-[var(--text-muted)]" />
        </motion.div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="overflow-hidden"
          >
            <div
              className="px-5 pb-5 space-y-3 border-t pt-4"
              style={{ borderColor: 'rgba(91,127,255,0.15)' }}
            >
              {steps.map((step, i) => {
                const color = STEP_COLORS[i % STEP_COLORS.length]
                return (
                  <div key={i} className="flex gap-3 items-start">
                    <div
                      className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-black"
                      style={{
                        background: `${color}20`,
                        border: `1px solid ${color}50`,
                        color,
                        textShadow: `0 0 8px ${color}`,
                      }}
                    >
                      {i + 1}
                    </div>
                    <p className="text-sm text-[var(--text-muted)] leading-relaxed pt-0.5">{step}</p>
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
