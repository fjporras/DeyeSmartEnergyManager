# CONFIGURATION — Deye Smart Energy Manager

Toda la configuración se realiza desde la UI de Home Assistant
(Ajustes → Dispositivos y servicios → Añadir integración → *Deye Smart
Energy Manager*). No hay YAML.

## 1. Paso inicial — selección de entidades

El asistente presenta selectores de entidad prefiltrados con los valores
auditados en `docs/ENTITY_AUDIT.md`. Todos son modificables.

### Requeridas

| Clave | Valor por defecto (GTS) | Requisito |
|---|---|---|
| `pv_power_entity` | `sensor.garaje_deye_sun_15k_sg05lp3_eu_sm2_microinverter_power` | sensor W/kW |
| `grid_power_entity` | `sensor.deye_sun_15k_sg05lp3_eu_sm2_external_power` | sensor W/kW (+import) |
| `load_power_entity` | `sensor.deye_sun_15k_sg05lp3_eu_sm2_load_ups_power` | sensor W/kW |
| `battery_soc_entity` | `sensor.deye_sun_15k_sg05lp3_eu_sm2_battery` | sensor % |
| `battery_power_entity` | `sensor.deye_sun_15k_sg05lp3_eu_sm2_battery_power` | sensor W/kW (−carga) |
| `price_import_entity` | `sensor.esios_pvpc` | sensor con `price_XXh` |

### Opcionales (la función se desactiva si falta)

| Clave | Valor sugerido | Función |
|---|---|---|
| `pv_forecast_entity` | `sensor.energy_production_today` | Escalado del perfil FV diario |
| `pv_forecast_tomorrow_entity` | `sensor.energy_production_tomorrow` | Energía FV de mañana |
| `energy_import_entity` | `sensor.deye_…_total_energy_import` | Contador kWh (economía) |
| `energy_export_entity` | `sensor.deye_…_total_energy_export` | Contador kWh exportación |
| `ev_*` / `acs_*` | *(vacío)* | Inactivos — no hay VE ni termo en la instalación |

Validación en el flujo: la entidad existe, está disponible y su unidad es
compatible. Los errores se muestran por campo.

## 2. Opciones (`Configure`)

### Batería

| Opción | Default | Notas |
|---|---|---|
| `battery_usable_kwh` | 30.0 | ⚠️ pendiente de validación empírica (BMS 439 Ah / config 628 Ah / estimador 36,1 kWh) |
| `soc_min_pct` | 20 | Por encima del `shutdown_soc` del inversor (15 %) |
| `soc_max_pct` | 95 | |
| `reserve_soc_pct` | 35 | Reserva modo `backup` |
| `max_charge_w` | 5300 | = `battery_max_charging_current` 100 A × ~53 V |
| `max_discharge_w` | 6300 | = 120 A × ~53 V |
| `charge_efficiency` | 0.95 | |
| `discharge_efficiency` | 0.95 | |
| `degradation_eur_kwh` | 0.02 | Coste de ciclo estimado |

### Optimizador

| Opción | Default |
|---|---|
| `horizon_hours` | 24 |
| `step_minutes` | 60 |
| `optimize_interval_min` | 15 |
| `export_price_eur_kwh` | 0.14 (confirmar con comercializadora) |
| `price_fallback` | `conservative` |

### Control

| Opción | Default | Efecto |
|---|---|---|
| `mode` | `shadow` | Modo inicial obligatorio |
| `enable_control` | `false` | Habilita modos ejecutores; sin él, `select.dsem_mode` rechaza `auto`/`economic`/`solar_priority`/`backup` |

## 3. Funciones deshabilitadas por ausencia de entidades

- **Vehículo eléctrico:** no hay cargador ni entidades de VE (CASA-GOMEZ es un móvil).
- **ACS/termo:** sin entidades `water_heater`/`climate` ni medida dedicada.

Cuando existan integraciones reales, se habilitarán añadiendo sus entity_ids
en options — sin reinstalar DSEM.

## 4. Entidades propias creadas

Ver `docs/ARCHITECTURE.md` §9. En el scaffold actual:
`sensor.dsem_*` (estado, estrategia, potencias normalizadas) y
`select.dsem_mode`.
