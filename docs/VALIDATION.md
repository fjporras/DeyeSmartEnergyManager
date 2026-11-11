# Validación SHADOW — datos reales vs modelo de previsión

Periodo analizado: **2026-11-05 → 2026-11-11** (7 días completos,
statistics horarias de Recorder + histórico de Forecast.Solar).
Fuentes reales: `load_ups_power`, `microinverter_power`,
`external_power`, `battery`, `battery_power`, `esios_pvpc`.

## 1. Previsión FV (Forecast.Solar)

| Día | Real (kWh) | FS pre-amanecer | Error |
|---|---|---|---|
| 11-05 | 41.5 | 31.3 | −25 % |
| 11-06 | 41.4 | 40.4 | −2 % |
| 11-07 | 36.7 | 28.3 | −23 % |
| 11-08 | 15.0 | 10.6 | −29 % |
| 11-09 | 4.9 | 10.6 | **+115 %** |
| 11-10 | 32.9 | 15.1 | −54 % |
| 11-11 | 5.0* | 10.4 | **+107 %** |

MAE diario ≈ **40-45 %**. Patrones:
- Sobreestima días muy nublados (>2× el real el 11-09/11-11).
- Subestima días soleados variables (−23…−54 %).
- `energy_production_today` se actualiza cada ~2 h e incorpora
  producción ya realizada — el valor usable como *previsión* es el
  pre-amanecer; intradía se autocorrige solo.

Perfil horario real (días >25 kWh): arranque ~6 h, meseta 10-14 h
(~5.4-6.2 kW), cero a las 18 h. La campana σ=3 centrada en el pico es
razonable en forma; el problema es la **escala** (total diario), no la
forma.

## 2. Perfil de consumo

kWh/día reales: 54.4–63.6 (**~57 kWh/día**). Rasgo dominante: carga
base nocturna de **~2.0-2.1 kW permanentes** (~49 kWh/día solo de base).
Por hora del día (media / p90 / max):

- Noche (00-06 h): media 2040-2130, p90 ≈ max → base estable.
- Mañana (07-13 h): 2260-2780, max hasta 3438.
- **Tarde/noche (14-21 h)**: media 2240-2750 pero p90 2700-3200 y
  picos aislados de **4463 (14 h), 3607 (15 h), 3609 (18 h), 3248 (21 h)**
  — cargas intermitentes grandes (¿VE? ¿ACS? ¿clima?).
- El sesgo observado en SHADOW ("subestima el pico vespertino") se
  confirma: en días con esos picos la media histórica queda ~1-1.7 kW
  por debajo del real.

## 3. Red / exportación

- **Cero horas con exportación >50 W** en 7 días — la batería + la
  carga base absorben todo el excedente FV. La serie de vertido de
  InfluxDB es hoy casi irrelevante para el coste (mantenerla, pero su
  impacto real ≈ 0).
- Importación neta diaria: **19.5–61.3 kWh**, inversamente correlada
  con la FV → el ahorro potencial del optimizador es muy sensible al
  error de previsión FV.

## 4. Batería (calibrado empírico)

- **Capacidad útil estimada: ~33 kWh/100 % SOC** (6 días con ciclos
  medibles → 29.5-33.3, mediana 33.1). El provisional de 30 kWh
  subestima ~10 %.
- **SOC mínimo real = 35 % exactamente, todos los días** — el inversor
  mantiene 35 % por su propia configuración. El `soc_min_pct=20` del
  modelo nunca se usa en la realidad → la trayectoria de SOC del plan
  diverge (el plan cree que puede descargar hasta 20 %).
- Máximos reales 94-96 % en días soleados → `soc_max_pct=95` correcto.
- Carga máxima media horaria observada ~4.0-4.1 kW < `max_charge_w`
  5.3 kW asumido → verificar límite real del inversor (posible
  limitación por corriente de batería, ~80 A×51 V).

## 5. Precios

PVPC medio por hora: valle nocturno ~0.169-0.19 (3-5 h), pico
**0.32-0.33 en 18-21 h**, repunte 0.28-0.30 en 6-8 h y 14 h valle
(0.157). Spread arbitraje noche→tarde ~0.15 €/kWh, claramente por
encima del umbral de eficiencias+degradación (~0.21) en horas valle —
el arbitraje carga-nocturna/descarga-tarde es rentable, como hace el
plan.

## 6. Ajustes propuestos al algoritmo

Prioridad por impacto:

1. **Corrección de sesgo FV (alto impacto, fácil)**: factor de sesgo
   móvil — mediana 3 días del ratio `real/fsolar`, acotado [0.5, 1.5],
   aplicado al total diario antes de sintetizar la campana. MAE esperada
   −40 % → ~25-30 %.
2. **Perfil de carga por cuantil + nowcast (alto impacto, medio)**:
   a. Usar **P65-75 por hora** en vez de media → cubre los picos
      intermitentes de tarde sin sobreestimar la noche.
   b. Corrección de corto plazo: residual medio de las últimas 2-3 h
      observadas persistiendo con decaimiento a las siguientes 3-6 h.
3. **Calibración batería (fácil)**:
   a. `battery_usable_kwh`: 30 → **33** (validado empíricamente).
   b. `soc_min_pct`: alinear con el suelo real del inversor (**30-35**)
      — el plan no debe asumir energía disponible por debajo de lo que
      el sistema real permite.
   c. `max_charge_w`: verificar contra el límite real (~4 kW observado).
4. **Margen de reserva en horas caras**: con `soc_min` real≈35 y
   `reserve`=35, el plan agota hasta la reserva — correcto, pero el
   heurístico debería mantener un pequeño buffer (~2-3 ptos) para no
   planear hasta el límite exacto (deriva SOC).
5. **Persistencia de predicciones para validación continua**:
   registrar el plan (o su snapshot de entrada) con timestamp para
   comparar automáticamente previsto vs real a T+24 h — hoy el plan
   solo vive en atributos; un historial propio mediría el error de plan
   completo, no solo de series.
6. **Día-tipo (media)** — laborable/festivo: solo 7 días; con más
   historial, separar perfil por `weekday` mejoraría lunes/laborables
   vs fin de semana (11-08/09, fin de semana, tuvieron consumo 56-63
   kWh también — la base domina y quizá baste con P-quantiles).
7. **Export**: sin cambios funcionales (no hay exportación real hoy);
   mantener la serie por si aparece VE/ACS.

### Datos confirmados por el usuario

- Los picos de 14-21 h son **carga del VE** — integrado vía
  `tuya_local` (`dé EV Charger`): `sensor.de_ev_charger_estado`,
  `number.de_ev_charger_charge_current`, `number.de_ev_charger_maximum_current`,
  `text.de_ev_charger_charge_mode` (horario ss/se). No hay sensor de
  potencia → estimación `A x 230 V` solo en estado `charging`.
- La base ~2 kW permanente son **servidores** — modelada como suelo
  del perfil (`min(profile)`), no como anomalía.
- Límite de carga del inversor (~4 kW observado): pendiente de
  confirmar si es configuración Deye o límite BMS.

## 7. Ajustes implementados (commit posterior a la validación)

| Ajuste | Implementación |
|---|---|
| Sesgo FV | `pv_bias()` compara la energía real del día (stats del
sensor de potencia FV) con la fracción de campana ya transcurrida;
acotado [0.5, 1.5], aplicado al total diario restante y mañana. |
| Carga | P70 por hora (`load_profile_quantile` configurable
0.5-0.95), nowcast = residual de las últimas 3 h con decaimiento
0.6^i durante 6 h, y boost VE `max(perfil, base + P_EV)` durante
4 h si el cargador reporta `charging`. |
| Batería | `usable_kwh` 30→**33**, `soc_min` 20→**30**, `max_charge`
5300→**4500**, `max_discharge` 6300→**4000** (medias horarias
reales -4.06/+3.25 kW; los defaults van algo por encima). |

La meta del plan expone ahora `pv_bias`, `pv_realized_today_kwh`,
`nowcast_kw`, `ev_state`, `ev_power_w`, `load_quantile` para
verificación continua en el dashboard.

Pendientes de una iteración futura: perfil por día-tipo, buffer ~2
puntos sobre la reserva, e integración del horario `ss/se` del
cargador.

**Persistencia implementada**: cada hora el coordinator añade una
línea JSON a `config/deye_smart_energy_manager/plan_log.jsonl`
(rotación a ~2 MB) con los 24 slots (acción, W batería, W red, SOC,
precio) y la meta. A partir de su despliegue se podrá comparar el
plan previsto vs los datos reales a T+24 h automáticamente.
