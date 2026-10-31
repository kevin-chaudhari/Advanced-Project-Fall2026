import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom'
import { DiagnosticsProvider, useDiagnostics, DATASETS } from './state/DiagnosticsContext'
import ApplicationLayout from './components/layout/ApplicationLayout'
import OverviewPage from './pages/OverviewPage'
import DashboardPage from './pages/DashboardPage'
import ChatPage from './pages/ChatPage'
import TraceExplorerPage from './pages/TraceExplorerPage'

// recharts is only needed on the evaluation page, so it loads on demand
const AnalysisDashboard = lazy(() => import('./pages/AnalysisDashboard'))

/** Keeps the old /diagnose/:dataset and /chat/:dataset links working: they select the dataset, then open chat. */
function DatasetRoute() {
  const { dataset } = useParams()
  const { setDataset } = useDiagnostics()
  const valid = DATASETS.some((d) => d.id === dataset)
  useEffect(() => { if (valid) setDataset(dataset) }, [dataset, valid, setDataset])
  return <Navigate to="/chat" replace />
}

export default function App() {
  return (
    <DiagnosticsProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<ApplicationLayout />}>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/traces" element={<TraceExplorerPage />} />
            <Route path="/traces/:traceId" element={<TraceExplorerPage />} />
            <Route path="/chat/:dataset" element={<DatasetRoute />} />
            <Route path="/diagnose/:dataset" element={<DatasetRoute />} />
            <Route path="/analysis" element={<Suspense fallback={<p className="p-6 text-[13px] text-muted">Loading…</p>}><AnalysisDashboard /></Suspense>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </DiagnosticsProvider>
  )
}
