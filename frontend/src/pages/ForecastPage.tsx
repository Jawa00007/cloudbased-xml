import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { fetchAccounts, fetchForecast, generateForecast } from '../api/client'

const SOURCE_COLORS: Record<string, string> = {
  E: '#2563eb',
  S: '#7c3aed',
  filled: '#0891b2',
  estimated: '#d97706',
  padded: '#64748b',
}

const SOURCE_LABELS: Record<string, string> = {
  E: 'Measured (E)',
  S: 'Estimated (S)',
  filled: 'Carry-forward',
  estimated: 'CONSUMO_TOT',
  padded: 'Padded',
}

function monthOptions() {
  const opts: { label: string; value: string }[] = []
  const now = new Date()
  for (let i = 0; i < 24; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const yyyy = d.getFullYear()
    opts.push({ label: `${mm}/${yyyy}`, value: `${mm}/${yyyy}` })
  }
  return opts
}

export default function ForecastPage() {
  const qc = useQueryClient()
  const [accountId, setAccountId] = useState('')
  const [meseAnno, setMeseAnno] = useState(monthOptions()[1].value)
  const [selectedPod, setSelectedPod] = useState<string | null>(null)
  const [generated, setGenerated] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: accounts = [] } = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })

  const generate = useMutation({
    mutationFn: () => generateForecast(accountId, meseAnno),
    onSuccess: (res) => {
      setGenerated(true)
      setError(null)
      qc.invalidateQueries({ queryKey: ['forecast', accountId, meseAnno] })
    },
    onError: (e: Error) => setError(e.message),
  })

  const { data: forecast = [], isLoading: loadingForecast } = useQuery({
    queryKey: ['forecast', accountId, meseAnno, selectedPod],
    queryFn: () => fetchForecast(accountId, meseAnno, selectedPod ?? undefined),
    enabled: generated && !!accountId,
  })

  // Derive POD list from forecast
  const pods = [...new Set(forecast.map(r => r.pod))].sort()

  // Build daily chart data: sum ea_mwh_with_loss per day per pod
  const dailyMap: Record<string, Record<string, number>> = {}
  for (const row of forecast) {
    if (!row.ea_mwh_with_loss) continue
    const key = row.forecast_date
    if (!dailyMap[key]) dailyMap[key] = {}
    dailyMap[key][row.pod] = (dailyMap[key][row.pod] ?? 0) + row.ea_mwh_with_loss
  }
  const chartData = Object.entries(dailyMap)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, vals]) => ({ date: date.slice(5), ...vals }))

  // Source type breakdown
  const sourceCount: Record<string, number> = {}
  for (const row of forecast) {
    sourceCount[row.source_type] = (sourceCount[row.source_type] ?? 0) + 1
  }
  const totalRows = forecast.length

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Forecast Engine</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Generate monthly energy forecasts from previous-year data with grid loss adjustment.
        </p>
      </div>

      {/* Controls */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
        <h2 className="text-sm font-semibold text-slate-700 mb-4">Generate Forecast</h2>
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Account</label>
            <select
              value={accountId}
              onChange={e => { setAccountId(e.target.value); setGenerated(false); setSelectedPod(null) }}
              className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[160px]"
            >
              <option value="">Select account…</option>
              {accounts.map(a => (
                <option key={a.account_id} value={a.account_id}>
                  {a.display_name ?? a.account_id}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Forecast Month</label>
            <select
              value={meseAnno}
              onChange={e => { setMeseAnno(e.target.value); setGenerated(false) }}
              className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[140px]"
            >
              {monthOptions().map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>

          <button
            onClick={() => generate.mutate()}
            disabled={!accountId || generate.isPending}
            className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {generate.isPending ? 'Generating…' : 'Generate Forecast'}
          </button>
        </div>

        {error && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            {error}
          </div>
        )}
        {generate.isSuccess && (
          <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
            {generate.data.periods_written.toLocaleString()} periods written for {generate.data.mese_anno}
          </div>
        )}
      </div>

      {generated && forecast.length > 0 && (
        <>
          {/* Stats row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
              <p className="text-xs text-slate-400 uppercase tracking-wide">PODs</p>
              <p className="text-2xl font-semibold text-slate-900 mt-1">{pods.length}</p>
            </div>
            <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
              <p className="text-xs text-slate-400 uppercase tracking-wide">Total MWh (with loss)</p>
              <p className="text-2xl font-semibold text-slate-900 mt-1 tabular-nums">
                {forecast.reduce((s, r) => s + (r.ea_mwh_with_loss ?? 0), 0).toFixed(1)}
              </p>
            </div>
            <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
              <p className="text-xs text-slate-400 uppercase tracking-wide">Periods</p>
              <p className="text-2xl font-semibold text-slate-900 mt-1 tabular-nums">
                {totalRows.toLocaleString()}
              </p>
            </div>
            <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
              <p className="text-xs text-slate-400 uppercase tracking-wide">Month</p>
              <p className="text-2xl font-semibold text-slate-900 mt-1">{meseAnno}</p>
            </div>
          </div>

          {/* Source type breakdown */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
            <h2 className="text-sm font-semibold text-slate-700 mb-3">Data Source Breakdown</h2>
            <div className="flex flex-wrap gap-3">
              {Object.entries(sourceCount).sort(([,a],[,b]) => b - a).map(([type, count]) => (
                <div
                  key={type}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium"
                  style={{ backgroundColor: `${SOURCE_COLORS[type]}18`, color: SOURCE_COLORS[type] }}
                >
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: SOURCE_COLORS[type] }}
                  />
                  {SOURCE_LABELS[type] ?? type}
                  <span className="font-semibold">{((count / totalRows) * 100).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>

          {/* POD filter */}
          {pods.length > 1 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-slate-500">Filter POD:</span>
              <button
                onClick={() => setSelectedPod(null)}
                className={`text-xs px-3 py-1.5 rounded-full font-medium transition-all ${
                  !selectedPod ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                All
              </button>
              {pods.map(p => (
                <button
                  key={p}
                  onClick={() => setSelectedPod(p === selectedPod ? null : p)}
                  className={`text-xs px-3 py-1.5 rounded-full font-medium transition-all ${
                    selectedPod === p ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          )}

          {/* Chart */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
            <h2 className="text-sm font-semibold text-slate-700 mb-4">Daily MWh Forecast (with grid loss)</h2>
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={chartData} margin={{ left: 0, right: 16, top: 8, bottom: 0 }}>
                <defs>
                  {(selectedPod ? [selectedPod] : pods.slice(0, 5)).map((pod, i) => (
                    <linearGradient key={pod} id={`grad-${i}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#2563eb" stopOpacity={0.18 - i * 0.03} />
                      <stop offset="95%" stopColor="#2563eb" stopOpacity={0} />
                    </linearGradient>
                  ))}
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  tickLine={false}
                  axisLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{ borderRadius: 12, border: '1px solid #e2e8f0', fontSize: 12 }}
                  formatter={(v: number) => [`${v.toFixed(3)} MWh`]}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {(selectedPod ? [selectedPod] : pods.slice(0, 5)).map((pod, i) => (
                  <Area
                    key={pod}
                    type="monotone"
                    dataKey={pod}
                    stroke="#2563eb"
                    strokeWidth={1.5}
                    fill={`url(#grad-${i})`}
                    dot={false}
                    connectNulls
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Table */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100">
              <h2 className="text-sm font-semibold text-slate-700">
                Forecast Periods
                <span className="ml-2 text-slate-400 font-normal">{forecast.length.toLocaleString()} rows</span>
              </h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-400 uppercase tracking-wide text-[10px] border-b border-slate-100">
                    <th className="text-left px-5 py-3 font-medium">POD</th>
                    <th className="text-left px-4 py-3 font-medium">Date</th>
                    <th className="text-right px-4 py-3 font-medium">Period</th>
                    <th className="text-right px-4 py-3 font-medium">ea_mwh</th>
                    <th className="text-right px-4 py-3 font-medium">ea_mwh+loss</th>
                    <th className="text-right px-4 py-3 font-medium">Loss%</th>
                    <th className="text-left px-4 py-3 font-medium">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {forecast.slice(0, 200).map((row, i) => (
                    <tr key={i} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                      <td className="px-5 py-2.5 font-mono text-slate-700">{row.pod}</td>
                      <td className="px-4 py-2.5 tabular-nums text-slate-600">{row.forecast_date}</td>
                      <td className="px-4 py-2.5 tabular-nums text-right text-slate-600">{row.periodo}</td>
                      <td className="px-4 py-2.5 tabular-nums text-right text-slate-700">
                        {row.ea_mwh?.toFixed(3) ?? '—'}
                      </td>
                      <td className="px-4 py-2.5 tabular-nums text-right font-medium text-slate-800">
                        {row.ea_mwh_with_loss?.toFixed(3) ?? '—'}
                      </td>
                      <td className="px-4 py-2.5 tabular-nums text-right text-slate-500">
                        {row.loss_pct != null ? `${(row.loss_pct * 100).toFixed(1)}%` : '—'}
                      </td>
                      <td className="px-4 py-2.5">
                        <span
                          className="px-2 py-0.5 rounded-full text-[10px] font-medium"
                          style={{
                            backgroundColor: `${SOURCE_COLORS[row.source_type] ?? '#64748b'}18`,
                            color: SOURCE_COLORS[row.source_type] ?? '#64748b',
                          }}
                        >
                          {SOURCE_LABELS[row.source_type] ?? row.source_type}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {forecast.length > 200 && (
                <p className="px-5 py-3 text-xs text-slate-400">
                  Showing first 200 of {forecast.length.toLocaleString()} rows
                </p>
              )}
            </div>
          </div>
        </>
      )}

      {generated && !loadingForecast && forecast.length === 0 && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-10 text-center">
          <p className="text-slate-400 text-sm">No forecast data yet. Click Generate Forecast above.</p>
        </div>
      )}
    </div>
  )
}
