import { useQuery } from '@tanstack/react-query'
import { fetchSystemStatus, getCurrentUser } from '../api/client'
import type { ContainerStatus, SchemaSize } from '../api/types'

function GaugeBar({ pct }: { pct: number }) {
  const color = pct >= 90 ? 'bg-red-500' : pct >= 75 ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
      <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

function ContainerRow({ c }: { c: ContainerStatus }) {
  const dot = c.healthy === true
    ? 'bg-emerald-500'
    : c.healthy === false
    ? 'bg-red-500'
    : c.status === 'running'
    ? 'bg-emerald-400'
    : 'bg-slate-300'
  return (
    <tr className="border-t border-slate-50 hover:bg-slate-50 transition-colors">
      <td className="px-5 py-2.5 text-xs font-mono text-slate-700">{c.name}</td>
      <td className="px-4 py-2.5">
        <span className="flex items-center gap-1.5 text-xs text-slate-600">
          <span className={`w-2 h-2 rounded-full ${dot}`} />
          {c.status}
        </span>
      </td>
      <td className="px-4 py-2.5 text-xs text-slate-500">
        {c.healthy === true ? 'healthy' : c.healthy === false ? 'unhealthy' : '—'}
      </td>
    </tr>
  )
}

function SchemaRow({ s }: { s: SchemaSize }) {
  return (
    <tr className="border-t border-slate-50 hover:bg-slate-50 transition-colors">
      <td className="px-5 py-2.5 text-xs font-mono text-slate-700">{s.schema}</td>
      <td className="px-4 py-2.5 text-xs tabular-nums text-right text-slate-600">{s.size_mb.toLocaleString()} MB</td>
      <td className="px-4 py-2.5 text-xs tabular-nums text-right text-slate-500">
        {s.est_rows > 0 ? `~${(s.est_rows / 1_000_000).toFixed(1)}M` : '—'}
      </td>
    </tr>
  )
}

export default function SystemPage() {
  const user = getCurrentUser()

  const { data: status, isLoading, isError, refetch } = useQuery({
    queryKey: ['system-status'],
    queryFn: fetchSystemStatus,
    refetchInterval: 30_000,
    enabled: user?.is_admin === true,
  })

  if (!user?.is_admin) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-sm text-slate-400">Admin access required.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">System Status</h1>
          <p className="text-sm text-slate-500 mt-0.5">Server health, disk, containers and database. Auto-refreshes every 30s.</p>
        </div>
        <button
          onClick={() => refetch()}
          className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center h-40">
          <p className="text-sm text-slate-400">Loading system status…</p>
        </div>
      )}

      {isError && (
        <div className="bg-red-50 rounded-2xl border border-red-100 p-5">
          <p className="text-sm text-red-600">Failed to load system status. The server may be unreachable.</p>
        </div>
      )}

      {status && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Disk */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5 space-y-4">
            <h2 className="text-sm font-semibold text-slate-700">Disk Usage</h2>
            <GaugeBar pct={status.disk.used_pct} />
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: 'Total', value: `${status.disk.total_gb} GB` },
                { label: 'Used', value: `${status.disk.used_gb} GB` },
                { label: 'Free', value: `${status.disk.free_gb} GB` },
              ].map(({ label, value }) => (
                <div key={label} className="text-center">
                  <p className="text-lg font-semibold text-slate-900 tabular-nums">{value}</p>
                  <p className="text-xs text-slate-400 mt-0.5">{label}</p>
                </div>
              ))}
            </div>
            <p className={`text-center text-sm font-medium ${status.disk.used_pct >= 90 ? 'text-red-600' : status.disk.used_pct >= 75 ? 'text-amber-600' : 'text-emerald-600'}`}>
              {status.disk.used_pct}% used
            </p>
          </div>

          {/* DB overview */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5 space-y-3">
            <h2 className="text-sm font-semibold text-slate-700">Database</h2>
            <div className="flex items-end gap-1">
              <span className="text-3xl font-bold text-slate-900 tabular-nums">{status.db_size_gb}</span>
              <span className="text-sm text-slate-400 mb-1">GB total</span>
            </div>
            <p className="text-xs text-slate-400">{status.db_schemas.length} schemas</p>
          </div>

          {/* Containers */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden lg:col-span-2">
            <div className="px-5 py-4 border-b border-slate-100">
              <h2 className="text-sm font-semibold text-slate-700">Containers</h2>
            </div>
            {status.containers.length === 0 ? (
              <p className="px-5 py-6 text-xs text-slate-400">No containers visible (docker may not be accessible from API).</p>
            ) : (
              <table className="w-full text-left">
                <thead className="text-xs text-slate-400 uppercase tracking-wide bg-slate-50">
                  <tr>
                    <th className="px-5 py-3">Name</th>
                    <th className="px-4 py-3">State</th>
                    <th className="px-4 py-3">Health</th>
                  </tr>
                </thead>
                <tbody>
                  {status.containers.map(c => <ContainerRow key={c.name} c={c} />)}
                </tbody>
              </table>
            )}
          </div>

          {/* Schema breakdown */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden lg:col-span-2">
            <div className="px-5 py-4 border-b border-slate-100">
              <h2 className="text-sm font-semibold text-slate-700">Schema Sizes</h2>
              <p className="text-xs text-slate-400 mt-0.5">Estimated from pg_class (no table scan). Includes indexes.</p>
            </div>
            {status.db_schemas.length === 0 ? (
              <p className="px-5 py-6 text-xs text-slate-400">No schema data available.</p>
            ) : (
              <table className="w-full text-left">
                <thead className="text-xs text-slate-400 uppercase tracking-wide bg-slate-50">
                  <tr>
                    <th className="px-5 py-3">Schema</th>
                    <th className="px-4 py-3 text-right">Size</th>
                    <th className="px-4 py-3 text-right">Est. rows</th>
                  </tr>
                </thead>
                <tbody>
                  {status.db_schemas.map(s => <SchemaRow key={s.schema} s={s} />)}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
