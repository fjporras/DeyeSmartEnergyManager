# Deye Smart Energy Manager (DSEM)

Integración personalizada de Home Assistant para optimización económica de una
vivienda con fotovoltaica (Fronius Symo AC-coupled), inversor híbrido Deye
SUN-15K-SG05LP3-EU-SM2 y batería SEPLOS (~32 kWh nominales).

**Instancia objetivo:** GTS Solutions — `http://10.0.100.20:8123` (HA Container
core-2026.8.3, Europe/Madrid).

## Estado del proyecto

- **Fase actual:** Fase 1 — Auditoría de entidades completada.
- **Modo objetivo inicial:** SHADOW (calcular decisiones sin ejecutarlas).
- El control real queda vetado hasta validación técnica y autorización explícita.

## Documentación

| Documento | Contenido |
|---|---|
| [docs/ENTITY_AUDIT.md](docs/ENTITY_AUDIT.md) | Auditoría real de entidades (Deye, Fronius, PVPC), topología eléctrica deducida, huecos y riesgos |

## Restricciones de desarrollo

- No modificar la integración `solarman` ni los registros Modbus directamente.
- No escribir en el inversor salvo en modo AUTO autorizado.
- Las únicas superficies de control permitidas son las entidades HA
  (`number`, `select`, `switch`, `time`) de la integración existente.
- No publicar credenciales ni direcciones sensibles.
