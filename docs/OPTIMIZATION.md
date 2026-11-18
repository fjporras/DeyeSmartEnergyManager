# DSEM — Modelo de optimización

Estado: **v1 heurístico determinista implementado** (`optimizer.py`), sin
dependencias externas. El LP con HiGHS es el objetivo de la iteración
siguiente, una vez validado el pipeline de datos en SHADOW.

## 1. Variables por hora `t` (paso 60 min)

| Variable | Unidad | Significado |
|---|---|---|
| `p_pv_bat[t]` | kW | FV → batería |
| `p_pv_load[t]` | kW | FV → carga |
| `p_pv_grid[t]` | kW | FV → exportación |
| `p_grid_bat[t]` | kW | Red → batería (carga en horas baratas) |
| `p_grid_load[t]` | kW | Red → carga (importación) |
| `p_bat_load[t]` | kW | Batería → carga (descarga) |
| `soc[t]` | kWh | Energía almacenada al final de la hora |

## 2. Restricciones

- Balance FV: `p_pv_bat + p_pv_load + p_pv_grid = pv_forecast[t]`
- Balance carga: `p_pv_load + p_grid_load + p_bat_load = load_forecast[t]`
- Dinámica SOC: `soc[t] = soc[t-1] + η_c·(p_pv_bat + p_grid_bat) − p_bat_load/η_d`
- `soc_min·C ≤ soc[t] ≤ soc_max·C`; en modo backup el suelo es `soc_reserve·C`
- `0 ≤ p_*_bat ≤ P_chg_max` / `0 ≤ p_bat_load ≤ P_dis_max`
- (Opcional, modo Zero Export) `p_pv_grid = 0`

## 3. Función objetivo (LP)

```
min Σ_t [ price[t]·(p_grid_load + p_grid_bat)
          − price_export·p_pv_grid
          + degradation·p_bat_load ]
```

Todos los términos son lineales → problema LP puro. No se necesitan
variables binarias salvo que se modelen inhibiciones carga/descarga
simultánea (la penalización de degradación ya lo desincentiva).

## 4. Decisión de solver

| Opción | Estado |
|---|---|
| **`highspy` (HiGHS)** | **Preferido.** Wheels amd64, sin licencia, solver LP/MIP de referencia. Requeriría `requirements` en manifest (instalación pip en el contenedor). |
| `scipy.optimize.linprog` | Alternativa si SciPy ya está disponible en el contenedor HA; API `method="highs"` idéntica. |
| Heurístico propio | **Implementado en v1** — sin dependencias, explicable, suficiente para SHADOW y para validar series de entrada. |

La v1 heurística y el futuro LP comparten `PlannerInput`/`EnergyPlan`,
así que el recambio será local a `optimizer.optimize()`.

## 5. Series de entrada (fuentes)

| Serie | Fuente | Fallback |
|---|---|---|
| `price[t]` | **InfluxDB `ree_indicators`** (serie horaria, si `influx_prices_enabled` y consulta OK) → merge sobre `sensor.esios_pvpc` attrs `price_XXh` (+ `price_next_day_XXh`) | Huecos: mediana del horizonte + warning `price_gaps_filled`; sin datos: `no_price_data`, sin arbitraje |
| `export_price[t]` | InfluxDB `ree_indicators` (vertido horario) | `export_price_eur_kwh` fijo (0,14) |
| `pv_kw[t]` | forecast_solar (totales hoy/mañana + hora de pico) distribuido en campana Gaussiana σ=3 h | 0 kW sin previsión |
| `load_kw[t]` | `statistics` de Recorder (media horaria 14 días del sensor de load) | Perfil residencial ES escalado a kWh/día recientes |

## 6. Heurística v1 (qué hace hoy)

Desde v0.4.0 el modelo refleja la física real del inversor: **la batería
descarga autónomamente en TODA hora con déficit** (`carga − FV`) hasta su
corte físico (`auto_floor_pct`, leído de
`number.<inversor>_battery_shutdown_soc` ≈ 10-15 %). No existe switch de
descarga ni decisión económica en ese flujo — el inversor no consulta
precios.

**Matiz de ejecución (verificado 2026-11-16):** en este inversor la
descarga a la carga solo ocurre con `off_grid` ON — con él OFF la
batería queda idle y la red paga el déficit. `energy_pattern` y
`work_mode` no gobiernan la descarga. Por eso el plan sigue modelando
`auto_discharge` pero el ejecutor (v0.8.x) activa `off_grid` en los
slots `discharge` y lo desactiva en `charge_grid` (donde ON bloquearía
la carga de red). Si `off_grid` queda OFF por una razón externa, el
plan sobreestima el ahorro: síntoma = `external_power` importando en
horas `discharge`.

1. Umbrales por cuantiles sobre los precios del horizonte: barato ≤ Q25,
   caro ≥ max(Q75, suelo de arbitraje con eficiencias+degradación).
2. Excedente FV → batería primero, exportación después.
3. Déficit → la batería cubre `min(déficit, P_dis_max, SOC − auto_floor)`;
   la red solo importa el remanente (`auto_discharge`).
4. **Suelo de trayectoria `req_end[i]`** (paso hacia atrás sobre el
   drenaje neto almacenado, acreditando la capacidad de carga por hora):
   - Reserva: `need_end` garantiza `soc ≥ soc_reserve` al final de cada
     hora; si la descarga autónoma lo violaría → `soc_reserve_charge`
     (carga forzada a cualquier precio; basta cualquier cantidad para
     que la red sirva el déficit).
   - Objetivo SOC: segunda trayectoria anclada a `soc_target` en
     `target_idx`, combinada por máximo → `soc_target_forced_charge`.
   - Si el suelo queda pineado en `soc_max` por una reserva inviable
     (sin objetivo que lo justifique), no se fuerza carga: la batería
     descarga hasta el piso físico y se emite `soc_reserve_risk`.
5. Arbitraje: en horas baratas con déficit caro futuro (o necesidad de
   objetivo) → `charge_grid` (`cheap_hour_precharge`,
   `soc_target_precharge`, `soc_target_forced_charge`), limitado al
   déficit caro/objetivo estimado restante. `tneed` es drain-aware
   (incluye la descarga autónoma esperada hasta la hora objetivo).
   **Crédito FV (`pv_fut`, v0.6.0)**: la energía FV prevista se simula
   en un pool FIFO — el excedente FV almacenado cubre los déficits
   siguientes antes que la energía de red — de modo que la precarga
   barata solo cubre el déficit caro que la FV **no puede** cubrir.
   Sin este crédito, la batería amanecía llena, el excedente FV del
   mediodía no cabía y se exportaba/curtaba (con el regulador de
   tensión de la acometida, se perdía producción).
   **Headroom FV (`pv_tail`, v0.9.0)**: `pv_tail[i]` es la energía FV
   excedentaria prevista después de la hora `i` **el mismo día
   natural** (limitada por la tasa de carga, en kWh almacenados). La
   carga de red queda topada a `max(req_end[i], soc_max − pv_tail[i])`
   para reservar sitio al sol que aún no ha llegado: la energía de red
   pagada a precio valle no debe ocupar el sitio que necesita el
   excedente FV gratuito del mediodía (que si no cabe se exporta o
   curta). La propia carga `charge_pv` NO se limita — es la energía
   para la que se reserva el margen. Los suelos de reserva/objetivo
   siempre prevalecen, y un objetivo SOC explícito pendiente anula el
   límite hasta su hora límite. La FV del día siguiente no restringe
   la carga de esta noche (la batería se descarga durante la noche de
   todos modos). Si el forecast FV falla (día nublado), el plan se
   recalcula cada ~15 min y el margen desaparece solo.
6. Coste esperado vs baseline (batería inerte) para estimar ahorro.

Cada `PlanSlot` lleva `reason` — explicable por diseño.

## 7. Limitaciones v1 → backlog LP

- Curva FV sintetizada (forecast_solar no expone vector horario): error
  intra-día, correcto a nivel diario.
- Perfil de carga = media histórica por hora (sin día-de-semana ni
  temperatura).
- Sin modelado de VE/ACS (sin entidades aún).
- Sin incertidumbre (P10/P90): considerar Solcast si el error FV observado
  en SHADOW es alto.
- `step_minutes` fijado a 60 en el planner v1 (la opción existe para el LP).
