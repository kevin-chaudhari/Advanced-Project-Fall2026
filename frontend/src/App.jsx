import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import ChatPage from './pages/ChatPage'
import AnalysisDashboard from './pages/AnalysisDashboard'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/diagnose/:dataset" element={<ChatPage />} />
        <Route path="/chat/:dataset" element={<ChatPage />} />
        <Route path="/analysis" element={<AnalysisDashboard />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
