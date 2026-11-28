# Guía rápida — Casa GTS

Esta guía explica en palabras sencillas cómo funciona tu instalación y
qué puedes tocar (y qué no) en la app de Home Assistant.

---

## ¿Qué hace el sistema por ti?

Tu casa tiene paneles solares, una batería y un inversor Deye. El
sistema decide solo, cada hora, qué le conviene a tu factura:

- **Horas baratas** → la casa usa la red (y si hace falta, la batería
  se recarga también de red, a precio bajo).
- **Horas caras** → la casa se desconecta de la red y vive de la
  batería. No notas nada: la luz ni parpadea.
- **Sol de sobra** → lo que no gastas se guarda en la batería.

Tú no tienes que hacer nada: trabaja solo las 24 h. En la pantalla
puedes ver en cada momento de dónde sale la energía.

## El cargador del coche (lo que más usarás)

En la tarjeta **Cargador** tienes los mandos del cargador del garaje:

- **Enchufa el coche cuando quieras.** Si hay un periodo programado
  activo en ese momento, empieza a cargar solo en menos de un minuto.
- **Periodos de carga:** en la sección *Programación* de la tarjeta
  hay hasta 3 horarios (con su botón de activar). Ejemplo típico:
  21:00–02:15. Activa los que uses; el cargador sigue el que toque.
- **Corriente automática** (sección *Ajustes*): si está activada, el
  sistema ajusta solo la velocidad de carga para no pasarse del límite
  de tu casa (y en modo isla, para no vaciar la batería). Recomendado
  dejarla activada.
- **Botón «VE: Red / Batería»**: fuerza que el coche cargue desde la
  red aunque la casa esté usando la batería. Al desactivarlo, todo
  vuelve a su sitio.

### Cosas buenas de saber sobre el coche y la batería

- En las horas caras, el coche puede cargar **desde la batería de la
  casa** si tiene margen — es gratis para ti.
- Si la batería baja a su reserva mientras el coche carga, el sistema
  **devuelve la casa a la red automáticamente** y ahí se queda hasta
  que el coche termine. Sin sobresaltos.
- Si la batería llega a su mínimo de seguridad con la casa en modo
  isla, la carga del coche **se para sola** para dejar reserva a la
  vivienda. Para reanudarla, pulsa inicio en la tarjeta o desconecta
  y vuelve a conectar el cable.
- Cuando la carga termina te llega un **aviso al móvil** diciendo
  cuántos kWh cargó y por qué paró (fin programado, batería, cable,
  etc.).

## Avisos que puedes recibir

- **Corte de red / recuperación**: normal, el sistema cambia a batería
  y vuelve solo. Si la casa se queda sin luz con red disponible, avisa
  — eso no debería pasar.
- **Carga finalizada / completada**: informativo, con el motivo.

## Qué NO hace falta tocar

- Las opciones de DSEM y los switches del inversor: están ajustados.
  Si algo huele raro, llámanos antes de tocarlos.
- **La app dé/Tuya del cargador**: úsala lo mínimo posible — cuando la
  abres, desconecta al cargador de Home Assistant y pierde la
  telemetría un rato. Todo lo que la app hace lo puedes hacer desde la
  tarjeta.

## Si algo va mal

| Síntoma | Qué hacer |
|---|---|
| El cargador aparece «no disponible» | Suele ser que la app dé se conectó y le robó la sesión; espera unos minutos. Si persiste, apaga/enciende el cargador en su interruptor y avísanos. |
| El coche no carga estando enchufado | Comprueba en la tarjeta que el periodo está activado y que el estado no pide un «Start» manual. |
| Aviso de «DSEM en pausa por fallos» | El sistema se protege solo tras errores repetidos — avísanos. |
| Corte total con red disponible | No debería pasar nunca. Si pasa, llámanos: nos interesa mucho saber la hora exacta. |

## Resumen en una frase

*Enchufa el coche, deja los periodos activados y el «corriente
automática» encendida: el sistema elige siempre la energía más barata
disponible — primero el sol, luego la batería, y la red solo cuando
toca.*
