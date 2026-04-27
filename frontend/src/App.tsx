import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import AccountsPage from './pages/AccountsPage'
import AccountPage from './pages/AccountPage'
import PodPage from './pages/PodPage'
import FilesPage from './pages/FilesPage'
import SyncPage from './pages/SyncPage'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<AccountsPage />} />
        <Route path="/account/:accountId" element={<AccountPage />} />
        <Route path="/account/:accountId/pod/:pod" element={<PodPage />} />
        <Route path="/files" element={<FilesPage />} />
        <Route path="/sync" element={<SyncPage />} />
      </Routes>
    </Layout>
  )
}
