import { useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import {
  fetchAccounts, fetchLossConfig, createLossRule, updateLossRule, deleteLossRule,
  fetchAnagrafica, uploadAnagrafica, deleteAnagrafica,
  fetchDispatchingConfig, setDispatchingWeights, deleteDispatchingConfig,
  fetchUsers, createUser, updateUser, deleteUser, getCurrentUser,
} from '../api/client'
import type { LossRule, User, UserCreate, UserUpdate } from '../api/types'
import { itNum, itKwh } from '../utils/format'

const COND_LABELS: Record<string, string> = {
  missing_pod: 'Missing POD',
  tensione_range: 'Voltage range',
  tariffa_prefix: 'Tariff prefix',
  default: 'Default (catch-all)',
}

const EMPTY_RULE = {
  name: '', condition_type: 'default', condition_value: '',
  loss_pct: 1.8, priority: 10, description: '', account_id: '',
}

// ── Loss Rule Row ──────────────────────────────────────────────────────────────
function LossRuleRow({
  rule, onDelete, onEdit,
}: { rule: LossRule; onDelete: () => void; onEdit: () => void }) {
  return (
    <tr className="border-b border-slate-50 hover:bg-slate-50 transition-colors group">
      <td className="px-5 py-3 text-xs font-medium text-slate-800">{rule.name}</td>
      <td className="px-4 py-3 text-xs text-slate-600">{COND_LABELS[rule.condition_type] ?? rule.condition_type}</td>
      <td className="px-4 py-3 text-xs text-slate-500 font-mono">{rule.condition_value ?? '—'}</td>
      <td className="px-4 py-3 text-xs tabular-nums text-right font-semibold text-slate-800">
        {itNum(rule.loss_pct * 100, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%
      </td>
      <td className="px-4 py-3 text-xs tabular-nums text-right text-slate-500">{rule.priority}</td>
      <td className="px-4 py-3 text-xs text-slate-400 truncate max-w-[180px]">{rule.description ?? '—'}</td>
      <td className="px-4 py-3 text-right">
        <div className="flex items-center justify-end gap-3 opacity-0 group-hover:opacity-100 transition-all">
          <button onClick={onEdit} className="text-xs text-blue-500 hover:text-blue-700">Edit</button>
          <button onClick={onDelete} className="text-xs text-red-400 hover:text-red-600">Delete</button>
        </div>
      </td>
    </tr>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
const EMPTY_USER: UserCreate = { username: '', password: '', is_admin: false, allowed_accounts: [] }

export default function AdminPage() {
  const qc = useQueryClient()
  const currentUser = getCurrentUser()
  const isAdmin = currentUser?.is_admin ?? false
  const [tab, setTab] = useState<'loss' | 'anagrafica' | 'dispatching' | 'users'>('loss')
  const [accountId, setAccountId] = useState(() => sessionStorage.getItem('admin_account') ?? '')
  const [meseAnno, setMeseAnno] = useState(() => sessionStorage.getItem('admin_mese_anno') ?? '')
  const fileRef = useRef<HTMLInputElement>(null)

  // Add/edit rule form
  const [showAddForm, setShowAddForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState({ ...EMPTY_RULE })

  // Dispatching config
  const [dispPoint, setDispPoint] = useState('')
  const [dispInput, setDispInput] = useState('')
  const [dispPointDraft, setDispPointDraft] = useState('')

  // Upload feedback — one entry per file
  type FileStatus = { name: string; state: 'pending' | 'ok' | 'error'; msg: string }
  const [fileStatuses, setFileStatuses] = useState<FileStatus[]>([])
  const [uploading, setUploading] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  // User management state
  const [userForm, setUserForm] = useState<UserCreate>({ ...EMPTY_USER })
  const [editingUserId, setEditingUserId] = useState<number | null>(null)
  const [showUserForm, setShowUserForm] = useState(false)
  const [userFormError, setUserFormError] = useState('')

  // ── Queries ──────────────────────────────────────────────────────────────────
  const { data: accounts = [] } = useQuery({ queryKey: ['accounts'], queryFn: fetchAccounts })

  const { data: users = [], isLoading: loadingUsers } = useQuery({
    queryKey: ['users'],
    queryFn: fetchUsers,
    enabled: tab === 'users' && isAdmin,
  })

  const { data: lossRules = [], isLoading: loadingLoss } = useQuery({
    queryKey: ['loss-config', accountId || null],
    queryFn: () => fetchLossConfig(accountId || undefined),
  })

  const { data: anagrafica = [], isLoading: loadingAna } = useQuery({
    queryKey: ['anagrafica', accountId, meseAnno],
    queryFn: () => fetchAnagrafica(accountId, meseAnno),
    enabled: !!accountId && !!meseAnno,
  })

  // null = global scope; non-empty string = account-specific
  const dispScope = accountId || null

  const { data: dispWeights = [], isLoading: loadingDisp } = useQuery({
    queryKey: ['dispatching-config', dispScope, dispPoint],
    queryFn: () => fetchDispatchingConfig(dispScope, dispPoint || undefined),
    enabled: tab === 'dispatching',
  })

  // Distinct dispatching points from loaded weights
  const dispPoints = [...new Set(dispWeights.map(w => w.punto_dispacciamento))].sort()
  const filteredWeights = dispPoint
    ? dispWeights.filter(w => w.punto_dispacciamento === dispPoint)
    : dispWeights.filter(w => w.punto_dispacciamento === dispPoints[0])
  const chartData = filteredWeights
    .sort((a, b) => a.periodo - b.periodo)
    .map(w => ({ periodo: w.periodo, pct: +(w.pct * 100).toFixed(4) }))

  // ── Mutations ─────────────────────────────────────────────────────────────────
  const deleteRule = useMutation({
    mutationFn: (id: number) => deleteLossRule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['loss-config'] }),
  })

  function closeForm() {
    setShowAddForm(false)
    setEditingId(null)
    setForm({ ...EMPTY_RULE })
  }

  function startEdit(rule: LossRule) {
    setForm({
      name: rule.name,
      condition_type: rule.condition_type,
      condition_value: rule.condition_value ?? '',
      loss_pct: +(rule.loss_pct * 100).toFixed(4),
      priority: rule.priority,
      description: rule.description ?? '',
      account_id: rule.account_id ?? '',
    })
    setEditingId(rule.id)
    setShowAddForm(true)
  }

  const ruleBody = () => ({
    ...form,
    loss_pct: form.loss_pct / 100,
    condition_value: form.condition_value || null,
    account_id: form.account_id || null,
    description: form.description || null,
  } as Omit<LossRule, 'id'>)

  const addRule = useMutation({
    mutationFn: () => createLossRule(ruleBody()),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['loss-config'] }); closeForm() },
  })

  const editRule = useMutation({
    mutationFn: () => updateLossRule(editingId!, ruleBody()),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['loss-config'] }); closeForm() },
  })

  const delAna = useMutation({
    mutationFn: () => deleteAnagrafica(accountId, meseAnno),
    onSuccess: () => {
      setConfirmDelete(false)
      qc.invalidateQueries({ queryKey: ['anagrafica', accountId, meseAnno] })
    },
  })

  function closeUserForm() {
    setShowUserForm(false)
    setEditingUserId(null)
    setUserForm({ ...EMPTY_USER })
    setUserFormError('')
  }

  function startEditUser(u: User) {
    setUserForm({ username: u.username, password: '', is_admin: u.is_admin, allowed_accounts: u.allowed_accounts ?? [] })
    setEditingUserId(u.id)
    setShowUserForm(true)
    setUserFormError('')
  }

  const saveUser = useMutation({
    mutationFn: async () => {
      const accts = userForm.is_admin ? null : (userForm.allowed_accounts?.length ? userForm.allowed_accounts : null)
      if (editingUserId !== null) {
        const upd: UserUpdate = {
          is_admin: userForm.is_admin,
          allowed_accounts: accts,
          is_active: true,
        }
        if (userForm.password) upd.password = userForm.password
        return updateUser(editingUserId, upd)
      }
      return createUser({ ...userForm, allowed_accounts: accts })
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['users'] }); closeUserForm() },
    onError: (e: Error) => setUserFormError(e.message),
  })

  const deactivateUser = useMutation({
    mutationFn: (id: number) => deleteUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  function toggleAccountChip(acct: string) {
    setUserForm(prev => {
      const current = prev.allowed_accounts ?? []
      const next = current.includes(acct) ? current.filter(a => a !== acct) : [...current, acct]
      return { ...prev, allowed_accounts: next }
    })
  }

  async function handleUpload(files: FileList) {
    if (!accountId || files.length === 0) return
    const initial: FileStatus[] = Array.from(files).map(f => ({ name: f.name, state: 'pending', msg: '' }))
    setFileStatuses(initial)
    setUploading(true)
    for (let i = 0; i < files.length; i++) {
      try {
        const res = await uploadAnagrafica(accountId, files[i])
        const forecastNote = res.forecast_job_id
          ? ` — forecast started (job: ${res.forecast_job_id.slice(0, 8)}…)`
          : ''
        setFileStatuses(prev => prev.map((s, j) =>
          j === i ? { ...s, state: 'ok', msg: `${res.records_upserted} records — ${res.mese_anno}${forecastNote}` } : s
        ))
      } catch (e) {
        setFileStatuses(prev => prev.map((s, j) =>
          j === i ? { ...s, state: 'error', msg: (e as Error).message } : s
        ))
      }
    }
    setUploading(false)
    qc.invalidateQueries({ queryKey: ['anagrafica', accountId] })
    if (fileRef.current) fileRef.current.value = ''
  }

  const saveWeights = useMutation({
    mutationFn: (weights: number[]) =>
      setDispatchingWeights(dispScope, { punto_dispacciamento: dispPoint || dispPointDraft, weights }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dispatching-config', dispScope] })
      setDispInput('')
      if (dispPointDraft && !dispPoint) setDispPoint(dispPointDraft)
    },
  })

  const delWeights = useMutation({
    mutationFn: (pd: string) => deleteDispatchingConfig(dispScope, pd),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dispatching-config', dispScope] })
      setDispPoint('')
    },
  })

  // ── Helpers ──────────────────────────────────────────────────────────────────
  function parseWeights(text: string): number[] {
    return text.split(/[\n,\s]+/).filter(Boolean).map(Number)
  }

  function equalWeights() {
    const val = (1 / 96).toFixed(8)
    setDispInput(Array(96).fill(val).join('\n'))
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

  const activeDispPoint = dispPoint || dispPoints[0] || ''

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Administration</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Manage loss config rules, dispatch weights, ANAGRAFICA files and account configuration.
        </p>
      </div>

      {/* Account selector */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Account</label>
            <select
              value={accountId}
              onChange={e => { setAccountId(e.target.value); sessionStorage.setItem('admin_account', e.target.value) }}
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
        {(['loss', 'anagrafica', 'dispatching', ...(isAdmin ? ['users'] : [])] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t as typeof tab)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              tab === t ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {t === 'loss' ? 'Loss Config' : t === 'anagrafica' ? 'ANAGRAFICA' : t === 'dispatching' ? 'Distribution Weights' : 'Users'}
          </button>
        ))}
      </div>

      {/* ── Loss Config tab ── */}
      {tab === 'loss' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-slate-700">Grid Loss Rules</h2>
              <p className="text-xs text-slate-400 mt-0.5">Rules evaluated in priority order. First match wins.</p>
            </div>
            <button
              onClick={() => showAddForm ? closeForm() : setShowAddForm(true)}
              className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              {showAddForm ? 'Cancel' : 'Add Rule'}
            </button>
          </div>

          {/* Inline add-rule form */}
          {showAddForm && (
            <div className="px-5 py-4 bg-blue-50 border-b border-blue-100">
              <p className="text-xs font-semibold text-blue-700 mb-3">
                {editingId ? `Edit Rule — ${form.name || '…'}` : 'New Loss Rule'}
              </p>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] font-medium text-slate-500 uppercase tracking-wide">Name</label>
                  <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                    className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
                    placeholder="e.g. High Voltage" />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] font-medium text-slate-500 uppercase tracking-wide">Condition</label>
                  <select value={form.condition_type} onChange={e => setForm(f => ({ ...f, condition_type: e.target.value }))}
                    className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-400">
                    <option value="missing_pod">Missing POD</option>
                    <option value="tensione_range">Voltage range</option>
                    <option value="tariffa_prefix">Tariff prefix</option>
                    <option value="default">Default</option>
                  </select>
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] font-medium text-slate-500 uppercase tracking-wide">Value</label>
                  <input value={form.condition_value} onChange={e => setForm(f => ({ ...f, condition_value: e.target.value }))}
                    className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
                    placeholder='e.g. "220,380" or "MT"' />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] font-medium text-slate-500 uppercase tracking-wide">Loss %</label>
                  <input type="number" step="0.01" min="0" max="100" value={form.loss_pct}
                    onChange={e => setForm(f => ({ ...f, loss_pct: +e.target.value }))}
                    className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-400" />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] font-medium text-slate-500 uppercase tracking-wide">Priority</label>
                  <input type="number" min="1" value={form.priority}
                    onChange={e => setForm(f => ({ ...f, priority: +e.target.value }))}
                    className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-400" />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] font-medium text-slate-500 uppercase tracking-wide">Account (blank = global)</label>
                  <select value={form.account_id} onChange={e => setForm(f => ({ ...f, account_id: e.target.value }))}
                    className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-400">
                    <option value="">Global (all accounts)</option>
                    {accounts.map(a => <option key={a.account_id} value={a.account_id}>{a.account_id}</option>)}
                  </select>
                </div>
                <div className="flex flex-col gap-1 sm:col-span-2">
                  <label className="text-[10px] font-medium text-slate-500 uppercase tracking-wide">Description</label>
                  <input value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                    className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
                    placeholder="Optional description" />
                </div>
              </div>
              <div className="flex items-center gap-2 mt-3">
                <button
                  onClick={() => editingId ? editRule.mutate() : addRule.mutate()}
                  disabled={!form.name || addRule.isPending || editRule.isPending}
                  className="px-4 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors"
                >
                  {(addRule.isPending || editRule.isPending) ? 'Saving…' : editingId ? 'Update Rule' : 'Save Rule'}
                </button>
                {(addRule.isError || editRule.isError) && (
                  <span className="text-xs text-red-600">
                    {((addRule.error || editRule.error) as Error).message}
                  </span>
                )}
              </div>
            </div>
          )}

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
                      onEdit={() => startEdit(rule)}
                      onDelete={() => deleteRule.mutate(rule.id)}
                    />
                  ))}
                  {lossRules.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-5 py-8 text-center text-slate-400 text-sm">
                        No rules configured. Click "Add Rule" to create one.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

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

      {/* ── ANAGRAFICA tab ── */}
      {tab === 'anagrafica' && (
        <div className="space-y-4">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
            <h2 className="text-sm font-semibold text-slate-700 mb-1">Upload ANAGRAFICA Files</h2>
            <p className="text-xs text-slate-500 mb-4">
              Accepts ZIP or CSV files. Only rows where Trattamento_04 (column F) = "O" are imported.
              You can select multiple files at once.
            </p>

            {!accountId ? (
              <p className="text-sm text-amber-600 bg-amber-50 px-4 py-2.5 rounded-lg">
                Select an account above before uploading.
              </p>
            ) : (
              <label className={`flex flex-col items-center gap-2 px-6 py-8 border-2 border-dashed rounded-xl cursor-pointer transition-colors ${
                uploading ? 'border-blue-200 bg-blue-50' : 'border-slate-200 hover:border-blue-300 hover:bg-blue-50'
              }`}>
                <svg className="w-8 h-8 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                <span className="text-sm text-slate-500">
                  {uploading ? 'Uploading…' : 'Click to select one or more ANAGRAFICA ZIP/CSV files'}
                </span>
                <span className="text-xs text-slate-400">Multiple files supported</span>
                <input ref={fileRef} type="file" accept=".zip,.csv" multiple className="hidden"
                  onChange={e => { if (e.target.files) handleUpload(e.target.files) }}
                  disabled={uploading} />
              </label>
            )}

            {fileStatuses.length > 0 && (
              <div className="mt-3 space-y-1.5">
                {fileStatuses.map((s, i) => (
                  <div key={i} className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs ${
                    s.state === 'ok' ? 'bg-green-50 text-green-700 border border-green-200'
                    : s.state === 'error' ? 'bg-red-50 text-red-700 border border-red-200'
                    : 'bg-slate-50 text-slate-500 border border-slate-200'
                  }`}>
                    <span className="font-medium shrink-0">
                      {s.state === 'ok' ? '✓' : s.state === 'error' ? '✗' : '…'}
                    </span>
                    <span className="font-mono truncate">{s.name}</span>
                    {s.msg && <span className="ml-auto shrink-0">{s.msg}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Month</label>
                <select value={meseAnno} onChange={e => { setMeseAnno(e.target.value); sessionStorage.setItem('admin_mese_anno', e.target.value); setConfirmDelete(false) }}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[130px]">
                  <option value="">Select…</option>
                  {monthOptions().map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              {accountId && meseAnno && (
                <p className="text-xs text-slate-400 pb-2 flex-1">{anagrafica.length} PODs</p>
              )}
              {accountId && meseAnno && anagrafica.length > 0 && (
                <div className="pb-2 flex items-center gap-2">
                  {confirmDelete ? (
                    <>
                      <span className="text-xs text-red-600">Delete all {anagrafica.length} records for {meseAnno}?</span>
                      <button
                        onClick={() => delAna.mutate()}
                        disabled={delAna.isPending}
                        className="text-xs px-3 py-1.5 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-40 transition-colors"
                      >
                        {delAna.isPending ? 'Deleting…' : 'Confirm Delete'}
                      </button>
                      <button onClick={() => setConfirmDelete(false)}
                        className="text-xs px-3 py-1.5 border border-slate-200 rounded-lg text-slate-500 hover:bg-slate-50">
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => setConfirmDelete(true)}
                      className="text-xs px-3 py-1.5 border border-red-200 text-red-400 rounded-lg hover:bg-red-50 hover:text-red-600 transition-colors"
                    >
                      Delete month
                    </button>
                  )}
                </div>
              )}
              {!accountId || !meseAnno ? (
                <p className="text-xs text-slate-400 pb-2">Select account + month to browse</p>
              ) : null}
            </div>

            {accountId && meseAnno && (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-400 uppercase tracking-wide text-[10px] border-b border-slate-100">
                      <th className="text-left px-5 py-3 font-medium">POD</th>
                      <th className="text-left px-4 py-3 font-medium">Dispatching Point</th>
                      <th className="text-left px-4 py-3 font-medium">Treatment</th>
                      <th className="text-right px-4 py-3 font-medium">CONSUMO_TOT (kWh)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {loadingAna ? (
                      <tr><td colSpan={4} className="px-5 py-8 text-center text-slate-400">Loading…</td></tr>
                    ) : anagrafica.length === 0 ? (
                      <tr><td colSpan={4} className="px-5 py-8 text-center text-slate-400">
                        No records. Upload an ANAGRAFICA file for this account and month.
                      </td></tr>
                    ) : (
                      anagrafica.map((r, i) => (
                        <tr key={i} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                          <td className="px-5 py-2.5 font-mono text-slate-800">{r.pod}</td>
                          <td className="px-4 py-2.5 text-slate-600">{r.punto_dispacciamento ?? '—'}</td>
                          <td className="px-4 py-2.5 text-slate-600">{r.trattamento ?? '—'}</td>
                          <td className="px-4 py-2.5 tabular-nums text-right font-medium text-slate-800">
                            {itKwh(r.consumo_tot)}
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

      {/* ── Dispatching Weights tab ── */}
      {tab === 'dispatching' && (
        <div className="space-y-4">
          <>
              {/* Dispatching point selector */}
              <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
                <div className="flex items-start justify-between mb-1">
                  <h2 className="text-sm font-semibold text-slate-700">Dispatching Point Weights</h2>
                  <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                    dispScope ? 'bg-blue-50 text-blue-700' : 'bg-slate-100 text-slate-600'
                  }`}>
                    {dispScope ? `Account: ${dispScope}` : 'Global (all accounts)'}
                  </span>
                </div>
                <p className="text-xs text-slate-400 mb-4">
                  96 per-period weights used when no historical data exists (Case 3 estimation).
                  All 96 weights must sum to 1.0. Global weights apply to all accounts unless
                  an account-specific override exists.
                </p>

                {loadingDisp ? (
                  <div className="text-xs text-slate-400">Loading…</div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {dispPoints.length === 0 && (
                      <p className="text-xs text-slate-400">No weights configured for {accountId || 'global'} yet.</p>
                    )}
                    {dispPoints.map(pd => (
                      <button
                        key={pd}
                        onClick={() => { setDispPoint(pd); setDispInput('') }}
                        className={`text-xs px-3 py-1.5 rounded-full font-medium transition-all ${
                          activeDispPoint === pd
                            ? 'bg-blue-600 text-white'
                            : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                        }`}
                      >
                        {pd}
                        <span className="ml-1.5 opacity-60">
                          {dispWeights.filter(w => w.punto_dispacciamento === pd).length}p
                        </span>
                      </button>
                    ))}
                    {/* Always show "+ New zone" so user can add more after saving the first */}
                    <button
                      onClick={() => { setDispPoint(''); setDispPointDraft(''); setDispInput('') }}
                      className={`text-xs px-3 py-1.5 rounded-full font-medium transition-all border border-dashed ${
                        !dispPoint
                          ? 'border-blue-400 text-blue-600 bg-blue-50'
                          : 'border-slate-300 text-slate-500 hover:border-blue-300 hover:text-blue-600'
                      }`}
                    >
                      + New zone
                    </button>
                  </div>
                )}
              </div>

              {/* Chart for selected dispatching point */}
              {activeDispPoint && chartData.length > 0 && (
                <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h2 className="text-sm font-semibold text-slate-700">
                        {activeDispPoint} — 96 Period Weights
                      </h2>
                      <p className="text-xs text-slate-400 mt-0.5">
                        Sum: {chartData.reduce((s, d) => s + d.pct, 0).toFixed(2)}%
                        · Average: {(chartData.reduce((s, d) => s + d.pct, 0) / chartData.length).toFixed(4)}%/period
                      </p>
                    </div>
                    <button
                      onClick={() => delWeights.mutate(activeDispPoint)}
                      disabled={delWeights.isPending}
                      className="text-xs text-red-400 hover:text-red-600 border border-red-100 hover:border-red-300 px-3 py-1.5 rounded-lg transition-colors"
                    >
                      {delWeights.isPending ? 'Deleting…' : 'Delete weights'}
                    </button>
                  </div>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={chartData} margin={{ left: 0, right: 4, top: 4, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                      <XAxis dataKey="periodo" tick={{ fontSize: 9, fill: '#94a3b8' }} interval={11}
                        axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 9, fill: '#94a3b8' }} axisLine={false} tickLine={false}
                        unit="%" width={42} />
                      <Tooltip
                        contentStyle={{ borderRadius: 10, border: '1px solid #e2e8f0', fontSize: 11 }}
                        formatter={(v: number) => [`${v.toFixed(4)}%`, 'Weight']}
                      />
                      <Bar dataKey="pct" fill="#3b82f6" radius={[2, 2, 0, 0]} maxBarSize={6} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* Set new weights */}
              <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
                <h2 className="text-sm font-semibold text-slate-700 mb-1">
                  {activeDispPoint ? `Set Weights — ${activeDispPoint}` : 'Set Weights — New Zone'}
                </h2>
                <p className="text-xs text-slate-400 mb-4">
                  Paste 96 values (comma or newline separated). Values must sum to 1.0.
                </p>

                {/* Always show the zone name input when no existing zone is selected */}
                {!dispPoint && (
                  <div className="flex flex-col gap-1 mb-3">
                    <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Zone Name</label>
                    <input
                      value={dispPointDraft}
                      onChange={e => setDispPointDraft(e.target.value.toUpperCase())}
                      className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-400 max-w-xs"
                      placeholder="e.g. NORD, SICI, CSUD…"
                    />
                  </div>
                )}

                <div className="flex gap-2 mb-2">
                  <button onClick={equalWeights}
                    className="text-xs px-3 py-1.5 bg-slate-100 text-slate-600 rounded-lg hover:bg-slate-200 transition-colors">
                    Equal distribution (1/96)
                  </button>
                  <span className="text-xs text-slate-400 self-center">
                    {dispInput ? `${parseWeights(dispInput).length}/96 values` : ''}
                  </span>
                </div>

                <textarea
                  value={dispInput}
                  onChange={e => setDispInput(e.target.value)}
                  rows={8}
                  className="w-full text-xs font-mono border border-slate-200 rounded-xl px-3 py-2.5 bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-400 resize-none"
                  placeholder="Paste 96 values separated by commas or newlines&#10;Example:&#10;0.010417&#10;0.010417&#10;..."
                />

                <div className="flex items-center gap-3 mt-3">
                  <button
                    onClick={() => {
                      const weights = parseWeights(dispInput)
                      if (weights.length !== 96) { alert(`Need exactly 96 values, got ${weights.length}`); return }
                      saveWeights.mutate(weights)
                    }}
                    disabled={!dispInput || saveWeights.isPending || (!activeDispPoint && !dispPointDraft)}
                    className="px-4 py-2 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors"
                  >
                    {saveWeights.isPending ? 'Saving…' : `Save to ${activeDispPoint || dispPointDraft || '—'}`}
                  </button>
                  {saveWeights.isSuccess && (
                    <span className="text-xs text-green-600">Saved successfully</span>
                  )}
                  {saveWeights.isError && (
                    <span className="text-xs text-red-600">{(saveWeights.error as Error).message}</span>
                  )}
                </div>
              </div>
            </>
        </div>
      )}

      {/* ── Users tab ── */}
      {tab === 'users' && isAdmin && (
        <div className="space-y-4">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-slate-700">User Accounts</h2>
                <p className="text-xs text-slate-400 mt-0.5">Manage login credentials and account access.</p>
              </div>
              <button
                onClick={() => showUserForm ? closeUserForm() : setShowUserForm(true)}
                className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                New User
              </button>
            </div>

            {/* Create / Edit form */}
            {showUserForm && (
              <div className="px-5 py-4 bg-slate-50 border-b border-slate-100 space-y-4">
                <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                  {editingUserId !== null ? 'Edit User' : 'New User'}
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-medium text-slate-500 block mb-1">Username</label>
                    <input
                      type="text"
                      value={userForm.username}
                      disabled={editingUserId !== null}
                      onChange={e => setUserForm(p => ({ ...p, username: e.target.value }))}
                      className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white disabled:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="e.g. alice"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-slate-500 block mb-1">
                      Password {editingUserId !== null && <span className="text-slate-400">(leave blank to keep)</span>}
                    </label>
                    <input
                      type="password"
                      value={userForm.password}
                      onChange={e => setUserForm(p => ({ ...p, password: e.target.value }))}
                      className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder={editingUserId !== null ? 'Unchanged' : 'Min 6 characters'}
                    />
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="is_admin"
                    checked={userForm.is_admin}
                    onChange={e => setUserForm(p => ({ ...p, is_admin: e.target.checked }))}
                    className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                  />
                  <label htmlFor="is_admin" className="text-sm text-slate-700">Administrator (unrestricted access to all accounts)</label>
                </div>

                {!userForm.is_admin && (
                  <div>
                    <label className="text-xs font-medium text-slate-500 block mb-2">
                      Allowed Accounts <span className="text-slate-400">(click to toggle; none selected = all accounts)</span>
                    </label>
                    <div className="flex flex-wrap gap-2">
                      {accounts.map(a => {
                        const selected = userForm.allowed_accounts?.includes(a.account_id) ?? false
                        return (
                          <button
                            key={a.account_id}
                            type="button"
                            onClick={() => toggleAccountChip(a.account_id)}
                            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                              selected
                                ? 'bg-blue-600 text-white border-blue-600'
                                : 'bg-white text-slate-600 border-slate-200 hover:border-blue-400'
                            }`}
                          >
                            {a.display_name ?? a.account_id}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}

                {userFormError && <p className="text-xs text-red-600">{userFormError}</p>}

                <div className="flex gap-3">
                  <button
                    onClick={() => saveUser.mutate()}
                    disabled={saveUser.isPending || !userForm.username || (editingUserId === null && !userForm.password)}
                    className="px-4 py-2 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors"
                  >
                    {saveUser.isPending ? 'Saving…' : editingUserId !== null ? 'Update' : 'Create User'}
                  </button>
                  <button
                    onClick={closeUserForm}
                    className="px-4 py-2 text-xs font-medium text-slate-600 rounded-lg border border-slate-200 hover:bg-slate-50 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Users table */}
            {loadingUsers ? (
              <div className="px-5 py-8 text-sm text-slate-400 text-center">Loading users…</div>
            ) : users.length === 0 ? (
              <div className="px-5 py-8 text-sm text-slate-400 text-center">No users yet. Create the first one above.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="text-xs text-slate-400 uppercase tracking-wide bg-slate-50">
                    <tr>
                      <th className="px-5 py-3">Username</th>
                      <th className="px-4 py-3">Role</th>
                      <th className="px-4 py-3">Accounts</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map(u => (
                      <tr key={u.id} className="border-t border-slate-50 hover:bg-slate-50 transition-colors group">
                        <td className="px-5 py-3 text-xs font-medium text-slate-800">
                          {u.username}
                          {u.username === currentUser?.username && (
                            <span className="ml-1.5 text-xs text-slate-400">(you)</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                            u.is_admin ? 'bg-purple-100 text-purple-700' : 'bg-slate-100 text-slate-600'
                          }`}>
                            {u.is_admin ? 'Admin' : 'User'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          {u.allowed_accounts === null || u.is_admin ? (
                            <span className="text-xs text-slate-400">All accounts</span>
                          ) : u.allowed_accounts.length === 0 ? (
                            <span className="text-xs text-slate-400">None</span>
                          ) : (
                            <div className="flex flex-wrap gap-1">
                              {u.allowed_accounts.map(a => (
                                <span key={a} className="text-xs px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full">{a}</span>
                              ))}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                            u.is_active ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-400 line-through'
                          }`}>
                            {u.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-3 opacity-0 group-hover:opacity-100 transition-all">
                            <button
                              onClick={() => startEditUser(u)}
                              className="text-xs text-blue-500 hover:text-blue-700"
                            >
                              Edit
                            </button>
                            {u.username !== currentUser?.username && (
                              <button
                                onClick={() => deactivateUser.mutate(u.id)}
                                disabled={deactivateUser.isPending}
                                className="text-xs text-red-400 hover:text-red-600"
                              >
                                {u.is_active ? 'Deactivate' : 'Reactivate'}
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
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
