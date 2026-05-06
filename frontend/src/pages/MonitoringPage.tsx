import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAccounts, fetchMissingPeriods, fetchCorrections, fetchFiles } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import { exportCSV } from '../utils/export'

function curMM() {
  const d = new Date()
  return `${String(d.getMonth()+1).padStart(2,'0')}/${d.getFullYear()}`
}

type Tab = 'missing' | 'corrections' | 'errors'

export default function MonitoringPage() {
  const [account,  setAccount]  = useState('')
  const [meseAnno, setMeseAnno] = useState(curMM)
  const [tab,      setTab]      = useState<Tab>('missing')

  const accounts = useQuery({ queryKey: ['accounts'], queryFn: fetchAccounts })

  const missing = useQuery({
    queryKey: ['missing', account, meseAnno],
    queryFn: () => fetchMissingPeriods(account, meseAnno),
    enabled: !!account,
  })

  const corrections = useQuery({
    queryKey: ['corrections', account, meseAnno],
    queryFn: () => fetchCorrections(account, meseAnno),
    enabled: !!account,
  })

  const errors = useQuery({
    queryKey: ['files-errors', account],
    queryFn: () => fetchFiles(account, 'error', 500),
    enabled: !!account,
  })

  const toIM   = (m: string) => `${m.slice(3)}-${m.slice(0,2)}`
  const fromIM = (v: string) => { const [y,m]=v.split('-'); return `${m}/${y}` }

  const TABS: { id: Tab; label: string; count?: number; alert?: boolean }[] = [
    { id: 'missing',     label: 'Missing Readings',  count: missing.data?.length,    alert: (missing.data?.length ?? 0) > 0 },
    { id: 'corrections', label: 'Corrections',        count: corrections.data?.reduce((s,r) => s+r.count, 0) },
    { id: 'errors',      label: 'Error Files',        count: errors.data?.length,     alert: (errors.data?.length ?? 0) > 0 },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Monitoring</h1>
        <p className="text-sm text-slate-500 mt-1">Data quality, missing readings and correction tracking</p>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">Filters</p>
        <div className="flex flex-wrap gap-3">
          <select
            value={account}
            onChange={e => setAccount(e.target.value)}
            className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300 min-w-[160px]"
          >
            <option value="">— Select account —</option>
            {accounts.data?.map(a => (
              <option key={a.account_id} value={a.account_id}>{a.account_id}</option>
            ))}
          </select>
          <input
            type="month"
            value={toIM(meseAnno)}
            onChange={e => setMeseAnno(fromIM(e.target.value))}
            className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300"
          />
        </div>
      </div>

      {/* Empty prompt */}
      {!account && (
        <div className="bg-white border border-slate-100 rounded-2xl shadow-sm flex flex-col items-center justify-center py-16">
          <div className="w-12 h-12 bg-slate-50 rounded-full flex items-center justify-center mb-3">
            <svg className="w-6 h-6 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <p className="text-sm text-slate-500 font-medium">Select an account</p>
          <p className="text-xs text-slate-400 mt-1">Choose an account above to view monitoring data</p>
        </div>
      )}

      {account && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-4">
            <StatCard
              icon={
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.7}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              }
              label="Missing readings"
              value={missing.data?.length ?? '…'}
              sub={`days incomplete · ${meseAnno}`}
              variant={(missing.data?.length ?? 0) > 0 ? 'red' : 'green'}
            />
            <StatCard
              icon={
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.7}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
              }
              label="Corrections"
              value={corrections.data?.reduce((s,r) => s+r.count, 0) ?? '…'}
              sub={`Flusso 2 files · ${meseAnno}`}
              variant="amber"
            />
            <StatCard
              icon={
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.7}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              }
              label="Error files"
              value={errors.data?.length ?? '…'}
              sub="ingestion failures"
              variant={(errors.data?.length ?? 0) > 0 ? 'red' : 'green'}
            />
          </div>

          {/* Tab panel */}
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
            {/* Tabs */}
            <div className="flex border-b border-slate-100 px-2 pt-2">
              {TABS.map(t => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 -mb-px transition-all rounded-t-lg ${
                    tab === t.id
                      ? 'border-blue-600 text-blue-700 bg-blue-50/50'
                      : 'border-transparent text-slate-500 hover:text-slate-700'
                  }`}
                >
                  {t.label}
                  {t.count != null && t.count > 0 && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold ${
                      t.alert ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                    }`}>
                      {t.count}
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* Missing Readings */}
            {tab === 'missing' && (
              <div>
                <div className="flex items-center justify-between px-6 py-3 border-b border-slate-50">
                  <p className="text-xs text-slate-400">Days where fewer than 96 periods were recorded (DST days excluded)</p>
                  {missing.data && missing.data.length > 0 && (
                    <button
                      onClick={() => exportCSV(missing.data!, `missing_${account}_${meseAnno.replace('/','-')}.csv`)}
                      className="flex items-center gap-1 text-xs text-slate-400 hover:text-blue-600 transition-colors"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                      CSV
                    </button>
                  )}
                </div>
                {missing.isLoading && <TableSkeleton />}
                {missing.data?.length === 0 && <AllGoodState text={`All readings complete for ${meseAnno}`} />}
                {missing.data && missing.data.length > 0 && (
                  <>
                    <div className="grid grid-cols-5 px-6 py-2.5 bg-slate-50 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                      <span>POD</span><span>Date</span><span>Periods</span><span>Missing</span><span>Source</span>
                    </div>
                    <div className="divide-y divide-slate-50 max-h-96 overflow-y-auto scrollbar-thin">
                      {missing.data.map((r, i) => (
                        <div key={i} className="grid grid-cols-5 px-6 py-2.5 text-xs hover:bg-slate-50/70">
                          <span className="font-mono text-slate-700 text-[11px]">{r.pod}</span>
                          <span className="text-slate-600 tabular-nums">{r.data_misura}</span>
                          <span className="text-slate-600 tabular-nums">{r.periods_found}/96</span>
                          <span className="text-red-600 font-semibold tabular-nums">{r.missing}</span>
                          <StatusBadge value={r.source} />
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* Corrections */}
            {tab === 'corrections' && (
              <div>
                <div className="flex items-center justify-between px-6 py-3 border-b border-slate-50">
                  <p className="text-xs text-slate-400">Flusso 2 correction files grouped by POD and flow code</p>
                  {corrections.data && corrections.data.length > 0 && (
                    <button
                      onClick={() => exportCSV(corrections.data!, `corrections_${account}_${meseAnno.replace('/','-')}.csv`)}
                      className="flex items-center gap-1 text-xs text-slate-400 hover:text-blue-600 transition-colors"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                      CSV
                    </button>
                  )}
                </div>
                {corrections.isLoading && <TableSkeleton />}
                {corrections.data?.length === 0 && <AllGoodState text={`No corrections for ${meseAnno}`} />}
                {corrections.data && corrections.data.length > 0 && (
                  <>
                    <div className="grid grid-cols-4 px-6 py-2.5 bg-slate-50 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                      <span>POD</span><span>Month</span><span>Flow code</span><span>Count</span>
                    </div>
                    <div className="divide-y divide-slate-50 max-h-96 overflow-y-auto scrollbar-thin">
                      {corrections.data.map((r, i) => (
                        <div key={i} className="grid grid-cols-4 px-6 py-2.5 text-xs hover:bg-slate-50/70">
                          <span className="font-mono text-slate-700 text-[11px]">{r.pod}</span>
                          <span className="text-slate-600">{r.mese_anno}</span>
                          <span className="text-amber-700 font-semibold">{r.cod_flusso}</span>
                          <span className="text-slate-700 tabular-nums font-semibold">{r.count}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* Error Files */}
            {tab === 'errors' && (
              <div>
                <div className="px-6 py-3 border-b border-slate-50">
                  <p className="text-xs text-slate-400">Files that failed during ingestion — check error messages for details</p>
                </div>
                {errors.isLoading && <TableSkeleton />}
                {errors.data?.length === 0 && <AllGoodState text="No ingestion errors — all files processed successfully" />}
                {errors.data && errors.data.length > 0 && (
                  <>
                    <div className="grid grid-cols-4 px-6 py-2.5 bg-slate-50 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                      <span className="col-span-2">File</span><span>Flow</span><span>Error</span>
                    </div>
                    <div className="divide-y divide-slate-50 max-h-96 overflow-y-auto scrollbar-thin">
                      {errors.data.map(f => (
                        <div key={f.file_id} className="grid grid-cols-4 px-6 py-2.5 text-xs hover:bg-slate-50/70">
                          <span className="col-span-2 font-mono text-slate-600 text-[11px] truncate" title={f.file_name}>{f.file_name}</span>
                          <span className="text-slate-500">{f.cod_flusso ?? '—'}</span>
                          <span className="text-red-500 truncate text-[11px]" title={f.error_message ?? ''}>{f.error_message ?? '—'}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function StatCard({
  icon, label, value, sub, variant,
}: {
  icon: React.ReactNode
  label: string
  value: number | string
  sub: string
  variant: 'red' | 'green' | 'amber'
}) {
  const styles = {
    red:   { card: 'bg-red-50 border-red-100',     icon: 'bg-red-100 text-red-500',     num: 'text-red-700' },
    green: { card: 'bg-emerald-50 border-emerald-100', icon: 'bg-emerald-100 text-emerald-600', num: 'text-emerald-700' },
    amber: { card: 'bg-amber-50 border-amber-100', icon: 'bg-amber-100 text-amber-600', num: 'text-amber-700' },
  }
  const s = styles[variant]
  return (
    <div className={`rounded-2xl border p-5 ${s.card}`}>
      <div className={`w-9 h-9 rounded-xl flex items-center justify-center mb-4 ${s.icon}`}>
        {icon}
      </div>
      <p className="text-xs text-slate-500 font-medium mb-1">{label}</p>
      <p className={`text-3xl font-bold tabular-nums leading-none ${s.num}`}>{value}</p>
      <p className="text-[11px] text-slate-400 mt-2">{sub}</p>
    </div>
  )
}

function TableSkeleton() {
  return (
    <div className="px-6 py-8 space-y-3">
      {[1,2,3].map(i => (
        <div key={i} className="h-3.5 bg-slate-100 rounded animate-pulse" style={{ width: `${55 + i * 12}%` }} />
      ))}
    </div>
  )
}

function AllGoodState({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="w-10 h-10 bg-emerald-100 rounded-full flex items-center justify-center mb-3">
        <svg className="w-5 h-5 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>
      <p className="text-sm font-medium text-slate-600">{text}</p>
    </div>
  )
}
