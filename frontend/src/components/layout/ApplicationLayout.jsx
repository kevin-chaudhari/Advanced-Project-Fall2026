import { Outlet } from 'react-router-dom'
import TopNavigation from './TopNavigation'

/**
 * Viewport-pinned frame: the navigation is fixed height and each page owns its own scroll
 * container inside <main>, so the dashboard can fit one screen while chat scrolls.
 */
export default function ApplicationLayout() {
  return (
    <div className="h-screen h-dvh flex flex-col overflow-hidden bg-canvas">
      <TopNavigation />
      <main className="flex-1 min-h-0">
        <Outlet />
      </main>
    </div>
  )
}
