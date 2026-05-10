"""
Pydantic v2 response schemas for all API endpoints.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# ── Auth ───────────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ── Accounts ───────────────────────────────────────────────────────────────────

class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    account_id: str
    schema_name: str
    display_name: str | None
    active: bool


# ── Measurements ───────────────────────────────────────────────────────────────

class PeriodOut(BaseModel):
    pod: str
    data_misura: date
    periodo: int
    ea_kwh: float | None
    er_kvarh: float | None
    tipo_dato: str | None
    dst: int


class MeasurementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    pod: str
    data_misura: date
    periodo: int
    ea_kwh: float | None
    er_kvarh: float | None
    tipo_dato: str | None
    raccolta: str | None
    validato: str | None
    tensione: int | None
    trattamento: str | None
    pot_max: float | None
    dst: int
    cod_flusso: str | None
    mese_anno: str | None
    source_file: str | None


# ── Aggregation ────────────────────────────────────────────────────────────────

class DailyTotalOut(BaseModel):
    pod: str
    data_misura: date
    daily_kwh: float | None
    daily_kvarh: float | None
    source: str
    periods: int


class MonthlyTotalOut(BaseModel):
    pod: str
    mese_anno: str
    monthly_kwh: float | None
    monthly_kvarh: float | None
    days: int
    source: str


# ── Files ──────────────────────────────────────────────────────────────────────

class FileLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    file_id: int
    file_name: str
    account_id: str
    cod_flusso: str | None
    mese_anno: str | None
    file_timestamp: datetime | None
    progressivo: int | None
    sm_status: str | None
    processed_at: datetime | None
    status: str | None
    error_message: str | None


# ── Monitoring ─────────────────────────────────────────────────────────────────

class MissingPeriodOut(BaseModel):
    pod: str
    data_misura: date
    periods_found: int
    missing: int
    source: str


class CorrectionSummaryOut(BaseModel):
    pod: str
    mese_anno: str
    cod_flusso: str
    count: int


class PodMetadataOut(BaseModel):
    pod: str
    codice_dp: str | None
    tensione: int | None
    trattamento: str | None
    valid_from: date | None
    valid_to: date | None
    source_file: str | None


# ── Sync ───────────────────────────────────────────────────────────────────────

class SyncStatusOut(BaseModel):
    account_id: str
    started_at: datetime | None
    finished_at: datetime | None
    files_ok: int
    files_error: int
    files_skipped: int
    running: bool
    # Live fields — only populated while an ingestion is in progress
    current_account: str | None = None   # which account is being processed right now
    triggered_by: str | None = None      # "scheduler" or "api"


class SyncTriggerOut(BaseModel):
    message: str
    account_id: str | None   # None = all accounts


# ── ANAGRAFICA ─────────────────────────────────────────────────────────────────

class AnagraficaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    pod: str
    mese_anno: str
    piva_utente: str | None
    punto_dispacciamento: str | None
    tipo_misuratore: str | None
    trattamento: str | None
    tensione: int | None
    codice_tariffa: str | None
    consumo_tot: float | None
    included: bool
    source_file: str | None


class AnagraficaUploadOut(BaseModel):
    message: str
    account_id: str
    mese_anno: str
    records_upserted: int


# ── Forecast ───────────────────────────────────────────────────────────────────

class ForecastGenerateIn(BaseModel):
    account_id: str
    mese_anno: str                          # forecast target month MM/YYYY
    anagrafica_mese_anno: str | None = None # which registry to use; defaults to mese_anno


class ForecastPeriodOut(BaseModel):
    pod: str
    mese_anno: str
    punto_dispacciamento: str | None
    forecast_date: date
    source_date: date | None
    periodo: int
    ea_mwh: float | None
    ea_mwh_with_loss: float | None
    loss_pct: float | None
    source_type: str


class ForecastGenerateOut(BaseModel):
    message: str
    account_id: str
    mese_anno: str
    periods_written: int


class ComparePeriodData(BaseModel):
    date: str
    periodo: int
    ea_mwh: float | None


class CompareOut(BaseModel):
    account_id: str
    pod: str
    current_period: dict[str, Any]
    previous_period: dict[str, Any]
    current_total_mwh: float
    previous_total_mwh: float


# ── Admin — loss config ────────────────────────────────────────────────────────

class LossRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: str | None
    name: str
    condition_type: str
    condition_value: str | None
    loss_pct: float
    priority: int
    description: str | None


class LossRuleIn(BaseModel):
    account_id: str | None = None
    name: str
    condition_type: str           # "tensione_range"|"tariffa_prefix"|"missing_pod"|"default"
    condition_value: str | None = None
    loss_pct: float
    priority: int
    description: str | None = None


# ── Admin — dispatching config ────────────────────────────────────────────────

class DispatchingWeightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: str | None       # None = global (applies to all accounts)
    punto_dispacciamento: str
    periodo: int
    pct: float


class DispatchingWeightIn(BaseModel):
    punto_dispacciamento: str
    weights: list[float]          # exactly 96 values summing to 1.0


# ── Totals (totalizer table) ───────────────────────────────────────────────────

class TotalizerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    pod: str
    data_misura: date | None
    mese_anno: str | None
    tipo_dato: str | None
    ea_f1: float | None
    ea_f2: float | None
    ea_f3: float | None
    ea_f4: float | None
    ea_f5: float | None
    ea_f6: float | None
    ea_m: float | None
    er_f1: float | None
    er_f2: float | None
    er_f3: float | None
    pot_f1: float | None
    pot_f2: float | None
    pot_f3: float | None
    cod_flusso: str | None
    source_file: str | None
