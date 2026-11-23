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
- Logbook: cada orden ejecutada con su motivo.
- `config/deye_smart_energy_manager/plan_log.jsonl` — historial de
  planes en JSON.
