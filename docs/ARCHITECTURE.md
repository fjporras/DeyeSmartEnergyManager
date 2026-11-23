# ARCHITECTURE — Deye Smart Energy Manager (DSEM)

**Dominio:** `deye_smart_energy_manager`
**Tipo:** integración personalizada (`custom_components`), config entry único, `iot_class: calculated`
**Objetivo HA:** Container `core-2026.8.3` (Python ≥3.13). **Estado:** producción — v0.8.x, control ejecutor verificado en vivo (2026-11-16).

## 1. Principios de diseño

1. **Sin comunicación propia con el inversor.** DSEM lee y escribe exclusivamente
   *entidades de Home Assistant* proporcionadas por integraciones existentes
   (`solarman`, `fronius`, `pvpc_hourly_pricing`, `forecast_solar`).
2. **SHADOW por defecto.** Toda la maquinaria de decisión funciona sin emitir
   ninguna orden. El modo `auto` exige doble habilitación: option
   `enable_control` + selección explícita del modo.
3. **Nada inventado.** Un sensor ausente desactiva la función afectada,
   nunca se sustituye por un valor supuesto.
4. **El optimizador manda, no los umbrales.** Los modos y preferencias son
   parámetros de la función objetivo, no reglas de disparo.
5. **Decisiones explicables.** Cada plan se publica con su motivo (entidad de
   diagnóstico + atributos estructurados acotados).

## 2. Mapa de módulos

```
┌────────────────────────────────────────────────────────────────────┐
│                        config_flow.py                              │
│  Entity pickers (entity ids reales auditadas) + validación         │
│  options flow: batería, optimizador, precios, modo, enable_control │
└──────────────┬─────────────────────────────────────────────────────┘
               │ entry.data (entities) / entry.options (params)
               ▼
┌────────────────────────────────────────────────────────────────────┐
│ coordinator.py  —  DsemCoordinator (DataUpdateCoordinator, 60 s)   │
│  ├─ model.py      snapshot normalizado (signos/unidades/freshness) │
│  ├─ prices.py     PVPC hoy/mañana + precio exportación + fallback  │
│  ├─ forecast.py   perfiles consumo (statistics) + FV (fc_solar)    │
│  ├─ optimizer.py  heurístico determinista 24 h (LP HiGHS = backlog)│
│  ├─ influx.py     precios REE desde InfluxDB (fallback PVPC)      │
│  ├─ tou.py        diagnóstico TOU (read-only)                     │
│  ├─ plan          EnergyPlan: acción/W batt/W grid/SOC por hora    │
│  └─ control.py    ejecutor: switch carga + guardias zero-export/   │
│                   off_grid + conflicto automatización PVPC        │
└──────────────┬─────────────────────────────────────────────────────┘
               │ coordinator.data
               ▼
   sensor.py · select.py (modo/objetivos) · number.py (SOC/time) · dashboard
               │
               ▼
   Panel Lovelace (fase 13) · diagnostics.py · logbook de decisiones
```

## 3. Modelo energético (auditado — `docs/ENTITY_AUDIT.md`)

| Variable | Entidad por defecto | Convención DSEM |
|---|---|---|
| `pv_w` | `sensor.garaje_…_microinverter_power` | ≥0, producción AC total (Fronius vía GEN) |
| `grid_w` | `sensor.…_external_power` | **+ import / − export** (CTs en entrada Grid) |
| `load_w` | `sensor.…_load_ups_power` | ≥0, consumo total vivienda |
| `bat_w` | `sensor.…_battery_power` | **− carga / + descarga** (nativo solarman) |
| `soc_pct` | `sensor.…_battery` | % |
| `price_imp` | `sensor.esios_pvpc` + `price_XXh` | €/kWh |
| `pv_forecast` | `forecast_solar` (today/tomorrow/now/next h) | kWh/Wh |

**Balance:** `pv + grid_imp + bat_dis ≈ load + bat_chg + losses` (verificado ~0,2 %).

## 4. Modos operativos

| Modo | Semántica | Ejecuta órdenes |
|---|---|---|
| `shadow` | Optimiza y publica planes; registro completo | ❌ nunca |
| `manual` | Sin acciones automáticas ni recomendaciones activas | ❌ |
| `safe` | Solo monitoriza; ignora planes no validables | ❌ |
| `solar_priority` | Optimiza maximizando autoconsumo | ✅ si `enable_control` |
| `economic` | Optimiza por mínimo coste | ✅ si `enable_control` |
| `backup` | Mantiene reserva SOC configurable | ✅ si `enable_control` |
| `target_soc` | Objetivo SOC a una hora: precarga en horas baratas / FV, suelo de trayectoria que bloquea descargas por debajo de lo necesario | ✅ si `enable_control` |
| `auto` | Optimizador + ejecución verificada | ✅ si `enable_control` |

`enable_control` es una option no trivial (boolean + confirmación). Cambiar a
`auto`/`economic`/… con `enable_control=false` lanza `ServiceValidationError`
en la entidad `select` y deja el modo anterior.

## 5. Superficie de control (solo AUTO, tras habilitación)

Escritura exclusivamente sobre entidades solarman (NO servicios `solarman.write_*`):

| Mecanismo | Entidades | Uso DSEM |
|---|---|---|
| TOU programas | `time.program_N_time`, `number.program_N_power/soc`, `select.program_N_charging` | Solo lectura/diagnóstico (`tou_*` en plan_meta) |
| Carga de red | `switch.battery_grid_charging`, `number.battery_grid_charging_current` | Activar/limitar carga desde red |
| Zero-export | `select.work_mode`, `switch.export_surplus`, `number.zero_export_power` | Guardia: mantiene `Zero Export To CT` / off / 20 W |
| Límites | `number.battery_max_charging/discharging_current`, `number.grid_max_import/export_power` | Acotar potencia |
| Modo trabajo | `select.work_mode`, `select.energy_pattern`, `select.time_of_use` | `work_mode` solo vía guardia zero-export |
| Soporte de carga | `switch.off_grid` | Guardia: ON en slots `discharge` (única vía de descarga a carga), OFF el resto (bloquea carga de red); escritura solo tras 8 evaluaciones seguidas pidiendo el cambio (histéresis anti-ciclo-límite) |

Reglas de seguridad (control.py): validación de dominio + límites, min-dwell
entre escrituras, histéresis, máx. reintentos, modo `safe` ante error persistente,
registro `logbook` de cada orden y su motivo. Protecciones del inversor
(`*_protection_*`, SOC shutdown/low, tensiones) **jamás** se modifican.

## 6. Optimizador (heurístico v1 implementado; LP = backlog)

- **Implementado:** heurístico determinista por intervalos Δt=1 h,
  horizonte 24 h (`optimizer.py`). Detalle completo en
  `docs/OPTIMIZATION.md` §6. Incluye física real de descarga autónoma,
  suelo de trayectoria (reserva + objetivo SOC), crédito FV para
  precarga y arbitrador precio.
- **Backlog LP:** si el heurístico se queda corto, formulación LP por
  intervalos (ver OPTIMIZATION.md §1-3) con `highspy`/HiGHS; comparte
  `PlannerInput`/`EnergyPlan` → recambio local a `optimizer.optimize()`.

## 7. Precios

- **Primario:** InfluxDB bucket `ree_indicators`, measurement
  `electricity_price`, field `precio_kwh`, tags `tipo=consumo|excedentes`
  (vía la config entry `influxdb` instalada; solo lectura).
- **Fallback:** `sensor.esios_pvpc` (`price_XXh` del día en curso) +
  precio de exportación fijo (`export_price_eur_kwh`, default 0,14).
- Huecos en la serie → mediana del horizonte + warning `price_gaps_filled`;
  sin datos → `no_price_data`, sin arbitraje.

## 8. Previsiones

- **FV:** `forecast_solar` (energy_today/tomorrow + power now/next hour).
  Limitación conocida: sin curva horaria completa → perfil horario sintetizado
  (histórico `microinverter_power` + forecast_solar como factor de escala +
  met.no cloud/uv como refinador). Si se instala Solcast → serie horaria directa.
- **Consumo:** perfiles desde `statistics` (`total_load_consumption`,
  `load_power` horario) por hora/día-semana; incertidumbre = dispersión.

## 9. Entidades DSEM (nombres reales en HA)

- `sensor.deye_smart_energy_manager_estado_del_optimizador` — modo,
  `missing/stale_entities`, `control_enabled`.
- `sensor.deye_smart_energy_manager_proxima_accion_del_plan` — acción
  actual + slots horarios + meta (`zero_export`, `offgrid`, `control`,
  `tou_*`, `pv_bias`, `nowcast_kw`, `ev_*`, `price_source`…).
- `sensor.deye_smart_energy_manager_estrategia_actual`.
- `select.deye_smart_energy_manager_modo` — modo (rechaza ejecutores
  sin `enable_control`).
- `number.deye_smart_energy_manager_soc_objetivo` +
  `time.deye_smart_energy_manager_hora_objetivo` — objetivo `target_soc`.
- Historial de planes: `config/deye_smart_energy_manager/plan_log.jsonl`
  (una línea JSON por hora de inicio de plan, rotación ~2 MB).

## 10. Ciclo de vida y recursos

- `async_setup_entry` → `DsemCoordinator` + `runtime_data` + plataformas.
- `async_unload_entry` → unload plataformas; coordinator sin listeners propios
  (lee `hass.states`, no suscribe); listeners de opciones cancelados con
  `entry.async_on_unload`.
- Sin tareas de fondo fuera del coordinator; sin I/O bloqueante; sin
  dependencias pip en el scaffold.
- `diagnostics.py`: entry data/options (sin secretos — solo entity_ids y
  parámetros) + último snapshot + último plan/errores.

## 11. Despliegue

**Vía HACS (producción):** repo público
`github.com/fjporras/DeyeSmartEnergyManager`, releases con tag
(`v0.x.y`). HACS → actualizar → reiniciar HA. Procedimientos manuales
y checklist en `docs/DEPLOYMENT.md`.

## 12. Conflictos externos

`automation.pvpc_carga_bateria_deye_en_horas_baratas` actúa sobre
`switch.battery_grid_charging`. En SHADOW convive; con un modo
ejecutor + `enable_control` DSEM la desactiva automáticamente
(`pvpc_automation_entity`, opción configurable) y la restaura al
salir del modo ejecutor (`control.py`, `conflict_suspended`/
`conflict_restored` en `plan_meta.control`).

`automation.aviso_de_corte_de_red` también escribe `switch.off_grid`
(ON al detectar corte de tensión en cualquier fase, OFF al restablecer).
DSEM no escribe `off_grid` cuando la tensión L1 < 150 V (la guardia
cede el control a la automatización en isla) y restaura a OFF al salir
de modos ejecutores un ON propio. `binary_sensor.*_grid` no es señal
de presencia de red: marca `off` siempre que el intercambio sea cero.
