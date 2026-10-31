import { useId, useState } from 'react'
import { ChevronRight, CheckCircle2, ShieldAlert, XCircle, CircleDashed, RotateCcw, AlertTriangle } from 'lucide-react'
import { cx } from './ui'
import { AGENT_STATUS, confidenceTone } from '../lib/diagnosis'

const TONE_TEXT = { success: 'text-success-700', warning: 'text-warning-700', danger: 'text-danger-700', muted: 'text-muted', accent: 'text-primary-700' }
const TONE_BAR = { success: 'bg-success-500', warning: 'bg-warning-500', danger: 'bg-danger-500', muted: 'bg-slate-300' }

/**
 * Confidence on a 0–100 scale with the review threshold marked.
 * The 0.65 tick is the backend's own G1 gate criterion, drawn only when the response contains it.
 */
export function ConfidenceIndicator({ value, threshold, size = 'md', showLabel = true }) {
  if (value == null) return <span className="text-sm text-muted">Confidence not reported</span>
  const v = Math.max(0, Math.min(1, value))
  const tone = confidenceTone(v)
  return (
    <div className="w-full" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v * 100)} aria-label="Confidence">
      {showLabel && (
        <div className="flex items-baseline justify-between gap-2">
          <span className={cx('font-semibold tabular-nums leading-none', size === 'lg' ? 'text-[28px]' : 'text-[15px]', TONE_TEXT[tone])}>
            {Math.round(v * 100)}<span className={size === 'lg' ? 'text-base ml-0.5' : 'text-[11px] ml-px'}>%</span>
          </span>
          <span className="text-[11.5px] text-muted">confidence</span>
        </div>
      )}
      <div className={cx('relative mt-2 rounded-full bg-well', size === 'lg' ? 'h-2' : 'h-1.5')}>
        <div className={cx('absolute inset-y-0 left-0 rounded-full transition-[width] duration-500', TONE_BAR[tone])} style={{ width: `${v * 100}%` }} />
        {threshold != null && (
          <span className="absolute -top-1 -bottom-1 w-px bg-ink/50" style={{ left: `${threshold * 100}%` }} title={`Review threshold ${Math.round(threshold * 100)}%`} aria-hidden />
        )}
      </div>
    </div>
  )
}

/** Review decision as a stamped mark: the one place a decision is shown loudly. */
export function ReviewDecision({ decision, variant = 'stamp', animate = false }) {
  if (!decision) return null
  const auto = decision === 'AUTO_RESOLVE'
  if (variant === 'inline') {
    return (
      <span className={cx('inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-semibold',
        auto ? 'border-success-100 bg-success-50 text-success-700' : 'border-warning-100 bg-warning-50 text-warning-700')}>
        {auto ? <CheckCircle2 size={12} /> : <ShieldAlert size={12} />}
        {auto ? 'Auto-resolve' : 'Human review'}
      </span>
    )
  }
  return (
    <div className={cx('inline-flex flex-col items-center justify-center rounded-lg border-2 px-3 py-1.5 -rotate-3 select-none',
      auto ? 'border-success-500 text-success-700' : 'border-warning-500 text-warning-700', animate && 'stamp-in')}
      title={auto ? 'All review-gate criteria passed' : 'At least one review-gate criterion failed'}>
      <span className="font-mono text-[11px] font-medium tracking-wide">{decision}</span>
      <span className="text-[10.5px] opacity-80">{auto ? 'no human review needed' : 'a person must confirm'}</span>
    </div>
  )
}

export function StatusMark({ status, size = 13 }) {
  const s = AGENT_STATUS[status] || AGENT_STATUS.idle
  const Icon = { done: CheckCircle2, rerun: RotateCcw, warning: AlertTriangle, failed: XCircle, idle: CircleDashed }[status] || CircleDashed
  return <Icon size={size} className={cx('shrink-0', TONE_TEXT[s.tone])} aria-label={s.label} />
}

/** Accessible disclosure. Collapsed by default unless `defaultOpen`. */
export function Disclosure({ title, meta, defaultOpen = false, children, className, headerClass, bodyClass, open: openProp, onToggle }) {
  const [inner, setInner] = useState(defaultOpen)
  const open = openProp ?? inner
  const id = useId()
  const toggle = () => (onToggle ? onToggle(!open) : setInner(!open))
  return (
    <div className={className}>
      <button type="button" onClick={toggle} aria-expanded={open} aria-controls={id}
        className={cx('group flex w-full items-center gap-2 text-left focus-ring rounded-md', headerClass)}>
        <ChevronRight size={14} className={cx('shrink-0 text-muted transition-transform duration-150', open && 'rotate-90')} aria-hidden />
        <span className="min-w-0 flex-1">{title}</span>
        {meta && <span className="shrink-0 text-[11.5px] text-muted">{meta}</span>}
      </button>
      {open && <div id={id} className={bodyClass}>{children}</div>}
    </div>
  )
}

export function Fact({ label, children, tone }) {
  return (
    <div className="min-w-0">
      <div className="text-[11.5px] text-muted">{label}</div>
      <div className={cx('text-[13px] font-medium text-ink truncate', tone && TONE_TEXT[tone])}>{children}</div>
    </div>
  )
}

/** REAL / SYNTHETIC split as one proportional bar. */
export function ProvenanceBar({ composition }) {
  if (!composition) return <span className="text-[12px] text-muted">Provenance not reported</span>
  const real = composition.real || 0, syn = composition.synthetic || 0, total = real + syn
  if (!total) return <span className="text-[12px] text-muted">No evidence records</span>
  return (
    <div>
      <div className="flex h-1.5 overflow-hidden rounded-full bg-well" aria-hidden>
        <div className="bg-primary-500" style={{ width: `${(real / total) * 100}%` }} />
        <div className="bg-secondary-500" style={{ width: `${(syn / total) * 100}%` }} />
      </div>
      <div className="mt-1.5 flex justify-between text-[11.5px] text-muted tabular-nums">
        <span><span className="inline-block w-2 h-2 rounded-sm bg-primary-500 mr-1 align-[-1px]" />{real} real</span>
        <span>{syn} synthetic<span className="inline-block w-2 h-2 rounded-full bg-secondary-500 ml-1 align-[-1px]" /></span>
      </div>
    </div>
  )
}
