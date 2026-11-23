# DEPLOYMENT — Deye Smart Energy Manager

Despliegue de la integración `deye_smart_energy_manager` en la instancia
**GTS Solutions** (HA Container `core-2026.8.3`, `http://10.0.100.20:8123`).

> ⚠️ El MCP no tiene acceso al filesystem ni a `/config`: el despliegue es
> por SSH/SCP al host Docker. El reinicio de HA puede hacerse por MCP
> (`ha_restart`) o `docker restart`, **siempre con autorización previa**.

## 1. Prerrequisitos

- Acceso SSH al host Docker que ejecuta el contenedor `homeassistant`
  (solo para la vía manual — la vía HACS no lo necesita).
- Ruta del directorio `/config` de HA en el host (p. ej.
  `/opt/homeassistant` o `/srv/homeassistant`). En este documento:
  `$HA_CONFIG`.
- Puerta de control **desactivada** por defecto — el despliegue es seguro:
  tras el reinicio, DSEM arranca en modo `shadow` y `enable_control=false`.

## 2A. Vía HACS (recomendada — actualizaciones desde la UI)

1. Subir este repositorio a GitHub (público; o privado configurando un
   token de GitHub en HACS).
2. En HA: **HACS → ⋮ → Custom repositories** → pegar la URL del repo,
   categoría `Integration` → **Add**.
3. Buscar "Deye Smart Energy Manager" en HACS → **Download** →
   **reiniciar HA**.
4. Cada `git push` a la rama seguida aparecerá como actualización
   disponible en HACS.

La estructura del repo ya cumple el layout de HACS
(`custom_components/deye_smart_energy_manager/` + `hacs.json` en raíz).

## 2B. Vía manual (SSH/SCP)

```bash
# Desde la raíz del repo (host local)
scp -r custom_components/deye_smart_energy_manager \
      usuario@<host>:$HA_CONFIG/custom_components/

# Verificar permisos legibles por el contenedor (root del container lee todo;
# si el bind-mount preserva UID, asegurar lectura):
ssh usuario@<host> 'ls -la $HA_CONFIG/custom_components/deye_smart_energy_manager'
```

Equivalente Windows (PowerShell + OpenSSH): ver `scripts/deploy.ps1`.
También se puede descargar el repo directamente en el host:

```bash
ssh usuario@<host> 'cd /tmp && \
  curl -L https://github.com/<usuario>/<repo>/archive/refs/heads/master.tar.gz \
  | tar xz && cp -r <repo>-master/custom_components/deye_smart_energy_manager \
  $HA_CONFIG/custom_components/'
```

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
| 2 | Entidades `sensor.deye_smart_energy_manager_*` + `select.deye_smart_energy_manager_modo` creadas | Desarrollador → Estados |
| 3 | `sensor.deye_smart_energy_manager_estado_del_optimizador` = `ok` (o con `missing_entities`/`stale_entities` indicando qué falta) | Estado del sensor |
| 4 | `sensor.deye_smart_energy_manager_proxima_accion_del_plan` con `plan_available: true` y 24+ slots | Atributos del sensor |
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

## 9. Releases y actualizaciones

- Cada versión se publica con `git tag vX.Y.Z` + push → HACS la ofrece
  como actualización. Historial: v0.4.0 física descarga autónoma,
  v0.5.x conflicto PVPC + fix stale, v0.6.0 crédito FV,
  v0.7.0 guardia de exportación (zero-export), v0.8.x guardia off_grid,
  v0.9.x headroom FV + modo `auto_export` (vertido permitido) +
  histéresis de persistencia en `off_grid` (v0.9.5).
- **Activación del control** (una sola vez): Opciones → `enable_control`
  = ON → seleccionar modo ejecutor (`auto`…) en
  `select.deye_smart_energy_manager_modo`. La automatización PVPC se
  pausa sola mientras haya modo ejecutor.
- En `shadow`/`manual`/`safe` DSEM no escribe nada; un `off_grid` ON
  puesto por DSEM se restaura a OFF al salir del modo ejecutor.

## 10. Iteraciones futuras posibles

- Perfil de carga por día-tipo (laborable/fin de semana).
- Solcast para curva FV horaria + intervalos P10/P90.
- Optimizer LP con HiGHS si el heurístico se queda corto.
- `microinverter_export_cut_off` queda como ajuste **manual** (opción A,
  decidido 2026-11-20): la causa del vertido fantasma era el regulador
  de tensión intercalado en la acometida, ya eliminado — la medida del CT
  ahora es real. Ver VALIDATION.md §8.
