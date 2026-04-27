import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAccounts, fetchFiles } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import { exportCSV } from '../utils/export'

const STATUS_OPTIONS = ['', 'ok', 'error', 'skipped', 'duplicate']

export default function FilesPage() {
  const [account, setAccount] = useState('')
  const [status, setStatus] = useState('')

  const accounts = useQuery({ queryKey: ['accounts'], queryFn: fetchAccounts })

  const files = useQuery({
    queryKey: ['files', account, status],
    queryFn: () => fetchFiles(account, status || undefined, 500),
    enabled: !!account,
  })

  const countsByStatus = files.data?.reduce<Record<string, number>>((acc, f) => {
    acc[f.status] = (acc[f.status] ?? 0) + 1
    return acc
  }, {}) ?? {}

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">File Log</h1>
        <p className="text-sm text-slate-500 mt-0.5">Ingestion history and error details</p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select value={account} onChange={e => setAccount(e.target.value)}
          className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300">
          <option value="">— Select account —</option>
          {accounts.data?.map(a => <option key={a.account_id} value={a.account_id}>{a.account_id}</option>)}
        </select>

        <select value={status} onChange={e => setStatus(e.target.value)}
          className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300">
          {STATUS_OPTIONS.map(s => (
            <option key={s} value={s}>{s || 'All statuses'}</option>
          ))}
        </select>
      </div>

      {!account && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-8 text-center">
          <p className="text-sm text-slate-400">Select an account to view ingestion logs</p>
        </div>
      )}

      {account && (
        <>
          {/* Summary pills */}
          {files.data && (
            <div className="flex flex-wrap gap-2">
              {(['ok', 'error', 'duplicate', 'skipped'] as const).map(s => {
                const n = countsByStatus[s] ?? 0
                if (!n && status && status !== s) return null
                const colors: Record<string, string> = {
                  ok:        'bg-emerald-50 text-emerald-700 ring-emerald-200',
                  error:     'bg-red-50 text-red-700 ring-red-200',
                  duplicate: 'bg-amber-50 text-amber-700 ring-amber-200',
                  skipped:   'bg-slate-100 text-slate-600 ring-slate-200',
                }
                return (
                  <button key={s} onClick={() => setStatus(status === s ? '' : s)}
                    className={`text-xs px-2.5 py-1 rounded-full ring-1 ring-inset font-medium transition-opacity ${colors[s]} ${status && status !== s ? 'opacity-40' : ''}`}>
                    {n} {s}
                  </button>
                )
              })}
              {files.data.length > 0 && (
                <button onClick={() => exportCSV(files.data!, `files_${account}${status ? '_' + status : ''}.csv`)}
                  className="ml-auto text-xs text-slate-500 hover:text-blue-600 flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                  Export CSV
                </button>
              )}
            </div>
          )}

          {/* Table */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="grid grid-cols-6 px-5 py-2 bg-slate-50 text-xs font-medium text-slate-500 border-b border-slate-100">
              <span className="col-span-2">File</span>
              <span>Flow · Month</span>
              <span>Processed</span>
              <span>Status</span>
              <span>Error</span>
            </div>

            {files.isLoading && (
              <div className="px-5 py-8 space-y-3">
                {[1,2,3,4,5].map(i => <div key={i} className="h-4 bg-slate-100 rounded animate-pulse" />)}
              </div>
            )}

            {files.data?.length === 0 && (
              <div className="px-5 py-10 text-center text-sm text-slate-400">No files found</div>
            )}

            {files.data && files.data.length > 0 && (
              <div className="divide-y divide-slate-50 max-h-[65vh] overflow-y-auto scrollbar-thin">
                {files.data.map(f => (
                  <div key={f.file_id} className="grid grid-cols-6 px-5 py-2 text-xs hover:bg-slate-50">
                    <span className="col-span-2 font-mono text-slate-700 truncate" title={f.file_name}>{f.file_name}</span>
                    <span className="text-slate-500">
                      {f.cod_flusso ?? '—'}{f.mese_anno ? ` · ${f.mese_anno}` : ''}
                    </span>
                    <span className="text-slate-400">
                      {f.processed_at ? new Date(f.processed_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' }) : '—'}
                    </span>
                    <span><StatusBadge value={f.status} /></span>
                    <span className="text-red-500 truncate" title={f.error_message ?? ''}>{f.error_message ?? ''}</span>
                  </div>
                ))}
              </div>
            )}

            {files.data && (
              <div className="px-5 py-2 border-t border-slate-100 text-xs text-slate-400">
                {files.data.length} files shown
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
