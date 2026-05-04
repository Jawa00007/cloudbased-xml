"""
Grid loss percentage calculator.

Rules are loaded from the loss_config table. Defaults are applied if the
table is empty or has no matching rule for a given account.

Default rule set (from requirements):
  1. tensione IN (220, 380) OR pod not found in metadata → +10%
  2. codice_tariffa starts with 'MT'                    → +3.8%
  3. anything else (catch-all)                          → +1.8%
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LossRule:
    condition_type: str       # "tensione_range" | "tariffa_prefix" | "missing_pod" | "default"
    condition_value: str | None
    loss_pct: float
    priority: int


# ── Default rules (used when DB config is empty) ──────────────────────────────

DEFAULT_RULES: list[LossRule] = [
    LossRule("missing_pod",    None,       0.10, 1),
    LossRule("tensione_range", "220,380",  0.10, 2),
    LossRule("tariffa_prefix", "MT",       0.038, 3),
    LossRule("default",        None,       0.018, 99),
]


def calculate_loss_pct(
    tensione: int | None,
    codice_tariffa: str | None,
    pod_found: bool,
    rules: list[LossRule] | None = None,
) -> float:
    """
    Return the applicable grid loss percentage for a POD.

    Args:
        tensione:       Voltage level (V) from pod_metadata, or None if unknown.
        codice_tariffa: Tariff code from pod_metadata, or None if unknown.
        pod_found:      False if the POD was not found in pod_metadata at all.
        rules:          Ordered list of LossRule from DB. Uses DEFAULT_RULES if None.

    Returns:
        Loss fraction (e.g., 0.10 for 10%).
    """
    effective_rules = sorted(rules or DEFAULT_RULES, key=lambda r: r.priority)

    for rule in effective_rules:
        if rule.condition_type == "missing_pod" and not pod_found:
            return rule.loss_pct

        if rule.condition_type == "tensione_range" and tensione is not None:
            try:
                values = {int(v.strip()) for v in (rule.condition_value or "").split(",")}
                if tensione in values:
                    return rule.loss_pct
            except ValueError:
                pass

        if rule.condition_type == "tariffa_prefix" and codice_tariffa and rule.condition_value:
            if codice_tariffa.upper().startswith(rule.condition_value.upper()):
                return rule.loss_pct

        if rule.condition_type == "default":
            return rule.loss_pct

    return 0.018  # absolute fallback


def apply_loss(ea_kwh: float | None, loss_pct: float) -> float | None:
    """Return energy after applying loss percentage: value × (1 + loss_pct)."""
    if ea_kwh is None:
        return None
    return ea_kwh * (1 + loss_pct)


def kwh_to_mwh(ea_kwh: float | None, decimals: int = 3) -> float | None:
    """Convert kWh to MWh, rounded to `decimals` decimal places."""
    if ea_kwh is None:
        return None
    return round(ea_kwh / 1000.0, decimals)
