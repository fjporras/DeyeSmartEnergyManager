# ENTITY AUDIT — Deye Smart Energy Manager (DSEM)

**Instancia auditada:** Home Assistant GTS Solutions — `http://10.0.100.20:8123`
**Fecha de la auditoría:** 2026-10-18 (~17:40 Europe/Madrid)
**Método:** MCP `ha-gts-solutions` (ha-mcp 8.4.0) — solo consultas de lectura. Sin órdenes de control, sin cambios de configuración, sin reinicios.

---

## 1. Verificación de la instancia

| Parámetro | Valor verificado | Esperado | Estado |
|---|---|---|---|
| URL / base_url | `http://10.0.100.20:8123` | `http://10.0.100.20:8123` | ✅ coincide |
| Versión Core | `core-2026.8.3` | 2026.8.3 | ✅ coincide |
| Tipo de instalación | **Home Assistant Container** (docker, amd64, root) | Container | ✅ coincide |
| Python (dentro del contenedor) | 3.14.6 | — | ✅ |
| SO anfitrión | Linux 7.0.0-38-generic (Ubuntu/Proxmox VM, `ens18` 192.168.1.60) | Ubuntu | ✅ |
| Zona horaria | Europe/Madrid | — | ✅ |
| Nombre ubicación | "Casa" | — | — |
| Red | `wg0` (10.0.100.20/32) presente — acceso vía WireGuard | WireGuard | ✅ |
| Entidades totales | **297** en 21 dominios | — | — |
| Integraciones (config entries) | 19 | — | — |
| Dispositivos | 21 | — | — |
| Áreas | 6 (`salon`, `cocina`, `dormitorio`, `cuarto_instalaciones`, `garaje`, `oficina`) | — | — |
| Recorder | SQLite, ~1657 MB, run más antiguo 2026-10-06 | — | — |
| HACS | 2.0.5 (9 repos descargados: solarman, scheduler, Bermuda, apexcharts, mushroom, PVPC card, BMS Connector…​) | — | ✅ |

**Nota sobre históricos:** la retención de historia cruda es ~10 días (estándar recorder). Las **estadísticas de largo plazo** existen desde ≈ **agosto 2026** (~2,5 meses) — verificable con `total_load_consumption` mensual. Suficiente para perfiles iniciales, pero escaso para estacionalidad anual.

## 2. Capacidades del MCP `ha-gts-solutions` (verificadas)

| Capacidad | Herramienta | Verificado |
|---|---|---|
| Listar/inspeccionar entidades | `ha_search`, `ha_get_entity` | ✅ |
| Estados y atributos | `ha_get_state` (batch ≤100) | ✅ |
| Historial crudo y estadísticas | `ha_get_history` (`history`/`statistics`) | ✅ |
| Dispositivos e integraciones | `ha_get_device`, `ha_get_integration` | ✅ |
| Servicios disponibles | `ha_list_services` | ✅ |
| Automatizaciones (config) | `ha_config_get_automation` | ✅ |
| Plantillas Jinja (lectura derivada) | `ha_eval_template` | ✅ |
| Previsión meteorológica | `ha_call_service weather.get_forecasts` | ✅ (lectura) |
| Energy Dashboard prefs | `ha_manage_energy_prefs mode=get` | ✅ — **nunca configurado** (vacío) |
| System health / overview | `ha_get_system_health`, `ha_get_overview` | ✅ |
| Ejecutar servicios / escribir entidades | `ha_call_service`, `ha_set_entity`, `ha_config_set_*` | ⚠️ Disponibles pero **NO usados** en la auditoría (prohibido en esta fase) |
| Reinicio / gestión apps / backups | `ha_restart`, `ha_manage_app`, `ha_manage_backup` | ⚠️ Disponibles, no usados |
| Acceso a archivos (`/config`, `custom_components`, YAML) | — | ❌ **No disponible.** El MCP no expone filesystem. El despliegue requerirá SSH/otro mecanismo (pendiente determinar) |
| Logs | `ha_get_logs` | disponible (no usado) |

**Limitación MCP crítica:** no se puede instalar ni copiar código a `/config/custom_components/` mediante el MCP. Se documenta como bloqueo para la fase de despliegue; el repositorio se desarrollará en este workspace y se transferirá por SSH/manualmente.

---

## 3. Integraciones energéticas instaladas

| Integración | Entrada | Dispositivos | Uso en DSEM |
|---|---|---|---|
| `solarman` (ha-solarman, davidrapan) | `Deye-SUN-15K-SG05LP3-EU-SM2` — 192.168.1.7:8899, perfil **`deye_p3.yaml`**, mppt=2, phase=3, poll ≈ 5,4 s | Deye SUN-15K | Fuente principal: inversor + batería |
| `fronius` (core) | `SolarNet Datalogger at 192.168.1.3` | FroniusSolarNet (datamanager 3.34.1-5), Symo 8.2-3-M, Smart Meter 63A | Fuente FV secundaria + medida de rama |
| `pvpc_hourly_pricing` | `PVPC - 2.0TD`, potencia contratada 9800 W, sin API token | ESIOS | Precio de compra PVPC |
| `template` | "Autoconsumo total", "Autonomía total" | — | Sensores derivados existentes |
| `met` | Home (Fuengirola) | Forecast | Previsión meteorológica (proxy solar) |
| `scheduler` (nielsfaber 3.3.8) | Scheduler | — | Planificación auxiliar (sin usar aún) |
| `mobile_app` | CASA-GOMEZ | Móvil HONOR REA-NX9 | ⚠️ **No es un VE** — es un teléfono |
| Otras | sun, nmap_tracker, ipp, google_translate, hacs, backup, shopping_list, radio_browser, local_ip, analytics, go2rtc | — | No relevantes |

**No presentes:** MQTT, InfluxDB, Node-RED (no integrados en HA aunque puedan existir en la red), Solcast/Forecast.Solar, cargador VE, termo/ACS.

## 4. Topología eléctrica deducida (VERIFICADA con datos)

```
RED ELÉCTRICA ─────────────┬───────────────────────────────────────┐
                           │                                       │
                    [Fronius Smart Meter]                   CTs del Deye
                    rama ~2,2 kW constante          (grid port + CTs externos,
                    (monofásicas asimétricas)        ~equilibrado trifásico)
                           │                                       │
                    Cargas "directas"                      ┌────────┴────────┐
                    (~2-2,7 kW típico)                     │  DEYE 15K 3ph   │
                                                           │ GRID ── LOAD*   │
                                                           │ GEN ◄── FRONIUS │  ← Symo 8.2-3-M
                                                           │  (Microinverter)│    AC-coupled
                                                           │ BAT ── SEPLOS   │  ~32 kWh nom.
                                                           │ MPPT1/MPPT2 = 0 │  sin strings DC
                                                           └─────────────────┘
```

**Evidencia:**

1. **Fronius en puerto GEN (acoplamiento AC):** `select.deye_…_io_mode` = `Microinverter`; `microinverter_power` = 3220 W ≈ `froniussymo alimentacion_ca` = 3305 W; `microinverter_energy` == `total_production` del Deye (idénticos en estadística diaria); `pv1_power`/`pv2_power` = 0 siempre; PV1/PV2 voltage ≈ 0-2 V → **sin strings DC en el Deye**.
2. **El Smart Meter NO cubre la rama del Deye:** con batería descargando 2,3-2,9 kW y `grid_power`≈0 (23-01h), el meter sigue ~2,2 kW; con `grid_power`=8,9 kW (20h), el meter sigue ~2,3 kW. Además su reparto por fases (608/16/1690 W) es asimétrico frente al trifásico simétrico del Deye.
3. **Autodeclarado:** `froniussmart_meter_63a_descripcion_de_la_ubicacion_del_contador` = `feed_in`, pero los datos demuestran que no mide el feed-in completo — mide una **rama de cargas directas** no respaldadas por el Deye (o el Deye conecta aguas arriba del meter). ⚠️ **Verificación física pendiente** (posición real de pinzas/CTs y relación con el contador fiscal de la distribuidora).
4. **Balance instantáneo del subsistema Deye (17:36):** entrada = grid 8548 W + microinv 3220 W; salida = load 9053 W (UPS) + batería cargando 2532 W + pérdidas 171 W → ≈ 11770 ≈ 11756 W. **Cierra** (<0,2% error).
5. **Signos:** `battery_power` **negativo = cargando**, positivo = descargando (verificado con `battery_state` y descarga nocturna). `grid_power` positivo = import (estadísticas horarias muestran valores ~0/-104 W durante descarga; `today_energy_export` solo 0,2 kWh/día → el inversor opera en *Zero Export To CT* casi sin exportar).
6. **Contadores diarios (sum estadísticas, kWh):** Deye import ~25-47/día; Deye load ~55-91/día; meter consumida ~53-88 kWh/día; FV ~33-49 kWh/día; batería carga ~7-11, descarga ~3-18 kWh/día.

### Lectura de referencia (snapshot 18-oct ~17:36 Madrid)

| Magnitud | Valor |
|---|---|
| PV Deye (MPPT1+2) | 0 W (sin strings) |
| Fronius Symo AC | 3305 W / 28,1 kWh hoy |
| Deye microinverter (GEN) | 3220 W / 27,4 kWh hoy |
| Batería | SOC 66 %, cargando −2532 W (−47 A @ 53,8 V), SOH 99,92 % |
| Deye grid port | +8548 W importación |
| Deye load (UPS) | 9053 W |
| Smart Meter (rama) | +2317 W |
| Inversor | Normal, relay `Inv-Grid-Gen`, alarmas OK, 53,8 °C |
| PVPC actual (P3) | 0,05338 €/kWh (mín hoy 0,0468 @14h, máx 0,259 @20h) |

---

## 5. Inventario de entidades

Prefijo común Deye: `*.deye_sun_15k_sg05lp3_eu_sm2_*` (algunas con prefijo de área `garaje_`). Prefijo Fronius: `sensor.fronius*`, `sensor.cuarto_instalaciones_fr*`, `sensor.smart_meter_63a_*`.

### 5.1. DEYE — Lectura (función DSEM)

| entity_id (sufijo) | Estado | Unidad | Función DSEM |
|---|---|---|---|
| `sensor.…_pv_power` (+pv1/pv2 power, voltage, current) | 0 | W/V/A | FV DC del Deye — **inactiva** (sin strings) |
| `sensor.garaje_…_microinverter_power` (+l1/l2/l3, voltajes) | 3220 | W | **Producción FV real (Fronius por GEN)** |
| `sensor.garaje_…_microinverter_energy(_today)` | 27,4 hoy | kWh | Energía FV diaria/total |
| `sensor.…_battery` | 66 | % | **SOC batería** (attrs BMS: voltaje, corriente, límites 200 A, `Corrected Capacity` 439 Ah) |
| `sensor.…_battery_power` | −2532 | W | **Potencia batería** (− carga / + descarga) |
| `sensor.…_battery_voltage` / `_current` / `_temperature` / `_state` / `_soh` / `_capacity` | 54,0 V / −47 A / 30,2 °C / charging / 99,9 % / 36,1 kWh | — | Estado batería; `battery_capacity` = estimación dinámica kWh |
| `sensor.…_grid_power` (+l1/l2/l3) | 8548 | W | **Potencia puerto GRID** (CT externos) |
| `sensor.…_internal_power` / `internal_ct1..3` | 8532 | W | Medida interna puerto grid |
| `sensor.…_external_power` / `external_ct1..3` | 8548 | W | CTs externos (zero-export) |
| `sensor.…_load_power` (+l1/l2/l3) | 8976 | W | **Consumo puerto LOAD/backup** |
| `sensor.…_load_ups_power` (+l1/l2/l3) | 9053 | W | Potencia salida UPS |
| `sensor.…_output_l1..3_power`, `sensor.…_power` | −116…/−2699 | W | Potencia salida inversor (conv. −) |
| `sensor.…_today_production` / `_total_production` | 27,4 | kWh | Producción diaria/total (incluye microinverter) |
| `sensor.…_today_energy_import` / `total_energy_import` | 45,8 | kWh | Importación diaria/total (rama Deye) |
| `sensor.…_today_energy_export` / `total_energy_export` | 0,2 | kWh | Exportación diaria/total |
| `sensor.…_today_load_consumption` / `total_load_consumption` | 61,4 | kWh | Consumo diario/total |
| `sensor.…_today_battery_charge/discharge` (+total) | 10,2 / 0,1 | kWh | Energía batería |
| `sensor.…_today_losses` / `_total_losses`, `_power_losses` | 1,5 / 171 W | kWh/W | Pérdidas inversor |
| `sensor.…_grid_l1..3_voltage`, `_grid_frequency` | — | V/Hz | Calidad red |
| `sensor.…_device_state` / `_device_alarm` / `_device_fault` / `_device_relay` | Normal/OK/OK/Inv-Grid-Gen | enum | Estado/errores |
| `binary_sensor.…_connection`, `_battery_alarm`, `_battery_fault`, `_grid` | on/off/off/on | — | Conectividad/alarmas |
| `sensor.…_temperature`, `_dc_temperature` | 53,8 / 25 (stale) | °C | Temperaturas |
| `sensor.…_update_interval` | 5,4 | s | Diagnóstico polling |
| `sensor.…_today_battery_life_cycles` / `_total_battery_life_cycles` | — | — | Ciclos (degradación) |
| `datetime.…_date_time` | — | — | Reloj inversor |

### 5.2. DEYE — Control (entidades escribibles; **capacidad de escritura NO probada** — solo lectura en auditoría)

| entity_id (sufijo) | Valor actual | Rango/opciones | Función DSEM prevista |
|---|---|---|---|
| `switch.…_battery_grid_charging` | **on** | on/off | Permitir carga de red (ya lo usa la automatización PVPC) |
| `switch.…_battery_generator_charging` | off | on/off | Carga desde generador — N/A |
| `switch.…_export_surplus` | off | on/off | Exportar excedentes |
| `switch.…_grid_peak_shaving` | on | on/off | Peak shaving (límite importación) |
| `switch.…_off_grid` | off | on/off | Modo isla |
| `switch.garaje_…_microinverter` | on | on/off | Habilitar entrada GEN/microinverter |
| `switch.…_microinverter_export_cut_off` | off | on/off | Cortar export del microinverter |
| `switch.…_export_asymmetry` | on | on/off | Exportación asimétrica por fases |
| `switch.…_battery_wake_up` / `_mppt_multi_point_scanning` | off | on/off | Utilidades |
| `switch.…_` (principal inversor) | on | on/off | ⚠️ Encendido inversor — **excluir de DSEM** |
| `select.…_work_mode` | `Zero Export To CT` | Export First / Zero Export To Load / Zero Export To CT | Modo de trabajo |
| `select.…_energy_pattern` | `Load First` | Battery First / Load First | Prioridad energía |
| `select.…_time_of_use` | `Enabled` | Disabled/Enabled/días… | **TOU activo** — clave para programación |
| `select.…_program_1..6_charging` | 1-3 `Disabled`, 4-6 `Grid` | Disabled/Grid/Generator/Both | Fuente de carga por franja TOU |
| `select.…_charging_signal` | `Normal` | Normal/Grid/Generator/Both | — |
| `select.…_battery_operation_mode` | `Capacity` | Voltage/Capacity/No Battery | Modo control batería (SOC) |
| `select.…_battery_control_mode` | `Lithium` | Lead/Lithium | — |
| `select.…_io_mode` | `Microinverter` | Generator/SmartLoad/Microinverter | **No tocar** (Fronius en GEN) |
| `select.…_ac_coupling` | `Disabled` | Disabled/Grid/Load | — |
| `select.…_battery_bms_type` | `PYLON` | lista BMS | SEPLOS vía protocolo PYLON |
| `select.…_grid_voltage` / `_grid_frequency` | 230/398 V, 50 Hz | — | Config red — no tocar |
| `number.…_battery_max_charging_current` | 100 | 0-350 A | **Límite carga batería** (~5,3 kW @53 V) |
| `number.…_battery_max_discharging_current` | 120 | 0-350 A | **Límite descarga** (~6,4 kW) |
| `number.…_battery_grid_charging_current` | 50 | 0-350 A | **Corriente carga desde red** (~2,7 kW) |
| `number.…_battery_generator_charging_current` | 40 | 0-240 A | — |
| `number.…_program_1..6_power` | 15000 ×6 | 0-32000 W | **Potencia TOU por franja** |
| `number.…_program_1..6_soc` | 30/30/100/100/70/30 | 0-100 % | **SOC objetivo TOU por franja** |
| `number.…_program_1..6_voltage` | 49 ×6 | 0-61 V | Voltaje objetivo TOU |
| `time.…_program_1..6_time` | 01:00/05:00/09:00/13:00/17:00/21:00 | hh:mm | **Inicio franjas TOU** |
| `number.…_grid_max_import_power` | 9200 | 0-80000 W | Límite importación (~contratado 9,8 kW) |
| `number.…_grid_max_export_power` | 15000 | 0-80000 W | Límite exportación |
| `number.…_grid_peak_shaving` / `_generator_peak_shaving` | 9000 / 9000 | W | Peak shaving |
| `number.…_export_surplus_power` | 15000 | 0-24000 W | — |
| `number.…_zero_export_power` | 20 | −20-500 W | Margen zero-export |
| `number.…_pv_power` | 16500 | 0-32000 W | Potencia FV máxima declarada |
| `number.…_battery_capacity` | 628 | 0-2000 Ah | Capacidad configurada (≈32 kWh @51 V) |
| `number.…_battery_shutdown_soc/_restart_soc/_low_soc` | 15/50/35 | % | Límites SOC (protección — **no modificar por DSEM**, usar como约束) |
| `number.…_battery_shutdown_voltage/_restart_voltage/_low_voltage/_empty` | 46/52/47,5/45 | V | Protecciones tensión |
| `number.…_battery_equalization(_cycle/_time)`, `_absorption`, `_float`, `_charging_efficiency`, `_temperature_compensation`, `_resistance` | varios | — | Parámetros carga — no tocar |
| `number.…_smartload_*`, `_generator_*`, `_grid_voltage/frequency_protection_*`, `_grid_reconnection_time` | varios | — | Protecciones / generador — **no tocar** |
| `button.…_restart` | unavailable | — | No usar |
| `sensor.…_battery_grid_charging_start(_voltage)` | 20 % / 51,6 V | — | Arranque carga red |

> ⚠️ **Criterio de control DSEM:** usar únicamente `number`, `select`, `switch`, `time` — escritura vía servicios estándar de HA. Los servicios `solarman.write_*` (Modbus crudo) quedan **prohibidos** por riesgo y por la especificación del proyecto. Toda escritura pasa por la capa de validación de DSEM y está vetada en SHADOW.

### 5.3. FRONIUS — Lectura (sin entidades de control)

| entity_id | Estado | Unidad | Función DSEM |
|---|---|---|---|
| `sensor.cuarto_instalaciones_froniussymo_8_2_3_m_1_alimentacion_ca` | 3305 | W | **Potencia FV Fronius (referencia)** |
| `sensor.froniussymo_8_2_3_m_1_energia_al_dia` / `_ano` / `_total` | 28103 Wh | Wh | Energía FV |
| `sensor.froniussymo_8_2_3_m_1_corriente_alterna/continua`, `_tension_de_cc`, `cuarto_…_corriente_alterna` | — | A/V | Diagnóstico |
| `sensor.froniussymo_8_2_3_m_1_mensaje_de_estado` / `_error` | running / no_error | enum | Estado/errores |
| `sensor.froniussmart_meter_63a_potencia_real` (+fase 1/2/3) | 2317 (608/16/1690) | W | **Potencia rama no-Deye** |
| `sensor.froniussmart_meter_63a_energia_real_consumida` / `_producida` | 72,7 / 33,96 MWh | Wh | Contadores rama |
| `sensor.froniussmart_meter_63a_factor_de_potencia`, `_promedio_de_frecuencia_de_fase` | 0,94 | —/Hz | Calidad |
| `sensor.froniussmart_meter_63a_ubicacion_del_medidor` / `_descripcion…` | 0 / feed_in | enum | Ubicación declarada |
| `sensor.froniussolarnet_importacion/exportacion_de_la_red_electrica` | 2319/0 | W | Vista SolarNet del meter |
| `sensor.froniussolarnet_carga_de_energia_consumida` | 5637 | W | Consumo de la rama (PV+import) |
| `sensor.cuarto_instalaciones_froniussolarnet_energia_fotovoltaica` | 3318 | W | FV vista SolarNet |
| `sensor.froniussolarnet_autonomia/autoconsumo_relativo`, `_factor_co2`, `_modo_medidor`, `_tarifa_importacion (0,25 €)/_exportacion (0,14 €)` | — | — | Ratios y tarifas estáticas configuradas en SolarNet |

### 5.4. PRECIOS

| entity_id | Valor | Detalle |
|---|---|---|
| `sensor.esios_pvpc` | 0,05338 €/kWh | **PVPC 2.0TD.** Atributos `price_00h`…`price_23h` (precio del día, €/kWh), `period`/`next_period`, `min/max_price(+_at)`, `price_position`, `available_power` 9800 W. Mañana se publica ~20:35 (aún no disponible a las 17:40). Es el **precio regulado completo** (incluye peajes/cargos del PVPC), no solo OMIE. |
| Precio de exportación | — | ❌ **No existe sensor** de compensación por excedentes. `froniussolarnet_tarifa_exportacion`=0,14 €/kWh es un valor estático configurado en SolarNet (no contractual verificado). DSEM necesitará parámetro configurable. |

### 5.5. VEHÍCULO ELÉCTRICO — ❌ NO DISPONIBLE

No hay cargador ni entidades de VE. `sensor.casa_gomez_*` (`battery_level` 12 %, `battery_state` charging, `charger_type`) pertenecen al **móvil HONOR REA-NX9** (mobile_app). `device_tracker.casa_gomez` = teléfono.
→ El módulo VE de DSEM quedará **opcional/deshabilitado** hasta que exista integración real. El optimizador debe funcionar sin él.

### 5.6. TERMO / ACS — ❌ NO DISPONIBLE

Sin dominios `water_heater`, `climate`, ni sensores dedicados. El pico vespertino ~9 kW trifásico en el puerto LOAD podría incluir un termo o similar, pero **no hay medida ni control individuales**.
→ Módulo ACS deshabilitado; se podría recomendar un medidor/enchufe con medida (p. ej. Shelly) o integración del termo como requisito previo.

### 5.7. Otros relevantes

| entity_id | Valor | Nota |
|---|---|---|
| `sensor.autoconsumo_total` (template) | 82668,8 kWh | `fronius_energia_total/1000 − deye_total_energy_export` |
| `sensor.autonomia_total` (template) | 14,39 % | `1 − import/consumo` (totales Deye) |
| `weather.forecast_home` (met.no) | partlycloudy | Forecast horario vía `weather.get_forecasts` (cloud_coverage, uv_index, condition, precipitation) — proxy de previsión FV |
| `sun.sun` | above_horizon | Amanecer/atardecer |
| `input_select.rango_grafica_energia` | 24h | UI auxiliar existente |
| `device_tracker.*` | — | nmap (impresora, cámaras) — sin uso |

### 5.8. Automatizaciones existentes (¡conflicto potencial!)

| Automación | Función | Riesgo con DSEM |
|---|---|---|
| `automation.pvpc_carga_bateria_deye_en_horas_baratas` | ON/OFF de `switch.…_battery_grid_charging` en las **4 h PVPC más baratas** (trigger cada hora + en update del sensor) | **Alto** — pisa las decisiones del optimizador. En modo AUTO habrá que desactivarla (con autorización del usuario) o reimplementarla como parte de DSEM. En SHADOW convive sin problema. |
| `automation.pvpc_aviso_hora_barata` | Notificación hora barata | Informativa, sin conflicto |
| `automation.pvpc_resumen_diario_de_precios` | Resumen diario | Informativa, sin conflicto |
| `automation.pvpc_umbral_de_precio` | Notificación <0,05 / >0,20 €/kWh | Informativa, sin conflicto |

### 5.9. Entidades no disponibles (estado `unavailable`/`unknown`)

`sensor.…_load_consumption_power` + l1/l2/l3 (restored), `sensor.…_generator_*` (7 entidades — sin generador físico), `sensor.…_grid_power_factor`, `sensor.…_total_losses` (unknown), `number.…_generator_min_pv_power`, `number.…_grid_reconnection_time`, `select.…_cloud`, `select.…_mode`, `switch.…_access_point`, `switch.…_generator(_on_grid)`, `binary_sensor.…_generator`, `button.…_restart`, `number.garaje_…_grid_power_factor` (unknown).
→ Todas relacionadas con hardware ausente (generador) o registros no soportados. Sin impacto en DSEM salvo `load_consumption_*` (consumo "load" directo) — se usa `load_power`/`load_ups_power` en su lugar.

---

## 6. Huecos y riesgos detectados

| # | Hallazgo | Impacto en DSEM | Acción propuesta |
|---|---|---|---|
| 1 | **VE inexistente** | Función VE deshabilitada | Diseño opcional; integrar cargador/VE antes de activar |
| 2 | **Termo/ACS inexistente** | Función ACS deshabilitada | Igual; evaluar medidor dedicado |
| 3 | **Cobertura del Smart Meter ambigua** | El meter no cubre la rama Deye; la facturación real depende del contador fiscal (no visible). Modelo de balance debe usar CTs del Deye + meter por separado | Verificación física de pinzas y del esquema unifilar; validar contra factura |
| 4 | **Sin previsión solar dedicada** | Precisión limitada | Usar met.no (cloud/uv) + histórico; recomendar Solcast o Forecast.Solar (HACS) |
| 5 | **Historia cruda ~10 días; estadísticas ~2,5 meses** | Perfiles estacionales débiles | Acumular estadísticas; valorar InfluxDB si tiene histórico largo (acceso no verificable por MCP) |
| 6 | **Capacidad útil batería incierta** | Nominal config 628 Ah; BMS "Corrected Capacity" 439 Ah; estimador solarman 36,1 kWh | Validar empíricamente; hacerlo parámetro configurable |
| 7 | **Automatización PVPC de carga ya controla `battery_grid_charging`** | Conflicto de actuadores en AUTO | Coordinar/desactivar en fase de activación (con autorización) |
| 8 | **Sin sensor de precio de exportación** | Compensación no modelable desde HA | Parámetro configurable en DSEM (o integración adicional p. ej. esios compensación) |
| 9 | **Energy Dashboard nunca configurado** | — | Opcionalmente aprovechar DSEM para definir fuentes |
| 10 | Escritura Modbus por entidades number/select/switch/time | Desgaste EEPROM del logger/inversor si se escribe cada ciclo | Rate-limiting, escritura solo al cambiar decisión, min-dwell |
| 11 | MCP sin acceso a filesystem ni a `/config` | Despliegue manual/SSH | Definir procedimiento de despliegue con el usuario |
| 12 | `pv_power`/`dc_temperature`/`pv1..` reportan valores "stale" sin cambio | Diferenciar 0 real vs no reportado | Usar `last_reported`/`last_updated` en normalización |
| 13 | Sensores `load_consumption_*` unavailable | — | Usar `load_power` (puerto) como consumo medido |
| 14 | Precios PVPC solo "hoy" hasta ~20:35 | Horizonte nocturno sin precios del día siguiente hasta publicación | Estrategia conservadora configurable; recalcular al publicarse |

## 7. Modelo energético propuesto (a partir de entidades reales)

- **PV(t)** = `garaje_…_microinverter_power` (≈ Fronius AC; validar contra `froniussymo alimentacion_ca`). PV DC del Deye = 0.
- **GridDeye(t)** = `…_external_power` (CTs externos; alternativa `grid_power`/`internal_power`) — conv. + import.
- **GridBranch(t)** = `froniussmart_meter_63a_potencia_real` — rama no respaldada (fuera del balance del Deye; sumar al consumo total de la vivienda).
- **Load(t)** = `…_load_ups_power` (o `load_power`) — consumo del puerto backup.
- **Bat(t)** = `…_battery_power` (− carga, + descarga); SOC = `…_battery`.
- **Balance Deye:** `PV + GridDeye + Bat_dis ≈ Load + Bat_chg + Losses` — verificado ≈0,2 % error.
- **Consumo vivienda total** = Load + consumo rama meter (`froniussolarnet_carga_de_energia_consumida`), pendiente confirmar que no haya solape.
- **Energía:** contadores `total/today_*` (`total_increasing`) + estadísticas largo plazo para perfiles.
- **Precio compra:** `sensor.esios_pvpc` (+attrs `price_XXh`). **Precio exportación:** parámetro configurable.
- **Control futuro (solo AUTO, tras habilitación explícita):** TOU — `time_of_use`, `program_N_time/power/soc/charging`, `battery_grid_charging`, `battery_grid_charging_current`, `battery_max_charging/discharging_current`, `grid_max_import/export_power`, `work_mode`, `energy_pattern`.

## 8. Arquitectura propuesta de la integración

```
deye_smart_energy_manager/
├── config_flow.py        # Selector de entidades reales (selects con entity picker) + options flow
├── coordinator.py        # DataUpdateCoordinator: polling lectura entidades, ciclo optimización
├── model.py              # Normalización: signos, unidades, disponibilidad, antigüedad
├── forecast.py           # Perfiles consumo (statistics) + FV (histórico + met.no/solcast opcional)
├── prices.py             # PVPC sensor + precio exportación configurable + fallback conservador
├── optimizer.py          # LP/MILP (HiGHS vía scipy.optimize.linprog / highs — decisión documentada en fase 7)
├── planner_battery.py    # Traduce plan → franjas TOU/program SOC/power
├── planner_ev.py         # Inactivo hasta existir entidades VE
├── planner_acs.py        # Inactivo hasta existir termo
├── control.py            # Capa de validación + ejecución (vetada en SHADOW)
├── sensor.py/select.py/switch.py/number.py  # Entidades DSEM (estado, plan, modo)
├── diagnostics.py
└── const.py, manifest.json, strings.json, translations/(es,en), services.yaml
```

**Decisiones clave:**
- Modo inicial **SHADOW** (constante por defecto; AUTO requiere `enable_control` explícito en options + no persistente tras reinstalación limpia).
- Sin dependencias de comunicación propias: lee entidades HA y escribe solo en entidades solarman estándar.
- Optimizador LP horario 24-48 h; recálculo por tiempo + triggers (cambio PVPC, SOC anómalo, dispositivo offline).
- Sin acceso a `/config` desde MCP: desarrollo en este repo; despliegue manual documentado en `DEPLOYMENT.md`.

---

*Generado por auditoría MCP de solo lectura. Ninguna entidad fue escrita ni ningún servicio de control ejecutado (excepto `weather.get_forecasts`, consulta de solo lectura).*
