import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { fetchPods, fetchMonthlySummary } from '../api/client'

function currentMeseAnno() {
  const now = new Date()
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  return `${mm}/${now.getFullYear()}`
}

export default function AccountPage() {
  const { accountId } = useParams<{ accountId: string }>()
  const account = accountId!
  const [meseAnno, setMeseAnno] = useState(currentMeseAnno)

  const pods = useQuery({
    queryKey: ['pods', account],
    queryFn: () => fetchPods(account),
  })

  const summary = useQuery({
    queryKey: ['summary', account, meseAnno],
    queryFn: () => fetchMonthlySummary(account, meseAnno),
    enabled: !!meseAnno,
  })

  // convert MM/YYYY to input[type=month] value YYYY-MM
  const toInputMonth = (m: string) => `${m.slice(3)}-${m.slice(0, 2)}`
  const fromInputMonth = (v: string) => `${v.slice(5)}-${v.slice(0, 4)}`  // MM/YYYY

  const handleMonthChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const [yyyy, mm] = e.target.value.split('-')
    setMeseAnno(`${mm}/${yyyy}`)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link to="/" className="text-sm text-blue-600 hover:underline">Accounts</Link>
        <span className="text-gray-400">/</span>
        <h1 className="text-xl font-semibold text-gray-900">{account}</h1>
      </div>

      {/* Month selector */}
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-gray-700">Month:</label>
        <input
          type="month"
          value={toInputMonth(meseAnno)}
          onChange={handleMonthChange}
          className="border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
        />
      </div>

      {/* Monthly summary chart */}
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">
          Monthly totals by POD — {meseAnno}
        </h2>
        {summary.isLoading && <p className="text-gray-400 text-sm">Loading…</p>}
        {summary.error && <p className="text-red-500 text-sm">No data for {meseAnno}</p>}
        {summary.data && summary.data.length > 0 && (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={summary.data} margin={{ top: 4, right: 16, left: 0, bottom: 40 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="pod"
                tick={{ fontSize: 10 }}
                angle={-35}
                textAnchor="end"
                interval={0}
              />
              <YAxis tick={{ fontSize: 11 }} unit=" kWh" width={80} />
              <Tooltip formatter={(v: number) => [`${v?.toFixed(1)} kWh`, 'Active energy']} />
              <Bar dataKey="monthly_kwh" fill="#3b82f6" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
        {summary.data?.length === 0 && (
          <p className="text-gray-400 text-sm">No measurements for {meseAnno}</p>
        )}
      </div>

      {/* POD list */}
      <div className="bg-white border border-gray-200 rounded-lg">
        <div className="px-4 py-3 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-700">
            PODs {pods.data ? `(${pods.data.length})` : ''}
          </h2>
        </div>
        {pods.isLoading && <p className="p-4 text-gray-400 text-sm">Loading…</p>}
        {pods.data && (
          <ul className="divide-y divide-gray-50">
            {pods.data.map((pod) => {
              const row = summary.data?.find((r) => r.pod === pod)
              return (
                <li key={pod}>
                  <Link
                    to={`/account/${account}/pod/${pod}`}
                    className="flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
                  >
                    <span className="text-sm font-mono text-gray-800">{pod}</span>
                    <div className="flex items-center gap-4 text-xs text-gray-500">
                      {row && (
                        <>
                          <span>{row.monthly_kwh?.toFixed(1)} kWh</span>
                          <span>{row.days} days</span>
                        </>
                      )}
                      <span className="text-blue-500">View →</span>
                    </div>
                  </Link>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
