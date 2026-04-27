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
