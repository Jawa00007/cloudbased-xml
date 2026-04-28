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


class SyncTriggerOut(BaseModel):
    message: str
    account_id: str | None   # None = all accounts


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
