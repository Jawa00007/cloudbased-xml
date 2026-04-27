import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
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
    <div className="space-y-5">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <Link to="/" className="text-slate-400 hover:text-slate-600">Accounts</Link>
        <span className="text-slate-300">/</span>
        <span className="font-medium text-slate-900">{account}</span>
      </div>

      {/* Month selector + chart */}
      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Monthly totals by POD</h2>
            <p className="text-xs text-slate-400 mt-0.5">{meseAnno}</p>
          </div>
          <input
            type="month"
            value={toInputMonth(meseAnno)}
            onChange={handleMonth}
            className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300"
          />
        </div>

        {summary.isLoading && <div className="h-56 bg-slate-50 rounded-lg animate-pulse" />}
        {summary.data && summary.data.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={summary.data} margin={{ top: 4, right: 8, left: 0, bottom: 48 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="pod" tick={{ fontSize: 9, fill: '#94a3b8' }} angle={-40} textAnchor="end" interval={0} />
              <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} unit=" kWh" width={72} />
              <Tooltip
                contentStyle={{ border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12 }}
                formatter={(v: number) => [`${v?.toFixed(1)} kWh`, 'Active energy']}
              />
              <Bar dataKey="monthly_kwh" fill="#3b82f6" radius={[4, 4, 0, 0]} maxBarSize={40} />
            </BarChart>
          </ResponsiveContainer>
        ) : summary.data?.length === 0 ? (
          <EmptyState text={`No data for ${meseAnno}`} />
        ) : null}
      </div>

      {/* PODs / Metadata tabs */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100">
          <div className="flex gap-4">
            {(['pods', 'metadata'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`text-sm font-medium pb-0.5 border-b-2 transition-colors ${
                  tab === t ? 'border-blue-500 text-blue-700' : 'border-transparent text-slate-500 hover:text-slate-700'
                }`}
              >
                {t === 'pods' ? `PODs (${pods.data?.length ?? '…'})` : 'F2G Metadata'}
              </button>
            ))}
          </div>
        </div>

        {tab === 'pods' && (
          <>
            {pods.isLoading && <LoadingRows />}
            <div className="divide-y divide-slate-50">
              {pods.data?.map((pod) => {
                const row = summary.data?.find((r) => r.pod === pod)
                return (
                  <Link
                    key={pod}
                    to={`/account/${account}/pod/${pod}`}
                    className="flex items-center justify-between px-5 py-3 hover:bg-slate-50 transition-colors group"
                  >
                    <span className="text-sm font-mono text-slate-700">{pod}</span>
                    <div className="flex items-center gap-4 text-xs text-slate-400">
                      {row && (
                        <>
                          <span className="text-slate-600 font-medium">{row.monthly_kwh?.toFixed(1)} kWh</span>
                          <StatusBadge value={row.source} />
                          <span>{row.days}d</span>
                        </>
                      )}
                      <svg className="w-4 h-4 text-slate-300 group-hover:text-blue-400 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
                    </div>
                  </Link>
                )
              })}
            </div>
          </>
        )}

        {tab === 'metadata' && (
          <>
            {metadata.isLoading && <LoadingRows />}
            {metadata.data?.length === 0 && <EmptyState text="No F2G metadata ingested yet" />}
            {metadata.data && metadata.data.length > 0 && (
              <>
                <div className="grid grid-cols-5 px-5 py-2 bg-slate-50 text-xs font-medium text-slate-500 border-b border-slate-100">
                  <span>POD</span><span>Contract DP</span><span>Voltage</span><span>Treatment</span><span>Valid from</span>
                </div>
                {metadata.data.map((m, i) => (
                  <div key={i} className="grid grid-cols-5 px-5 py-2.5 text-xs border-b border-slate-50 hover:bg-slate-50">
                    <span className="font-mono text-slate-700">{m.pod}</span>
                    <span className="text-slate-600">{m.codice_dp ?? '—'}</span>
                    <span className="text-slate-500">{m.tensione ? `${m.tensione}V` : '—'}</span>
                    <span className="text-slate-500">{m.trattamento ?? '—'}</span>
                    <span className="text-slate-400">{m.valid_from ?? '—'}</span>
                  </div>
                ))}
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return <p className="px-5 py-8 text-sm text-slate-400 text-center">{text}</p>
}

function LoadingRows() {
  return (
    <div className="px-5 py-4 space-y-3">
      {[1,2,3].map(i => <div key={i} className="h-4 bg-slate-100 rounded animate-pulse" />)}
    </div>
  )
}
