import { useEffect, useRef } from 'react'
import { Gauge } from 'lucide-react'

function getColor(pct) {
  if (pct >= 75) return {
    gradient: 'linear-gradient(90deg, #39ff14, #6ee7b7)',
    glow: '#39ff14',
    text: '#6ee7b7',
    label: 'High Confidence',
    labelStyle: { background: 'rgba(52,211,153,0.15)', border: '1px solid rgba(52,211,153,0.35)', color: '#6ee7b7' },
  }
  if (pct >= 50) return {
    gradient: 'linear-gradient(90deg, #ff9f1c, #ffd93d)',
    glow: '#ffd93d',
    text: '#ffd93d',
    label: 'Moderate Confidence',
    labelStyle: { background: 'rgba(255,217,61,0.12)', border: '1px solid rgba(255,217,61,0.35)', color: '#ffd93d' },
  }
  return {
    gradient: 'linear-gradient(90deg, #f472b6, #bf5fff)',
    glow: '#f472b6',
    text: '#f9a8d4',
    label: 'Low Confidence',
    labelStyle: { background: 'rgba(244,114,182,0.12)', border: '1px solid rgba(244,114,182,0.35)', color: '#f9a8d4' },
  }
}

export default function ConfidenceBar({ confidence }) {
  const pct = Math.round((confidence || 0) * 100)
  const { gradient, glow, text, label, labelStyle } = getColor(pct)
  const barRef = useRef(null)

  useEffect(() => {
    if (barRef.current) {
      barRef.current.style.setProperty('--target-width', `${pct}%`)
      barRef.current.classList.add('progress-fill')
    }
  }, [pct])

  return (
    <div
      className="glass-card p-5"
      style={{ borderColor: `${glow}30` }}
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Gauge size={16} style={{ color: text, filter: `drop-shadow(0 0 5px ${glow})` }} />
          <span className="text-sm font-bold text-white">Confidence Score</span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="text-2xl font-black font-mono"
            style={{ color: text, textShadow: `0 0 18px ${glow}80` }}
          >
            {pct}%
          </span>
          <span className="text-xs px-2.5 py-1 rounded-full font-semibold" style={labelStyle}>
            {label}
          </span>
        </div>
      </div>

      {/* Track */}
      <div className="h-3 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
        <div
          ref={barRef}
          style={{ width: 0, background: gradient, boxShadow: `0 0 12px ${glow}80` }}
          className="h-full rounded-full"
        />
      </div>

      <p className="text-xs text-[var(--text-muted)] mt-3 leading-relaxed">
        Final confidence recalibrated by OpenAI GPT-4o after inline evaluation — checks faithfulness, reasoning quality, agreement, and hallucination risk.
      </p>
    </div>
  )
}
