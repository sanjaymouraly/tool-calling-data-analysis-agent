import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import Dashboard from './pages/Dashboard'
import Datasets from './pages/Datasets'
import DatasetDetail from './pages/DatasetDetail'
import Workspace from './pages/Workspace'
import VisualBuilder from './pages/VisualBuilder'
import Reports from './pages/Reports'
import HistoryPage from './pages/HistoryPage'
import Settings from './pages/Settings'
import NotFound from './pages/NotFound'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/datasets" element={<Datasets />} />
        <Route path="/datasets/:id" element={<DatasetDetail />} />
        <Route path="/workspace" element={<Workspace />} />
        <Route path="/builder" element={<VisualBuilder />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/index.html" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  )
}
