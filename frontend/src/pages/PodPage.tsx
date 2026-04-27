import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { fetchPeriods, fetchMonthlyTotals, fetchDailyTotals } from '../api/client'

function periodToTime(p: number) {
  const totalMin = (p - 1) * 15
  const h = String(Math.floor(totalMin / 60)).padStart(2, '0')
  const m = String(totalMin % 60).padStart(2, '0')
  return `${h}:${m}`
}

function today() {
  return new Date().toISOString().slice(0, 10)
}

function currentMeseAnno() {
  const now = new Date()
  return `${String(now.getMonth() + 1).padStart(2, '0')}/${now.getFullYear()}`
}

type Tab = 'curve' | 'daily' | 'monthly'

export default function PodPage() {
  const { accountId, pod } = useParams<{ accountId: string; pod: string }>()
  const account = accountId!

  const [tab, setTab] = useState<Tab>('curve')
  const [date, setDate] = useState(today)
  const [meseAnno, setMeseAnno] = useState(currentMeseAnno)
  const [year, setYear] = useState(String(new Date().getFullYear()))

  // 96-period curve for selected date
  const periods = useQuery({
    queryKey: ['periods', account, pod, date],
    queryFn: () => fetchPeriods(account, pod!, date),
    enabled: tab === 'curve' && !!date,
  })

  // Daily totals for selected month
  const daily = useQuery({
    queryKey: ['daily', account, pod, meseAnno],
    queryFn: () => fetchDailyTotals(account, pod!, meseAnno),
    enabled: tab === 'daily' && !!meseAnno,
  })

  // Monthly totals for selected year
  const monthly = useQuery({
    queryKey: ['monthly', account, pod, year],
    queryFn: () => fetchMonthlyTotals(account, pod!, year),
    enabled: tab === 'monthly' && !!year,
  })

  const handleMonthChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const [yyyy, mm] = e.target.value.split('-')
    setMeseAnno(`${mm}/${yyyy}`)
  }

  const toInputMonth = (m: string) => `${m.slice(3)}-${m.slice(0, 2)}`

  const tabs: { id: Tab; label: string }[] = [
    { id: 'curve', label: '96-Period Curve' },
    { id: 'daily', label: 'Daily Totals' },
    { id: 'monthly', label: 'Monthly Totals' },
  ]

  return (
    <div className="space-y-5">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <Link to="/" className="text-blue-600 hover:underline">Accounts</Link>
        <span className="text-gray-400">/</span>
        <Link to={`/account/${account}`} className="text-blue-600 hover:underline">{account}</Link>
        <span className="text-gray-400">/</span>
        <span className="font-mono text-gray-700 text-xs">{pod}</span>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t.id
                ? 'border-blue-500 text-blue-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── 96-Period Curve ── */}
      {tab === 'curve' && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <label className="text-sm font-medium text-gray-700">Date:</label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
          </div>

          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-700">
                Quarter-hourly active energy — {date}
              </h2>
              {periods.data && (
                <span className="text-xs text-gray-400">
                  {periods.data.filter((r) => r.ea_kwh != null).length} / 96 periods
                </span>
              )}
            </div>

            {periods.isLoading && <p className="text-gray-400 text-sm">Loading…</p>}
            {periods.error && <p className="text-red-500 text-sm">No data for {date}</p>}

            {periods.data && (
              <ResponsiveContainer width="100%" height={300}>
                <LineChart
                  data={periods.data.map((r) => ({
                    time: periodToTime(r.periodo),
                    kWh: r.ea_kwh != null ? Number(r.ea_kwh) : null,
                    kVArh: r.er_kvarh != null ? Number(r.er_kvarh) : null,
                  }))}
                  margin={{ top: 4, right: 16, left: 0, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    dataKey="time"
                    tick={{ fontSize: 10 }}
                    interval={7}
                    label={{ value: 'Time (15-min periods)', position: 'insideBottom', offset: -2, fontSize: 11 }}
                  />
                  <YAxis tick={{ fontSize: 11 }} unit=" kWh" width={70} />
                  <Tooltip
                    formatter={(v: number, name: string) => [`${v?.toFixed(3)} ${name === 'kWh' ? 'kWh' : 'kVArh'}`, name]}
                  />
                  <ReferenceLine y={0} stroke="#e5e7eb" />
                  <Line
                    type="monotone"
                    dataKey="kWh"
                    stroke="#3b82f6"
                    dot={false}
                    strokeWidth={1.5}
                    connectNulls={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Period table */}
          {periods.data && (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-4 py-2 border-b border-gray-100 text-xs font-semibold text-gray-600 grid grid-cols-4">
                <span>Period</span><span>Time</span><span>kWh</span><span>kVArh</span>
              </div>
              <div className="max-h-64 overflow-y-auto">
                {periods.data.map((r) => (
                  <div
                    key={r.periodo}
                    className="px-4 py-1.5 text-xs grid grid-cols-4 border-b border-gray-50 hover:bg-gray-50"
                  >
                    <span className="text-gray-500">{r.periodo}</span>
                    <span className="text-gray-600">{periodToTime(r.periodo)}</span>
                    <span className={r.ea_kwh == null ? 'text-gray-300' : 'text-gray-800'}>
                      {r.ea_kwh != null ? Number(r.ea_kwh).toFixed(3) : '—'}
                    </span>
                    <span className={r.er_kvarh == null ? 'text-gray-300' : 'text-gray-600'}>
                      {r.er_kvarh != null ? Number(r.er_kvarh).toFixed(3) : '—'}
                    </span>
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
          <div className="flex items-center gap-3">
            <label className="text-sm font-medium text-gray-700">Month:</label>
            <input
              type="month"
              value={toInputMonth(meseAnno)}
              onChange={handleMonthChange}
              className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
            />
          </div>

          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">
              Daily active energy — {meseAnno}
            </h2>
            {daily.isLoading && <p className="text-gray-400 text-sm">Loading…</p>}
            {daily.error && <p className="text-red-500 text-sm">No data for {meseAnno}</p>}
            {daily.data && (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={daily.data} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="data_misura" tick={{ fontSize: 10 }} interval={1} />
                  <YAxis tick={{ fontSize: 11 }} unit=" kWh" width={72} />
                  <Tooltip formatter={(v: number) => [`${v?.toFixed(3)} kWh`, 'Daily total']} />
                  <Bar dataKey="daily_kwh" fill="#3b82f6" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {daily.data && (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-4 py-2 border-b border-gray-100 text-xs font-semibold text-gray-600 grid grid-cols-4">
                <span>Date</span><span>kWh</span><span>kVArh</span><span>Source / Periods</span>
              </div>
              {daily.data.map((r) => (
                <div key={r.data_misura} className="px-4 py-2 text-xs grid grid-cols-4 border-b border-gray-50 hover:bg-gray-50">
                  <span className="text-gray-700">{r.data_misura}</span>
                  <span className="text-gray-800 font-medium">{r.daily_kwh?.toFixed(3) ?? '—'}</span>
                  <span className="text-gray-500">{r.daily_kvarh?.toFixed(3) ?? '—'}</span>
                  <span className="text-gray-400">{r.source} · {r.periods} periods</span>
                </div>
              ))}
              <div className="px-4 py-2 text-xs font-semibold text-gray-700 bg-gray-50 grid grid-cols-4">
                <span>Total</span>
                <span>{daily.data.reduce((s, r) => s + (r.daily_kwh ?? 0), 0).toFixed(3)} kWh</span>
                <span>{daily.data.reduce((s, r) => s + (r.daily_kvarh ?? 0), 0).toFixed(3)} kVArh</span>
                <span>{daily.data.length} days</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Monthly Totals ── */}
      {tab === 'monthly' && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <label className="text-sm font-medium text-gray-700">Year:</label>
            <select
              value={year}
              onChange={(e) => setYear(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
            >
              {[2020, 2021, 2022, 2023, 2024, 2025, 2026].map((y) => (
                <option key={y} value={String(y)}>{y}</option>
              ))}
            </select>
          </div>

          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">
              Monthly active energy — {year}
            </h2>
            {monthly.isLoading && <p className="text-gray-400 text-sm">Loading…</p>}
            {monthly.error && <p className="text-red-500 text-sm">No data for {year}</p>}
            {monthly.data && (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={monthly.data} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="mese_anno" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} unit=" kWh" width={80} />
                  <Tooltip formatter={(v: number) => [`${v?.toFixed(1)} kWh`, 'Monthly total']} />
                  <Bar dataKey="monthly_kwh" fill="#3b82f6" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {monthly.data && (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-4 py-2 border-b border-gray-100 text-xs font-semibold text-gray-600 grid grid-cols-4">
                <span>Month</span><span>kWh</span><span>kVArh</span><span>Days / Source</span>
              </div>
              {monthly.data.map((r) => (
                <div key={r.mese_anno} className="px-4 py-2 text-xs grid grid-cols-4 border-b border-gray-50 hover:bg-gray-50">
                  <span className="text-gray-700">{r.mese_anno}</span>
                  <span className="text-gray-800 font-medium">{r.monthly_kwh?.toFixed(1) ?? '—'}</span>
                  <span className="text-gray-500">{r.monthly_kvarh?.toFixed(1) ?? '—'}</span>
                  <span className="text-gray-400">{r.days} days · {r.source}</span>
                </div>
              ))}
              <div className="px-4 py-2 text-xs font-semibold text-gray-700 bg-gray-50 grid grid-cols-4">
                <span>Total {year}</span>
                <span>{monthly.data.reduce((s, r) => s + (r.monthly_kwh ?? 0), 0).toFixed(1)} kWh</span>
                <span>{monthly.data.reduce((s, r) => s + (r.monthly_kvarh ?? 0), 0).toFixed(1)} kVArh</span>
                <span>{monthly.data.length} months</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
