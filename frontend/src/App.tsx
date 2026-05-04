import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import LoginPage from './pages/LoginPage'
import AccountsPage from './pages/AccountsPage'
import AccountPage from './pages/AccountPage'
import PodPage from './pages/PodPage'
import FilesPage from './pages/FilesPage'
import SyncPage from './pages/SyncPage'
import MonitoringPage from './pages/MonitoringPage'
import ForecastPage from './pages/ForecastPage'
import AdminPage from './pages/AdminPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <Layout>
              <Routes>
                <Route path="/" element={<AccountsPage />} />
                <Route path="/account/:accountId" element={<AccountPage />} />
                <Route path="/account/:accountId/pod/:pod" element={<PodPage />} />
                <Route path="/files" element={<FilesPage />} />
                <Route path="/sync" element={<SyncPage />} />
                <Route path="/monitoring" element={<MonitoringPage />} />
                <Route path="/forecast" element={<ForecastPage />} />
                <Route path="/admin" element={<AdminPage />} />
              </Routes>
            </Layout>
          </ProtectedRoute>
        }
      />
    </Routes>
  )
}
