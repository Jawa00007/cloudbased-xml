import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { fetchPods, fetchMonthlySummary, fetchPodMetadata } from '../api/client'
import StatusBadge from '../components/StatusBadge'

function currentMeseAnno() {
  const d = new Date()
  return `${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`
}

export default function AccountPage() {
  const { accountId } = useParams<{ accountId: string }>()
  const account = accountId!
  const [meseAnno, setMeseAnno] = useState(currentMeseAnno)
  const [tab, setTab] = useState<'pods' | 'metadata'>('pods')

  const pods     = useQuery({ queryKey: ['pods', account], queryFn: () => fetchPods(account) })
  const metadata = useQuery({ queryKey: ['pod_metadata', account], queryFn: () => fetchPodMetadata(account), enabled: tab === 'metadata' })
  const summary  = useQuery({
    queryKey: ['summary', account, meseAnno],
    queryFn: () => fetchMonthlySummary(account, meseAnno),
    enabled: !!meseAnno,
  })

  const toInputMonth = (m: string) => `${m.slice(3)}-${m.slice(0, 2)}`
  const handleMonth = (e: React.ChangeEvent<HTMLInputElement>) => {
    const [y, m] = e.target.value.split('-')
    setMeseAnno(`${m}/${y}`)
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <Link to="/" className="text-slate-400 hover:text-slate-600 transition-colors">Accounts</Link>
        <svg className="w-3.5 h-3.5 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
        <span className="font-semibold text-slate-800">{account}</span>
      </div>

      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{account}</h1>
          <p className="text-sm text-slate-500 mt-1">
            {pods.data ? `${pods.data.length} PODs` : '…'}
            {summary.data ? ` · ${summary.data.length} active this month` : ''}
          </p>
        </div>
      </div>

      {/* Monthly chart card */}
      <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-50">
          <div>
            <p className="text-sm font-semibold text-slate-900">Energy by POD</p>
            <p className="text-xs text-slate-400 mt-0.5">{meseAnno} · active energy (kWh)</p>
          </div>
          <input
            type="month"
            value={toInputMonth(meseAnno)}
            onChange={handleMonth}
            className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400"
          />
        </div>

        <div className="px-6 py-5">
          {summary.isLoading && <div className="h-56 bg-slate-50 rounded-xl animate-pulse" />}
          {summary.data && summary.data.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={summary.data} margin={{ top: 4, right: 4, left: 0, bottom: 52 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                <XAxis
                  dataKey="pod"
                  tick={{ fontSize: 9, fill: '#94a3b8' }}
                  angle={-40}
                  textAnchor="end"
                  interval={0}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  axisLine={false}
                  tickLine={false}
                  unit=" kWh"
                  width={72}
                />
                <Tooltip
                  contentStyle={{ border: '1px solid #e2e8f0', borderRadius: 10, fontSize: 12, boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                  formatter={(v: number) => [`${v?.toFixed(1)} kWh`, 'Active energy']}
                  cursor={{ fill: '#f8fafc' }}
                />
                <Bar dataKey="monthly_kwh" radius={[4, 4, 0, 0]} maxBarSize={36}>
                  {summary.data.map((_, i) => (
                    <Cell key={i} fill={i % 2 === 0 ? '#3b82f6' : '#60a5fa'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : summary.data?.length === 0 ? (
            <EmptyState text={`No data for ${meseAnno}`} />
          ) : null}
        </div>
      </div>

      {/* PODs / Metadata */}
      <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
        {/* Tab header */}
        <div className="flex items-center gap-1 px-6 py-3 border-b border-slate-100">
          {(['pods', 'metadata'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                tab === t
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
              }`}
            >
              {t === 'pods' ? `PODs${pods.data ? ` (${pods.data.length})` : ''}` : 'F2G Metadata'}
            </button>
          ))}
        </div>

        {/* PODs tab */}
        {tab === 'pods' && (
          <>
            {pods.isLoading && <LoadingRows />}
            {pods.data?.length === 0 && <EmptyState text="No PODs found for this account" />}
            <div className="divide-y divide-slate-50">
              {pods.data?.map((pod) => {
                const row = summary.data?.find((r) => r.pod === pod)
                return (
                  <Link
                    key={pod}
                    to={`/account/${account}/pod/${pod}`}
                    className="flex items-center justify-between px-6 py-3.5 hover:bg-slate-50/70 transition-colors group"
                  >
                    <span className="text-xs font-mono text-slate-600 tracking-wide">{pod}</span>
                    <div className="flex items-center gap-4 text-xs text-slate-400">
                      {row && (
                        <>
                          <span className="font-semibold text-slate-800 tabular-nums">{row.monthly_kwh?.toFixed(1)} kWh</span>
                          <StatusBadge value={row.source} />
                          <span className="text-slate-400">{row.days}d</span>
                        </>
                      )}
                      <svg className="w-4 h-4 text-slate-200 group-hover:text-blue-400 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </div>
                  </Link>
                )
              })}
            </div>
          </>
        )}

        {/* Metadata tab */}
        {tab === 'metadata' && (
          <>
            {metadata.isLoading && <LoadingRows />}
            {metadata.data?.length === 0 && <EmptyState text="No F2G metadata ingested yet" />}
            {metadata.data && metadata.data.length > 0 && (
              <>
                <div className="grid grid-cols-5 px-6 py-2.5 bg-slate-50 text-[10px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-100">
                  <span>POD</span><span>Contract DP</span><span>Voltage</span><span>Treatment</span><span>Valid from</span>
                </div>
                <div className="divide-y divide-slate-50">
                  {metadata.data.map((m, i) => (
                    <div key={i} className="grid grid-cols-5 px-6 py-3 text-xs hover:bg-slate-50/70">
                      <span className="font-mono text-slate-700 text-[11px]">{m.pod}</span>
                      <span className="text-slate-600">{m.codice_dp ?? '—'}</span>
                      <span className="text-slate-500">{m.tensione ? `${m.tensione} V` : '—'}</span>
                      <span className="text-slate-500">{m.trattamento ?? '—'}</span>
                      <span className="text-slate-400">{m.valid_from ?? '—'}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="w-10 h-10 bg-slate-50 rounded-full flex items-center justify-center mb-3">
        <svg className="w-5 h-5 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
        </svg>
      </div>
      <p className="text-sm text-slate-400">{text}</p>
    </div>
  )
}

function LoadingRows() {
  return (
    <div className="px-6 py-5 space-y-3">
      {[1, 2, 3, 4].map(i => (
        <div key={i} className="h-3.5 bg-slate-100 rounded animate-pulse" style={{ width: `${70 + i * 7}%` }} />
      ))}
    </div>
  )
}
