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
