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
| `pv_peak_today_entity` | `sensor.power_highest_peak_time_today` | Centra la curva FV sintetizada |
| `pv_peak_tomorrow_entity` | `sensor.power_highest_peak_time_tomorrow` | Ídem mañana |
| `energy_import_entity` | `sensor.deye_…_total_energy_import` | Contador kWh (economía) |
| `energy_export_entity` | `sensor.deye_…_total_energy_export` | Contador kWh exportación |
| `ev_state_entity` | `sensor.de_ev_charger_estado` | Estado del cargador VE (tuya_local); `charging` activa el boost de carga |
| `ev_charge_current_entity` | `number.de_ev_charger_charge_current` | Corriente VE en A; potencia estimada = A × 230 V |
| `acs_*` | *(vacío)* | Inactivo — no hay termo instrumentado |

Validación en el flujo: la entidad existe, está disponible y su unidad es
compatible. Los errores se muestran por campo.

## 2. Opciones (`Configure`)

### Batería

| Opción | Default | Notas |
|---|---|---|
| `battery_usable_kwh` | 33.0 | Calibrado: ~33 kWh/100 % SOC en 7 días de stats reales |
| `soc_min_pct` | 30 | El suelo real del inversor es 35 %; 30 da margen bajo la reserva |
| `soc_max_pct` | 95 | Máximos reales observados 94-96 % |
| `reserve_soc_pct` | 35 | Reserva modo `backup`; coincide con el suelo real |
| `max_charge_w` | 4500 | Observado −4.06 kW pico horario (el límite teórico 5.3 kW no se alcanza) |
| `max_discharge_w` | 4000 | Observado +3.25 kW pico horario (teórico 6.3 kW no se alcanza) |
| `charge_efficiency` | 0.95 | |
| `discharge_efficiency` | 0.95 | |
| `degradation_eur_kwh` | 0.02 | Coste de ciclo estimado |

### Optimizador

| Opción | Default |
|---|---|
| `horizon_hours` | 24 |
| `step_minutes` | 60 |
| `optimize_interval_min` | 15 |
| `load_profile_quantile` | 0.70 | Cuantil del perfil horario de carga (P70 cubre picos de VE sin diluirlos) |
| `export_price_eur_kwh` | 0.14 (fallback si no hay serie horaria de vertido) |
| `price_fallback` | `conservative` |

### Precios InfluxDB (REE indicators)

Esquema real del bucket `ree_indicators` (verificado en Data Explorer):
`_measurement = electricity_price`, `_field = precio_kwh`,
tag `source = ree`, tag `tipo = consumo|excedentes`. La otra instancia
escribe los precios REE en este bucket; `ha-gts-solutions` **solo lee**
— la entrada `influxdb` de HA no debe exportar a este bucket
(configurar su exportación a otro bucket, p. ej. `homeassistant`).

| Opción | Default | Notas |
|---|---|---|
| `influx_prices_enabled` | `true` | Consulta el bucket vía la config entry `influxdb` instalada (reutiliza URL/token/org — sin duplicar credenciales). Si la consulta falla, fallback a PVPC. |
| `influx_bucket` | `ree_indicators` | Bucket de **lectura** de precios. Independiente del bucket de exportación configurado en la entrada influxdb de HA. |
| `influx_tag_key` | `tipo` | Tag que discrimina consumo/vertido dentro del mismo measurement. |
| `influx_import_measurement` / `influx_import_field` / `influx_import_tag` | `electricity_price` / `precio_kwh` / `consumo` | Serie de precio de consumo. |
| `influx_export_measurement` / `influx_export_field` / `influx_export_tag` | `electricity_price` / `precio_kwh` / `excedentes` | Serie de precio de vertido. |

Indicadores REE/ESIOS origen: **1001** = precio consumo,
**1739** = precio excedentes/vertido.

Las series usadas quedan visibles en los atributos de
`sensor.dsem_plan_next_action` (`import_series`/`export_series`,
`price_source`).

### Control

| Opción | Default | Efecto |
|---|---|---|
| `mode` | `shadow` | Modo inicial obligatorio |
| `enable_control` | `false` | Habilita modos ejecutores; sin él, `select.dsem_mode` rechaza `auto`/`economic`/`solar_priority`/`backup`/`target_soc` |
| `grid_charge_switch_entity` | `switch.deye_…_battery_grid_charging` | Interruptor que escribe el ejecutor (acción `charge_grid` → on; resto → off) |
| `pvpc_automation_entity` | `automation.pvpc_carga_bateria_deye_en_horas_baratas` | Automatización legada que comparte el interruptor; DSEM la pausa/restaura automáticamente |

#### Ejecutor v1 (`control.py`)

Con `enable_control` activo y un modo ejecutor, el coordinator traduce
la acción del slot actual a **una única escritura**: el interruptor
`battery_grid_charging` del Deye (permiso de carga desde red — el
inversor sigue decidiendo potencia y tiempos). No escribe nada más.

**Guardia zero-export** (`plan_meta.zero_export`): en el mismo ciclo
verifica que el inversor no pueda verter a la red — la vivienda no
tiene camino físico de exportación, así que el excedente FV debe ir a
la batería o curtarse. Si alguna entidad difiere, la corrige (una por
ciclo, mismo min-dwell):

| Entidad (prefijo del switch) | Objetivo |
|---|---|
| `select.<prefix>_work_mode` | `Zero Export To CT` |
| `switch.<prefix>_export_surplus` | `off` |
| `number.<prefix>_zero_export_power` | `20` (W de margen) |

Estados: `ze_ok`, `ze_written:<entity>`, `ze_unavailable`,
`ze_rate_limited`, `ze_backoff`, `ze_write_failed`.

**Guardia `off_grid`** (`plan_meta.offgrid`): verificado en vivo
(2026-11-16) que en este inversor `off_grid` es el **único** interruptor
que permite a la batería descargar para servir la carga — con él OFF la
batería queda idle y la red paga todo. Pero ON **bloquea la carga desde
red**, así que el ejecutor lo gestiona según el slot: **ON solo cuando
la acción es `discharge`**, OFF en cualquier otro caso. No escribe si
`binary_sensor.<prefix>_grid` indica red ausente (la automatización de
cortes es dueña del switch en isla), ni fuerza ON por debajo de
`OFFGRID_MIN_SOC_PCT` (12 %). Al salir de los modos ejecutores, un ON
puesto por DSEM se restaura a OFF. Estados: `og_ok:on|off`,
`og_written:on|off`, `og_rate_limited`, `og_unavailable`,
`og_grid_down`, `og_low_soc`, `og_backoff`, `og_unsafe_data`, …

Interlocks: plan disponible + snapshot completo sin entidades
missing/stale + gracia de 5 min tras arranque + mínimo 10 min entre
escrituras + verificación leyendo el estado + 3 fallos seguidos →
backoff 30 min + notificación persistente. El estado queda en
`plan_meta.control` (`control_ok:on`, `control_written:off`,
`control_backoff`, …) y se notifica una vez al activar.

**Conflicto gestionado automáticamente**: la opción
`pvpc_automation_entity` apunta a la automatización legada que también
escribe `battery_grid_charging`
(`automation.pvpc_carga_bateria_deye_en_horas_baratas`). Mientras haya
un modo ejecutor con `enable_control`, DSEM la desactiva sola y guarda
su estado previo; al volver a `shadow`/`manual`/`safe` (o al apagar
`enable_control`) la restaura. Si la entidad no existe, simplemente no
hace nada. El estado del ciclo queda en `plan_meta.control`
(`conflict_suspended` / `conflict_restored`).

### Programas TOU del inversor (time-of-use)

El Deye tiene 6 programas horarios que en cada ventana de 4 h definen
tres cosas: fuente de carga (`program_N_charging`:
`Disabled`/`Grid`/`Generator`/`Both`), **SOC objetivo**
(`program_N_soc`) y potencia (`program_N_power`). El inversor **deja de
cargar al alcanzar el SOC del programa activo** — un límite oculto que
puede hacer fracasar un `target_soc` aunque el switch esté ON (caso
real: programa de 17–21 h con SOC 70 % clavó la batería en 70 %).

**Recomendado**: para que el switch `battery_grid_charging` sea la
única superficie de control, poner los programas que puedan coincidir
con ventanas de carga a fuente `Both`/`Grid` y SOC objetivo alto
(100 % o el `soc_max` configurado).

DSEM **lee** los programas en cada ciclo (deriva los entity IDs del
prefijo del switch de carga desde red) y expone en `plan_meta`:

- `tou_status`: `ok` / `unavailable` / `error`
- `tou_now`: fuente de carga de la ventana actual (`grid`, `disabled`…)
- `tou_now_soc`: SOC objetivo del programa activo (si la entidad existe)
- `tou_grid_blocked_hours`: horas del horizonte donde el TOU no permite
  carga desde red

Es solo diagnóstico: el plan **no** se restringe por el TOU. Si el TOU
bloquea la ventana que el plan necesita, el síntoma es que el switch
está ON pero `battery_power` no muestra carga.

#### `switch.*_off_grid` — modo isla (verificado 2026-11-15)

⚠️ **`off_grid` ON bloquea la carga de batería desde red**: con él
activado el inversor prioriza batería→carga (grid exchange = 0) y
`battery_grid_charging` ON no produce carga. Comprobado en vivo:
al apagarlo, `battery_power` pasó de +2,2 kW a −5 kW y
`external_power` a +7,1 kW en ~2 min.

**Regla operativa**: `off_grid` debe estar **OFF** para cargar desde
red y **ON** para que la batería descargue a la carga (verificado:
`energy_pattern` y `work_mode` no gobiernan la descarga). En modos
ejecutores DSEM lo gestiona automáticamente según el plan (ver
guardia `off_grid` arriba); en `shadow`/`manual`/`safe` queda bajo
control manual. Para conservar backup en cortes reales, la automatización
de corte lo activa al detectar tensión <100 V.

### Modo `target_soc` — objetivo SOC programado

Cuando el modo es `target_soc`, el plan debe terminar la hora que
contiene `time.deye_smart_energy_manager_hora_objetivo` con un SOC
≥ `number.deye_smart_energy_manager_soc_objetivo` (%). El optimizador:

- Precarga en las horas más baratas antes del objetivo, cubriendo solo
  lo que la FV prevista no va a aportar (`soc_target_precharge`).
- **Carga forzada**: si las horas baratas (P25) no bastan, compra en las
  horas de precio medio/siguiente más barato antes de la hora límite —
  solo el déficit que las horas más baratas futuras no pueden cubrir
  (`soc_target_forced_charge`). El objetivo se alcanza aunque los
  precios no sean los mejores del día; `soc_target_not_reached` solo
  aparece cuando es físicamente inviable (capacidad/ventana).
- Mantiene un **suelo de trayectoria**: no permite descargas que dejen
  el SOC por debajo de lo necesario para alcanzar el objetivo
  (capacidad de carga garantizada restante por hora).
- Avisa con `soc_target_not_reached`, `soc_target_not_configured` o
  `soc_target_out_of_horizon` si el objetivo no es viable.
- En `shadow` solo calcula el plan; la ejecución requeriría
  `enable_control` igual que el resto de modos ejecutores.

Las dos entidades son propias de DSEM (number + time), restauran su
valor tras reinicio y son controlables desde cualquier tarjeta
(entities/number card) de Paneles, Inicio o el dashboard DSEM.

## 3. Vehículo eléctrico y ACS

- **Vehículo eléctrico (integrado, solo lectura):** cargador `dé EV
  Charger` vía `tuya_local`. DSEM lee `ev_state_entity` y
  `ev_charge_current_entity`; mientras el estado sea `charging`, el
  perfil de carga garantiza `max(perfil, base + corriente × 230 V)`
  durante las próximas 4 h (`load_source` queda `+ev_live`). Es una
  **estimación** — el cargador no expone sensor de potencia — y se
  reporta en `plan_meta.ev_power_w`. Los botones charge/stop del
  cargador **no se usan** mientras DSEM esté en SHADOW.
- **ACS/termo:** sin entidades `water_heater`/`climate` ni medida
  dedicada — pendiente.

La base de ~2 kW permanente (servidores) queda cubierta por el suelo
del perfil (`min(profile)`), no por el boost VE.

## 4. Entidades propias creadas

Ver `docs/ARCHITECTURE.md` §9. En el scaffold actual:
`sensor.dsem_*` (estado, estrategia, potencias normalizadas) y
`select.dsem_mode`.
