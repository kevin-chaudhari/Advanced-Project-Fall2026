import { motion } from 'framer-motion'
import { CheckCircle2, AlertTriangle, FileText, Lightbulb, TrendingUp } from 'lucide-react'
import ConfidenceBar from './ConfidenceBar'
import ReasoningAccordion from './ReasoningAccordion'
import AgentContributions from './AgentContributions'
import PersonaOutputs from './PersonaOutputs'
import PhaseTestPanel from './PhaseTestPanel'

export default function DiagnosisCard({ result }) {
  const {
    final_diagnosis,
    direct_answer,
    confidence = 0,
    reasoning = [],
    supporting_evidence = [],
    agent_contributions,
    agent_outputs = [],
    ambiguity = false,
    dataset_used,
    retrieved_context_count = 0,
    phase_test_results,
  } = result

  const confidencePct = Math.round(confidence * 100)
  const isHigh = confidencePct >= 75
  const isMed  = confidencePct >= 50 && confidencePct < 75

  // Accent for the border-left strip
  const accentColor = ambiguity
    ? '#ff9f1c'
    : isHigh ? '#39ff14' : isMed ? '#ffd93d' : '#f472b6'

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-4 w-full"
    >
      {/* Direct answer banner */}
      {direct_answer && (
        <div
          className="rounded-2xl p-5"
          style={{
            borderLeft: '4px solid #7c9fff',
            background: 'rgba(91,127,255,0.07)',
            border: '1px solid rgba(91,127,255,0.25)',
            borderLeftColor: '#7c9fff',
            borderLeftWidth: '4px',
          }}
        >
          <div className="flex items-start gap-3">
            <div
              className="w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0"
              style={{ background: 'rgba(91,127,255,0.18)', border: '1px solid rgba(91,127,255,0.35)' }}
            >
              <Lightbulb size={16} style={{ color: '#a5bfff' }} />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2 flex-wrap mb-2">
                <span className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">Direct Answer</span>
                <span
                  className="text-xs px-2 py-0.5 rounded-full font-semibold"
                  style={{ background: 'rgba(91,127,255,0.15)', border: '1px solid rgba(91,127,255,0.35)', color: '#a5bfff' }}
                >
                  Question-focused output
                </span>
              </div>
              <p className="text-white font-semibold text-base leading-relaxed">{direct_answer}</p>
            </div>
          </div>
        </div>
      )}

      {/* Final diagnosis */}
      <div
        className="rounded-2xl p-5"
        style={{
          borderLeft: `4px solid ${accentColor}`,
          background: `${accentColor}09`,
          border: `1px solid ${accentColor}30`,
          borderLeftColor: accentColor,
          borderLeftWidth: '4px',
        }}
      >
        <div className="flex items-start gap-3">
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0"
            style={{ background: `${accentColor}20`, border: `1px solid ${accentColor}40` }}
          >
            {ambiguity
              ? <AlertTriangle size={16} style={{ color: '#ffd93d' }} />
              : <CheckCircle2 size={16} style={{ color: accentColor }} />
            }
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2 flex-wrap mb-2">
              <span className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">Final Synthesis</span>
              {ambiguity && (
                <span className="badge-warn text-xs px-2 py-0.5 rounded-full font-semibold">Human review advised</span>
              )}
              {dataset_used && (
                <span
                  className="text-xs px-2 py-0.5 rounded-full font-semibold capitalize"
                  style={{ background: 'rgba(91,127,255,0.15)', border: '1px solid rgba(91,127,255,0.35)', color: '#a5bfff' }}
                >
                  {dataset_used.replace('_', ' ')}
                </span>
              )}
            </div>
            <p className="text-white font-bold text-base leading-relaxed">{final_diagnosis}</p>
          </div>
        </div>
      </div>

      <PersonaOutputs agentOutputs={agent_outputs} />

      <PhaseTestPanel phaseTestResults={phase_test_results} />

      <ConfidenceBar confidence={confidence} />

      {reasoning.length > 0 && <ReasoningAccordion steps={reasoning} />}

      {supporting_evidence.length > 0 && (
        <div
          className="rounded-2xl p-5"
          style={{ background: 'rgba(10,12,30,0.75)', border: '1px solid rgba(91,127,255,0.20)' }}
        >
          <div className="flex items-center gap-2 mb-4">
            <FileText size={16} style={{ color: '#7c9fff' }} />
            <h4 className="text-sm font-bold text-white">Supporting Evidence</h4>
            <span className="text-xs text-[var(--text-muted)]">({retrieved_context_count} docs retrieved)</span>
          </div>
          <ul className="space-y-2.5">
            {supporting_evidence.map((evidence, index) => (
              <li key={index} className="flex items-start gap-2.5 text-sm text-[var(--text-muted)]">
                <span
                  className="font-mono text-xs mt-0.5 font-bold flex-shrink-0"
                  style={{ color: '#7c9fff' }}
                >
                  [{index + 1}]
                </span>
                <span className="leading-relaxed">{evidence}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {agent_contributions && <AgentContributions contributions={agent_contributions} />}
    </motion.div>
  )
}
