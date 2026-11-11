# ARCHITECTURE — Deye Smart Energy Manager (DSEM)

**Dominio:** `deye_smart_energy_manager`
**Tipo:** integración personalizada (`custom_components`), config entry único, `iot_class: calculated`
**Objetivo HA:** Container `core-2026.8.3` (Python ≥3.13). **Estado:** Fase 2 — scaffold SHADOW.

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
│  ├─ optimizer.py  LP 24-48 h (HiGHS)  [FASE 7]                     │
│  ├─ plan          EnergyPlan: E_imp/E_exp/E_bat±/SOC por intervalo │
│  └─ control.py    validación + ejecución TOU (VETADO en SHADOW)    │
└──────────────┬─────────────────────────────────────────────────────┘
               │ coordinator.data
               ▼
   sensor.py · select.py (modo) · number.py/switch.py (futuros parámetros)
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
| TOU programas | `time.program_N_time`, `number.program_N_power/soc`, `select.program_N_charging` | Traducir plan SOC/potencia a franjas del inversor |
| Carga de red | `switch.battery_grid_charging`, `number.battery_grid_charging_current` | Activar/limitar carga desde red |
| Límites | `number.battery_max_charging/discharging_current`, `number.grid_max_import/export_power` | Acotar potencia |
| Modo trabajo | `select.work_mode`, `select.energy_pattern`, `select.time_of_use` | Solo con validación previa |

Reglas de seguridad (control.py): validación de dominio + límites, min-dwell
entre escrituras, histéresis, máx. reintentos, modo `safe` ante error persistente,
registro `logbook` de cada orden y su motivo. Protecciones del inversor
(`*_protection_*`, SOC shutdown/low, tensiones) **jamás** se modifican.

## 6. Optimizador (FASE 7 — decisión pendiente de librería)

- **Formulación:** LP por intervalos Δt=1 h, horizonte 24-48 h.
- **Variables por intervalo:** `e_imp, e_exp, e_pv_used, e_bat_chg, e_bat_dis,
  soc, e_ev, e_acs, e_pv_curt`.
- **Objetivo:** `Σ price_imp·e_imp − price_exp·e_exp + c_deg·(e_chg+e_dis)
  + c_loss·pérdidas + penalizaciones`.
- **Restricciones:** balance por intervalo; `soc_min≤soc≤soc_max`;
  potencias máx; eficiencias; reserva configurable; necesidades EV/ACS
  (inactivas mientras no haya entidades).
- **Candidatos de solver:** `highspy` (HiGHS, wheels musllinux, ligero) — preferido;
  `scipy.optimize.linprog` (usa HiGHS, pero ~40 MB); fallback heurístico propio si
  la dependencia no es instalable en el contenedor. **Decisión registrada en
  docs/OPTIMIZATION.md al implementar.**

## 7. Precios

- Importación: `sensor.esios_pvpc` (`price_00h…23h` del día en curso;
  `next_day` no expuesto → horizonte usa precio de hoy + marca
  `prices_incomplete` hasta la publicación ~20:35).
- Exportación: option `export_price_eur_kwh` (default 0,14 — valor SolarNet,
  confirmar contrato con el usuario).
- Fallback ante datos ausentes: estrategia `price_fallback` (conservadora).

## 8. Previsiones

- **FV:** `forecast_solar` (energy_today/tomorrow + power now/next hour).
  Limitación conocida: sin curva horaria completa → perfil horario sintetizado
  (histórico `microinverter_power` + forecast_solar como factor de escala +
  met.no cloud/uv como refinador). Si se instala Solcast → serie horaria directa.
- **Consumo:** perfiles desde `statistics` (`total_load_consumption`,
  `load_power` horario) por hora/día-semana; incertidumbre = dispersión.

## 9. Entidades DSEM (convención `sensor.dsem_*`)

Implementadas en scaffold: `sensor.dsem_optimization_status`,
`sensor.dsem_current_strategy`, `sensor.dsem_grid_power`,
`sensor.dsem_pv_power`, `sensor.dsem_battery_power`,
`sensor.dsem_battery_soc`, `select.dsem_mode`.

Fases posteriores: `predicted_grid_import/export`, `predicted_energy_cost`,
`estimated_savings`, `battery_soc_target`, `next_charge/discharge_period`,
`last_optimization`, `last_error`, planes horarios como atributos acotados.

## 10. Ciclo de vida y recursos

- `async_setup_entry` → `DsemCoordinator` + `runtime_data` + plataformas.
- `async_unload_entry` → unload plataformas; coordinator sin listeners propios
  (lee `hass.states`, no suscribe); listeners de opciones cancelados con
  `entry.async_on_unload`.
- Sin tareas de fondo fuera del coordinator; sin I/O bloqueante; sin
  dependencias pip en el scaffold.
- `diagnostics.py`: entry data/options (sin secretos — solo entity_ids y
  parámetros) + último snapshot + último plan/errores.

## 11. Despliegue (pendiente)

El MCP no tiene acceso a `/config`. Procedimiento previsto: copia del paquete a
`<config>/custom_components/deye_smart_energy_manager/` vía SSH + reinicio
controlado autorizado por el usuario → alta en UI → modo SHADOW.
Detallado en `docs/DEPLOYMENT.md` (a redactar en fase 16).

## 12. Conflictos externos

`automation.pvpc_carga_bateria_deye_en_horas_baratas` actúa sobre
`switch.battery_grid_charging`. En SHADOW convive; antes de cualquier modo
ejecutor debe desactivarse **con autorización del usuario** (documentado en
ENTITY_AUDIT §5.8 y DEPLOYMENT).
