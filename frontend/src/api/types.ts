export interface Account {
  account_id: string
  schema_name: string
  display_name: string | null
  active: boolean
}

export interface DailyTotal {
  pod: string
  data_misura: string
  daily_kwh: number | null
  daily_kvarh: number | null
  source: string
  periods: number
}

export interface MonthlyTotal {
  pod: string
  mese_anno: string
  monthly_kwh: number | null
  monthly_kvarh: number | null
  days: number
  source: string
}

export interface PeriodRow {
  pod: string
  data_misura: string
  periodo: number
  ea_kwh: number | null
  er_kvarh: number | null
  tipo_dato: string | null
  dst: number
}

export interface FileLog {
  file_id: number
  file_name: string
  account_id: string
  cod_flusso: string | null
  mese_anno: string | null
  file_timestamp: string | null
  progressivo: number | null
  sm_status: string | null
  processed_at: string | null
  status: string | null
  error_message: string | null
}

export interface SyncStatus {
  account_id: string
  started_at: string | null
  finished_at: string | null
  files_ok: number
  files_error: number
  files_skipped: number
  running: boolean
  current_account: string | null
  triggered_by: string | null
  elapsed_seconds: number | null
  accounts_done: number | null
  accounts_total: number | null
  next_run: string | null
  phase: string | null
  files_done: number | null
  files_total: number | null
  backfill_queued: boolean
}

export interface MissingPeriod {
  pod: string
  data_misura: string
  periods_found: number
  missing: number
  source: string
}

export interface CorrectionSummary {
  pod: string
  mese_anno: string
  cod_flusso: string
  count: number
}

export interface PodMetadata {
  pod: string
  codice_dp: string | null
  tensione: number | null
  trattamento: string | null
  valid_from: string | null
  valid_to: string | null
  source_file: string | null
}

// ── Forecast ──────────────────────────────────────────────────────────────────

export interface ForecastPeriod {
  pod: string
  mese_anno: string
  punto_dispacciamento: string | null
  forecast_date: string
  source_date: string | null
  periodo: number
  ea_mwh: number | null
  ea_mwh_with_loss: number | null
  loss_pct: number | null
  source_type: string
}

export interface ForecastGenerateResult {
  message: string
  account_id: string
  mese_anno: string
  periods_written: number
}

export interface ForecastJob {
  status: 'running' | 'done' | 'error'
  result: ForecastGenerateResult | null
  error: string | null
}

export interface CompareOut {
  account_id: string
  pod: string
  current_period: { from: string; to: string; data: { date: string; periodo: number; ea_mwh: number | null }[] }
  previous_period: { from: string; to: string; data: { date: string; periodo: number; ea_mwh: number | null }[] }
  current_total_mwh: number
  previous_total_mwh: number
}

export interface CompareDPDailyRow {
  date: string
  total: number
  [dp: string]: number | string
}

export interface CompareDPOut {
  account_id: string
  anagrafica_month: string
  current_period: { from: string; to: string }
  previous_period: { from: string; to: string }
  dispatching_points: string[]
  current_daily: CompareDPDailyRow[]
  previous_daily: CompareDPDailyRow[]
  current_total_mwh: number
  previous_total_mwh: number
}

// ── Admin ─────────────────────────────────────────────────────────────────────

export interface LossRule {
  id: number
  account_id: string | null
  name: string
  condition_type: string
  condition_value: string | null
  loss_pct: number
  priority: number
  description: string | null
}

export interface DispatchingWeight {
  id: number
  account_id: string | null   // null = global (all accounts)
  punto_dispacciamento: string
  periodo: number
  pct: number
}

export interface AnagraficaRecord {
  pod: string
  mese_anno: string
  piva_utente: string | null
  punto_dispacciamento: string | null
  tipo_misuratore: string | null
  trattamento: string | null
  tensione: number | null
  codice_tariffa: string | null
  consumo_tot: number | null
  included: boolean
  source_file: string | null
}
