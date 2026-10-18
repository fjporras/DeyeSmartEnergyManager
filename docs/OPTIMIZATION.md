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
| `price[t]` | `sensor.esios_pvpc` attrs `price_XXh` (+ `price_next_day_XXh` cuando ESIOS publica) | Huecos: mediana del horizonte + warning `price_gaps_filled`; sin datos: warning `no_price_data`, sin arbitraje |
| `pv_kw[t]` | forecast_solar (totales hoy/mañana + hora de pico) distribuido en campana Gaussiana σ=3 h | 0 kW sin previsión |
| `load_kw[t]` | `statistics` de Recorder (media horaria 14 días del sensor de load) | Perfil residencial ES escalado a kWh/día recientes |

## 6. Heurística v1 (qué hace hoy)

1. Umbrales por cuantiles sobre los precios del horizonte: barato ≤ Q25,
   caro ≥ max(Q75, suelo de arbitraje con eficiencias+degradación).
2. Excedente FV → batería primero, exportación después.
3. Déficit en hora cara → descarga hasta la reserva.
4. Hora barata con déficit caro futuro → precarga desde red limitada al
   déficit caro estimado restante.
5. Coste esperado vs baseline (batería inerte) para estimar ahorro.

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
