import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAccounts, fetchFiles } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import { exportCSV } from '../utils/export'

const STATUS_OPTIONS = ['', 'ok', 'error', 'skipped', 'duplicate']

const STATUS_COLORS: Record<string, string> = {
  ok:        'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200 hover:ring-emerald-300',
  error:     'bg-red-50 text-red-600 ring-1 ring-inset ring-red-200 hover:ring-red-300',
  duplicate: 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200 hover:ring-amber-300',
  skipped:   'bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200 hover:ring-slate-300',
}

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
    const key = f.status ?? 'unknown'
    acc[key] = (acc[key] ?? 0) + 1
    return acc
  }, {}) ?? {}

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">File Log</h1>
        <p className="text-sm text-slate-500 mt-1">Ingestion history, status and error details</p>
      </div>

      {/* Filter bar */}
      <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">Filters</p>
        <div className="flex flex-wrap gap-3">
          <select
            value={account}
            onChange={e => setAccount(e.target.value)}
            className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300 min-w-[160px]"
          >
            <option value="">— Select account —</option>
            {accounts.data?.map(a => (
              <option key={a.account_id} value={a.account_id}>{a.account_id}</option>
            ))}
          </select>

          <select
            value={status}
            onChange={e => setStatus(e.target.value)}
            className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300"
          >
            {STATUS_OPTIONS.map(s => (
              <option key={s} value={s}>{s || 'All statuses'}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Empty prompt */}
      {!account && (
        <div className="bg-white border border-slate-100 rounded-2xl shadow-sm flex flex-col items-center justify-center py-16">
          <div className="w-12 h-12 bg-slate-50 rounded-full flex items-center justify-center mb-3">
            <svg className="w-6 h-6 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <p className="text-sm text-slate-500 font-medium">Select an account</p>
          <p className="text-xs text-slate-400 mt-1">Choose an account above to view its ingestion log</p>
        </div>
      )}

      {account && (
        <>
          {/* Status summary pills */}
          {files.data && (
            <div className="flex flex-wrap items-center gap-2">
              {(['ok', 'error', 'duplicate', 'skipped'] as const).map(s => {
                const n = countsByStatus[s] ?? 0
                if (!n && status && status !== s) return null
                return (
                  <button
                    key={s}
                    onClick={() => setStatus(status === s ? '' : s)}
                    className={`text-xs px-3 py-1 rounded-full font-semibold transition-all ${STATUS_COLORS[s]} ${
                      status && status !== s ? 'opacity-30' : ''
                    }`}
                  >
                    {n.toLocaleString()} {s}
                  </button>
                )
              })}
              <span className="text-xs text-slate-300 mx-1">·</span>
              <span className="text-xs text-slate-400">{files.data.length.toLocaleString()} total shown</span>

              {files.data.length > 0 && (
                <button
                  onClick={() => exportCSV(files.data!, `files_${account}${status ? '_' + status : ''}.csv`)}
                  className="ml-auto flex items-center gap-1.5 text-xs text-slate-500 hover:text-blue-600 border border-slate-200 hover:border-blue-300 rounded-lg px-3 py-1.5 bg-white transition-all"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Export CSV
                </button>
              )}
            </div>
          )}

          {/* Table */}
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
            <div className="grid grid-cols-6 px-6 py-3 bg-slate-50 text-[10px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-100">
              <span className="col-span-2">File name</span>
              <span>Flow · Month</span>
              <span>Processed</span>
              <span>Status</span>
              <span>Error</span>
            </div>

            {files.isLoading && (
              <div className="px-6 py-8 space-y-3">
                {[1,2,3,4,5].map(i => (
                  <div key={i} className="h-3.5 bg-slate-100 rounded animate-pulse" style={{ width: `${55 + i * 8}%` }} />
                ))}
              </div>
            )}

            {files.data?.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="w-10 h-10 bg-emerald-50 rounded-full flex items-center justify-center mb-3">
                  <svg className="w-5 h-5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <p className="text-sm text-slate-500">No files found</p>
              </div>
            )}

            {files.data && files.data.length > 0 && (
              <div className="divide-y divide-slate-50 max-h-[60vh] overflow-y-auto scrollbar-thin">
                {files.data.map(f => (
                  <div key={f.file_id} className="grid grid-cols-6 px-6 py-2.5 text-xs hover:bg-slate-50/70 items-center">
                    <span className="col-span-2 font-mono text-slate-600 text-[11px] truncate" title={f.file_name}>
                      {f.file_name}
                    </span>
                    <span className="text-slate-500">
                      {f.cod_flusso ?? '—'}{f.mese_anno ? ` · ${f.mese_anno}` : ''}
                    </span>
                    <span className="text-slate-400 tabular-nums">
                      {f.processed_at
                        ? new Date(f.processed_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })
                        : '—'}
                    </span>
                    <span><StatusBadge value={f.status} /></span>
                    <span className="text-red-500 text-[10px] truncate" title={f.error_message ?? ''}>
                      {f.error_message ?? ''}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
