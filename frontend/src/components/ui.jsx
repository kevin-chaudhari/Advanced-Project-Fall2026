import { useState } from 'react'
import { AlertTriangle, CheckCircle2, ShieldAlert, Info } from 'lucide-react'

export const cx = (...c) => c.filter(Boolean).join(' ')
export const pct = (v, d = 0) => (v == null || Number.isNaN(v) ? '—' : `${(v * 100).toFixed(d)}%`)
export const fmtNum = (v, d = 2) => (v == null || Number.isNaN(v) ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }))

export function Card({ title, subtitle, right, children, className = '', pad = true }) {
  return (
    <section className={cx('card', className)}>
      {(title || right) && (
        <header className="flex items-start justify-between gap-3 px-5 pt-4">
          <div>
            {title && <h3 className="section-title">{title}</h3>}
            {subtitle && <p className="text-xs text-muted mt-0.5">{subtitle}</p>}
          </div>
          {right}
        </header>
      )}
      <div className={pad ? 'p-5' : ''}>{children}</div>
    </section>
  )
}

/** REAL / SYNTHETIC / COMBINED provenance badge */
export function SourceBadge({ source, size = 'sm' }) {
  const s = (source || '').toLowerCase()
  const styles = {
    real: 'bg-primary-50 text-primary-700 border-primary-200',
    synthetic: 'bg-secondary-50 text-secondary-700 border-secondary-100',
    combined: 'bg-slate-50 text-slate-700 border-slate-200',
  }
  return (
    <span className={cx('chip', styles[s] || styles.combined, size === 'xs' && 'px-1.5 py-0 text-[10px]')}>
      {s === 'synthetic' && <span aria-hidden className="w-1.5 h-1.5 rounded-full bg-secondary-600" />}
      {s === 'real' && <span aria-hidden className="w-1.5 h-1.5 rounded-sm bg-primary-600" />}
      {(s || 'combined').toUpperCase()}
    </span>
  )
}

export function DecisionBadge({ decision }) {
  const auto = decision === 'AUTO_RESOLVE'
  return (
    <span className={cx('chip', auto ? 'bg-success-50 text-success-700 border-success-100' : 'bg-warning-50 text-warning-700 border-warning-100')}>
      {auto ? <CheckCircle2 size={12} /> : <ShieldAlert size={12} />}
      {auto ? 'AUTO_RESOLVE' : 'REQUIRES HUMAN REVIEW'}
    </span>
  )
}

export function StatusIcon({ status, size = 14 }) {
  if (status === 'error') return <AlertTriangle size={size} className="text-danger-600" />
  if (status === 'warning') return <AlertTriangle size={size} className="text-warning-500" />
  if (status === 'loop') return <Info size={size} className="text-secondary-600" />
  return <CheckCircle2 size={size} className="text-success-600" />
}

export function StatTile({ label, value, hint, accent }) {
  return (
    <div className="rounded-lg border border-line bg-white px-4 py-3">
      <div className="eyebrow">{label}</div>
      <div className={cx('text-2xl font-semibold mt-1 tabular-nums', accent)}>{value}</div>
      {hint && <div className="text-[11px] text-muted mt-0.5">{hint}</div>}
    </div>
  )
}

export function Tabs({ tabs, initial }) {
  const [active, setActive] = useState(initial || tabs[0]?.id)
  const cur = tabs.find((t) => t.id === active) || tabs[0]
  return (
    <div>
      <div role="tablist" className="flex flex-wrap gap-1 border-b border-line px-2">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={t.id === active} onClick={() => setActive(t.id)}
            className={cx('px-3 py-2 text-[13px] font-medium border-b-2 -mb-px transition-colors',
              t.id === active ? 'border-primary-600 text-primary-700' : 'border-transparent text-muted hover:text-ink')}>
            {t.label}{t.count != null && <span className="ml-1.5 text-[11px] text-muted">{t.count}</span>}
          </button>
        ))}
      </div>
      <div className="pt-4">{cur?.render()}</div>
    </div>
  )
}

/** Evidence / derived-value ID chip, e.g. EV-003 or D-002 */
export function IdChip({ id, onClick }) {
  const isEv = id?.startsWith('EV-')
  return (
    <button type="button" onClick={onClick ? () => onClick(id) : undefined}
      className={cx('mono rounded px-1 py-px border', isEv ? 'border-primary-200 bg-primary-50 text-primary-700 hover:bg-primary-100' : 'border-slate-200 bg-slate-50 text-slate-600')}>
      {id}
    </button>
  )
}

/** Renders text, turning EV-xxx / D-xxx references into chips */
export function Cited({ text, onEvidence }) {
  if (!text) return null
  const parts = String(text).split(/(\bEV-\d{3,}\b|\bD-\d{3,}\b)/g)
  return (
    <span>
      {parts.map((p, i) => (/^(EV|D)-\d{3,}$/.test(p) ? <IdChip key={i} id={p} onClick={p.startsWith('EV-') ? onEvidence : undefined} /> : <span key={i}>{p}</span>))}
    </span>
  )
}

export function Empty({ children }) {
  return <p className="text-sm text-muted italic">{children}</p>
}

export function Meter({ value, color = 'bg-primary-600', label }) {
  const v = Math.max(0, Math.min(1, value || 0))
  return (
    <div className="flex items-center gap-2" aria-label={label}>
      <div className="h-1.5 flex-1 rounded-full bg-slate-100 overflow-hidden">
        <div className={cx('h-full rounded-full', color)} style={{ width: `${v * 100}%` }} />
      </div>
      <span className="w-10 text-right text-xs tabular-nums text-ink">{v.toFixed(2)}</span>
    </div>
  )
}
