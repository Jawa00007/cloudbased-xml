import { useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchAccounts, fetchLossConfig, deleteLossRule,
  fetchAnagrafica, uploadAnagrafica,
} from '../api/client'
import type { LossRule } from '../api/types'

const COND_LABELS: Record<string, string> = {
  missing_pod: 'Missing POD',
  tensione_range: 'Voltage range',
  tariffa_prefix: 'Tariff prefix',
  default: 'Default (catch-all)',
}

function LossRuleRow({ rule, onDelete }: { rule: LossRule; onDelete: () => void }) {
  return (
    <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors group">
      <td className="px-5 py-3 text-xs font-medium text-slate-800">{rule.name}</td>
      <td className="px-4 py-3 text-xs text-slate-600">{COND_LABELS[rule.condition_type] ?? rule.condition_type}</td>
      <td className="px-4 py-3 text-xs text-slate-500 font-mono">{rule.condition_value ?? '—'}</td>
      <td className="px-4 py-3 text-xs tabular-nums text-right font-semibold text-slate-800">
        {(rule.loss_pct * 100).toFixed(1)}%
      </td>
      <td className="px-4 py-3 text-xs tabular-nums text-right text-slate-500">{rule.priority}</td>
      <td className="px-4 py-3 text-xs text-slate-400 truncate max-w-[180px]">{rule.description ?? '—'}</td>
      <td className="px-4 py-3 text-right">
        <button
          onClick={onDelete}
          className="opacity-0 group-hover:opacity-100 text-xs text-red-400 hover:text-red-600 transition-all"
        >
          Delete
        </button>
      </td>
    </tr>
  )
}

export default function AdminPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<'loss' | 'anagrafica'>('loss')
  const [accountId, setAccountId] = useState('')
  const [meseAnno, setMeseAnno] = useState('')
  const [uploadResult, setUploadResult] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const { data: accounts = [] } = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })

  const { data: lossRules = [], isLoading: loadingLoss } = useQuery({
    queryKey: ['loss-config', accountId || null],
    queryFn: () => fetchLossConfig(accountId || undefined),
  })

  const deleteRule = useMutation({
    mutationFn: (id: number) => deleteLossRule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['loss-config'] }),
  })

  const { data: anagrafica = [], isLoading: loadingAna } = useQuery({
    queryKey: ['anagrafica', accountId, meseAnno],
    queryFn: () => fetchAnagrafica(accountId, meseAnno),
    enabled: !!accountId && !!meseAnno,
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadAnagrafica(accountId, file),
    onSuccess: (res) => {
      setUploadResult(`${res.records_upserted} records uploaded for ${res.mese_anno}`)
      setUploadError(null)
      qc.invalidateQueries({ queryKey: ['anagrafica', accountId] })
      if (fileRef.current) fileRef.current.value = ''
    },
    onError: (e: Error) => { setUploadError(e.message); setUploadResult(null) },
  })

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file && accountId) uploadMutation.mutate(file)
  }

  function monthOptions() {
    const opts: string[] = []
    const now = new Date()
    for (let i = 0; i < 24; i++) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
      const mm = String(d.getMonth() + 1).padStart(2, '0')
      opts.push(`${mm}/${d.getFullYear()}`)
    }
    return opts
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Administration</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Manage loss config rules, upload ANAGRAFICA files, and configure dispatching weights.
        </p>
      </div>

      {/* Account selector */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Account</label>
            <select
              value={accountId}
              onChange={e => setAccountId(e.target.value)}
              className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[180px]"
            >
              <option value="">All accounts (global rules)</option>
              {accounts.map(a => (
                <option key={a.account_id} value={a.account_id}>
                  {a.display_name ?? a.account_id}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-slate-100 rounded-xl w-fit">
        {(['loss', 'anagrafica'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              tab === t ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {t === 'loss' ? 'Loss Config' : 'ANAGRAFICA'}
          </button>
        ))}
      </div>

      {/* Loss Config tab */}
      {tab === 'loss' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-slate-700">Grid Loss Rules</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Rules evaluated in priority order. First match wins.
              </p>
            </div>
          </div>

          {loadingLoss ? (
            <div className="px-5 py-8 text-center text-sm text-slate-400">Loading…</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-400 uppercase tracking-wide text-[10px] border-b border-slate-100">
                    <th className="text-left px-5 py-3 font-medium">Name</th>
                    <th className="text-left px-4 py-3 font-medium">Condition</th>
                    <th className="text-left px-4 py-3 font-medium">Value</th>
                    <th className="text-right px-4 py-3 font-medium">Loss %</th>
                    <th className="text-right px-4 py-3 font-medium">Priority</th>
                    <th className="text-left px-4 py-3 font-medium">Description</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {lossRules.map(rule => (
                    <LossRuleRow
                      key={rule.id}
                      rule={rule}
                      onDelete={() => deleteRule.mutate(rule.id)}
                    />
                  ))}
                  {lossRules.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-5 py-8 text-center text-slate-400 text-sm">
                        No rules configured. Default rules are used (missing POD → 10%, MT tariff → 3.8%, other → 1.8%).
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* Legend */}
          <div className="px-5 py-4 border-t border-slate-100 bg-slate-50">
            <div className="flex flex-wrap gap-4 text-xs text-slate-500">
              <span><span className="font-medium text-slate-700">missing_pod</span> — POD not in pod_metadata</span>
              <span><span className="font-medium text-slate-700">tensione_range</span> — voltage IN comma-list (e.g. "220,380")</span>
              <span><span className="font-medium text-slate-700">tariffa_prefix</span> — codice_tariffa starts with value (e.g. "MT")</span>
              <span><span className="font-medium text-slate-700">default</span> — catch-all fallback</span>
            </div>
          </div>
        </div>
      )}

      {/* ANAGRAFICA tab */}
      {tab === 'anagrafica' && (
        <div className="space-y-4">
          {/* Upload */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
            <h2 className="text-sm font-semibold text-slate-700 mb-3">Upload ANAGRAFICA File</h2>
            <p className="text-xs text-slate-500 mb-4">
              Accepts ZIP or CSV files. Only rows where the filter column = "O" are imported.
              Filename format: <span className="font-mono">ANAGRAFICA_YYYYMM_PIvautente_PuntoDisp.zip</span>
            </p>

            {!accountId ? (
              <p className="text-sm text-amber-600 bg-amber-50 px-4 py-2.5 rounded-lg">
                Select an account above before uploading.
              </p>
            ) : (
              <label
                className={`flex flex-col items-center gap-2 px-6 py-8 border-2 border-dashed rounded-xl cursor-pointer transition-colors ${
                  uploadMutation.isPending
                    ? 'border-blue-200 bg-blue-50'
                    : 'border-slate-200 hover:border-blue-300 hover:bg-blue-50'
                }`}
              >
                <svg className="w-8 h-8 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                <span className="text-sm text-slate-500">
                  {uploadMutation.isPending ? 'Uploading…' : 'Click to upload ANAGRAFICA ZIP or CSV'}
                </span>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".zip,.csv"
                  className="hidden"
                  onChange={handleFileChange}
                  disabled={uploadMutation.isPending}
                />
              </label>
            )}

            {uploadResult && (
              <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
                {uploadResult}
              </div>
            )}
            {uploadError && (
              <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                {uploadError}
              </div>
            )}
          </div>

          {/* Browse */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-end gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Month</label>
                <select
                  value={meseAnno}
                  onChange={e => setMeseAnno(e.target.value)}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[130px]"
                >
                  <option value="">Select…</option>
                  {monthOptions().map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <p className="text-xs text-slate-400 pb-2">
                {accountId && meseAnno ? `${anagrafica.length} PODs` : 'Select account + month to browse'}
              </p>
            </div>

            {accountId && meseAnno && (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-400 uppercase tracking-wide text-[10px] border-b border-slate-100">
                      <th className="text-left px-5 py-3 font-medium">POD</th>
                      <th className="text-left px-4 py-3 font-medium">Dispatching Point</th>
                      <th className="text-right px-4 py-3 font-medium">Tensione</th>
                      <th className="text-left px-4 py-3 font-medium">Tariffa</th>
                      <th className="text-right px-4 py-3 font-medium">CONSUMO_TOT (kWh)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {loadingAna ? (
                      <tr>
                        <td colSpan={5} className="px-5 py-8 text-center text-slate-400">Loading…</td>
                      </tr>
                    ) : anagrafica.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="px-5 py-8 text-center text-slate-400">
                          No records. Upload an ANAGRAFICA file for this account and month.
                        </td>
                      </tr>
                    ) : (
                      anagrafica.map((r, i) => (
                        <tr key={i} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                          <td className="px-5 py-2.5 font-mono text-slate-800">{r.pod}</td>
                          <td className="px-4 py-2.5 text-slate-600">{r.punto_dispacciamento ?? '—'}</td>
                          <td className="px-4 py-2.5 tabular-nums text-right text-slate-600">{r.tensione ?? '—'}</td>
                          <td className="px-4 py-2.5 text-slate-600">{r.codice_tariffa ?? '—'}</td>
                          <td className="px-4 py-2.5 tabular-nums text-right font-medium text-slate-800">
                            {r.consumo_tot != null ? r.consumo_tot.toLocaleString() : '—'}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
