import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchAccounts, fetchSyncStatus, triggerSync } from '../api/client'
import StatusBadge from '../components/StatusBadge'

export default function SyncPage() {
  const qc = useQueryClient()
  const [selectedAccount, setSelectedAccount] = useState('')

  const accounts = useQuery({ queryKey: ['accounts'], queryFn: fetchAccounts })
  const syncStatus = useQuery({
    queryKey: ['sync-status'],
    queryFn: fetchSyncStatus,
    refetchInterval: 5000,
  })

  const trigger = useMutation({
    mutationFn: () => triggerSync(selectedAccount || undefined),
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ['sync-status'] }), 1200)
    },
  })

  const isAnyRunning = syncStatus.data?.some(s => s.running)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Sync</h1>
        <p className="text-sm text-slate-500 mt-1">Trigger manual ingestion and monitor sync history</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Trigger card */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-6">
            <div className="flex items-center gap-3 mb-5">
              <div className="w-9 h-9 bg-blue-50 rounded-xl flex items-center justify-center">
                <svg className="w-4.5 h-4.5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-900">Manual ingestion</p>
                <p className="text-xs text-slate-400">Run the pipeline now</p>
              </div>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-slate-500 mb-1.5">Account</label>
                <select
                  value={selectedAccount}
                  onChange={e => setSelectedAccount(e.target.value)}
                  className="w-full text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300"
                >
                  <option value="">All accounts</option>
                  {accounts.data?.map(a => (
                    <option key={a.account_id} value={a.account_id}>{a.account_id}</option>
                  ))}
                </select>
              </div>

              <button
                onClick={() => trigger.mutate()}
                disabled={trigger.isPending || !!isAnyRunning}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {trigger.isPending || isAnyRunning ? (
                  <>
                    <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    {isAnyRunning ? 'Running…' : 'Starting…'}
                  </>
                ) : (
                  <>
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Run sync
                  </>
                )}
              </button>
            </div>

            {trigger.isSuccess && (
              <div className="mt-4 flex items-start gap-2 text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-xl px-3 py-2.5">
                <svg className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                {trigger.data?.message ?? 'Sync started'}
              </div>
            )}
            {trigger.isError && (
              <div className="mt-4 text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl px-3 py-2.5">
                {String(trigger.error)}
              </div>
            )}
          </div>

          {/* Schedule info */}
          <div className="mt-4 bg-slate-50 border border-slate-100 rounded-2xl p-4 flex items-start gap-3">
            <svg className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div>
              <p className="text-xs font-semibold text-slate-700">Scheduled nightly at 02:00</p>
              <p className="text-xs text-slate-400 mt-1 leading-relaxed">Files are pulled from the Italian server and processed automatically. Manual trigger is available anytime.</p>
            </div>
          </div>
        </div>

        {/* Status table */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <p className="text-sm font-semibold text-slate-900">Last sync results</p>
              <span className="flex items-center gap-1.5 text-xs text-slate-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse inline-block" />
                Live · updates every 5s
              </span>
            </div>

            {syncStatus.isLoading && (
              <div className="px-6 py-8 space-y-3">
                {[1,2,3].map(i => (
                  <div key={i} className="h-3.5 bg-slate-100 rounded animate-pulse" style={{ width: `${60 + i * 12}%` }} />
                ))}
              </div>
            )}

            {syncStatus.data?.length === 0 && (
              <div className="flex flex-col items-center justify-center py-14 text-center">
                <div className="w-10 h-10 bg-slate-50 rounded-full flex items-center justify-center mb-3">
                  <svg className="w-5 h-5 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </div>
                <p className="text-sm text-slate-400">No sync has run yet</p>
              </div>
            )}

            {syncStatus.data && syncStatus.data.length > 0 && (
              <>
                <div className="grid grid-cols-6 px-6 py-2.5 bg-slate-50 text-[10px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-100">
                  <span>Account</span>
                  <span>Status</span>
                  <span>OK</span>
                  <span>Errors</span>
                  <span>Started</span>
                  <span>Finished</span>
                </div>
                <div className="divide-y divide-slate-50">
                  {syncStatus.data.map(s => (
                    <div key={s.account_id} className="grid grid-cols-6 px-6 py-3 text-xs items-center hover:bg-slate-50/70">
                      <span className="font-semibold text-slate-800">{s.account_id}</span>
                      <StatusBadge value={s.running ? 'running' : 'ok'} />
                      <span className="text-emerald-600 font-semibold tabular-nums">{s.files_ok}</span>
                      <span className={`tabular-nums font-semibold ${s.files_error > 0 ? 'text-red-500' : 'text-slate-300'}`}>
                        {s.files_error > 0 ? s.files_error : '—'}
                      </span>
                      <span className="text-slate-400 tabular-nums">
                        {s.started_at ? new Date(s.started_at).toLocaleTimeString('it-IT') : '—'}
                      </span>
                      <span className="text-slate-400 tabular-nums">
                        {s.finished_at
                          ? new Date(s.finished_at).toLocaleTimeString('it-IT')
                          : s.running ? <span className="text-blue-500 font-medium">running…</span> : '—'}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
