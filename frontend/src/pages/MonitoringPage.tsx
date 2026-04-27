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
    enabled: !!account && tab === 'missing',
  })

  const corrections = useQuery({
    queryKey: ['corrections', account, meseAnno],
    queryFn: () => fetchCorrections(account, meseAnno),
    enabled: !!account && tab === 'corrections',
  })

  const errors = useQuery({
    queryKey: ['files-errors', account],
    queryFn: () => fetchFiles(account, 'error', 500),
    enabled: !!account && tab === 'errors',
  })

  const toIM   = (m: string) => `${m.slice(3)}-${m.slice(0,2)}`
  const fromIM = (v: string) => { const [y,m]=v.split('-'); return `${m}/${y}` }

  const TABS: { id: Tab; label: string; count?: number }[] = [
    { id: 'missing',     label: 'Missing Readings',  count: missing.data?.length },
    { id: 'corrections', label: 'Corrections',        count: corrections.data?.reduce((s,r) => s+r.count, 0) },
    { id: 'errors',      label: 'Error Files',        count: errors.data?.length },
  ]

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Monitoring</h1>
        <p className="text-sm text-slate-500 mt-0.5">Data quality, missing readings and corrections</p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select value={account} onChange={e => setAccount(e.target.value)}
          className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300">
          <option value="">— Select account —</option>
          {accounts.data?.map(a => <option key={a.account_id} value={a.account_id}>{a.account_id}</option>)}
        </select>
        <input type="month" value={toIM(meseAnno)} onChange={e => setMeseAnno(fromIM(e.target.value))}
          className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300" />
      </div>

      {!account && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-8 text-center">
          <p className="text-sm text-slate-400">Select an account to view monitoring data</p>
        </div>
      )}

      {account && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-3">
            <SummaryCard
              label="Missing readings"
              value={missing.data?.length ?? '…'}
              sub={`days with < 96 periods · ${meseAnno}`}
              color={missing.data && missing.data.length > 0 ? 'red' : 'green'}
            />
            <SummaryCard
              label="Corrections"
              value={corrections.data?.reduce((s,r) => s+r.count, 0) ?? '…'}
              sub={`correction files · ${meseAnno}`}
              color="amber"
            />
            <SummaryCard
              label="Error files"
              value={errors.data?.length ?? '…'}
              sub="files with ingestion errors"
              color={errors.data && errors.data.length > 0 ? 'red' : 'green'}
            />
          </div>

          {/* Tabs */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="flex border-b border-slate-100">
              {TABS.map(t => (
                <button key={t.id} onClick={() => setTab(t.id)}
                  className={`flex items-center gap-2 px-5 py-3 text-sm font-medium border-b-2 -mb-px transition-colors ${
                    tab === t.id ? 'border-blue-500 text-blue-700' : 'border-transparent text-slate-500 hover:text-slate-700'
                  }`}
                >
                  {t.label}
                  {t.count != null && t.count > 0 && (
                    <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
                      t.id === 'missing' || t.id === 'errors' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                    }`}>{t.count}</span>
                  )}
                </button>
              ))}
            </div>

            {/* Missing Readings */}
            {tab === 'missing' && (
              <div>
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-50">
                  <p className="text-xs text-slate-400">Days where fewer than 96 periods were recorded (DST days excluded)</p>
                  {missing.data && missing.data.length > 0 && (
                    <button onClick={() => exportCSV(missing.data!, `missing_${account}_${meseAnno.replace('/','-')}.csv`)}
                      className="text-xs text-slate-500 hover:text-blue-600 flex items-center gap-1">
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                      CSV
                    </button>
                  )}
                </div>
                {missing.isLoading && <Loading />}
                {missing.data?.length === 0 && <EmptyGreen text={`All readings complete for ${meseAnno}`} />}
                {missing.data && missing.data.length > 0 && (
                  <>
                    <div className="grid grid-cols-5 px-5 py-2 bg-slate-50 text-xs font-medium text-slate-500">
                      <span>POD</span><span>Date</span><span>Periods found</span><span>Missing</span><span>Source</span>
                    </div>
                    <div className="divide-y divide-slate-50 max-h-96 overflow-y-auto scrollbar-thin">
                      {missing.data.map((r, i) => (
                        <div key={i} className="grid grid-cols-5 px-5 py-2 text-xs hover:bg-slate-50">
                          <span className="font-mono text-slate-700">{r.pod}</span>
                          <span className="text-slate-600">{r.data_misura}</span>
                          <span className="text-slate-600">{r.periods_found}/96</span>
                          <span className="text-red-600 font-medium">{r.missing} missing</span>
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
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-50">
                  <p className="text-xs text-slate-400">Flusso 2 correction files grouped by POD and flow code</p>
                  {corrections.data && corrections.data.length > 0 && (
                    <button onClick={() => exportCSV(corrections.data!, `corrections_${account}_${meseAnno.replace('/','-')}.csv`)}
                      className="text-xs text-slate-500 hover:text-blue-600 flex items-center gap-1">
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                      CSV
                    </button>
                  )}
                </div>
                {corrections.isLoading && <Loading />}
                {corrections.data?.length === 0 && <EmptyGreen text={`No corrections for ${meseAnno}`} />}
                {corrections.data && corrections.data.length > 0 && (
                  <>
                    <div className="grid grid-cols-4 px-5 py-2 bg-slate-50 text-xs font-medium text-slate-500">
                      <span>POD</span><span>Month</span><span>Flow code</span><span>Count</span>
                    </div>
                    <div className="divide-y divide-slate-50 max-h-96 overflow-y-auto scrollbar-thin">
                      {corrections.data.map((r, i) => (
                        <div key={i} className="grid grid-cols-4 px-5 py-2 text-xs hover:bg-slate-50">
                          <span className="font-mono text-slate-700">{r.pod}</span>
                          <span className="text-slate-600">{r.mese_anno}</span>
                          <span className="text-amber-700 font-medium">{r.cod_flusso}</span>
                          <span className="text-slate-700">{r.count}</span>
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
                <div className="px-5 py-3 border-b border-slate-50">
                  <p className="text-xs text-slate-400">Files that failed during ingestion</p>
                </div>
                {errors.isLoading && <Loading />}
                {errors.data?.length === 0 && <EmptyGreen text="No ingestion errors" />}
                {errors.data && errors.data.length > 0 && (
                  <>
                    <div className="grid grid-cols-4 px-5 py-2 bg-slate-50 text-xs font-medium text-slate-500">
                      <span className="col-span-2">File</span><span>Flow</span><span>Error</span>
                    </div>
                    <div className="divide-y divide-slate-50 max-h-96 overflow-y-auto scrollbar-thin">
                      {errors.data.map(f => (
                        <div key={f.file_id} className="grid grid-cols-4 px-5 py-2 text-xs hover:bg-slate-50">
                          <span className="col-span-2 font-mono text-slate-600 truncate" title={f.file_name}>{f.file_name}</span>
                          <span className="text-slate-500">{f.cod_flusso ?? '—'}</span>
                          <span className="text-red-600 truncate" title={f.error_message ?? ''}>{f.error_message ?? '—'}</span>
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

function SummaryCard({ label, value, sub, color }: { label: string; value: number | string; sub: string; color: 'red'|'green'|'amber' }) {
  const colors = {
    red:   'bg-red-50 border-red-100',
    green: 'bg-emerald-50 border-emerald-100',
    amber: 'bg-amber-50 border-amber-100',
  }
  const text = {
    red:   'text-red-700',
    green: 'text-emerald-700',
    amber: 'text-amber-700',
  }
  return (
    <div className={`rounded-xl border p-4 ${colors[color]}`}>
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${text[color]}`}>{value}</p>
      <p className="text-xs text-slate-400 mt-1">{sub}</p>
    </div>
  )
}

function Loading() { return <div className="px-5 py-8"><div className="h-4 bg-slate-100 rounded animate-pulse" /></div> }
function EmptyGreen({ text }: { text: string }) {
  return (
    <div className="px-5 py-8 text-center">
      <div className="w-8 h-8 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-2">
        <svg className="w-4 h-4 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
      </div>
      <p className="text-sm text-slate-500">{text}</p>
    </div>
  )
}
