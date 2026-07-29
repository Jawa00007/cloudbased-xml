import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  AreaChart, Area, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import {
  fetchAccounts, fetchPods, fetchForecast, generateForecast, fetchForecastStatus,
  fetchForecastCompare, fetchForecastCompareDP,
  fetchAnagraficaMonths, fetchMeasurementMonths, fetchForecastSummary,
  downloadForecastExcel, downloadForecastPodsCsv, downloadMeasurementsWideExcel,
  downloadCompareDPExcel, downloadComparePodExcel,
} from '../api/client'
import type { ForecastGenerateResult } from '../api/types'
import { itNum, itMwh } from '../utils/format'

const SOURCE_COLORS: Record<string, string> = {
  E: '#2563eb', S: '#7c3aed', filled: '#0891b2', estimated: '#d97706', padded: '#64748b',
}
const SOURCE_LABELS: Record<string, string> = {
  E: 'Measured (E)', S: 'Estimated (S)', filled: 'Carry-forward', estimated: 'CONSUMO_TOT', padded: 'Padded',
}
const DP_COLORS = ['#2563eb', '#16a34a', '#dc2626', '#d97706', '#7c3aed', '#0891b2', '#db2777', '#059669']

function monthOptions() {
  const opts: { label: string; value: string }[] = []
  const now = new Date()
  for (let i = -2; i < 24; i++) {
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

function resolvedSourceMonth(forecastMonth: string, availableMonths: string[]): { month: string; fallback: boolean } {
  const [mm, yy] = forecastMonth.split('/')
  const target = `${mm}/${parseInt(yy) - 1}`
  if (!availableMonths.length || availableMonths.includes(target)) return { month: target, fallback: false }
  const toDate = (m: string) => { const [mo, yr] = m.split('/'); return new Date(parseInt(yr), parseInt(mo) - 1, 1) }
  const targetDate = toDate(target)
  const nearest = availableMonths.reduce((best, m) =>
    Math.abs(toDate(m).getTime() - targetDate.getTime()) < Math.abs(toDate(best).getTime() - targetDate.getTime()) ? m : best
  )
  return { month: nearest, fallback: true }
}


// ── Generate Tab ──────────────────────────────────────────────────────────────
function GenerateTab() {
  const qc = useQueryClient()
  const [accountId, setAccountId] = useState('')
  const [meseAnno, setMeseAnno] = useState(monthOptions()[1].value)
  const [anagraficaMonth, setAnagraficaMonth] = useState<string>('')
  const [selectedPod, setSelectedPod] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)
  const [downloadingPods, setDownloadingPods] = useState(false)
  const [downloadingMeasurements, setDownloadingMeasurements] = useState(false)
  const [measMonth, setMeasMonth] = useState('')

  // Async job state
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [jobResult, setJobResult] = useState<ForecastGenerateResult | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const { data: accounts = [] } = useQuery({ queryKey: ['accounts'], queryFn: fetchAccounts })

  const { data: anagraficaMonths = [] } = useQuery({
    queryKey: ['anagrafica-months', accountId],
    queryFn: () => fetchAnagraficaMonths(accountId),
    enabled: !!accountId,
  })

  const { data: measurementMonths = [] } = useQuery({
    queryKey: ['measurement-months', accountId],
    queryFn: () => fetchMeasurementMonths(accountId),
    enabled: !!accountId,
  })

  const effectiveAnaMonth = anagraficaMonth || anagraficaMonths[0] || meseAnno

  // Submit job
  const generate = useMutation({
    mutationFn: () => generateForecast(accountId, meseAnno, effectiveAnaMonth),
    onSuccess: (data) => {
      setJobId(data.job_id)
      setJobStatus('running')
      setError(null)
      setJobResult(null)
      setElapsed(0)
    },
    onError: (e: Error) => { setError(e.message); setJobStatus('error') },
  })

  // Elapsed timer
  useEffect(() => {
    if (jobStatus === 'running') {
      timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000)
    } else {
      if (timerRef.current) clearInterval(timerRef.current)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [jobStatus])

  // Poll job status
  const { data: statusData, error: statusQueryError } = useQuery({
    queryKey: ['forecast-status', jobId],
    queryFn: () => fetchForecastStatus(jobId!),
    enabled: !!jobId && jobStatus === 'running',
    refetchInterval: 2000,
    retry: false,
  })

  useEffect(() => {
    if (statusQueryError) {
      setJobStatus('error')
      setError('Job not found — the server may have restarted. Please try again.')
      return
    }
    if (!statusData) return
    if (statusData.status === 'done') {
      setJobStatus('done')
      setJobResult(statusData.result)
      qc.invalidateQueries({ queryKey: ['forecast', accountId, meseAnno] })
    } else if (statusData.status === 'error') {
      setJobStatus('error')
      setError(statusData.error ?? 'Forecast generation failed')
    }
  }, [statusData, statusQueryError])

  const { data: forecast = [], isLoading: loadingForecast } = useQuery({
    queryKey: ['forecast', accountId, meseAnno, selectedPod],
    queryFn: () => fetchForecast(accountId, meseAnno, selectedPod ?? undefined),
    // Frozen while a job is running: forecast_periods is being deleted and bulk-rewritten
    // during generation, so refetching here would both return meaningless mid-flux rows
    // and pile expensive queries onto the exact table the job needs I/O for, slowing the
    // job down. Cached data (from before generation started) stays visible; the explicit
    // invalidateQueries() below fires the one fetch that matters right when it's ready.
    enabled: !!accountId && !!meseAnno && jobStatus !== 'running',
  })

  const { data: summary } = useQuery({
    queryKey: ['forecast-summary', accountId, meseAnno],
    queryFn: () => fetchForecastSummary(accountId, meseAnno),
    enabled: !!accountId && !!meseAnno && forecast.length > 0 && jobStatus !== 'running',
    staleTime: 30_000,
  })

  // Auto-clear job-not-found error when forecast data is present — data survived the restart
  useEffect(() => {
    if (forecast.length > 0 && error === 'Job not found — the server may have restarted. Please try again.') {
      setError(null)
      setJobStatus('idle')
      setJobId(null)
    }
  }, [forecast.length, error])

  const pods = [...new Set(forecast.map(r => r.pod))].sort()

  const dailyMap: Record<string, Record<string, number>> = {}
  for (const row of forecast) {
    if (!row.ea_mwh_with_loss) continue
    if (!dailyMap[row.forecast_date]) dailyMap[row.forecast_date] = {}
    dailyMap[row.forecast_date][row.pod] = (dailyMap[row.forecast_date][row.pod] ?? 0) + row.ea_mwh_with_loss
  }
  const chartData = Object.entries(dailyMap).sort(([a], [b]) => a.localeCompare(b))
    .map(([date, vals]) => ({ date: date.slice(5), ...vals }))

  const localSourceCount: Record<string, number> = {}
  for (const row of forecast) localSourceCount[row.source_type] = (localSourceCount[row.source_type] ?? 0) + 1
  const totalRows = forecast.length

  const displayPods = summary?.pods ?? pods.length
  const displayMwh = summary?.total_mwh ?? forecast.reduce((s, r) => s + (r.ea_mwh_with_loss ?? 0), 0)
  const displayPeriods = summary?.total_periods ?? totalRows
  const displaySourceCount = summary?.source_breakdown ?? localSourceCount
  const displayTotal = summary?.total_periods ?? totalRows

  const isRunning = jobStatus === 'running' || generate.isPending

  async function handleDownload() {
    setDownloading(true)
    try {
      await downloadForecastExcel(accountId, meseAnno)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDownloading(false)
    }
  }

  async function handleDownloadPods() {
    setDownloadingPods(true)
    try {
      await downloadForecastPodsCsv(accountId, meseAnno)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDownloadingPods(false)
    }
  }

  async function handleDownloadMeasurements() {
    const month = measMonth || measurementMonths[0]
    if (!month) return
    setDownloadingMeasurements(true)
    try {
      await downloadMeasurementsWideExcel(accountId, month)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDownloadingMeasurements(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
        <h2 className="text-sm font-semibold text-slate-700 mb-4">Generate Forecast</h2>
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Account</label>
            <select value={accountId}
              onChange={e => { setAccountId(e.target.value); setSelectedPod(null); setAnagraficaMonth(''); setJobStatus('idle'); setJobId(null); setError(null) }}
              className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[160px]">
              <option value="">Select account…</option>
              {accounts.map(a => <option key={a.account_id} value={a.account_id}>{a.display_name ?? a.account_id}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Forecast Month</label>
            <select value={meseAnno} onChange={e => { setMeseAnno(e.target.value); setJobStatus('idle'); setJobId(null); setError(null) }}
              className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[140px]">
              {monthOptions().map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <span className="text-[10px] text-slate-400 mt-0.5">
              Source measurements: <span className={`font-medium ${resolvedSourceMonth(meseAnno, measurementMonths).fallback ? 'text-amber-500' : 'text-slate-500'}`}>
                {resolvedSourceMonth(meseAnno, measurementMonths).month} (auto{resolvedSourceMonth(meseAnno, measurementMonths).fallback ? ', nearest' : ''})
              </span>
            </span>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">
              Registry (Anagrafica)
            </label>
            <select
              value={anagraficaMonth || effectiveAnaMonth}
              onChange={e => { setAnagraficaMonth(e.target.value); setJobStatus('idle'); setJobId(null); setError(null) }}
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
          <button onClick={() => generate.mutate()} disabled={!accountId || isRunning}
            className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            {isRunning ? 'Generating…' : 'Generate Forecast'}
          </button>
        </div>

        {/* Progress indicator */}
        {jobStatus === 'running' && (
          <div className="mt-3 flex items-center gap-3">
            <div className="flex items-center gap-2 p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-700 flex-1">
              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Generating forecast… {elapsed}s elapsed
            </div>
          </div>
        )}

        {error && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 flex items-center justify-between gap-3">
            <span>{error}</span>
            <button
              onClick={() => { setError(null); setJobStatus('idle'); setJobId(null) }}
              className="shrink-0 text-xs font-medium px-3 py-1 rounded-md bg-red-100 hover:bg-red-200 text-red-800 transition-colors"
            >
              Dismiss
            </button>
          </div>
        )}

        {jobStatus === 'done' && jobResult && (
          <div className="mt-3 flex items-center gap-3 flex-wrap">
            <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700 flex-1">
              {jobResult.periods_written.toLocaleString()} periods written for {jobResult.mese_anno}
              {effectiveAnaMonth !== meseAnno && (
                <span className="ml-2 text-green-600">(registry: {effectiveAnaMonth})</span>
              )}
              <span className="ml-2 text-green-500">({elapsed}s)</span>
            </div>
            <button
              onClick={handleDownload}
              disabled={downloading}
              className="flex items-center gap-2 px-4 py-2.5 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
            >
              <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
              {downloading ? 'Downloading…' : 'Download Excel (by DP)'}
            </button>
            <button
              onClick={handleDownloadPods}
              disabled={downloadingPods}
              className="flex items-center gap-2 px-4 py-2.5 bg-violet-600 text-white text-sm font-medium rounded-lg hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
            >
              <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
              {downloadingPods ? 'Downloading…' : 'Download CSV (per POD)'}
            </button>
          </div>
        )}
      </div>

      {forecast.length > 0 && (
        <>
          {/* Download toolbar — always visible when data exists */}
          <div className="flex flex-wrap gap-2 items-center">
            <span className="text-xs text-slate-400 font-medium uppercase tracking-wide mr-1">Forecast:</span>
            <button
              onClick={handleDownload}
              disabled={downloading || !accountId}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 text-white text-xs font-medium rounded-lg hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
              {downloading ? 'Downloading…' : 'By dispatching point'}
            </button>
            <button
              onClick={handleDownloadPods}
              disabled={downloadingPods || !accountId}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-600 text-white text-xs font-medium rounded-lg hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
              {downloadingPods ? 'Downloading…' : 'Per POD (96 periods)'}
            </button>
            <span className="text-xs text-slate-300 mx-1">|</span>
            <span className="text-xs text-slate-400 font-medium uppercase tracking-wide mr-1">Source data:</span>
            {measurementMonths.length === 0 ? (
              <span className="text-xs text-slate-400 italic">No measurement data available</span>
            ) : (
              <>
                <select
                  value={measMonth || measurementMonths[0]}
                  onChange={e => setMeasMonth(e.target.value)}
                  className="text-xs border border-slate-200 rounded-lg px-2 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-amber-500"
                >
                  {measurementMonths.map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
                <button
                  onClick={handleDownloadMeasurements}
                  disabled={downloadingMeasurements}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 text-white text-xs font-medium rounded-lg hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                  {downloadingMeasurements ? 'Downloading…' : 'Measurements (96 periods)'}
                </button>
              </>
            )}
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'PODs', value: itNum(displayPods, { maximumFractionDigits: 0 }) },
              { label: 'Total MWh (with loss)', value: itNum(displayMwh, { maximumFractionDigits: 1 }) },
              { label: 'Periods', value: itNum(displayPeriods, { maximumFractionDigits: 0 }) },
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
              {Object.entries(displaySourceCount).sort(([, a], [, b]) => b - a).map(([type, count]) => (
                <div key={type} className="flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium"
                  style={{ backgroundColor: `${SOURCE_COLORS[type]}18`, color: SOURCE_COLORS[type] }}>
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: SOURCE_COLORS[type] }} />
                  {SOURCE_LABELS[type] ?? type}
                  <span className="font-semibold">{displayTotal > 0 ? ((count / displayTotal) * 100).toFixed(1) : '0.0'}%</span>
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

      {!loadingForecast && forecast.length === 0 && !!accountId && jobStatus === 'idle' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-10 text-center">
          <p className="text-slate-400 text-sm">No forecast data for {meseAnno}. Click Generate Forecast above.</p>
        </div>
      )}
    </div>
  )
}


// ── Compare Tab ───────────────────────────────────────────────────────────────
function CompareTab() {
  const [accountId, setAccountId] = useState('')
  const [compareMode, setCompareMode] = useState<'pod' | 'dp'>('pod')

  // Single-POD state
  const [pod, setPod] = useState('')
  const [fromDate, setFromDate] = useState(firstOfMonth)
  const [toDate, setToDate] = useState(today)
  const [submittedPod, setSubmittedPod] = useState(false)
  const [podDownloading, setPodDownloading] = useState(false)
  const [podDownloadError, setPodDownloadError] = useState<string | null>(null)

  // DP-aggregate state
  const [dpFromDate, setDpFromDate] = useState(firstOfMonth)
  const [dpToDate, setDpToDate] = useState(today)
  const [dpAnaMonth, setDpAnaMonth] = useState('')
  const [dpSubmitted, setDpSubmitted] = useState(false)
  const [dpDownloading, setDpDownloading] = useState(false)
  const [dpError, setDpError] = useState<string | null>(null)

  const { data: accounts = [] } = useQuery({ queryKey: ['accounts'], queryFn: fetchAccounts })
  const { data: pods = [] } = useQuery({
    queryKey: ['pods', accountId], queryFn: () => fetchPods(accountId), enabled: !!accountId && compareMode === 'pod',
  })
  const { data: anagraficaMonths = [] } = useQuery({
    queryKey: ['anagrafica-months', accountId],
    queryFn: () => fetchAnagraficaMonths(accountId),
    enabled: !!accountId && compareMode === 'dp',
  })

  // Single-POD query
  const { data: compare, isLoading: podLoading, error: podError, refetch: podRefetch } = useQuery({
    queryKey: ['forecast-compare', accountId, pod, fromDate, toDate],
    queryFn: () => fetchForecastCompare(accountId, pod, fromDate, toDate),
    enabled: false,
  })

  // DP query
  const { data: dpCompare, isLoading: dpLoading, refetch: dpRefetch } = useQuery({
    queryKey: ['forecast-compare-dp', accountId, dpFromDate, dpToDate, dpAnaMonth],
    queryFn: () => fetchForecastCompareDP(accountId, dpFromDate, dpToDate, dpAnaMonth || undefined),
    enabled: false,
  })

  function runPod() { setSubmittedPod(true); setPodDownloadError(null); podRefetch() }
  function runDP() { setDpSubmitted(true); setDpError(null); dpRefetch() }

  async function handlePodDownload() {
    setPodDownloading(true)
    setPodDownloadError(null)
    try {
      await downloadComparePodExcel(accountId, pod, fromDate, toDate)
    } catch (e) {
      setPodDownloadError((e as Error).message)
    } finally {
      setPodDownloading(false)
    }
  }

  async function handleDPDownload() {
    setDpDownloading(true)
    try {
      await downloadCompareDPExcel(accountId, dpFromDate, dpToDate, dpAnaMonth || undefined)
    } catch (e) {
      setDpError((e as Error).message)
    } finally {
      setDpDownloading(false)
    }
  }

  // Single-POD chart
  const podChartData = (() => {
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

  const podDelta = compare ? compare.current_total_mwh - compare.previous_total_mwh : 0
  const podDeltaPct = compare && compare.previous_total_mwh
    ? ((podDelta / compare.previous_total_mwh) * 100).toFixed(1)
    : null

  // DP chart — show total current vs total previous
  const dpChartData = (() => {
    if (!dpCompare) return []
    const prevByIdx: Record<number, number> = {}
    dpCompare.previous_daily.forEach((r, i) => { prevByIdx[i] = r.total })
    return dpCompare.current_daily.map((r, i) => ({
      date: r.date.slice(5),
      'Current year': r.total,
      'Previous year': prevByIdx[i] ?? null,
    }))
  })()

  const dpDelta = dpCompare ? dpCompare.current_total_mwh - dpCompare.previous_total_mwh : 0
  const dpDeltaPct = dpCompare && dpCompare.previous_total_mwh
    ? ((dpDelta / dpCompare.previous_total_mwh) * 100).toFixed(1)
    : null

  // Derive default ana month from dp from_date
  const defaultAnaMonth = (() => {
    const d = new Date(dpFromDate)
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    return `${mm}/${d.getFullYear()}`
  })()

  return (
    <div className="space-y-6">
      {/* Mode toggle */}
      <div className="flex gap-1 p-1 bg-slate-100 rounded-xl w-fit">
        <button onClick={() => setCompareMode('pod')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${compareMode === 'pod' ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}>
          Single POD
        </button>
        <button onClick={() => setCompareMode('dp')}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${compareMode === 'dp' ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}>
          All PODs by Dispatching Point
        </button>
      </div>

      {/* ── Single-POD mode ── */}
      {compareMode === 'pod' && (
        <>
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
            <h2 className="text-sm font-semibold text-slate-700 mb-1">Partial Month Comparison — Single POD</h2>
            <p className="text-xs text-slate-400 mb-4">
              Compare a date range in the current year against the same range one year prior.
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
              <button onClick={runPod} disabled={!accountId || !pod || podLoading}
                className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                {podLoading ? 'Loading…' : 'Run Compare'}
              </button>
              {compare && (
                <button
                  onClick={handlePodDownload}
                  disabled={podDownloading}
                  className="flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                  {podDownloading ? 'Downloading…' : 'Download Excel'}
                </button>
              )}
            </div>
            {(podError || podDownloadError) && (
              <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {podDownloadError ?? (podError as Error).message}
              </div>
            )}
          </div>

          {compare && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
                  <p className="text-xs text-slate-400 uppercase tracking-wide">Current period</p>
                  <p className="text-[11px] text-slate-400 mt-0.5">{compare.current_period.from} → {compare.current_period.to}</p>
                  <p className="text-2xl font-semibold text-blue-700 mt-2 tabular-nums">
                    {itMwh(compare.current_total_mwh)}<span className="text-sm font-normal text-slate-400 ml-1">MWh</span>
                  </p>
                </div>
                <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
                  <p className="text-xs text-slate-400 uppercase tracking-wide">Previous year</p>
                  <p className="text-[11px] text-slate-400 mt-0.5">{compare.previous_period.from} → {compare.previous_period.to}</p>
                  <p className="text-2xl font-semibold text-slate-700 mt-2 tabular-nums">
                    {itMwh(compare.previous_total_mwh)}<span className="text-sm font-normal text-slate-400 ml-1">MWh</span>
                  </p>
                </div>
                <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
                  <p className="text-xs text-slate-400 uppercase tracking-wide">Difference</p>
                  <p className="text-2xl font-semibold mt-2 tabular-nums" style={{ color: podDelta >= 0 ? '#16a34a' : '#dc2626' }}>
                    {podDelta >= 0 ? '+' : ''}{itMwh(podDelta)}<span className="text-sm font-normal text-slate-400 ml-1">MWh</span>
                  </p>
                </div>
                <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
                  <p className="text-xs text-slate-400 uppercase tracking-wide">Change %</p>
                  <p className="text-2xl font-semibold mt-2 tabular-nums" style={{ color: podDelta >= 0 ? '#16a34a' : '#dc2626' }}>
                    {podDeltaPct != null ? `${Number(podDeltaPct) >= 0 ? '+' : ''}${podDeltaPct}%` : '—'}
                  </p>
                </div>
              </div>

              <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
                <h2 className="text-sm font-semibold text-slate-700 mb-1">Daily MWh — Current vs Previous Year</h2>
                <p className="text-xs text-slate-400 mb-4">POD: <span className="font-mono">{compare.pod}</span></p>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={podChartData} margin={{ left: 0, right: 16, top: 8, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="day" tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} unit=" MWh" />
                    <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #e2e8f0', fontSize: 12 }}
                      formatter={(v: number) => [`${v.toFixed(4)} MWh`]} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="Current year" stroke="#2563eb" strokeWidth={2} dot={false} connectNulls />
                    <Line type="monotone" dataKey="Previous year" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 2" dot={false} connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              </div>

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
                      {podChartData.map((row, i) => {
                        const curr = row['Current year'] as number | null
                        const prev = row['Previous year'] as number | null
                        const d = curr != null && prev != null ? curr - prev : null
                        const pct = d != null && prev ? (d / prev) * 100 : null
                        return (
                          <tr key={i} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                            <td className="px-5 py-2.5 text-slate-600">{row._curr_date as string}</td>
                            <td className="px-4 py-2.5 tabular-nums text-right font-medium text-blue-700">{itMwh(curr)}</td>
                            <td className="px-4 py-2.5 tabular-nums text-right text-slate-500">{itMwh(prev)}</td>
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
                          style={{ color: podDelta >= 0 ? '#16a34a' : '#dc2626' }}>
                          {podDelta >= 0 ? '+' : ''}{itMwh(podDelta)}
                        </td>
                        <td className="px-4 py-3 tabular-nums text-right text-xs"
                          style={{ color: podDelta >= 0 ? '#16a34a' : '#dc2626' }}>
                          {podDeltaPct != null ? `${Number(podDeltaPct) >= 0 ? '+' : ''}${itNum(Number(podDeltaPct), { maximumFractionDigits: 1 })}%` : '—'}
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            </>
          )}

          {submittedPod && !podLoading && !compare && !podError && (
            <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-10 text-center">
              <p className="text-slate-400 text-sm">No forecast data found for the selected POD and date range.</p>
            </div>
          )}
        </>
      )}

      {/* ── All PODs by DP mode ── */}
      {compareMode === 'dp' && (
        <>
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
            <h2 className="text-sm font-semibold text-slate-700 mb-1">Partial Month Comparison — All PODs by Dispatching Point</h2>
            <p className="text-xs text-slate-400 mb-4">
              Aggregates all PODs from the ANAGRAFICA registry and compares daily MWh per dispatching point against the same range one year prior.
            </p>
            <div className="flex flex-wrap gap-3 items-end">
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Account</label>
                <select value={accountId} onChange={e => setAccountId(e.target.value)}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[160px]">
                  <option value="">Select account…</option>
                  {accounts.map(a => <option key={a.account_id} value={a.account_id}>{a.display_name ?? a.account_id}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Registry Month</label>
                <select
                  value={dpAnaMonth || defaultAnaMonth}
                  onChange={e => setDpAnaMonth(e.target.value)}
                  disabled={!accountId}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[140px] disabled:opacity-40"
                >
                  {anagraficaMonths.length === 0
                    ? <option value={defaultAnaMonth}>{defaultAnaMonth} (auto)</option>
                    : anagraficaMonths.map(m => <option key={m} value={m}>{m}</option>)
                  }
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">From date</label>
                <input type="date" value={dpFromDate} onChange={e => setDpFromDate(e.target.value)}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">To date</label>
                <input type="date" value={dpToDate} onChange={e => setDpToDate(e.target.value)}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <button onClick={runDP} disabled={!accountId || dpLoading}
                className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                {dpLoading ? 'Loading…' : 'Run Compare'}
              </button>
              {dpCompare && dpCompare.dispatching_points.length > 0 && (
                <button
                  onClick={handleDPDownload}
                  disabled={dpDownloading}
                  className="flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                  {dpDownloading ? 'Downloading…' : 'Download Excel'}
                </button>
              )}
            </div>
            {dpError && (
              <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{dpError}</div>
            )}
          </div>

          {dpCompare && dpCompare.dispatching_points.length > 0 && (
            <>
              {/* Summary cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
                  <p className="text-xs text-slate-400 uppercase tracking-wide">Current period</p>
                  <p className="text-[11px] text-slate-400 mt-0.5">{dpCompare.current_period.from} → {dpCompare.current_period.to}</p>
                  <p className="text-2xl font-semibold text-blue-700 mt-2 tabular-nums">
                    {itMwh(dpCompare.current_total_mwh)}<span className="text-sm font-normal text-slate-400 ml-1">MWh</span>
                  </p>
                </div>
                <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
                  <p className="text-xs text-slate-400 uppercase tracking-wide">Previous year</p>
                  <p className="text-[11px] text-slate-400 mt-0.5">{dpCompare.previous_period.from} → {dpCompare.previous_period.to}</p>
                  <p className="text-2xl font-semibold text-slate-700 mt-2 tabular-nums">
                    {itMwh(dpCompare.previous_total_mwh)}<span className="text-sm font-normal text-slate-400 ml-1">MWh</span>
                  </p>
                </div>
                <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
                  <p className="text-xs text-slate-400 uppercase tracking-wide">Difference</p>
                  <p className="text-2xl font-semibold mt-2 tabular-nums" style={{ color: dpDelta >= 0 ? '#16a34a' : '#dc2626' }}>
                    {dpDelta >= 0 ? '+' : ''}{itMwh(dpDelta)}<span className="text-sm font-normal text-slate-400 ml-1">MWh</span>
                  </p>
                </div>
                <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
                  <p className="text-xs text-slate-400 uppercase tracking-wide">Dispatching Points</p>
                  <p className="text-2xl font-semibold text-slate-900 mt-2">{dpCompare.dispatching_points.length}</p>
                </div>
              </div>

              {/* DP legend */}
              <div className="flex flex-wrap gap-2 items-center">
                {dpCompare.dispatching_points.map((dp, i) => (
                  <span key={dp} className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium"
                    style={{ backgroundColor: `${DP_COLORS[i % DP_COLORS.length]}18`, color: DP_COLORS[i % DP_COLORS.length] }}>
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: DP_COLORS[i % DP_COLORS.length] }} />
                    {dp}
                  </span>
                ))}
              </div>

              {/* Chart — total current vs total previous */}
              <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
                <h2 className="text-sm font-semibold text-slate-700 mb-1">Daily Total MWh — All DPs Combined</h2>
                <p className="text-xs text-slate-400 mb-4">
                  Current year (solid) vs previous year (dashed) — registry: {dpCompare.anagrafica_month}
                </p>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={dpChartData} margin={{ left: 0, right: 16, top: 8, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} unit=" MWh" />
                    <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #e2e8f0', fontSize: 12 }}
                      formatter={(v: number) => [`${v.toFixed(4)} MWh`]} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="Current year" stroke="#2563eb" strokeWidth={2} dot={false} connectNulls />
                    <Line type="monotone" dataKey="Previous year" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 2" dot={false} connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              {/* Table — per-DP breakdown */}
              <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
                <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-slate-700">
                    Daily Breakdown by Dispatching Point
                    <span className="ml-2 text-slate-400 font-normal text-xs">Current year</span>
                  </h2>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-slate-400 uppercase tracking-wide text-[10px] border-b border-slate-100">
                        <th className="text-left px-5 py-3 font-medium">Date</th>
                        {dpCompare.dispatching_points.map((dp, i) => (
                          <th key={dp} className="text-right px-3 py-3 font-medium" style={{ color: DP_COLORS[i % DP_COLORS.length] }}>
                            {dp}
                          </th>
                        ))}
                        <th className="text-right px-4 py-3 font-medium text-slate-600">Total</th>
                        <th className="text-right px-4 py-3 font-medium text-slate-400">Prev Total</th>
                        <th className="text-right px-4 py-3 font-medium">Δ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dpCompare.current_daily.map((row, i) => {
                        const prevRow = dpCompare.previous_daily[i]
                        const prevTotal = prevRow?.total ?? 0
                        const delta = row.total - prevTotal
                        return (
                          <tr key={i} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                            <td className="px-5 py-2.5 text-slate-600 tabular-nums">{row.date}</td>
                            {dpCompare.dispatching_points.map((dp, j) => (
                              <td key={dp} className="px-3 py-2.5 tabular-nums text-right text-slate-700">
                                {itMwh(row[dp] as number)}
                              </td>
                            ))}
                            <td className="px-4 py-2.5 tabular-nums text-right font-medium text-slate-800">{itMwh(row.total)}</td>
                            <td className="px-4 py-2.5 tabular-nums text-right text-slate-400">{itMwh(prevTotal)}</td>
                            <td className="px-4 py-2.5 tabular-nums text-right font-medium"
                              style={{ color: delta >= 0 ? '#16a34a' : '#dc2626' }}>
                              {delta >= 0 ? '+' : ''}{itMwh(delta)}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                    <tfoot>
                      <tr className="border-t border-slate-200 bg-slate-50 font-semibold">
                        <td className="px-5 py-3 text-xs text-slate-600">Total</td>
                        {dpCompare.dispatching_points.map(dp => (
                          <td key={dp} className="px-3 py-3 tabular-nums text-right text-xs text-slate-700">
                            {itMwh(dpCompare.current_daily.reduce((s, r) => s + (r[dp] as number || 0), 0))}
                          </td>
                        ))}
                        <td className="px-4 py-3 tabular-nums text-right text-xs text-blue-700">{itMwh(dpCompare.current_total_mwh)}</td>
                        <td className="px-4 py-3 tabular-nums text-right text-xs text-slate-500">{itMwh(dpCompare.previous_total_mwh)}</td>
                        <td className="px-4 py-3 tabular-nums text-right text-xs"
                          style={{ color: dpDelta >= 0 ? '#16a34a' : '#dc2626' }}>
                          {dpDelta >= 0 ? '+' : ''}{itMwh(dpDelta)}
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            </>
          )}

          {dpSubmitted && !dpLoading && dpCompare && dpCompare.dispatching_points.length === 0 && (
            <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-10 text-center">
              <p className="text-slate-400 text-sm">
                No ANAGRAFICA data found for {dpCompare.anagrafica_month}. Upload an ANAGRAFICA file or change the registry month.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}


// ── Page shell ────────────────────────────────────────────────────────────────
export default function ForecastPage() {
  const [mode, setMode] = useState<'generate' | 'compare'>('generate')

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Forecast Engine</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Generate monthly energy forecasts and compare periods across years.
          </p>
        </div>
      </div>

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

      {/* Keep both tabs mounted so state survives tab switches */}
      <div className={mode !== 'generate' ? 'hidden' : ''}><GenerateTab /></div>
      <div className={mode !== 'compare' ? 'hidden' : ''}><CompareTab /></div>
    </div>
  )
}
