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
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Sync</h1>
        <p className="text-sm text-slate-500 mt-0.5">Trigger manual ingestion and view sync history</p>
      </div>

      {/* Trigger card */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <h2 className="text-sm font-semibold text-slate-900 mb-1">Manual ingestion</h2>
        <p className="text-xs text-slate-400 mb-4">Runs the full pipeline for one account or all accounts at once</p>

        <div className="flex flex-wrap gap-3 items-center">
          <select value={selectedAccount} onChange={e => setSelectedAccount(e.target.value)}
            className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300">
            <option value="">All accounts</option>
            {accounts.data?.map(a => (
              <option key={a.account_id} value={a.account_id}>{a.account_id}</option>
            ))}
          </select>

          <button onClick={() => trigger.mutate()} disabled={trigger.isPending || !!isAnyRunning}
            className="flex items-center gap-2 px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors">
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
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
                Run Sync
              </>
            )}
          </button>
        </div>

        {trigger.isSuccess && (
          <div className="mt-3 flex items-center gap-2 text-sm text-emerald-700 bg-emerald-50 rounded-lg px-3 py-2">
            <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
            {trigger.data?.message ?? 'Sync started'}
          </div>
        )}
        {trigger.isError && (
          <div className="mt-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
            {String(trigger.error)}
          </div>
        )}
      </div>

      {/* Status table */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-900">Last sync results</h2>
          <span className="text-xs text-slate-400 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
            Auto-refreshes every 5s
          </span>
        </div>

        {syncStatus.isLoading && (
          <div className="px-5 py-8 space-y-3">
            {[1,2,3].map(i => <div key={i} className="h-4 bg-slate-100 rounded animate-pulse" />)}
          </div>
        )}

        {syncStatus.data?.length === 0 && (
          <div className="px-5 py-10 text-center text-sm text-slate-400">No sync has run yet</div>
        )}

        {syncStatus.data && syncStatus.data.length > 0 && (
          <>
            <div className="grid grid-cols-6 px-5 py-2 bg-slate-50 text-xs font-medium text-slate-500">
              <span>Account</span>
              <span>Status</span>
              <span>OK</span>
              <span>Errors</span>
              <span>Started</span>
              <span>Finished</span>
            </div>
            <div className="divide-y divide-slate-50">
              {syncStatus.data.map(s => (
                <div key={s.account_id} className="grid grid-cols-6 px-5 py-2.5 text-xs items-center">
                  <span className="font-medium text-slate-800">{s.account_id}</span>
                  <StatusBadge value={s.running ? 'running' : 'ok'} />
                  <span className="text-emerald-700 font-medium">{s.files_ok}</span>
                  <span className={s.files_error > 0 ? 'text-red-600 font-medium' : 'text-slate-400'}>
                    {s.files_error > 0 ? s.files_error : '—'}
                  </span>
                  <span className="text-slate-400">
                    {s.started_at ? new Date(s.started_at).toLocaleTimeString('it-IT') : '—'}
                  </span>
                  <span className="text-slate-400">
                    {s.finished_at
                      ? new Date(s.finished_at).toLocaleTimeString('it-IT')
                      : s.running ? <span className="text-blue-500">running…</span> : '—'}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Info card */}
      <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 flex items-start gap-3">
        <svg className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
        <div>
          <p className="text-xs font-medium text-slate-700">Scheduled ingestion</p>
          <p className="text-xs text-slate-400 mt-0.5">The pipeline runs automatically every night at 02:00 (server time). Files are rsynced from the Italian server at 01:00.</p>
        </div>
      </div>
    </div>
  )
}
