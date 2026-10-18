"""Normalized energy model for Deye Smart Energy Manager."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class EnergySnapshot:
    """Instantaneous, normalized view of the installation.

    Sign conventions (normalized on top of the audited entities):
      pv_power_w        >= 0  PV production (Fronius via Deye GEN/microinverter)
      grid_power_w      + import / - export  (external CTs at the grid entry)
      load_power_w      >= 0  house consumption (Deye load/UPS port)
      battery_power_w   - charging / + discharging (native solarman convention)
      battery_soc_pct   0-100
    """

    timestamp: datetime
    pv_power_w: float | None = None
    grid_power_w: float | None = None
    load_power_w: float | None = None
    battery_power_w: float | None = None
    battery_soc_pct: float | None = None
    price_import_eur_kwh: float | None = None
    pv_forecast_today_kwh: float | None = None
    pv_forecast_tomorrow_kwh: float | None = None
    energy_import_today_kwh: float | None = None
    energy_export_today_kwh: float | None = None
    missing_entities: tuple[str, ...] = field(default_factory=tuple)
    stale_entities: tuple[str, ...] = field(default_factory=tuple)

    @property
    def complete(self) -> bool:
        """True when every required measurement is available."""
        return not self.missing_entities

    @property
    def battery_charging_w(self) -> float | None:
        """Positive charge power in W (0 when idle/discharging)."""
        if self.battery_power_w is None:
            return None
        return max(0.0, -self.battery_power_w)

    @property
    def battery_discharging_w(self) -> float | None:
        """Positive discharge power in W (0 when idle/charging)."""
        if self.battery_power_w is None:
            return None
        return max(0.0, self.battery_power_w)


# ---------------------------------------------------------------------------
# Energy plan (optimizer output)
# ---------------------------------------------------------------------------

# Plan actions (machine-readable; translated in strings.json)
ACTION_CHARGE_PV = "charge_pv"        # store PV surplus
ACTION_CHARGE_GRID = "charge_grid"    # buy cheap energy for later
ACTION_DISCHARGE = "discharge"        # battery covers an expensive deficit
ACTION_IMPORT = "import"              # deficit covered by grid (battery held)
ACTION_EXPORT = "export"              # PV surplus exported (battery full/held)
ACTION_IDLE = "idle"                  # balanced / no decision needed
ACTION_HOLD = "hold"                  # explicit reserve protection


@dataclass(frozen=True)
class PlanSlot:
    """One hourly decision of the energy plan."""

    start: datetime
    action: str
    battery_power_w: float            # signed: - charge / + discharge
    grid_power_w: float               # expected exchange: + import / - export
    soc_end_pct: float
    import_price_eur_kwh: float | None
    reason: str                       # short explainable justification


@dataclass(frozen=True)
class EnergyPlan:
    """Hourly plan produced by the optimizer (computed in every mode)."""

    generated_at: datetime
    horizon_hours: int
    slots: tuple[PlanSlot, ...]
    expected_cost_eur: float | None   # net cost of the plan (import - export)
    baseline_cost_eur: float | None   # cost if the battery did nothing
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def current_slot(self) -> PlanSlot | None:
        """Slot covering the plan start (index 0)."""
        return self.slots[0] if self.slots else None

    @property
    def expected_savings_eur(self) -> float | None:
        """Estimated savings vs doing nothing with the battery."""
        if self.expected_cost_eur is None or self.baseline_cost_eur is None:
            return None
        return self.baseline_cost_eur - self.expected_cost_eur
