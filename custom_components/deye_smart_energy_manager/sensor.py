"""Sensors for Deye Smart Energy Manager."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DsemConfigEntry
from .const import DOMAIN, MANUFACTURER, NAME, VERSION
from .coordinator import DsemCoordinator
from .model import EnergySnapshot


@dataclass(frozen=True, kw_only=True)
class DsemSensorDescription(SensorEntityDescription):
    """Sensor description with a snapshot value function."""

    value_fn: Callable[[EnergySnapshot, DsemCoordinator], float | str | None]
    attributes_fn: Callable[[EnergySnapshot, DsemCoordinator], dict] | None = None


def _status(snapshot: EnergySnapshot) -> str:
    if snapshot.missing_entities:
        return "degraded"
    return "ok"


def _status_attrs(
    snapshot: EnergySnapshot, coordinator: DsemCoordinator
) -> dict:
    return {
        "missing_entities": list(snapshot.missing_entities),
        "stale_entities": list(snapshot.stale_entities),
        "mode": coordinator.mode,
        "control_enabled": coordinator.control_enabled,
        "timestamp": snapshot.timestamp.isoformat(),
    }


SENSORS: tuple[DsemSensorDescription, ...] = (
    DsemSensorDescription(
        key="optimization_status",
        translation_key="optimization_status",
        icon="mdi:brain",
        value_fn=lambda s, c: _status(s),
        attributes_fn=_status_attrs,
    ),
    DsemSensorDescription(
        key="current_strategy",
        translation_key="current_strategy",
        icon="mdi:strategy",
        value_fn=lambda s, c: c.mode,
    ),
    DsemSensorDescription(
        key="grid_power",
        translation_key="grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda s, c: s.grid_power_w,
    ),
    DsemSensorDescription(
        key="pv_power",
        translation_key="pv_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda s, c: s.pv_power_w,
    ),
    DsemSensorDescription(
        key="battery_power",
        translation_key="battery_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda s, c: s.battery_power_w,
    ),
    DsemSensorDescription(
        key="battery_soc",
        translation_key="battery_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda s, c: s.battery_soc_pct,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DsemConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DSEM sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        DsemSensor(coordinator, entry, description) for description in SENSORS
    )


class DsemSensor(CoordinatorEntity[DsemCoordinator], SensorEntity):
    """A DSEM snapshot-backed sensor."""

    _attr_has_entity_name = True
    entity_description: DsemSensorDescription

    def __init__(
        self,
        coordinator: DsemCoordinator,
        entry: DsemConfigEntry,
        description: DsemSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model=NAME,
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> float | str | None:
        """Return the normalized value from the latest snapshot."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(
            self.coordinator.data, self.coordinator
        )

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return structured attributes when defined."""
        if (
            self.entity_description.attributes_fn is None
            or self.coordinator.data is None
        ):
            return None
        return self.entity_description.attributes_fn(
            self.coordinator.data, self.coordinator
        )
