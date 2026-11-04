import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { Activity, Database, LayoutDashboard, Home, Factory, Menu, X, Gauge } from 'lucide-react'
import { cx } from './ui'

const NAV = [
  { to: '/', label: 'Overview', icon: Home, end: true },
  { to: '/diagnose/afrb', label: 'Diagnose · AFRB sensors', icon: Activity },
  { to: '/diagnose/failure_iq', label: 'Diagnose · FailureSensorIQ', icon: Database },
  { to: '/diagnose/hydraulic', label: 'Diagnose · Hydraulic rig (real)', icon: Gauge },
  { to: '/analysis', label: 'Data & evaluation', icon: LayoutDashboard },
]

function Brand() {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="w-8 h-8 shrink-0 rounded-lg bg-primary-600 text-white flex items-center justify-center"><Factory size={16} /></div>
      <div className="min-w-0">
        <div className="text-[13px] font-semibold leading-tight truncate">Mission Control for Agentic AI</div>
        <div className="text-[11px] text-muted leading-tight">six-agent harness</div>
      </div>
    </div>
  )
}

/**
 * Application frame.
 *
 * The frame is pinned to the viewport (h-dvh + overflow-hidden) so the sidebar and the main
 * column each own an independent scroll container. Previously the root was `min-h-screen`,
 * which let a long sidebar stretch the whole document: the page scrolled as one unit, the
 * sidebar's top scrolled away and blank space appeared under the main column.
 *
 * Below `md` the sidebar becomes an off-canvas drawer. Any element inside it marked with
 * `data-drawer-close` (e.g. a scenario button) closes the drawer after its own click handler.
 */
export default function AppShell({ children, aside }) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const { pathname } = useLocation()
  useEffect(() => { setDrawerOpen(false) }, [pathname])
  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (e) => { if (e.key === 'Escape') setDrawerOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  const onAsideClick = (e) => { if (e.target.closest?.('[data-drawer-close]')) setDrawerOpen(false) }

  return (
    <div className="h-screen h-dvh flex flex-col md:flex-row overflow-hidden bg-canvas">
      {/* Mobile top bar (sidebar is a drawer below md) */}
      <div className="md:hidden shrink-0 h-12 flex items-center justify-between gap-2 border-b border-line bg-white px-3">
        <Brand />
        <button type="button" className="btn-ghost px-2" aria-label="Open navigation" aria-expanded={drawerOpen}
          aria-controls="app-sidebar" onClick={() => setDrawerOpen(true)}>
          <Menu size={18} />
        </button>
      </div>

      {drawerOpen && (
        <div className="md:hidden fixed inset-0 z-40 bg-slate-900/30 de-fade" aria-hidden onClick={() => setDrawerOpen(false)} />
      )}

      <aside id="app-sidebar" onClick={onAsideClick}
        className={cx(
          'flex flex-col bg-white border-r border-line w-[min(20rem,88vw)] md:w-64 lg:w-72 shrink-0 min-h-0',
          'fixed inset-y-0 left-0 z-50 transition-transform duration-200 md:static md:z-auto md:translate-x-0 md:h-full',
          drawerOpen ? 'translate-x-0 shadow-lift' : '-translate-x-full',
        )}
        aria-label="Primary">
        <div className="flex items-center justify-between gap-2 px-5 h-14 shrink-0 border-b border-line">
          <Brand />
          <button type="button" className="md:hidden btn-ghost px-1.5" aria-label="Close navigation" onClick={() => setDrawerOpen(false)}>
            <X size={16} />
          </button>
        </div>
        <nav className="p-3 space-y-0.5 shrink-0 border-b border-line">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => cx('flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px]',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
                isActive ? 'bg-primary-50 text-primary-700 font-medium' : 'text-muted hover:bg-slate-50 hover:text-ink')}>
              <Icon size={15} className="shrink-0" /> <span className="truncate">{label}</span>
            </NavLink>
          ))}
        </nav>
        {/* Independent scroll region for page-specific controls */}
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-3 pb-6">{aside}</div>
      </aside>

      {/* Main column scrolls on its own; pages that need a fixed header/footer fill it with h-full */}
      <main className="flex-1 min-w-0 min-h-0 overflow-y-auto">{children}</main>
    </div>
  )
}
