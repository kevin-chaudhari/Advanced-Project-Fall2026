import { motion } from 'framer-motion'
import { User, Bot, AlertTriangle, Activity } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import DiagnosisCard from './DiagnosisCard'

export default function ChatMessage({ message }) {
  const navigate = useNavigate()

  if (message.role === 'user') {
    return (
      <div className="flex justify-end gap-3 items-start">
        <div className="max-w-[75%]">
          <p className="text-xs text-[var(--text-muted)] text-right mb-1">You</p>
          <div className="chat-bubble-user px-5 py-3 text-white text-sm leading-relaxed">
            {message.content}
          </div>
        </div>
        <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center flex-shrink-0">
          <User size={15} />
        </div>
      </div>
    )
  }

  if (message.role === 'error') {
    return (
      <div className="flex gap-3 items-start">
        <div className="w-8 h-8 rounded-full bg-red-500/20 flex items-center justify-center flex-shrink-0">
          <AlertTriangle size={15} className="text-red-400" />
        </div>
        <div className="max-w-[85%]">
          <p className="text-xs text-[var(--text-muted)] mb-1">System Error</p>
          <div className="chat-bubble-ai px-5 py-3 text-red-300 text-sm border-red-500/30">
            {message.content}
          </div>
        </div>
      </div>
    )
  }

  // assistant
  const hasAnalysis = message.content?.analysis_report
  
  return (
    <div className="flex gap-3 items-start">
      <div className="w-8 h-8 rounded-full bg-primary-500/30 border border-primary-500/50 flex items-center justify-center flex-shrink-0">
        <Bot size={15} className="text-primary-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs text-[var(--text-muted)]">Industrial Diagnostic AI</p>
          {hasAnalysis && (
            <button
              onClick={() => navigate('/analysis', { state: { analysis: message.content.analysis_report } })}
              className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-white/5 border border-white/10 hover:bg-primary-500/20 hover:border-primary-500/30 text-primary-400 text-[10px] font-bold uppercase tracking-wider transition-all"
            >
              <Activity size={12} />
              View Analysis
            </button>
          )}
        </div>
        <DiagnosisCard result={message.content} />
      </div>
    </div>
  )
}
