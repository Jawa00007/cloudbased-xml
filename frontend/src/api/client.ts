import type {
  Account, CorrectionSummary, DailyTotal, FileLog,
  MissingPeriod, MonthlyTotal, PeriodRow, PodMetadata, SyncStatus,
} from './types'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const API_KEY = import.meta.env.VITE_API_KEY ?? ''

async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(BASE + path)
  if (params) Object.entries(params).forEach(([k, v]) => v && url.searchParams.set(k, v))
  const res = await fetch(url.toString(), { headers: { 'X-API-Key': API_KEY } })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json() as Promise<T>
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path, { method: 'POST', headers: { 'X-API-Key': API_KEY } })
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`)
  return res.json() as Promise<T>
}

export const fetchAccounts    = () => get<Account[]>('/accounts')
export const fetchPods        = (account: string) => get<string[]>('/pods', { account })
export const fetchPodMetadata = (account: string) => get<PodMetadata[]>('/pod_metadata', { account })

export const fetchDailyTotals   = (account: string, pod: string, mese_anno: string) =>
  get<DailyTotal[]>('/aggregation/daily', { account, pod, mese_anno })

export const fetchMonthlyTotals = (account: string, pod: string, year: string) =>
  get<MonthlyTotal[]>('/aggregation/monthly', { account, pod, year })

export const fetchMonthlySummary = (account: string, mese_anno: string) =>
  get<MonthlyTotal[]>('/aggregation/summary', { account, mese_anno })

export const fetchPeriods = (account: string, pod: string, date: string) =>
  get<PeriodRow[]>('/measurements', { account, pod, date })

export const fetchPeriodRange = (
  account: string, pod: string,
  from_date: string, to_date: string,
  tipo_dato?: string,
) => get<PeriodRow[]>('/measurements/range', {
  account, pod, from_date, to_date, ...(tipo_dato ? { tipo_dato } : {}),
})

export const fetchFiles      = (account: string, status?: string, limit = 200) =>
  get<FileLog[]>('/files', { account, ...(status ? { status } : {}), limit: String(limit) })

export const fetchSyncStatus = () => get<SyncStatus[]>('/sync/status')
export const triggerSync     = (account?: string) =>
  post<{ message: string }>(account ? `/sync/${account}` : '/sync')

export const fetchMissingPeriods  = (account: string, mese_anno: string) =>
  get<MissingPeriod[]>('/monitoring/missing', { account, mese_anno })

export const fetchCorrections = (account: string, mese_anno?: string) =>
  get<CorrectionSummary[]>('/monitoring/corrections', { account, ...(mese_anno ? { mese_anno } : {}) })
