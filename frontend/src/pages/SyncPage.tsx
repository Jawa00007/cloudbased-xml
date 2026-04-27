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
      setTimeout(() => qc.invalidateQueries({ queryKey: ['sync-status'] }), 1000)
    },
  })

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-gray-900">Sync</h1>

      {/* Trigger */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
        <h2 className="text-sm font-semibold text-gray-700">Manual ingestion trigger</h2>
        <div className="flex gap-3 items-center">
          <select
            value={selectedAccount}
            onChange={(e) => setSelectedAccount(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
          >
            <option value="">All accounts</option>
            {accounts.data?.map((a) => (
              <option key={a.account_id} value={a.account_id}>{a.account_id}</option>
            ))}
          </select>
          <button
            onClick={() => trigger.mutate()}
            disabled={trigger.isPending}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {trigger.isPending ? 'Starting…' : 'Run Sync'}
          </button>
        </div>
        {trigger.isSuccess && (
          <p className="text-sm text-green-700">{trigger.data?.message}</p>
        )}
        {trigger.isError && (
          <p className="text-sm text-red-600">{String(trigger.error)}</p>
        )}
      </div>

      {/* Status table */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Last sync status</h2>
          <span className="text-xs text-gray-400">Refreshes every 5s</span>
        </div>

        {syncStatus.isLoading && <p className="p-4 text-gray-400 text-sm">Loading…</p>}

        {syncStatus.data && syncStatus.data.length === 0 && (
          <p className="p-4 text-gray-400 text-sm">No sync has run yet.</p>
        )}

        {syncStatus.data && syncStatus.data.length > 0 && (
          <>
            <div className="px-4 py-2 border-b border-gray-100 text-xs font-semibold text-gray-500 grid grid-cols-6">
              <span>Account</span>
              <span>Status</span>
              <span>OK</span>
              <span>Errors</span>
              <span>Started</span>
              <span>Finished</span>
            </div>
            <div className="divide-y divide-gray-50">
              {syncStatus.data.map((s) => (
                <div key={s.account_id} className="px-4 py-2.5 text-xs grid grid-cols-6">
                  <span className="font-medium text-gray-800">{s.account_id}</span>
                  <StatusBadge value={s.running ? 'running' : 'ok'} />
                  <span className="text-green-700">{s.files_ok}</span>
                  <span className={s.files_error > 0 ? 'text-red-600 font-medium' : 'text-gray-400'}>
                    {s.files_error}
                  </span>
                  <span className="text-gray-400">
                    {s.started_at ? new Date(s.started_at).toLocaleTimeString() : '—'}
                  </span>
                  <span className="text-gray-400">
                    {s.finished_at ? new Date(s.finished_at).toLocaleTimeString() : s.running ? 'running…' : '—'}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
