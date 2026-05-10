import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchAccounts, fetchSyncStatus, triggerSync } from '../api/client'
import StatusBadge from '../components/StatusBadge'

function fmtElapsed(secs: number): string {
  if (secs < 60) return `${secs}s`
  const m = Math.floor(secs / 60)
  const s = secs % 60
  if (m < 60) return `${m}m ${s}s`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

function fmtRelative(iso: string | null): string {
  if (!iso) return '—'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function fmtNextRun(iso: string | null): string {
  if (!iso) return '—'
  const diff = Math.floor((new Date(iso).getTime() - Date.now()) / 1000)
  if (diff < 0) return 'soon'
  if (diff < 3600) return `in ${Math.floor(diff / 60)}m`
  if (diff < 86400) return `in ${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m`
  return new Date(iso).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })
}

export default function SyncPage() {
  const qc = useQueryClient()
  const [selectedAccount, setSelectedAccount] = useState('')

  const accounts = useQuery({ queryKey: ['accounts'], queryFn: fetchAccounts })
  const syncStatus = useQuery({
    queryKey: ['sync-status'],
    queryFn: fetchSyncStatus,
    refetchInterval: 3000,
  })

  const trigger = useMutation({
    mutationFn: () => triggerSync(selectedAccount || undefined),
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ['sync-status'] }), 1000)
    },
  })

  const statuses = syncStatus.data ?? []
  const isRunning = statuses.some(s => s.running)
  const first = statuses[0]

  // Progress from any running row
  const running = statuses.find(s => s.running)
  const elapsedSecs = running?.elapsed_seconds ?? null
  const accountsDone = running?.accounts_done ?? null
  const accountsTotal = running?.accounts_total ?? null
  const currentAccount = running?.current_account ?? null
  const triggeredBy = running?.triggered_by ?? null
  const nextRun = first?.next_run ?? null

  // Last completed sync — most recent finished_at across all accounts
  const lastFinishedArr = statuses.map(s => s.finished_at).filter(Boolean).sort()
  const lastFinished = lastFinishedArr.length > 0 ? lastFinishedArr[lastFinishedArr.length - 1] : null

  const progressPct = accountsDone !== null && accountsTotal && accountsTotal > 0
    ? Math.round((accountsDone / accountsTotal) * 100)
    : null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Sync</h1>
        <p className="text-sm text-slate-500 mt-1">Trigger manual ingestion and monitor sync history</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Left column */}
        <div className="lg:col-span-1 space-y-4">

          {/* Trigger card */}
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
                  disabled={isRunning}
                  className="w-full text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300 disabled:opacity-50"
                >
                  <option value="">All accounts</option>
                  {accounts.data?.map(a => (
                    <option key={a.account_id} value={a.account_id}>{a.account_id}</option>
                  ))}
                </select>
              </div>

              <button
                onClick={() => trigger.mutate()}
                disabled={trigger.isPending || isRunning}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {trigger.isPending || isRunning ? (
                  <>
                    <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    {isRunning ? 'Sync running…' : 'Starting…'}
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

            {trigger.isSuccess && !isRunning && (
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

          {/* Schedule info card */}
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5 space-y-4">
            <p className="text-xs font-semibold text-slate-700 uppercase tracking-wide">Schedule</p>

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <svg className="w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                Last sync
              </div>
              <span className="text-xs font-semibold text-slate-800">{fmtRelative(lastFinished)}</span>
            </div>

            {lastFinished && (
              <div className="text-[10px] text-slate-400 -mt-2">
                {new Date(lastFinished).toLocaleString('it-IT', { dateStyle: 'medium', timeStyle: 'short' })}
              </div>
            )}

            <div className="border-t border-slate-100 pt-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <svg className="w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Next nightly run
              </div>
              <span className="text-xs font-semibold text-blue-700">{fmtNextRun(nextRun)}</span>
            </div>

            {nextRun && (
              <div className="text-[10px] text-slate-400 -mt-2">
                {new Date(nextRun).toLocaleString('it-IT', { dateStyle: 'medium', timeStyle: 'short' })} UTC
              </div>
            )}

            <div className="border-t border-slate-100 pt-3 space-y-1.5">
              <div className="flex items-center gap-1.5 text-[10px] text-slate-500 font-medium">
                <svg className="w-3 h-3 text-slate-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
                Nightly ingestion at 02:00 UTC
              </div>
              <div className="text-[10px] text-slate-400 leading-relaxed">
                Files are also pulled every 2 hours (30 */2 * * *) from the Italian server, then ingested automatically.
              </div>
            </div>
          </div>

          {/* Live progress card — only while running */}
          {isRunning && (
            <div className="bg-blue-50 border border-blue-100 rounded-2xl p-5 space-y-3">
              <div className="flex items-center gap-2">
                <svg className="w-3.5 h-3.5 text-blue-600 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                <span className="text-xs font-semibold text-blue-800">
                  {triggeredBy === 'scheduler' ? 'Nightly sync running' : 'Manual sync running'}
                </span>
              </div>

              {currentAccount && (
                <div className="text-xs text-blue-700">
                  Processing: <span className="font-semibold">{currentAccount}</span>
                </div>
              )}

              {accountsDone !== null && accountsTotal !== null && accountsTotal > 0 && (
                <div className="space-y-1.5">
                  <div className="flex justify-between text-[10px] text-blue-600">
                    <span>{accountsDone} / {accountsTotal} accounts</span>
                    <span>{progressPct}%</span>
                  </div>
                  <div className="w-full h-1.5 bg-blue-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-600 rounded-full transition-all duration-500"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </div>
              )}

              {elapsedSecs !== null && (
                <div className="text-[10px] text-blue-500">
                  Elapsed: {fmtElapsed(elapsedSecs)}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Status table */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <p className="text-sm font-semibold text-slate-900">Sync history — per account</p>
              <span className="flex items-center gap-1.5 text-xs text-slate-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse inline-block" />
                Live · updates every 3s
              </span>
            </div>

            {syncStatus.isLoading && (
              <div className="px-6 py-8 space-y-3">
                {[1, 2, 3].map(i => (
                  <div key={i} className="h-3.5 bg-slate-100 rounded animate-pulse" style={{ width: `${60 + i * 12}%` }} />
                ))}
              </div>
            )}

            {statuses.length === 0 && !syncStatus.isLoading && (
              <div className="flex flex-col items-center justify-center py-14 text-center">
                <div className="w-10 h-10 bg-slate-50 rounded-full flex items-center justify-center mb-3">
                  <svg className="w-5 h-5 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </div>
                <p className="text-sm text-slate-400">No sync has run yet</p>
              </div>
            )}

            {statuses.length > 0 && (
              <>
                <div className="grid grid-cols-7 px-6 py-2.5 bg-slate-50 text-[10px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-100">
                  <span>Account</span>
                  <span>Status</span>
                  <span>OK</span>
                  <span>Errors</span>
                  <span>Last run</span>
                  <span>Source</span>
                  <span>Finished</span>
                </div>
                <div className="divide-y divide-slate-50">
                  {statuses.map(s => (
                    <div
                      key={s.account_id}
                      className={`grid grid-cols-7 px-6 py-3 text-xs items-center transition-colors ${
                        s.running && s.current_account === s.account_id
                          ? 'bg-blue-50/60'
                          : 'hover:bg-slate-50/70'
                      }`}
                    >
                      <span className="font-semibold text-slate-800 flex items-center gap-1.5">
                        {s.running && s.current_account === s.account_id && (
                          <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse flex-shrink-0" />
                        )}
                        {s.account_id}
                      </span>
                      <StatusBadge value={s.running ? 'running' : (s.finished_at ? 'ok' : 'idle')} />
                      <span className="text-emerald-600 font-semibold tabular-nums">
                        {s.files_ok > 0 ? s.files_ok.toLocaleString() : '—'}
                      </span>
                      <span className={`tabular-nums font-semibold ${s.files_error > 0 ? 'text-red-500' : 'text-slate-300'}`}>
                        {s.files_error > 0 ? s.files_error : '—'}
                      </span>
                      <span className="text-slate-400 tabular-nums text-[10px]">
                        {fmtRelative(s.finished_at)}
                      </span>
                      <span className="tabular-nums">
                        {s.running
                          ? (s.triggered_by === 'scheduler'
                            ? <span className="text-purple-600 text-[10px] font-medium bg-purple-50 px-1.5 py-0.5 rounded-md">nightly</span>
                            : <span className="text-blue-600 text-[10px] font-medium bg-blue-50 px-1.5 py-0.5 rounded-md">manual</span>)
                          : s.triggered_by === 'scheduler'
                          ? <span className="text-purple-500 text-[10px] font-medium bg-purple-50 px-1.5 py-0.5 rounded-md">nightly</span>
                          : s.triggered_by === 'api'
                          ? <span className="text-blue-500 text-[10px] font-medium bg-blue-50 px-1.5 py-0.5 rounded-md">manual</span>
                          : <span className="text-slate-300">—</span>}
                      </span>
                      <span className="text-slate-400 tabular-nums">
                        {s.running && s.current_account === s.account_id
                          ? <span className="text-blue-500 font-medium animate-pulse">active…</span>
                          : s.running
                          ? <span className="text-slate-300">waiting</span>
                          : s.finished_at
                          ? new Date(s.finished_at).toLocaleTimeString('it-IT')
                          : '—'}
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
