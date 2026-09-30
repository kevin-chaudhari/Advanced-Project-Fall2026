import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Database, Activity, RefreshCw, Upload, ArrowLeft,
  CheckCircle2, XCircle, Loader2, ChevronRight, Zap
} from 'lucide-react'

const DATASET_LABELS = {
  failure_iq: { label: 'Failure IQ', icon: Activity, color: '#7c9fff',   bg: 'rgba(91,127,255,0.18)'  },
  afrb:       { label: 'AFRB',       icon: Database,  color: '#6ee7b7',   bg: 'rgba(52,211,153,0.18)'  },
}

const AGENTS = [
  {
    emoji: '🧠', label: 'Diagnostic Expert',
    persona: 'Dr. Elena Vasquez', role: 'Senior Reliability Engineer',
    desc: 'Hypothesis-driven root-cause investigator; ranks evidence before concluding.',
    phase: 'Phase 1', phaseColor: '#7c9fff',
  },
  {
    emoji: '🔍', label: 'Pattern Recognition',
    persona: 'Dr. Aisha Patel', role: 'Predictive Maintenance Scientist',
    desc: 'Spots recurring failure signatures and degradation trends in historical data.',
    phase: 'Phase 1', phaseColor: '#7c9fff',
  },
  {
    emoji: '⚡', label: 'Aggressive Decision',
    persona: 'Commander Marcus Chen', role: 'Rapid Failure Triage Officer',
    desc: 'Safety-first fast responder who pushes the strongest danger signal immediately.',
    phase: 'Phase 1', phaseColor: '#7c9fff',
  },
  {
    emoji: '✅', label: 'Verification Analyst',
    persona: 'Priya Raman', role: 'Reliability Assurance Lead',
    desc: 'Cross-checks all agent claims, removes contradictions, keeps only defensible conclusions.',
    phase: 'Phase 2', phaseColor: '#6ee7b7',
  },
  {
    emoji: '🎯', label: 'Ambiguity Detection',
    persona: 'Dr. Sofia Nakamura', role: 'Uncertainty Quantification Specialist',
    desc: 'Measures uncertainty and decides whether human review is warranted.',
    phase: 'Phase 3', phaseColor: '#ffd93d',
  },
  {
    emoji: '🏁', label: 'Human Coordinator',
    persona: 'Director Sarah Mitchell', role: 'Plant Operations Director',
    desc: 'Synthesizes all outputs into an operator-ready final recommendation.',
    phase: 'Phase 4', phaseColor: '#f472b6',
  },
]

export default function Sidebar({
  dataset, meta, dataStatus, onLoadDataset, onSwitchDataset,
  fileInputRef, onFileUpload, uploadLoading
}) {
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(false)
  const [width, setWidth] = useState(288) // Default 288px (w-72 equivalent)
  const isDragging = useRef(false)
  const ds = DATASET_LABELS[dataset] || DATASET_LABELS.failure_iq
  const Icon = ds.icon

  const handleMouseDown = (e) => {
    e.preventDefault()
    isDragging.current = true
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    document.body.style.cursor = 'col-resize'
  }

  const handleMouseMove = (e) => {
    if (!isDragging.current) return
    const newWidth = Math.max(200, Math.min(e.clientX, 800))
    setWidth(newWidth)
  }

  const handleMouseUp = () => {
    isDragging.current = false
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', handleMouseUp)
    document.body.style.cursor = 'default'
  }

  if (collapsed) {
    return (
      <div
        className="w-12 flex flex-col items-center py-4 backdrop-blur-sm flex-shrink-0"
        style={{ borderRight: '1px solid rgba(91,127,255,0.15)', background: 'rgba(3,4,10,0.70)' }}
      >
        <button
          onClick={() => setCollapsed(false)}
          className="p-2 rounded-lg hover:bg-white/10 text-[var(--text-muted)] hover:text-white transition-colors"
          title="Expand sidebar"
        >
          <ChevronRight size={18} />
        </button>
      </div>
    )
  }

  return (
    <motion.aside
      initial={{ x: -20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      className="flex-shrink-0 flex flex-col backdrop-blur-sm relative"
      style={{ width: `${width}px`, borderRight: '1px solid rgba(91,127,255,0.15)', background: 'rgba(3,4,10,0.72)' }}
    >
      {/* Resizer Handle */}
      <div
        className="absolute top-0 right-[-4px] bottom-0 w-2 cursor-col-resize z-50 flex justify-center group"
        onMouseDown={handleMouseDown}
      >
        <div className="w-[2px] h-full bg-transparent group-hover:bg-[#5b7fff] transition-colors opacity-50" />
      </div>

      
      {/* Actions */}
      <div className="p-5 space-y-2.5" style={{ borderBottom: '1px solid rgba(91,127,255,0.10)' }}>
        <div className="flex items-center justify-between mb-3">
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">Actions</p>
          <button
            onClick={() => setCollapsed(true)}
            className="p-1 rounded hover:bg-white/10 text-[var(--text-muted)] transition-colors"
            title="Collapse"
          >
            <ChevronRight size={14} className="rotate-180" />
          </button>
        </div>

        <button
          id="load-dataset-btn"
          onClick={onLoadDataset}
          disabled={uploadLoading}
          className="w-full flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50"
          style={{
            background: 'rgba(91,127,255,0.12)',
            border: '1px solid rgba(91,127,255,0.35)',
            color: '#a5bfff',
          }}
        >
          {uploadLoading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
          {dataStatus.loaded ? 'Reload Dataset' : 'Load Dataset'}
        </button>

        {dataset === 'afrb' && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              className="hidden"
              id="csv-file-input"
              onChange={(e) => e.target.files?.[0] && onFileUpload(e.target.files[0])}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadLoading}
              className="w-full flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-50"
              style={{
                background: 'rgba(52,211,153,0.10)',
                border: '1px solid rgba(52,211,153,0.30)',
                color: '#6ee7b7',
              }}
            >
              <Upload size={15} />
              Upload CSV
            </button>
          </>
        )}

        <button
          onClick={onSwitchDataset}
          className="w-full flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all hover:bg-white/8 text-[var(--text-muted)] hover:text-white"
          style={{ border: '1px solid rgba(255,255,255,0.10)' }}
        >
          <ArrowLeft size={15} />
          Switch Dataset
        </button>
      </div>

      {/* Agent list */}
      <div className="p-4 flex-1 overflow-y-auto">
        <div className="flex items-center gap-2 mb-3">
          <Zap size={11} style={{ color: '#f472b6' }} />
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
            6-Agent Pipeline
          </p>
        </div>
        <div className="space-y-2">
          {AGENTS.map(({ emoji, label, persona, role, desc, phase, phaseColor }) => (
            <div
              key={label}
              className="rounded-xl p-3 space-y-1 transition-all hover:bg-white/[0.04]"
              style={{ border: '1px solid rgba(255,255,255,0.07)', background: 'rgba(255,255,255,0.02)' }}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="text-base leading-none">{emoji}</span>
                  <span className="text-xs font-bold text-white/90">{label}</span>
                </div>
                <span className="text-[9px] font-bold uppercase tracking-wider" style={{ color: phaseColor }}>
                  {phase}
                </span>
              </div>
              <p className="text-[10px] font-semibold leading-tight" style={{ color: '#a5bfff' }}>
                {persona}
              </p>
              <p className="text-[9px] text-[var(--text-muted)] italic leading-tight">{role}</p>
              <p className="text-[9px] text-[var(--text-muted)] leading-tight pt-0.5">{desc}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="p-4 text-center" style={{ borderTop: '1px solid rgba(91,127,255,0.12)' }}>
        <p className="text-[9px] text-[var(--text-muted)]">
          Industrial Diagnostic AI v2.0
        </p>
        <p className="text-[9px] mt-0.5" style={{ color: 'rgba(91,127,255,0.5)' }}>
          OpenAI GPT-4o · RAG · FAISS · 6-Agent
        </p>
      </div>
    </motion.aside>
  )
}
