# Manual de usuario — Modos de funcionamiento del DSEM

**Deye Smart Energy Manager (DSEM)** decide cada hora qué debe hacer la
batería del inversor Deye: cargar desde red, descargar a la vivienda o
quedarse en reposo. El **modo de funcionamiento** define qué objetivo
persigue esa decisión y si DSEM solo *calcula* el plan o también lo
*ejecuta* escribiendo en el inversor.

El modo se elige en la entidad **`select.deye_smart_energy_manager_modo`**
(disponible en los paneles DSEM, Inicio y Energy Hub, y en
Herramientas para desarrolladores → Estados).

---

## 1. Los dos grupos de modos

| Grupo | Modos | ¿Escribe en el inversor? |
|---|---|---|
| **Solo lectura** | `shadow`, `manual`, `safe` | ❌ Nunca |
| **Ejecutores** | `auto`, `auto_export`, `economic`, `solar_priority`, `backup`, `target_soc` | ✅ Solo si `enable_control` está activo |

Los modos ejecutores exigen **doble habilitación**:

1. Activar la opción **`enable_control`** en la configuración de la
   integración (Dispositivos y servicios → DSEM → Configurar → Control).
2. Seleccionar el modo en `select.deye_smart_energy_manager_modo`.

Si eliges un modo ejecutor sin `enable_control`, el select lo rechaza
(error de validación) y se queda el modo anterior. Es el seguro
obligatorio: nada escribe en el inversor por accidente.

---

## 2. Modos de solo lectura

### `shadow` — Shadow (solo calcula) · **modo por defecto**

DSEM hace todo el trabajo excepto actuar: calcula el plan hora a hora,
publica la acción recomendada y el motivo en los sensores y registra cada
decisión en el logbook y en `plan_log.jsonl`. **Nunca toca el inversor.**

- Es el modo inicial obligatorio y el correcto mientras se valida que la
  instalación lee bien (sensores, precios, previsiones).
- Sirve también como "qué haría DSEM si pudiera" — el plan calculado se
  puede comparar con lo que realmente hace el inversor.

### `manual` — Manual

Control 100 % manual de la instalación. DSEM no actúa ni publica
recomendaciones activas: es el modo para cuando el usuario gobierna el
inversor a mano (TOU propio, switches manuales, otras automatizaciones).

### `safe` — Seguro

Solo monitoriza. Ignora cualquier plan que no pueda validarse por
completo (datos ausentes o incoherentes). Es además el **modo de
retirada automática**: si el ejecutor acumula errores persistentes, DSEM
cae a `safe` por sí solo y lo notifica.

---

## 3. Modos ejecutores (requieren `enable_control`)

Todos ejecutan el plan horario calculado por el optimizador; la
diferencia está en **qué optimiza el plan** y, en `auto_export`, en qué
hace la guardia de exportación.

### `auto` — Auto (ejecuta, sin vertido)

El modo general recomendado para la instalación GTS. El optimizador
decide por precio y previsión FV, y el ejecutor aplica el plan con
verificación. La guardia de exportación fuerza **cero vertido**
(`work_mode = Zero Export To CT`, `export_surplus = off`, margen 20 W):
el excedente solar va a la batería o lo recorta el inversor.

### `auto_export` — Auto + vertido a red

Igual que `auto` pero la guardia de exportación se invierte:
`work_mode = Export First` y `export_surplus = on`, para vender el
excedente solar a red cuando compensa. Pensado para instalaciones con
camino físico de exportación. Si la instalación no debe verter, **`auto`
es el modo correcto.**

### `economic` — Económico

El objetivo pasa a ser **mínimo coste**: el plan arbitra precios hora a
hora (serie REE/PVPC de consumo y vertido), cargando batería en horas
baratas o de excedente FV y descargando en las caras. Es el modo más
agresivo con el arbitraje de precio.

### `solar_priority` — Prioridad solar

Maximiza el **autoconsumo**: prioriza cargar batería con excedente FV y
descargar para servir la vivienda antes de comprar a red. Útil cuando lo
importante es no depender de la red aunque no sea el céntimo óptimo.

### `backup` — Reserva

Mantiene una **reserva de batería** para cortes: el plan nunca descarga
por debajo del `reserve_soc_pct` configurado (por defecto 35 %, igual
que el suelo real del inversor). El resto de la capacidad se optimiza
con normalidad. Recomendado si los cortes son frecuentes.

### `target_soc` — Objetivo SOC (restricción)

Modo puntual: **alcanzar un SOC concreto a una hora concreta**. Se
configura con dos entidades propias de DSEM:

- `number.deye_smart_energy_manager_soc_objetivo` — SOC objetivo (%)
- `time.deye_smart_energy_manager_hora_objetivo` — hora límite

El optimizador precarga en las horas baratas previas, descuenta lo que
la FV prevista va a aportar, y si las horas baratas no bastan **fuerza
la carga** en las siguientes más baratas hasta garantizar el objetivo.
Además impone un suelo de trayectoria: bloquea descargas que dejarían el
SOC por debajo de lo necesario para llegar a tiempo. Si es físicamente
inviable, avisa (`soc_target_not_reached`).

Ejemplo de uso: "quiero la batería al 90 % a las 18:00" antes de un pico
de precio o de un posible corte programado.

⚠️ Ojo con los **programas TOU del inversor**: cada ventana TOU tiene su
propio SOC objetivo y el inversor deja de cargar al alcanzarlo. Si un
programa clava el SOC en 70 %, un `target_soc` de 90 % puede no llegar
aunque el switch de carga esté activado. Se recomienda poner los
programas que coincidan con ventanas de carga a fuente `Both`/`Grid` y
SOC alto (100 %).

### Detección del cargador VE

DSEM lee el cargador del coche (por defecto el dé EV Charger vía
`tuya_local`) a través de tres entidades configurables:
`sensor.de_ev_charger_estado`, `number.de_ev_charger_charge_current` y
`sensor.garaje_de_ev_charger_cargador_ve_potencia` (si falta el sensor
de potencia, la estima como `A × 230 V`).

Cuando el VE carga, esa potencia se suma a la previsión de consumo del
plan — los slots dejan de subestimar la demanda de la vivienda. Y hay
un efecto físico importante: como el cargador cuelga del puerto **Load**
del Deye, con `off_grid` ON la batería alimenta **todo**, VE incluido
(~3–6 kW extra de descarga). El optimizador lo sabe: en horas baratas
mantiene `off_grid` OFF (`hold_for_expensive`) para que el VE lo pague
la red, y reserva la batería para las horas caras.

Si la carga VE drena la batería hasta el suelo de reserva
(`reserve_soc_pct`) estando en isla, la guardia `off_grid` pasa a OFF
y **se mantiene OFF hasta que termina la sesión** — sin ese latch, el
plan alternaba isla/red cada ~10 min re-cargando desde red lo que la
batería acababa de gastar en el coche (incidente 28-11).

---

## 4. Qué escribe realmente el ejecutor

Con un modo ejecutor activo, DSEM toca **solo tres superficies**, un
cambio por entidad y ciclo (mínimo 10 min entre escrituras):

| Superficie | Qué hace |
|---|---|
| `switch.battery_grid_charging` | ON cuando el plan pide `charge_grid`; OFF el resto. El inversor decide potencia y ritmo. |
| Guardia de exportación (`work_mode`, `export_surplus`, `zero_export_power`) | Mantiene cero vertido en todos los modos salvo `auto_export`, que configura `Export First` + vertido ON. |
| Guardia `off_grid` | ON solo en horas de descarga (es la única vía para que la batería sirva la carga); OFF el resto, porque ON bloquea la carga desde red. Cada cambio exige ~8 min de demanda estable (histéresis anti-parpadeo). |

Lo que **nunca** toca: protecciones del inversor (`*_protection_*`,
SOC shutdown/low, tensiones) ni el switch `microinverter_export_cut_off`
(gestión manual).

## 5. Redes de seguridad del ejecutor

- **Arranque suave:** 5 min de gracia tras iniciar HA.
- **Datos completos:** no escribe si falta alguna entidad o está caduca.
- **Verificación:** lee la entidad tras cada escritura; 3 fallos
  seguidos → espera 30 min y notificación persistente.
- **`off_grid` en isla:** si la tensión L1 baja de 150 V, DSEM cede el
  switch a la automatización de corte de red y no lo toca.
- **`off_grid` anti-vaivén:** un cambio de estado solo se escribe si la
  demanda se mantiene 8 evaluaciones seguidas (~8 min) — evita que el
  plan parpadeando en el borde de la reserva cargue/descargue la
  batería en círculo. La excepción: con SOC en el suelo físico el OFF
  de protección se escribe al momento.
- **`off_grid` y el VE:** si durante una carga VE el SOC llega a
  `reserve_soc_pct`, `off_grid` queda OFF enganchado hasta que el
  cargador deja de reportar `charging` — el coche pasa a la red y no
  vuelve a isla aunque el SOC se recupere a mitad de sesión.
- **Automatización PVPC legada:** la que cargaba en horas baratas se
  desactiva sola mientras haya un modo ejecutor y se restaura al volver
  a `shadow`/`manual`/`safe` o al quitar `enable_control`.
- **Al salir:** al volver a un modo de solo lectura, DSEM restaura lo
  que activó (`off_grid` a OFF, la automatización PVPC a su estado).

## 6. Qué modo elegir

| Situación | Modo |
|---|---|
| Validando la instalación / solo quiero ver el plan | `shadow` |
| Uso normal, sin vertido a red | **`auto`** |
| Quiero vender el excedente solar | `auto_export` |
| Priorizo ahorro por arbitraje de precio | `economic` |
| Priorizo no depender de la red | `solar_priority` |
| Cortes frecuentes, quiero colchón | `backup` |
| "Quiero X % de batería a las HH:MM" | `target_soc` |
| Lo controlo yo a mano | `manual` |
| DSEM se retiró solo por errores | `safe` (revísalo) |

## 7. Dónde mirar qué está haciendo DSEM

- `sensor.deye_smart_energy_manager_estado_del_optimizador` — modo,
  control habilitado, entidades ausentes/caducas.
- `sensor.deye_smart_energy_manager_proxima_accion_del_plan` — acción
  actual, slots del plan y metadatos (`control`, `zero_export`,
  `offgrid`, `tou_*`, `ev_*`, `price_source`…).
- `sensor.deye_smart_energy_manager_estrategia_actual` — estrategia en
  lenguaje llano.
- Sensores espejo (`potencia_fv`, `potencia_de_red`,
  `potencia_de_bateria`, `soc_de_bateria`) — réplica en vivo de lo que
  DSEM está leyendo del inversor; útiles para comprobar que la entrada
  de datos es sana.
- En el meta del plan, `offgrid` muestra el estado de la guardia:
  `og_ok:on|off` (estado = demanda), `og_pending:on|off:N` (demanda
  pendiente, N evaluaciones de 8), `og_written` / `og_rate_limited` /
  `og_low_soc` / `og_ev_floor_hold` (latch VE: OFF retenido hasta el
  fin de la sesión)…
- Servicio `deye_smart_energy_manager.reoptimize` — fuerza un
  recálculo inmediato del plan (útil tras enchufar el VE, cambiar el
  límite de carga o corregir una previsión).
- Logbook: cada orden ejecutada con su motivo.
- `config/deye_smart_energy_manager/plan_log.jsonl` — historial de
  planes en JSON.

---

## 8. Limitador de importación de red (fuera de DSEM)

`automation.deye_limitar_carga_de_bateria_a_grid_max_import` es una
automatización independiente de DSEM (funciona en cualquier modo,
incluido `manual`). Su misión: que la **importación total de red nunca
supere `Grid Max Import Power`** del inversor
(`number.deye_sun_15k_sg05lp3_eu_sm2_grid_max_import_power`), que en GTS
está fijado a **9.000 W**.

### Cómo funciona

Cada vez que el inversor publica una lectura de potencia de red (y cada
minuto por seguridad) recalcula la corriente de carga de batería
permitida y la escribe en
`number.deye_sun_15k_sg05lp3_eu_sm2_battery_grid_charging_current`:

```
I_bat = (Grid Max Import − importación sin batería − margen) / V_batería
```

- `importación sin batería` = lo que consume la casa + VE sin contar lo
  que la batería está cargando desde red (`grid_power` − `battery_power`
  cuando carga).
- `margen` = **500 W** de seguridad (variable `margen_w`, editable en la
  automatización).
- El resultado se satura a `[0, battery_max_charging_current]` (100 A en
  GTS): con margen suficiente la carga vuelve sola a plena corriente.
- Solo escribe si el ajuste es de **5 A o más** — no machaca el inversor
  con escrituras por ruido de sensores.
- Si casa + VE ya superan el límite por sí solos, la corriente cae a
  **0 A**: la carga de batería se pausa hasta que sobre margen.

### Ejemplo real (noche de despliegue)

VE cargando a 4,5 kW + casa 1,8 kW + batería a 100 A (5,1 kW) →
importación 11,4 kW > 9 kW. El limitador bajó la corriente a 41 A
(~2,2 kW) y la importación quedó en 8,6 kW. Al terminar la carga del VE
a la 1:30, la corriente vuelve sola a ~100 A en la siguiente evaluación.

### Convivencia con el resto del sistema

- **PVPC** (`pvpc_carga_bateria_deye_en_horas_baratas`) decide **cuándo**
  cargar (switch on/off en horas baratas); el limitador decide **a qué
  ritmo**. No se pisan.
- **DSEM** gestiona el mismo switch en los slots `charge_grid` /
  `soc_reserve_charge`; el limitador solo dimensiona la corriente, así
  que protege igualmente las cargas ordenadas por el plan.
- Si cambias `Grid Max Import Power` en el inversor, el limitador lee el
  nuevo valor en la siguiente evaluación — no hay que tocar nada más.

## 9. Corriente del cargador VE según contexto

`automation.cargador_ve_ajustar_corriente_segun_contexto` ajusta la
consigna de corriente del cargador
(`number.de_ev_charger_charge_current`, pasos discretos de 6 a 32 A/fase,
~690 W por amperio/fase en trifásica) según el contexto. Se activa o
desactiva desde la tarjeta Cargador (botón «Corriente automática» en la
sección Ajustes).

### Con red conectada — dinámico

```
I_VE = (Grid Max Import − consumo casa − carga batería − 500 W) / 690 W
→ se redondea hacia abajo al paso disponible
```

El VE tiene **prioridad** sobre la carga de batería: el limitador de §8
rellena el hueco que la consigna del VE deje libre. Si subes
`Grid Max Import`, la consigna sube sola.

### En isla — escalonado por SOC

Los umbrales se derivan de los registros del propio inversor (los que
DSEM respeta), más un margen configurable:

| SOC de batería | Consigna |
|---|---|
| ≥ `battery_restart_soc` (50 %) | 10 A |
| ≥ `battery_low_soc` + margen (35 + 5 = 40 %) | 8 A |
| > `battery_low_soc` (35 %) | 6 A |
| ≤ `battery_low_soc` (35 %) | **parada total** (pulsa Stop) |

- **`input_number.cargador_ve_margen_soc_bajo`** (slider 0–30 %,
  por defecto 5): colchón sobre el Low SOC para el piso de 8 A. Ajustable
  desde la UI.
- **Parada por reserva**: en isla y cargando, si el SOC llega al
  `battery_low_soc` (35 %) la automatización pulsa Stop para dejar la
  reserva a la casa. No reanuda sola — reanudación manual o por replug.
- Solo escribe cuando el paso objetivo cambia; se reevalúa con cada
  lectura de potencia/SOC y cada 2 min por barrido.

### Motivo de parada en el aviso de fin de carga

El sensor de plantilla `sensor.cargador_ve_motivo_de_parada` clasifica
por qué terminó una sesión, y
`automation.cargador_ve_aviso_fin_de_carga` lo incluye en la notificación
cuando la carga se detiene sin completarse:

1. `Cable desconectado` — el cargador pasó a `idle`
2. `Reserva de batería (…% en modo isla)` — isla + SOC ≤ Low SOC
3. `Fin del periodo programado (hh:mm-hh:mm)` — la parada ocurrió en los
   5 min siguientes a la hora de fin de la ventana armada
4. `Parada manual (botón, tarjeta o app)` — cualquier otro caso

Los avisos de `completada`/`detenida` solo se envían si el tramo
`charging` previo duró **≥60 s** — los parpadeos que el firmware produce
al rearmar ventanas ya no generan notificaciones (incidente 28-11:
~30 avisos en 10 min). La rama `fallo` sigue avisando siempre.

## 10. Horarios del cargador VE (varios periodos)

`automation.cargador_ve_aplicar_horario_de_carga` gestiona el DP 151
(`charge_mode`) del cargador. El hardware solo guarda **una** ventana,
así que la automatización arma en cada momento la que toca entre los 3
periodos de la tarjeta (P1 = `horario_programado`, P2/P3 =
`periodo_N_activo` + sus `input_datetime`):

| Situación | `charge_mode` | Resultado |
|---|---|---|
| Dentro de una ventana activa | `m=0` (inmediato) | El VE carga al enchufar |
| Fuera, con ventana próxima | `m=1` armada (`ss`/`se`) | Espera al inicio |
| Sin periodos activos | `m=0` | Carga inmediata |

**Por qué `m=0` dentro de ventana:** el firmware 9.2.5 solo auto-arranca
una carga en el borde `ss` de una ventana armada — si el coche se
enchufa *dentro* de la ventana, `m=1` no lo inicia (lo intenta en
ciclos de ~20 s y aborta). Incidente real 28-11: enchufado a las 23 h
no cargó hasta un Start manual a las 03:09. Al cruzar el fin de
ventana, el barrido de cada minuto escribe `m=1` con la siguiente —
pendiente de verificar que el cargador detiene entonces la carga.

**Cuándo se reevalúa:** al cambiar cualquier helper, cada minuto
(cubre las fronteras con ≤60 s), a medianoche y al arrancar HA. **No**
reacciona al estado del cargador — ese disparo realimentaba las
escrituras del DP151 creando un bucle con el firmware (parpadeos
`charging↔plugged_in`, ~30 notificaciones la noche del 28-11).

**Sincronización con la app dé:**
`automation.cargador_ve_sincronizar_horario_del_cargador` adopta los
cambios del DP hechos desde fuera de HA: `m=1` externo → se adopta como
Periodo 1; `m=0` externo → desactiva los 3 periodos; `m=2` se ignora.
Las escrituras propias se ignoran comparando con
`input_text.cargador_ve_ultimo_horario_escrito`.
