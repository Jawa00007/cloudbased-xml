import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  AreaChart, Area,
  BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { fetchPeriods, fetchMonthlyTotals, fetchDailyTotals, fetchPeriodRange } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import { exportCSV } from '../utils/export'

const periodToTime = (p: number) => {
  const m = (p - 1) * 15
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}

const today  = () => new Date().toISOString().slice(0, 10)
const curMM  = () => { const d = new Date(); return `${String(d.getMonth()+1).padStart(2,'0')}/${d.getFullYear()}` }
const curYY  = () => String(new Date().getFullYear())
const toIM   = (m: string) => `${m.slice(3)}-${m.slice(0,2)}`
const fromIM = (v: string) => { const [y,m]=v.split('-'); return `${m}/${y}` }

type Tab = 'curve' | 'table' | 'daily' | 'monthly'

const CHART_STYLE = {
  contentStyle: {
    border: '1px solid #e2e8f0',
    borderRadius: 12,
    fontSize: 12,
    boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.08)',
  },
}

export default function PodPage() {
  const { accountId, pod } = useParams<{ accountId: string; pod: string }>()
  const account = accountId!

  const [tab,       setTab]       = useState<Tab>('curve')
  const [date,      setDate]      = useState(today)
  const [meseAnno,  setMeseAnno]  = useState(curMM)
  const [year,      setYear]      = useState(curYY)
  const [fromDate,  setFromDate]  = useState(() => { const d=new Date(); d.setDate(1); return d.toISOString().slice(0,10) })
  const [toDate,    setToDate]    = useState(today)
  const [tipoDato,  setTipoDato]  = useState<string>('')

  const periods = useQuery({
    queryKey: ['periods', account, pod, date],
    queryFn: () => fetchPeriods(account, pod!, date),
    enabled: tab === 'curve',
  })

  const rangeData = useQuery({
    queryKey: ['range', account, pod, fromDate, toDate, tipoDato],
    queryFn: () => fetchPeriodRange(account, pod!, fromDate, toDate, tipoDato || undefined),
    enabled: tab === 'table',
  })

  const daily = useQuery({
    queryKey: ['daily', account, pod, meseAnno],
    queryFn: () => fetchDailyTotals(account, pod!, meseAnno),
    enabled: tab === 'daily',
  })

  const monthly = useQuery({
    queryKey: ['monthly', account, pod, year],
    queryFn: () => fetchMonthlyTotals(account, pod!, year),
    enabled: tab === 'monthly',
  })

  const TABS: { id: Tab; label: string }[] = [
    { id: 'curve',   label: '96-Period Curve' },
    { id: 'table',   label: 'Data Table' },
    { id: 'daily',   label: 'Daily Totals' },
    { id: 'monthly', label: 'Monthly Totals' },
  ]

  return (
    <div className="space-y-5">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <Link to="/" className="text-slate-400 hover:text-slate-600 transition-colors">Accounts</Link>
        <svg className="w-3.5 h-3.5 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
        <Link to={`/account/${account}`} className="text-slate-400 hover:text-slate-600 transition-colors">{account}</Link>
        <svg className="w-3.5 h-3.5 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
        <span className="text-slate-700 text-xs font-mono">{pod}</span>
      </div>

      {/* POD header */}
      <div className="bg-white rounded-2xl border border-slate-100 shadow-sm px-6 py-5">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest mb-1">Point of Delivery</p>
            <p className="text-lg font-mono font-semibold text-slate-900 tracking-wide">{pod}</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200 px-2.5 py-1 rounded-lg font-medium">{account}</span>
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-slate-100/80 p-1 rounded-xl w-fit">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              tab === t.id
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── 96-Period Curve ── */}
      {tab === 'curve' && (
        <div className="space-y-4">
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-50">
              <div>
                <p className="text-sm font-semibold text-slate-900">Quarter-hourly curve</p>
                {periods.data && (
                  <p className="text-xs text-slate-400 mt-0.5 flex items-center gap-2">
                    <span>{periods.data.filter(r => r.ea_kwh != null).length} of 96 periods</span>
                    {periods.data[0] && <StatusBadge value={periods.data[0].tipo_dato} />}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {periods.data && periods.data.length > 0 && (
                  <ExportBtn onClick={() => exportCSV(
                    periods.data!.map(r => ({ ...r, time: periodToTime(r.periodo) })),
                    `${account}_${pod}_${date}_curve.csv`
                  )} />
                )}
                <input
                  type="date"
                  value={date}
                  onChange={e => setDate(e.target.value)}
                  className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-300"
                />
              </div>
            </div>

            <div className="px-6 pt-5 pb-4">
              {periods.isLoading && <ChartSkeleton />}
              {periods.error && <EmptyState text={`No data for ${date}`} />}
              {periods.data && periods.data.length === 0 && <EmptyState text={`No readings for ${date}`} />}
              {periods.data && periods.data.length > 0 && (
                <ResponsiveContainer width="100%" height={280}>
                  <AreaChart
                    data={periods.data.map(r => ({ time: periodToTime(r.periodo), kWh: r.ea_kwh != null ? +r.ea_kwh : null }))}
                    margin={{ top: 4, right: 4, left: 0, bottom: 4 }}
                  >
                    <defs>
                      <linearGradient id="gradKwh" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%"  stopColor="#3b82f6" stopOpacity={0.15} />
                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#94a3b8' }} interval={11} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} unit=" kWh" width={64} />
                    <Tooltip
                      {...CHART_STYLE}
                      formatter={(v: number) => [`${v?.toFixed(3)} kWh`, 'Active energy']}
                    />
                    <ReferenceLine y={0} stroke="#e2e8f0" />
                    <Area
                      type="monotone"
                      dataKey="kWh"
                      stroke="#3b82f6"
                      strokeWidth={2}
                      fill="url(#gradKwh)"
                      dot={false}
                      connectNulls={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* Period table */}
          {periods.data && periods.data.length > 0 && (
            <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
              <div className="grid grid-cols-5 px-6 py-3 bg-slate-50 text-[10px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-100">
                <span>Period</span><span>Time</span><span>kWh</span><span>kVArh</span><span>Type / DST</span>
              </div>
              <div className="max-h-72 overflow-y-auto scrollbar-thin divide-y divide-slate-50">
                {periods.data.map(r => (
                  <div key={r.periodo} className="grid grid-cols-5 px-6 py-2 text-xs hover:bg-slate-50/70">
                    <span className="text-slate-400 tabular-nums">{r.periodo}</span>
                    <span className="text-slate-600 font-mono">{periodToTime(r.periodo)}</span>
                    <span className={`tabular-nums font-medium ${r.ea_kwh == null ? 'text-slate-200' : 'text-slate-800'}`}>
                      {r.ea_kwh != null ? (+r.ea_kwh).toFixed(3) : '—'}
                    </span>
                    <span className="text-slate-400 tabular-nums">{r.er_kvarh != null ? (+r.er_kvarh).toFixed(3) : '—'}</span>
                    <span className="flex items-center gap-1.5">
                      <StatusBadge value={r.tipo_dato} />
                      {r.dst > 0 && <span className="text-amber-500 text-[10px] font-medium">DST{r.dst}</span>}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Data Table (range) ── */}
      {tab === 'table' && (
        <div className="space-y-4">
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Filters</p>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2">
                <label className="text-xs text-slate-400">From</label>
                <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
                  className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-300" />
              </div>
              <div className="flex items-center gap-2">
                <label className="text-xs text-slate-400">To</label>
                <input type="date" value={toDate} onChange={e => setToDate(e.target.value)}
                  className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-300" />
              </div>
              <div className="flex items-center gap-2">
                <label className="text-xs text-slate-400">Type</label>
                <select value={tipoDato} onChange={e => setTipoDato(e.target.value)}
                  className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-300">
                  <option value="">All (E + S)</option>
                  <option value="E">E — Effective</option>
                  <option value="S">S — Estimated</option>
                </select>
              </div>
              {rangeData.data && rangeData.data.length > 0 && (
                <ExportBtn onClick={() => exportCSV(
                  rangeData.data!.map(r => ({ ...r, time: periodToTime(r.periodo) })),
                  `${account}_${pod}_${fromDate}_${toDate}.csv`
                )} />
              )}
              {rangeData.data && (
                <span className="text-xs text-slate-400 ml-auto">{rangeData.data.length.toLocaleString()} records</span>
              )}
            </div>
          </div>

          {rangeData.isLoading && <LoadingSkeleton />}
          {rangeData.error && <ErrorCard text={String(rangeData.error)} />}
          {rangeData.data && (
            <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
              <div className="grid grid-cols-6 px-6 py-3 bg-slate-50 text-[10px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-100">
                <span>Date</span><span>Period</span><span>Time</span><span>kWh</span><span>kVArh</span><span>Type</span>
              </div>
              <div className="max-h-[60vh] overflow-y-auto scrollbar-thin divide-y divide-slate-50">
                {rangeData.data.length === 0 && <EmptyState text="No readings for selected range" />}
                {rangeData.data.map((r, i) => (
                  <div key={i} className="grid grid-cols-6 px-6 py-2 text-xs hover:bg-slate-50/70">
                    <span className="text-slate-700 tabular-nums">{r.data_misura}</span>
                    <span className="text-slate-400 tabular-nums">{r.periodo}</span>
                    <span className="text-slate-500 font-mono">{periodToTime(r.periodo)}</span>
                    <span className={`tabular-nums font-medium ${r.ea_kwh == null ? 'text-slate-200' : 'text-slate-800'}`}>
                      {r.ea_kwh != null ? (+r.ea_kwh).toFixed(3) : '—'}
                    </span>
                    <span className="text-slate-400 tabular-nums">{r.er_kvarh != null ? (+r.er_kvarh).toFixed(3) : '—'}</span>
                    <StatusBadge value={r.tipo_dato} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Daily Totals ── */}
      {tab === 'daily' && (
        <div className="space-y-4">
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-50">
              <div>
                <p className="text-sm font-semibold text-slate-900">Daily active energy</p>
                <p className="text-xs text-slate-400 mt-0.5">{meseAnno}</p>
              </div>
              <div className="flex items-center gap-2">
                {daily.data && daily.data.length > 0 && (
                  <ExportBtn onClick={() => exportCSV(daily.data!, `${account}_${pod}_daily_${meseAnno.replace('/','-')}.csv`)} />
                )}
                <input type="month" value={toIM(meseAnno)} onChange={e => setMeseAnno(fromIM(e.target.value))}
                  className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-300" />
              </div>
            </div>

            <div className="px-6 pt-5 pb-4">
              {daily.isLoading && <ChartSkeleton />}
              {daily.error && <EmptyState text={`No data for ${meseAnno}`} />}
              {daily.data && daily.data.length === 0 && <EmptyState text={`No daily data for ${meseAnno}`} />}
              {daily.data && daily.data.length > 0 && (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={daily.data} margin={{ top: 4, right: 4, left: 0, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis dataKey="data_misura" tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={d => d.slice(8)} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} unit=" kWh" width={64} />
                    <Tooltip {...CHART_STYLE} formatter={(v: number) => [`${v?.toFixed(3)} kWh`, 'Daily total']} cursor={{ fill: '#f8fafc' }} />
                    <Bar dataKey="daily_kwh" fill="#3b82f6" radius={[4, 4, 0, 0]} maxBarSize={28} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {daily.data && daily.data.length > 0 && (
            <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
              <div className="grid grid-cols-5 px-6 py-3 bg-slate-50 text-[10px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-100">
                <span>Date</span><span>kWh</span><span>kVArh</span><span>Periods</span><span>Source</span>
              </div>
              <div className="divide-y divide-slate-50">
                {daily.data.map(r => (
                  <div key={r.data_misura} className="grid grid-cols-5 px-6 py-2.5 text-xs hover:bg-slate-50/70">
                    <span className="text-slate-700 tabular-nums">{r.data_misura}</span>
                    <span className="text-slate-800 font-semibold tabular-nums">{r.daily_kwh?.toFixed(3) ?? '—'}</span>
                    <span className="text-slate-500 tabular-nums">{r.daily_kvarh?.toFixed(3) ?? '—'}</span>
                    <span className={`tabular-nums font-medium ${r.periods < 96 ? 'text-amber-600' : 'text-slate-400'}`}>{r.periods}/96</span>
                    <StatusBadge value={r.source} />
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-5 px-6 py-3 bg-slate-50 text-xs font-semibold text-slate-700 border-t border-slate-100">
                <span>{daily.data.length} days</span>
                <span className="tabular-nums">{daily.data.reduce((s, r) => s + (r.daily_kwh ?? 0), 0).toFixed(3)} kWh</span>
                <span className="tabular-nums">{daily.data.reduce((s, r) => s + (r.daily_kvarh ?? 0), 0).toFixed(3)} kVArh</span>
                <span /><span />
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Monthly Totals ── */}
      {tab === 'monthly' && (
        <div className="space-y-4">
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-50">
              <div>
                <p className="text-sm font-semibold text-slate-900">Monthly active energy</p>
                <p className="text-xs text-slate-400 mt-0.5">{year}</p>
              </div>
              <div className="flex items-center gap-2">
                {monthly.data && monthly.data.length > 0 && (
                  <ExportBtn onClick={() => exportCSV(monthly.data!, `${account}_${pod}_monthly_${year}.csv`)} />
                )}
                <select value={year} onChange={e => setYear(e.target.value)}
                  className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-300">
                  {[2020,2021,2022,2023,2024,2025,2026].map(y => <option key={y} value={y}>{y}</option>)}
                </select>
              </div>
            </div>

            <div className="px-6 pt-5 pb-4">
              {monthly.isLoading && <ChartSkeleton />}
              {monthly.error && <EmptyState text={`No data for ${year}`} />}
              {monthly.data && monthly.data.length === 0 && <EmptyState text={`No data for ${year}`} />}
              {monthly.data && monthly.data.length > 0 && (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={monthly.data} margin={{ top: 4, right: 4, left: 0, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis dataKey="mese_anno" tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={m => m.slice(0,2)} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} unit=" kWh" width={72} />
                    <Tooltip {...CHART_STYLE} formatter={(v: number) => [`${v?.toFixed(1)} kWh`, 'Monthly total']} cursor={{ fill: '#f8fafc' }} />
                    <Bar dataKey="monthly_kwh" fill="#3b82f6" radius={[4, 4, 0, 0]} maxBarSize={40} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {monthly.data && monthly.data.length > 0 && (
            <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
              <div className="grid grid-cols-5 px-6 py-3 bg-slate-50 text-[10px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-100">
                <span>Month</span><span>kWh</span><span>kVArh</span><span>Days</span><span>Source</span>
              </div>
              <div className="divide-y divide-slate-50">
                {monthly.data.map(r => (
                  <div key={r.mese_anno} className="grid grid-cols-5 px-6 py-2.5 text-xs hover:bg-slate-50/70">
                    <span className="text-slate-700 font-medium">{r.mese_anno}</span>
                    <span className="text-slate-800 font-semibold tabular-nums">{r.monthly_kwh?.toFixed(1) ?? '—'}</span>
                    <span className="text-slate-500 tabular-nums">{r.monthly_kvarh?.toFixed(1) ?? '—'}</span>
                    <span className="text-slate-400">{r.days}</span>
                    <StatusBadge value={r.source} />
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-5 px-6 py-3 bg-slate-50 text-xs font-semibold text-slate-700 border-t border-slate-100">
                <span>Total {year}</span>
                <span className="tabular-nums">{monthly.data.reduce((s, r) => s + (r.monthly_kwh ?? 0), 0).toFixed(1)} kWh</span>
                <span className="tabular-nums">{monthly.data.reduce((s, r) => s + (r.monthly_kvarh ?? 0), 0).toFixed(1)} kVArh</span>
                <span>{monthly.data.length} months</span>
                <span />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ExportBtn({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-blue-600 border border-slate-200 hover:border-blue-300 rounded-lg px-3 py-1.5 transition-all bg-white"
    >
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
      </svg>
      Export
    </button>
  )
}

function ChartSkeleton() {
  return <div className="h-56 bg-slate-50 rounded-xl animate-pulse" />
}
function LoadingSkeleton() {
  return <div className="h-24 bg-slate-100 rounded-2xl animate-pulse" />
}
function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="w-10 h-10 bg-slate-50 rounded-full flex items-center justify-center mb-3">
        <svg className="w-5 h-5 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      </div>
      <p className="text-sm text-slate-400">{text}</p>
    </div>
  )
}
function ErrorCard({ text }: { text: string }) {
  return <div className="bg-red-50 border border-red-100 rounded-xl p-4 text-xs text-red-600">{text}</div>
}
