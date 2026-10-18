# DEPLOYMENT — Deye Smart Energy Manager

Despliegue de la integración `deye_smart_energy_manager` en la instancia
**GTS Solutions** (HA Container `core-2026.8.3`, `http://10.0.100.20:8123`).

> ⚠️ El MCP no tiene acceso al filesystem ni a `/config`: el despliegue es
> por SSH/SCP al host Docker. El reinicio de HA puede hacerse por MCP
> (`ha_restart`) o `docker restart`, **siempre con autorización previa**.

## 1. Prerrequisitos

- Acceso SSH al host Docker que ejecuta el contenedor `homeassistant`.
- Ruta del directorio `/config` de HA en el host (p. ej.
  `/opt/homeassistant` o `/srv/homeassistant`). En este documento:
  `$HA_CONFIG`.
- Puerta de control **desactivada** por defecto — el despliegue es seguro:
  tras el reinicio, DSEM arranca en modo `shadow` y `enable_control=false`.

## 2. Copiar la integración

```bash
# Desde la raíz del repo (host local)
scp -r custom_components/deye_smart_energy_manager \
      usuario@<host>:$HA_CONFIG/custom_components/

# Verificar permisos legibles por el contenedor (root del container lee todo;
# si el bind-mount preserva UID, asegurar lectura):
ssh usuario@<host> 'ls -la $HA_CONFIG/custom_components/deye_smart_energy_manager'
```

Equivalente Windows (PowerShell + OpenSSH): ver `scripts/deploy.ps1`.

## 3. Verificación de configuración (recomendado, sin reiniciar)

```bash
ssh usuario@<host> \
  'docker exec homeassistant python -m homeassistant --script check_config -c /config'
```

## 4. Reinicio de Home Assistant

Opciones (elegir una):

```bash
# a) Reiniciar solo el contenedor
ssh usuario@<host> 'docker restart homeassistant'

# b) O desde la UI: Ajustes → Sistema → ⋮ → Reiniciar
# c) O por MCP (requiere autorización explícita): ha_restart
```

## 5. Alta de la integración (UI)

1. **Ajustes → Dispositivos y servicios → Añadir integración** →
   `Deye Smart Energy Manager`.
2. Paso 1 — entidades requeridas (prefill con los valores auditados de
   GTS; validan existencia y unidad).
3. Paso 2 — opcionales (forecast_solar + contadores). Dejar VE/ACS vacíos.
4. Fin. La integración arranca en **SHADOW**.

## 6. Validación post-despliegue (checklist)

| # | Comprobación | Cómo |
|---|---|---|
| 1 | Integración cargada sin errores | Ajustes → Dispositivos → DSEM; `ha_get_logs` buscar `deye_smart_energy_manager` |
| 2 | 8 entidades `sensor.dsem_*` + `select.dsem_mode` creadas | Desarrollador → Estados |
| 3 | `sensor.dsem_optimization_status` = `ok` (o `degraded` con `missing_entities` indicando qué falta) | Estado del sensor |
| 4 | `sensor.dsem_plan_next_action` con `plan_available: true` y 24+ slots | Atributos del sensor |
| 5 | **Series InfluxDB**: atributos `price_source` (`influxdb`/`pvpc`), `import_series`, `export_series` → confirmar que el auto-descubrimiento encontró los measurement/field correctos del bucket `ree_indicators` | Atributos del sensor / diagnóstico descargable |
| 6 | Coste esperado y ahorro coherentes (€ razonables) | `expected_cost_eur` vs `baseline_cost_eur` |
| 7 | **Ninguna escritura**: `control_enabled=false`, modo `shadow`, sin cambios en entidades del Deye | Historial del `switch.…_battery_grid_charging` sin cambios atribuibles a DSEM |

## 7. Rollback

```bash
ssh usuario@<host> \
  'rm -rf $HA_CONFIG/custom_components/deye_smart_energy_manager'
# + eliminar la config entry en UI (Dispositivos → DSEM → ⋮ → Eliminar)
# + reiniciar HA
```

## 8. Qué NO hace este despliegue

- No toca la integración `solarman` ni la automatización PVPC existente.
- No escribe en ninguna entidad, servicio ni registro Modbus.
- No modifica `configuration.yaml` ni `.storage`.

## 9. Próximas iteraciones tras validar SHADOW

- Ajustar `battery_usable_kwh` con datos reales (SOC vs kWh BMS).
- Verificar `import_series`/`export_series` de InfluxDB contra PVPC/REE.
- Observar error de la curva FV sintetizada vs `froniussymo_alimentacion_ca`.
- Solo entonces: discutir la fase de control real (gating ya implementado).
