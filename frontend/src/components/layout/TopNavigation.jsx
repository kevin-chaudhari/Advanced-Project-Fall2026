import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { cx } from '../ui'
import { useDiagnostics, DATASETS } from '../../state/DiagnosticsContext'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/dashboard', label: 'Agent dashboard' },
  { to: '/chat', label: 'Diagnostic chat' },
]

/** Brand mark: a gauge needle in a ring — plain geometry, no stock icon. */
function Mark() {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden className="shrink-0">
      <circle cx="11" cy="11" r="9.25" fill="none" stroke="#302C25" strokeWidth="1.5" />
      <path d="M4.5 13.5a6.75 6.75 0 0 1 13 0" fill="none" stroke="#D3CABA" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M11 13.2 15.2 7.6" stroke="#A68A64" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="11" cy="13.2" r="1.4" fill="#302C25" />
    </svg>
  )
}

function ConnectionStatus() {
  const { health, refreshHealth, loaded } = useDiagnostics()
  const state = !health ? 'checking' : health.offline ? 'offline' : loaded ? 'ready' : 'empty'
  const text = { checking: 'Connecting…', offline: 'Backend offline', ready: 'Connected', empty: 'Dataset not loaded' }[state]
  const dot = { checking: 'bg-slate-400 pulse-dot', offline: 'bg-danger-500', ready: 'bg-success-500', empty: 'bg-warning-500' }[state]
  const engine = health && !health.offline ? (health.llm_mode === 'llm+deterministic' ? 'LLM + deterministic agents' : 'Deterministic agents (no LLM configured)') : null
  return (
    <div className="flex items-center gap-1.5 text-[12px] text-muted" title={engine || undefined}>
      <span className={cx('w-1.5 h-1.5 rounded-full', dot)} aria-hidden />
      <span className="hidden sm:inline whitespace-nowrap">{text}</span>
      <button type="button" onClick={refreshHealth} className="btn-ghost p-1 rounded-md" aria-label="Recheck backend connection" title="Recheck connection">
        <RefreshCw size={13} />
      </button>
    </div>
  )
}

function DatasetPicker() {
  const { dataset, setDataset, health } = useDiagnostics()
  const nav = useNavigate()
  const { pathname } = useLocation()
  const onChange = (e) => {
    setDataset(e.target.value)
    if (/^\/(chat|diagnose)\/[^/]+/.test(pathname)) nav('/chat', { replace: true })
  }
  return (
    <label className="flex items-center gap-1.5 text-[12px] text-muted">
      <span className="hidden lg:inline">Dataset</span>
      <select value={dataset} onChange={onChange} aria-label="Dataset"
        className="rounded-md border border-line bg-surface py-1 pl-2 pr-7 text-[12.5px] font-medium text-ink focus-ring cursor-pointer">
        {DATASETS.map((d) => {
          const loaded = Object.values(health?.record_counts?.[d.id] || {}).some((n) => n > 0)
          return <option key={d.id} value={d.id}>{d.label}{health && !health.offline && !loaded ? ' (not loaded)' : ''}</option>
        })}
      </select>
    </label>
  )
}

export default function TopNavigation() {
  const link = ({ isActive }) => cx(
    'relative whitespace-nowrap px-1 py-3.5 text-[13px] transition-colors focus-ring rounded-sm',
    isActive ? 'text-ink font-semibold after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:bg-ink' : 'text-muted hover:text-ink',
  )
  return (
    <header className="shrink-0 border-b border-line bg-canvas/95 backdrop-blur-[2px]">
      <div className="flex items-center gap-3 sm:gap-6 px-4 sm:px-6 h-[52px]">
        <NavLink to="/" className="flex items-center gap-2 min-w-0 focus-ring rounded-md" aria-label="Industrial Diagnostic AI — overview">
          <Mark />
          <span className="text-[14px] font-semibold tracking-[-0.01em] text-ink whitespace-nowrap hidden min-[420px]:inline">Industrial Diagnostic AI</span>
        </NavLink>
        <nav className="hidden md:flex items-center gap-5 self-stretch" aria-label="Primary">
          {NAV.map((n) => <NavLink key={n.to} to={n.to} end={n.end} className={link}>{n.label}</NavLink>)}
          <span className="h-4 w-px bg-line" aria-hidden />
          <NavLink to="/analysis" className={({ isActive }) => cx(link({ isActive }), !isActive && 'text-[12.5px]')}>Data & evaluation</NavLink>
        </nav>
        <div className="ml-auto flex items-center gap-3 sm:gap-4">
          <DatasetPicker />
          <ConnectionStatus />
        </div>
      </div>
      {/* compact tab row below md */}
      <nav className="md:hidden flex items-center gap-5 overflow-x-auto px-4 border-t border-line" aria-label="Primary">
        {NAV.map((n) => <NavLink key={n.to} to={n.to} end={n.end} className={link}>{n.label}</NavLink>)}
        <NavLink to="/analysis" className={link}>Data & evaluation</NavLink>
      </nav>
    </header>
  )
}
