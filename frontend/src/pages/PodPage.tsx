import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, BarChart, Bar,
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
    <div className="space-y-4">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <Link to="/" className="text-slate-400 hover:text-slate-600">Accounts</Link>
        <span className="text-slate-300">/</span>
        <Link to={`/account/${account}`} className="text-slate-400 hover:text-slate-600">{account}</Link>
        <span className="text-slate-300">/</span>
        <span className="font-mono text-slate-700 text-xs">{pod}</span>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-slate-100 p-1 rounded-xl w-fit">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-1.5 text-sm font-medium rounded-lg transition-all ${
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
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Quarter-hourly curve</h2>
                {periods.data && (
                  <p className="text-xs text-slate-400 mt-0.5">
                    {periods.data.filter(r => r.ea_kwh != null).length} / 96 valid periods
                    {periods.data[0] && <> · <StatusBadge value={periods.data[0].tipo_dato} /></>}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {periods.data && (
                  <ExportBtn onClick={() => exportCSV(
                    periods.data!.map(r => ({ ...r, time: periodToTime(r.periodo) })),
                    `${account}_${pod}_${date}_curve.csv`
                  )} />
                )}
                <input type="date" value={date} onChange={e => setDate(e.target.value)}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300" />
              </div>
            </div>

            {periods.isLoading && <ChartSkeleton />}
            {periods.error   && <ErrorMsg text={`No data for ${date}`} />}
            {periods.data && periods.data.length === 0 && <ErrorMsg text={`No readings for ${date}`} />}
            {periods.data && periods.data.length > 0 && (
              <ResponsiveContainer width="100%" height={280}>
                <LineChart
                  data={periods.data.map(r => ({ time: periodToTime(r.periodo), kWh: r.ea_kwh != null ? +r.ea_kwh : null }))}
                  margin={{ top: 4, right: 8, left: 0, bottom: 4 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#94a3b8' }} interval={11} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} unit=" kWh" width={64} />
                  <Tooltip contentStyle={{ border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => [`${v?.toFixed(3)} kWh`, 'Active energy']} />
                  <ReferenceLine y={0} stroke="#e2e8f0" />
                  <Line type="monotone" dataKey="kWh" stroke="#3b82f6" dot={false} strokeWidth={1.5} connectNulls={false} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Period table */}
          {periods.data && periods.data.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="grid grid-cols-5 px-5 py-2.5 bg-slate-50 text-xs font-medium text-slate-500 border-b border-slate-100">
                <span>Period</span><span>Time</span><span>kWh</span><span>kVArh</span><span>Type / DST</span>
              </div>
              <div className="max-h-72 overflow-y-auto scrollbar-thin divide-y divide-slate-50">
                {periods.data.map(r => (
                  <div key={r.periodo} className="grid grid-cols-5 px-5 py-1.5 text-xs hover:bg-slate-50">
                    <span className="text-slate-400">{r.periodo}</span>
                    <span className="text-slate-600">{periodToTime(r.periodo)}</span>
                    <span className={r.ea_kwh == null ? 'text-slate-200' : 'text-slate-800 font-medium'}>
                      {r.ea_kwh != null ? (+r.ea_kwh).toFixed(3) : '—'}
                    </span>
                    <span className="text-slate-400">{r.er_kvarh != null ? (+r.er_kvarh).toFixed(3) : '—'}</span>
                    <span className="flex items-center gap-1">
                      <StatusBadge value={r.tipo_dato} />
                      {r.dst > 0 && <span className="text-amber-500 text-[10px]">DST{r.dst}</span>}
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
          {/* Filter bar */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2">
                <label className="text-xs font-medium text-slate-500">From</label>
                <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-300" />
              </div>
              <div className="flex items-center gap-2">
                <label className="text-xs font-medium text-slate-500">To</label>
                <input type="date" value={toDate} onChange={e => setToDate(e.target.value)}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-300" />
              </div>
              <div className="flex items-center gap-2">
                <label className="text-xs font-medium text-slate-500">Type</label>
                <select value={tipoDato} onChange={e => setTipoDato(e.target.value)}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-300">
                  <option value="">All (E + S)</option>
                  <option value="E">E — Effective</option>
                  <option value="S">S — Estimated</option>
                </select>
              </div>
              {rangeData.data && (
                <ExportBtn onClick={() => exportCSV(
                  rangeData.data!.map(r => ({ ...r, time: periodToTime(r.periodo) })),
                  `${account}_${pod}_${fromDate}_${toDate}.csv`
                )} />
              )}
              {rangeData.data && (
                <span className="text-xs text-slate-400 ml-auto">{rangeData.data.length} records</span>
              )}
            </div>
          </div>

          {rangeData.isLoading && <LoadingSkeleton />}
          {rangeData.error    && <ErrorMsg text={String(rangeData.error)} />}
          {rangeData.data && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="grid grid-cols-6 px-5 py-2.5 bg-slate-50 text-xs font-medium text-slate-500 border-b border-slate-100">
                <span>Date</span><span>Period</span><span>Time</span><span>kWh</span><span>kVArh</span><span>Type / Source</span>
              </div>
              <div className="max-h-[60vh] overflow-y-auto scrollbar-thin divide-y divide-slate-50">
                {rangeData.data.length === 0 && <EmptyState text="No readings for selected range" />}
                {rangeData.data.map((r, i) => (
                  <div key={i} className="grid grid-cols-6 px-5 py-1.5 text-xs hover:bg-slate-50">
                    <span className="text-slate-600">{r.data_misura}</span>
                    <span className="text-slate-400">{r.periodo}</span>
                    <span className="text-slate-500">{periodToTime(r.periodo)}</span>
                    <span className={r.ea_kwh == null ? 'text-slate-200' : 'text-slate-800 font-medium'}>
                      {r.ea_kwh != null ? (+r.ea_kwh).toFixed(3) : '—'}
                    </span>
                    <span className="text-slate-400">{r.er_kvarh != null ? (+r.er_kvarh).toFixed(3) : '—'}</span>
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
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Daily active energy</h2>
                <p className="text-xs text-slate-400 mt-0.5">{meseAnno}</p>
              </div>
              <div className="flex items-center gap-2">
                {daily.data && (
                  <ExportBtn onClick={() => exportCSV(daily.data!, `${account}_${pod}_daily_${meseAnno.replace('/','-')}.csv`)} />
                )}
                <input type="month" value={toIM(meseAnno)} onChange={e => setMeseAnno(fromIM(e.target.value))}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-300" />
              </div>
            </div>
            {daily.isLoading && <ChartSkeleton />}
            {daily.error    && <ErrorMsg text={`No data for ${meseAnno}`} />}
            {daily.data && daily.data.length === 0 && <ErrorMsg text={`No daily data for ${meseAnno}`} />}
            {daily.data && daily.data.length > 0 && (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={daily.data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                  <XAxis dataKey="data_misura" tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={d => d.slice(8)} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} unit=" kWh" width={64} />
                  <Tooltip contentStyle={{ border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => [`${v?.toFixed(3)} kWh`, 'Daily total']} />
                  <Bar dataKey="daily_kwh" fill="#3b82f6" radius={[3, 3, 0, 0]} maxBarSize={32} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {daily.data && daily.data.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="grid grid-cols-5 px-5 py-2.5 bg-slate-50 text-xs font-medium text-slate-500 border-b border-slate-100">
                <span>Date</span><span>kWh</span><span>kVArh</span><span>Periods</span><span>Source</span>
              </div>
              <div className="divide-y divide-slate-50">
                {daily.data.map(r => (
                  <div key={r.data_misura} className="grid grid-cols-5 px-5 py-2 text-xs hover:bg-slate-50">
                    <span className="text-slate-700">{r.data_misura}</span>
                    <span className="text-slate-800 font-medium">{r.daily_kwh?.toFixed(3) ?? '—'}</span>
                    <span className="text-slate-500">{r.daily_kvarh?.toFixed(3) ?? '—'}</span>
                    <span className={r.periods < 96 ? 'text-amber-600 font-medium' : 'text-slate-400'}>{r.periods}/96</span>
                    <StatusBadge value={r.source} />
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-5 px-5 py-2.5 bg-slate-50 text-xs font-semibold text-slate-700 border-t border-slate-100">
                <span>{daily.data.length} days</span>
                <span>{daily.data.reduce((s, r) => s + (r.daily_kwh ?? 0), 0).toFixed(3)} kWh</span>
                <span>{daily.data.reduce((s, r) => s + (r.daily_kvarh ?? 0), 0).toFixed(3)} kVArh</span>
                <span />
                <span />
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Monthly Totals ── */}
      {tab === 'monthly' && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Monthly active energy</h2>
                <p className="text-xs text-slate-400 mt-0.5">{year}</p>
              </div>
              <div className="flex items-center gap-2">
                {monthly.data && (
                  <ExportBtn onClick={() => exportCSV(monthly.data!, `${account}_${pod}_monthly_${year}.csv`)} />
                )}
                <select value={year} onChange={e => setYear(e.target.value)}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-300">
                  {[2020,2021,2022,2023,2024,2025,2026].map(y => <option key={y} value={y}>{y}</option>)}
                </select>
              </div>
            </div>
            {monthly.isLoading && <ChartSkeleton />}
            {monthly.error    && <ErrorMsg text={`No data for ${year}`} />}
            {monthly.data && monthly.data.length === 0 && <ErrorMsg text={`No data for ${year}`} />}
            {monthly.data && monthly.data.length > 0 && (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={monthly.data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                  <XAxis dataKey="mese_anno" tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={m => m.slice(0,2)} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} unit=" kWh" width={72} />
                  <Tooltip contentStyle={{ border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => [`${v?.toFixed(1)} kWh`, 'Monthly total']} />
                  <Bar dataKey="monthly_kwh" fill="#3b82f6" radius={[4, 4, 0, 0]} maxBarSize={40} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {monthly.data && monthly.data.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="grid grid-cols-5 px-5 py-2.5 bg-slate-50 text-xs font-medium text-slate-500 border-b border-slate-100">
                <span>Month</span><span>kWh</span><span>kVArh</span><span>Days</span><span>Source</span>
              </div>
              <div className="divide-y divide-slate-50">
                {monthly.data.map(r => (
                  <div key={r.mese_anno} className="grid grid-cols-5 px-5 py-2 text-xs hover:bg-slate-50">
                    <span className="text-slate-700">{r.mese_anno}</span>
                    <span className="text-slate-800 font-medium">{r.monthly_kwh?.toFixed(1) ?? '—'}</span>
                    <span className="text-slate-500">{r.monthly_kvarh?.toFixed(1) ?? '—'}</span>
                    <span className="text-slate-400">{r.days}</span>
                    <StatusBadge value={r.source} />
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-5 px-5 py-2.5 bg-slate-50 text-xs font-semibold text-slate-700 border-t border-slate-100">
                <span>Total {year}</span>
                <span>{monthly.data.reduce((s, r) => s + (r.monthly_kwh ?? 0), 0).toFixed(1)} kWh</span>
                <span>{monthly.data.reduce((s, r) => s + (r.monthly_kvarh ?? 0), 0).toFixed(1)} kVArh</span>
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
    <button onClick={onClick}
      className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-blue-600 border border-slate-200 hover:border-blue-300 rounded-lg px-3 py-1.5 transition-colors">
      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
      </svg>
      Export CSV
    </button>
  )
}

function ChartSkeleton() { return <div className="h-56 bg-slate-50 rounded-lg animate-pulse" /> }
function LoadingSkeleton() { return <div className="h-32 bg-slate-100 rounded-xl animate-pulse" /> }
function EmptyState({ text }: { text: string }) { return <p className="px-5 py-8 text-sm text-slate-400 text-center">{text}</p> }
function ErrorMsg({ text }: { text: string }) { return <p className="text-sm text-slate-400 text-center py-6">{text}</p> }
