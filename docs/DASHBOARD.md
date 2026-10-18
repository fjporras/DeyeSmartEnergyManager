# Dashboard de monitorización — DSEM

Panel Lovelace para supervisar el plan SHADOW: estado actual, resumen
económico y los 24 slots horarios con acción, potencias, SOC previsto,
precio y motivo de cada decisión.

El YAML completo está en [`lovelace/dsem-dashboard.yaml`](../lovelace/dsem-dashboard.yaml).

## Instalación

1. **Settings → Dashboards → Add dashboard** → título `DSEM` → Create.
2. Abre el nuevo dashboard → **Edit** → ⋮ → **Raw configuration editor**.
3. Pega el contenido de `lovelace/dsem-dashboard.yaml` (sin la cabecera
   de comentarios) → **Save**.

Todas las tarjetas usan tipos estándar de Lovelace — no requiere plugins.

## Contenido

### Vista «Estado actual»

- **Estado del optimizador**: `ok`/`error`, estrategia, modo (select),
  acción en curso del plan.
- **Gauge SOC** + potencias instantáneas (FV, red, batería) con el
  convenio de signos documentado.
- **Plan — resumen**: coste esperado vs baseline, ahorro estimado,
  fuente de cada serie (`price_source`, `load_source`, `pv_source`),
  horas sin precio y warnings. Sirve para detectar de un vistazo si el
  plan está usando `influxdb` o el fallback `pvpc`.
- **History-graph 24 h** de FV/red/batería.

### Vista «Plan 24 h»

Tabla generada por plantilla con los slots del plan:

| Columna | Significado |
|---|---|
| Acción | `import` / `charge` / `discharge` / `export` / `idle` |
| Bat W | <0 cargando, >0 descargando |
| Red W | >0 importando, <0 exportando |
| SOC | SOC previsto al final de la hora |
| €/kWh | precio de consumo usado (REE InfluxDB o PVPC) |
| Motivo | razón de la decisión (`pv_surplus`, `discharge_expensive`, …) |

## Verificación de calidad (modo SHADOW)

Para validar el plan durante los próximos días, comparar cada mañana:

- `eur_kwh` de los slots vs el precio PVPC real publicado (`sensor.esios_pvpc`
  atributos) — mide el desfase de la serie REE del bucket.
- `grid_w` previsto vs `sensor.deye_sun_15k_sg05lp3_eu_sm2_external_power`
  real — mide el sesgo del perfil de consumo (ya observado: subestima el
  pico vespertino ~20h).
- `soc_end` previsto vs `sensor..._soc_de_bateria` real — mide la
  deriva del modelo de batería.

## Opcional — gráficas con apexcharts-card

Para curvas de SOC previsto, precios y potencia de batería del plan,
instala **apexcharts-card** (HACS → Frontend) y añade una tarjeta manual:

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Plan — SOC, precio y batería
graph_span: 48h
span:
  offset: +0h
now:
  show: true
  label: ahora
yaxis:
  - id: soc
    min: 0
    max: 100
  - id: eur
    opposite: true
    decimals: 3
  - id: w
    opposite: true
series:
  - entity: sensor.deye_smart_energy_manager_proxima_accion_del_plan
    name: SOC previsto (%)
    yaxis_id: soc
    type: line
    data_generator: |
      return entity.attributes.slots.map(s =>
        [new Date(s.t).getTime(), s.soc_end]);
  - entity: sensor.deye_smart_energy_manager_proxima_accion_del_plan
    name: Precio (€/kWh)
    yaxis_id: eur
    type: line
    color: orange
    data_generator: |
      return entity.attributes.slots.map(s =>
        [new Date(s.t).getTime(), s.eur_kwh]);
  - entity: sensor.deye_smart_energy_manager_proxima_accion_del_plan
    name: Batería prevista (W)
    yaxis_id: w
    type: column
    color: steelblue
    data_generator: |
      return entity.attributes.slots.map(s =>
        [new Date(s.t).getTime(), s.batt_w]);
```

`data_generator` lee el atributo `slots` del sensor del plan y dibuja la
trayectoria futura — la gráfica avanza sola a medida que el plan se
recalcula cada 15 min.
