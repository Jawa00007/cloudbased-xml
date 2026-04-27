import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAccounts, fetchFiles } from '../api/client'
import StatusBadge from '../components/StatusBadge'

const STATUS_OPTIONS = ['', 'ok', 'error', 'skipped', 'duplicate']

export default function FilesPage() {
  const [account, setAccount] = useState('')
  const [status, setStatus] = useState('')

  const accounts = useQuery({ queryKey: ['accounts'], queryFn: fetchAccounts })

  const files = useQuery({
    queryKey: ['files', account, status],
    queryFn: () => fetchFiles(account, status || undefined),
    enabled: !!account,
  })

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-gray-900">File Ingestion Log</h1>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select
          value={account}
          onChange={(e) => setAccount(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
        >
          <option value="">— Select account —</option>
          {accounts.data?.map((a) => (
            <option key={a.account_id} value={a.account_id}>{a.account_id}</option>
          ))}
        </select>

        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s || 'All statuses'}</option>
          ))}
        </select>
      </div>

      {!account && (
        <p className="text-gray-400 text-sm">Select an account to view files.</p>
      )}

      {files.isLoading && <p className="text-gray-500 text-sm">Loading…</p>}
      {files.error && <p className="text-red-500 text-sm">Error: {String(files.error)}</p>}

      {files.data && (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <div className="px-4 py-2 border-b border-gray-100 text-xs font-semibold text-gray-500 grid grid-cols-6">
            <span className="col-span-2">File</span>
            <span>Flow / Month</span>
            <span>Processed</span>
            <span>Status</span>
            <span>Error</span>
          </div>
          <div className="max-h-[70vh] overflow-y-auto divide-y divide-gray-50">
            {files.data.length === 0 && (
              <p className="px-4 py-6 text-gray-400 text-sm">No files found.</p>
            )}
            {files.data.map((f) => (
              <div key={f.file_id} className="px-4 py-2 text-xs grid grid-cols-6 hover:bg-gray-50">
                <span className="col-span-2 font-mono text-gray-700 truncate" title={f.file_name}>
                  {f.file_name}
                </span>
                <span className="text-gray-500">
                  {f.cod_flusso ?? '—'} {f.mese_anno ? `· ${f.mese_anno}` : ''}
                </span>
                <span className="text-gray-400">
                  {f.processed_at ? new Date(f.processed_at).toLocaleString() : '—'}
                </span>
                <span><StatusBadge value={f.status} /></span>
                <span className="text-red-500 truncate" title={f.error_message ?? ''}>
                  {f.error_message ?? ''}
                </span>
              </div>
            ))}
          </div>
          <div className="px-4 py-2 border-t border-gray-100 text-xs text-gray-400">
            {files.data.length} files shown
          </div>
        </div>
      )}
    </div>
  )
}
