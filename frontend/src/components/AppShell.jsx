import { NavLink } from 'react-router-dom'
import { Activity, Database, LayoutDashboard, Home, Factory } from 'lucide-react'
import { cx } from './ui'

const NAV = [
  { to: '/', label: 'Overview', icon: Home, end: true },
  { to: '/diagnose/afrb', label: 'Diagnose · AFRB sensors', icon: Activity },
  { to: '/diagnose/failure_iq', label: 'Diagnose · FailureSensorIQ', icon: Database },
  { to: '/analysis', label: 'Data & evaluation', icon: LayoutDashboard },
]

export default function AppShell({ children, aside }) {
  return (
    <div className="min-h-screen flex bg-canvas">
      <aside className="hidden md:flex w-64 shrink-0 flex-col border-r border-line bg-white">
        <div className="flex items-center gap-2 px-5 h-14 border-b border-line">
          <div className="w-8 h-8 rounded-lg bg-primary-600 text-white flex items-center justify-center"><Factory size={16} /></div>
          <div>
            <div className="text-[13px] font-semibold leading-tight">Industrial Diagnostic AI</div>
            <div className="text-[11px] text-muted leading-tight">six-agent harness</div>
          </div>
        </div>
        <nav className="p-3 space-y-0.5">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => cx('flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px]',
                isActive ? 'bg-primary-50 text-primary-700 font-medium' : 'text-muted hover:bg-slate-50 hover:text-ink')}>
              <Icon size={15} /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="flex-1 overflow-y-auto px-3 pb-4">{aside}</div>
      </aside>
      <main className="flex-1 min-w-0">{children}</main>
    </div>
  )
}
