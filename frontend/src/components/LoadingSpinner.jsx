import { motion } from 'framer-motion'
import { Cpu } from 'lucide-react'

const AGENT_STEPS = [
  { label: 'RAG Retrieval',        color: '#7c9fff' },
  { label: 'Pattern Recognition',  color: '#a5bfff' },
  { label: 'Aggressive Decision',  color: '#ff9f1c' },
  { label: 'Diagnostic Expert',    color: '#f472b6' },
  { label: 'Verification Analyst', color: '#6ee7b7' },
  { label: 'Ambiguity Detection',  color: '#d8b4fe' },
  { label: 'Final Synthesis',      color: '#ffd93d' },
]

export default function LoadingSpinner() {
  return (
    <div
      className="px-6 py-5 inline-block max-w-sm rounded-2xl"
      style={{
        background: 'rgba(10,12,30,0.90)',
        border: '1px solid rgba(91,127,255,0.30)',
        boxShadow: '0 0 30px rgba(91,127,255,0.12)',
        backdropFilter: 'blur(16px)',
      }}
    >
      <div className="flex items-center gap-3 mb-4">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}
          style={{ filter: 'drop-shadow(0 0 6px #5b7fff)' }}
        >
          <Cpu size={18} style={{ color: '#7c9fff' }} />
        </motion.div>
        <span className="text-sm font-bold" style={{
          background: 'linear-gradient(135deg,#7c9fff,#f472b6)',
          WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text'
        }}>
          Running Agent Pipeline…
        </span>
      </div>

      <div className="space-y-2">
        {AGENT_STEPS.map((step, i) => (
          <motion.div
            key={step.label}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.3, repeat: Infinity, repeatDelay: AGENT_STEPS.length * 0.3 + 1 }}
            className="flex items-center gap-2"
          >
            <motion.div
              animate={{ scale: [1, 1.4, 1], opacity: [0.5, 1, 0.5] }}
              transition={{ delay: i * 0.3, duration: 0.5, repeat: Infinity, repeatDelay: AGENT_STEPS.length * 0.3 + 1 }}
              className="w-1.5 h-1.5 rounded-full flex-shrink-0"
              style={{ backgroundColor: step.color, boxShadow: `0 0 6px ${step.color}` }}
            />
            <span className="text-xs" style={{ color: 'rgba(160,170,210,0.85)' }}>{step.label}</span>
          </motion.div>
        ))}
      </div>

      <div className="flex gap-1.5 mt-5 justify-center">
        {['#5b7fff', '#f472b6', '#00f5ff'].map((color, i) => (
          <motion.div
            key={i}
            animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1, 0.8] }}
            transition={{ duration: 1.2, delay: i * 0.25, repeat: Infinity }}
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}` }}
          />
        ))}
      </div>
    </div>
  )
}
