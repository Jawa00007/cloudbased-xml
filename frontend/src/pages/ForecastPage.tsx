import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  AreaChart, Area, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import {
  fetchAccounts, fetchPods, fetchForecast, generateForecast, fetchForecastCompare,
  fetchAnagraficaMonths,
} from '../api/client'
import { itNum, itMwh } from '../utils/format'

const SOURCE_COLORS: Record<string, string> = {
  E: '#2563eb', S: '#7c3aed', filled: '#0891b2', estimated: '#d97706', padded: '#64748b',
}
const SOURCE_LABELS: Record<string, string> = {
  E: 'Measured (E)', S: 'Estimated (S)', filled: 'Carry-forward', estimated: 'CONSUMO_TOT', padded: 'Padded',
}

function monthOptions() {
  const opts: { label: string; value: string }[] = []
  const now = new Date()
  for (let i = 0; i < 24; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    opts.push({ label: `${mm}/${d.getFullYear()}`, value: `${mm}/${d.getFullYear()}` })
  }
  return opts
}

function today() { return new Date().toISOString().slice(0, 10) }
function firstOfMonth() {
  const d = new Date(); d.setDate(1); return d.toISOString().slice(0, 10)
}

// ── Generate Tab ──────────────────────────────────────────────────────────────
function GenerateTab() {
  const qc = useQueryClient()
  const [accountId, setAccountId] = useState('')
  const [meseAnno, setMeseAnno] = useState(monthOptions()[1].value)
  const [anagraficaMonth, setAnagraficaMonth] = useState<string>('')
  const [selectedPod, setSelectedPod] = useState<string | null>(null)
  const [generated, setGenerated] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: accounts = [] } = useQuery({ queryKey: ['accounts'], queryFn: fetchAccounts })

  const { data: anagraficaMonths = [] } = useQuery({
    queryKey: ['anagrafica-months', accountId],
    queryFn: () => fetchAnagraficaMonths(accountId),
    enabled: !!accountId,
  })

  // When available months load, default to forecast month if available, else latest
  const effectiveAnaMonth = anagraficaMonth || anagraficaMonths[0] || meseAnno

  const generate = useMutation({
    mutationFn: () => generateForecast(accountId, meseAnno, effectiveAnaMonth),
    onSuccess: () => {
      setGenerated(true); setError(null)
      qc.invalidateQueries({ queryKey: ['forecast', accountId, meseAnno] })
    },
    onError: (e: Error) => setError(e.message),
  })

  const { data: forecast = [], isLoading: loadingForecast } = useQuery({
    queryKey: ['forecast', accountId, meseAnno, selectedPod],
    queryFn: () => fetchForecast(accountId, meseAnno, selectedPod ?? undefined),
    enabled: generated && !!accountId,
  })

  const pods = [...new Set(forecast.map(r => r.pod))].sort()

  const dailyMap: Record<string, Record<string, number>> = {}
  for (const row of forecast) {
    if (!row.ea_mwh_with_loss) continue
    if (!dailyMap[row.forecast_date]) dailyMap[row.forecast_date] = {}
    dailyMap[row.forecast_date][row.pod] = (dailyMap[row.forecast_date][row.pod] ?? 0) + row.ea_mwh_with_loss
  }
  const chartData = Object.entries(dailyMap).sort(([a], [b]) => a.localeCompare(b))
    .map(([date, vals]) => ({ date: date.slice(5), ...vals }))

  const sourceCount: Record<string, number> = {}
  for (const row of forecast) sourceCount[row.source_type] = (sourceCount[row.source_type] ?? 0) + 1
  const totalRows = forecast.length

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
        <h2 className="text-sm font-semibold text-slate-700 mb-4">Generate Forecast</h2>
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Account</label>
            <select value={accountId}
              onChange={e => { setAccountId(e.target.value); setGenerated(false); setSelectedPod(null); setAnagraficaMonth('') }}
              className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[160px]">
              <option value="">Select account…</option>
              {accounts.map(a => <option key={a.account_id} value={a.account_id}>{a.display_name ?? a.account_id}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Forecast Month</label>
            <select value={meseAnno} onChange={e => { setMeseAnno(e.target.value); setGenerated(false) }}
              className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[140px]">
              {monthOptions().map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">
              Registry (Anagrafica)
            </label>
            <select
              value={anagraficaMonth || effectiveAnaMonth}
              onChange={e => { setAnagraficaMonth(e.target.value); setGenerated(false) }}
              disabled={!accountId}
              className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[140px] disabled:opacity-40"
            >
              {anagraficaMonths.length === 0
                ? <option value={meseAnno}>{meseAnno} (default)</option>
                : anagraficaMonths.map(m => (
                    <option key={m} value={m}>{m}{m === meseAnno ? ' ✓' : ''}</option>
                  ))
              }
            </select>
          </div>
          <button onClick={() => generate.mutate()} disabled={!accountId || generate.isPending}
            className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            {generate.isPending ? 'Generating…' : 'Generate Forecast'}
          </button>
        </div>
        {error && <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{error}</div>}
        {generate.isSuccess && (
          <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
            {generate.data.periods_written.toLocaleString()} periods written for {generate.data.mese_anno}
            {effectiveAnaMonth !== meseAnno && (
              <span className="ml-2 text-green-600">(registry: {effectiveAnaMonth})</span>
            )}
          </div>
        )}
      </div>

      {generated && forecast.length > 0 && (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'PODs', value: pods.length },
              { label: 'Total MWh (with loss)', value: itNum(forecast.reduce((s, r) => s + (r.ea_mwh_with_loss ?? 0), 0), { maximumFractionDigits: 1 }) },
              { label: 'Periods', value: itNum(totalRows, { maximumFractionDigits: 0 }) },
              { label: 'Month', value: meseAnno },
            ].map(c => (
              <div key={c.label} className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
                <p className="text-xs text-slate-400 uppercase tracking-wide">{c.label}</p>
                <p className="text-2xl font-semibold text-slate-900 mt-1 tabular-nums">{c.value}</p>
              </div>
            ))}
          </div>

          {/* Source breakdown */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
            <h2 className="text-sm font-semibold text-slate-700 mb-3">Data Source Breakdown</h2>
            <div className="flex flex-wrap gap-3">
              {Object.entries(sourceCount).sort(([, a], [, b]) => b - a).map(([type, count]) => (
                <div key={type} className="flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium"
                  style={{ backgroundColor: `${SOURCE_COLORS[type]}18`, color: SOURCE_COLORS[type] }}>
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: SOURCE_COLORS[type] }} />
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
              <button onClick={() => setSelectedPod(null)}
                className={`text-xs px-3 py-1.5 rounded-full font-medium transition-all ${!selectedPod ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>
                All
              </button>
              {pods.map(p => (
                <button key={p} onClick={() => setSelectedPod(p === selectedPod ? null : p)}
                  className={`text-xs px-3 py-1.5 rounded-full font-medium transition-all ${selectedPod === p ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>
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
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #e2e8f0', fontSize: 12 }}
                  formatter={(v: number) => [`${v.toFixed(3)} MWh`]} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {(selectedPod ? [selectedPod] : pods.slice(0, 5)).map((pod, i) => (
                  <Area key={pod} type="monotone" dataKey={pod} stroke="#2563eb" strokeWidth={1.5}
                    fill={`url(#grad-${i})`} dot={false} connectNulls />
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
                      <td className="px-4 py-2.5 tabular-nums text-right text-slate-700">{itMwh(row.ea_mwh)}</td>
                      <td className="px-4 py-2.5 tabular-nums text-right font-medium text-slate-800">{itMwh(row.ea_mwh_with_loss)}</td>
                      <td className="px-4 py-2.5 tabular-nums text-right text-slate-500">
                        {row.loss_pct != null ? `${itNum(row.loss_pct * 100, { maximumFractionDigits: 1 })}%` : '—'}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium"
                          style={{ backgroundColor: `${SOURCE_COLORS[row.source_type] ?? '#64748b'}18`, color: SOURCE_COLORS[row.source_type] ?? '#64748b' }}>
                          {SOURCE_LABELS[row.source_type] ?? row.source_type}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {forecast.length > 200 && (
                <p className="px-5 py-3 text-xs text-slate-400">Showing first 200 of {forecast.length.toLocaleString()} rows</p>
              )}
            </div>
          </div>
        </>
      )}

      {generated && !loadingForecast && forecast.length === 0 && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-10 text-center">
          <p className="text-slate-400 text-sm">No forecast data. Click Generate Forecast above.</p>
        </div>
      )}
    </div>
  )
}

// ── Compare Tab ───────────────────────────────────────────────────────────────
function CompareTab() {
  const [accountId, setAccountId] = useState('')
  const [pod, setPod] = useState('')
  const [fromDate, setFromDate] = useState(firstOfMonth)
  const [toDate, setToDate] = useState(today)
  const [submitted, setSubmitted] = useState(false)

  const { data: accounts = [] } = useQuery({ queryKey: ['accounts'], queryFn: fetchAccounts })
  const { data: pods = [] } = useQuery({
    queryKey: ['pods', accountId], queryFn: () => fetchPods(accountId), enabled: !!accountId,
  })

  const { data: compare, isLoading, error, refetch } = useQuery({
    queryKey: ['forecast-compare', accountId, pod, fromDate, toDate],
    queryFn: () => fetchForecastCompare(accountId, pod, fromDate, toDate),
    enabled: false,
  })

  function run() { setSubmitted(true); refetch() }

  // Aggregate per-period data by date for chart
  const chartData = (() => {
    if (!compare) return []
    const curr: Record<string, number> = {}
    const prev: Record<string, number> = {}
    for (const d of compare.current_period.data) {
      if (d.ea_mwh != null) curr[d.date] = (curr[d.date] ?? 0) + d.ea_mwh
    }
    for (const d of compare.previous_period.data) {
      if (d.ea_mwh != null) prev[d.date] = (prev[d.date] ?? 0) + d.ea_mwh
    }
    const allDates = [...new Set([...Object.keys(curr), ...Object.keys(prev)])].sort()
    return allDates.map((date, i) => ({
      day: `D${i + 1}`,
      'Current year': curr[date] != null ? +curr[date].toFixed(4) : null,
      'Previous year': prev[date] != null ? +prev[date].toFixed(4) : null,
      _curr_date: date,
    }))
  })()

  const delta = compare ? compare.current_total_mwh - compare.previous_total_mwh : 0
  const deltaPct = compare && compare.previous_total_mwh
    ? ((delta / compare.previous_total_mwh) * 100).toFixed(1)
    : null

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
        <h2 className="text-sm font-semibold text-slate-700 mb-1">Partial Month Comparison</h2>
        <p className="text-xs text-slate-400 mb-4">
          Compare a date range in the current year against the same range one year prior.
          Example: May 1–5 2026 vs May 1–5 2025.
        </p>
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Account</label>
            <select value={accountId} onChange={e => { setAccountId(e.target.value); setPod('') }}
              className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[160px]">
              <option value="">Select account…</option>
              {accounts.map(a => <option key={a.account_id} value={a.account_id}>{a.display_name ?? a.account_id}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">POD</label>
            <select value={pod} onChange={e => setPod(e.target.value)}
              className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[160px]"
              disabled={!accountId}>
              <option value="">Select POD…</option>
              {pods.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">From date</label>
            <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
              className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">To date</label>
            <input type="date" value={toDate} onChange={e => setToDate(e.target.value)}
              className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <button onClick={run} disabled={!accountId || !pod || isLoading}
            className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            {isLoading ? 'Loading…' : 'Run Compare'}
          </button>
        </div>
        {error && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            {(error as Error).message}
          </div>
        )}
      </div>

      {compare && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
              <p className="text-xs text-slate-400 uppercase tracking-wide">Current period</p>
              <p className="text-[11px] text-slate-400 mt-0.5">{compare.current_period.from} → {compare.current_period.to}</p>
              <p className="text-2xl font-semibold text-blue-700 mt-2 tabular-nums">
                {itMwh(compare.current_total_mwh)}
                <span className="text-sm font-normal text-slate-400 ml-1">MWh</span>
              </p>
            </div>
            <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
              <p className="text-xs text-slate-400 uppercase tracking-wide">Previous year</p>
              <p className="text-[11px] text-slate-400 mt-0.5">{compare.previous_period.from} → {compare.previous_period.to}</p>
              <p className="text-2xl font-semibold text-slate-700 mt-2 tabular-nums">
                {itMwh(compare.previous_total_mwh)}
                <span className="text-sm font-normal text-slate-400 ml-1">MWh</span>
              </p>
            </div>
            <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
              <p className="text-xs text-slate-400 uppercase tracking-wide">Difference</p>
              <p className="text-2xl font-semibold mt-2 tabular-nums" style={{ color: delta >= 0 ? '#16a34a' : '#dc2626' }}>
                {delta >= 0 ? '+' : ''}{itMwh(delta)}
                <span className="text-sm font-normal text-slate-400 ml-1">MWh</span>
              </p>
            </div>
            <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
              <p className="text-xs text-slate-400 uppercase tracking-wide">Change %</p>
              <p className="text-2xl font-semibold mt-2 tabular-nums" style={{ color: delta >= 0 ? '#16a34a' : '#dc2626' }}>
                {deltaPct != null ? `${Number(deltaPct) >= 0 ? '+' : ''}${deltaPct}%` : '—'}
              </p>
            </div>
          </div>

          {/* Chart */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
            <h2 className="text-sm font-semibold text-slate-700 mb-1">Daily MWh — Current vs Previous Year</h2>
            <p className="text-xs text-slate-400 mb-4">
              POD: <span className="font-mono">{compare.pod}</span>
            </p>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={chartData} margin={{ left: 0, right: 16, top: 8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="day" tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} unit=" MWh" />
                <Tooltip
                  contentStyle={{ borderRadius: 12, border: '1px solid #e2e8f0', fontSize: 12 }}
                  formatter={(v: number) => [`${v.toFixed(4)} MWh`]}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="Current year" stroke="#2563eb" strokeWidth={2} dot={false} connectNulls />
                <Line type="monotone" dataKey="Previous year" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 2" dot={false} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Table: side by side by day */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100">
              <h2 className="text-sm font-semibold text-slate-700">Daily Comparison</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-400 uppercase tracking-wide text-[10px] border-b border-slate-100">
                    <th className="text-left px-5 py-3 font-medium">Day</th>
                    <th className="text-right px-4 py-3 font-medium">Current (MWh)</th>
                    <th className="text-right px-4 py-3 font-medium">Prev Year (MWh)</th>
                    <th className="text-right px-4 py-3 font-medium">Delta (MWh)</th>
                    <th className="text-right px-4 py-3 font-medium">Change %</th>
                  </tr>
                </thead>
                <tbody>
                  {chartData.map((row, i) => {
                    const curr = row['Current year'] as number | null
                    const prev = row['Previous year'] as number | null
                    const d = curr != null && prev != null ? curr - prev : null
                    const pct = d != null && prev ? (d / prev) * 100 : null
                    return (
                      <tr key={i} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                        <td className="px-5 py-2.5 text-slate-600">{row._curr_date as string}</td>
                        <td className="px-4 py-2.5 tabular-nums text-right font-medium text-blue-700">
                          {itMwh(curr)}
                        </td>
                        <td className="px-4 py-2.5 tabular-nums text-right text-slate-500">
                          {itMwh(prev)}
                        </td>
                        <td className="px-4 py-2.5 tabular-nums text-right font-medium"
                          style={{ color: d == null ? '#94a3b8' : d >= 0 ? '#16a34a' : '#dc2626' }}>
                          {d != null ? `${d >= 0 ? '+' : ''}${itMwh(d)}` : '—'}
                        </td>
                        <td className="px-4 py-2.5 tabular-nums text-right"
                          style={{ color: pct == null ? '#94a3b8' : pct >= 0 ? '#16a34a' : '#dc2626' }}>
                          {pct != null ? `${pct >= 0 ? '+' : ''}${itNum(pct, { maximumFractionDigits: 1 })}%` : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t border-slate-200 bg-slate-50 font-semibold">
                    <td className="px-5 py-3 text-xs text-slate-600">Total</td>
                    <td className="px-4 py-3 tabular-nums text-right text-xs text-blue-700">{itMwh(compare.current_total_mwh)}</td>
                    <td className="px-4 py-3 tabular-nums text-right text-xs text-slate-600">{itMwh(compare.previous_total_mwh)}</td>
                    <td className="px-4 py-3 tabular-nums text-right text-xs"
                      style={{ color: delta >= 0 ? '#16a34a' : '#dc2626' }}>
                      {delta >= 0 ? '+' : ''}{itMwh(delta)}
                    </td>
                    <td className="px-4 py-3 tabular-nums text-right text-xs"
                      style={{ color: delta >= 0 ? '#16a34a' : '#dc2626' }}>
                      {deltaPct != null ? `${Number(deltaPct) >= 0 ? '+' : ''}${itNum(Number(deltaPct), { maximumFractionDigits: 1 })}%` : '—'}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        </>
      )}

      {submitted && !isLoading && !compare && !error && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-10 text-center">
          <p className="text-slate-400 text-sm">No forecast data found for the selected POD and date range.</p>
        </div>
      )}
    </div>
  )
}

// ── Page shell ────────────────────────────────────────────────────────────────
export default function ForecastPage() {
  const [mode, setMode] = useState<'generate' | 'compare'>('generate')

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Forecast Engine</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Generate monthly energy forecasts and compare periods across years.
          </p>
        </div>
      </div>

      {/* Mode tab bar */}
      <div className="flex gap-1 p-1 bg-slate-100 rounded-xl w-fit">
        {(['generate', 'compare'] as const).map(m => (
          <button key={m} onClick={() => setMode(m)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              mode === m ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'
            }`}>
            {m === 'generate' ? 'Generate' : 'Compare'}
          </button>
        ))}
      </div>

      {mode === 'generate' ? <GenerateTab /> : <CompareTab />}
    </div>
  )
}
