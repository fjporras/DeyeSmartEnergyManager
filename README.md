# Deye Smart Energy Manager (DSEM)

Integración personalizada de Home Assistant para optimización económica de una
vivienda con fotovoltaica (Fronius Symo AC-coupled), inversor híbrido Deye
SUN-15K-SG05LP3-EU-SM2 y batería SEPLOS (~32 kWh nominales).

**Instancia objetivo:** HA Container core-2026.8.3, Europe/Madrid).

## Estado del proyecto

- **Versión:** v0.8.1 — integración en producción con **control real
  verificado en vivo** (modo `auto` + `enable_control`).
- **Capacidades:** planificador horario 24 h (heurístico determinista,
  46 tests), precios PVPC/InfluxDB, previsión FV con corrección de sesgo,
  perfil de carga con cuantil+nowcast+VE, guardia zero-export,
  guardia `off_grid` (descarga a carga) y gestión automática del
  conflicto con la automatización PVPC.
- **Modo por defecto:** `shadow` — el control exige `enable_control`
  en opciones + modo ejecutor.

## Instalación (HACS)

[![Abrir en HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fjporras&repository=DeyeSmartEnergyManager&category=integration)

1. HACS → ⋮ → **Custom repositories** →
   `https://github.com/fjporras/DeyeSmartEnergyManager` — categoría *Integration*.
2. Descargar → reiniciar HA → Añadir integración → *Deye Smart Energy Manager*.
3. Despliegue manual alternativo: `docs/DEPLOYMENT.md` / `scripts/deploy.ps1`.

## Documentación

| Documento | Contenido |
|---|---|
| [docs/ENTITY_AUDIT.md](docs/ENTITY_AUDIT.md) | Auditoría real de entidades (Deye, Fronius, PVPC, forecast_solar, InfluxDB), topología eléctrica, huecos y riesgos |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Módulos, modos operativos, superficie de control y ciclo de vida |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Entidades requeridas/opcionales y opciones (batería, optimizador, InfluxDB) |
| [docs/OPTIMIZATION.md](docs/OPTIMIZATION.md) | Modelo LP objetivo, heurística v1 y decisión de solver |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Despliegue (HACS/SSH), validación SHADOW y rollback |

## Restricciones de desarrollo

- No modificar la integración `solarman` ni los registros Modbus directamente.
- No escribir en el inversor salvo en modo AUTO autorizado.
- Las únicas superficies de control permitidas son las entidades HA
  (`number`, `select`, `switch`, `time`) de la integración existente.
- No publicar credenciales ni direcciones sensibles.
