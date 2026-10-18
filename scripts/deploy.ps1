# deploy.ps1 — Despliegue de DSEM al host Home Assistant (Windows/PowerShell)
#
# Uso:
#   .\scripts\deploy.ps1 -HAHost ha-host -User usuario -HaConfig /opt/homeassistant
#
# Solo copia ficheros. El reinicio de HA y el alta de la integración se
# hacen manualmente (docs/DEPLOYMENT.md).

param(
    [Parameter(Mandatory=$true)][string]$HAHost,        # host SSH
    [Parameter(Mandatory=$true)][string]$User,          # usuario SSH
    [Parameter(Mandatory=$true)][string]$HaConfig,      # ruta de /config en el host
    [switch]$Check                                      # ejecuta check_config remoto
)

$ErrorActionPreference = "Stop"
$component = "custom_components/deye_smart_energy_manager"
$remote = "${User}@${HAHost}:$HaConfig/custom_components/"

Write-Host "==> Copiando $component -> $remote"
scp -r $component $remote
if ($LASTEXITCODE -ne 0) { throw "scp falló ($LASTEXITCODE)" }

Write-Host "==> Verificando estructura remota"
ssh "${User}@${HAHost}" "ls $HaConfig/custom_components/deye_smart_energy_manager | wc -l"

if ($Check) {
    Write-Host "==> check_config en el contenedor"
    ssh "${User}@${HAHost}" "docker exec homeassistant python -m homeassistant --script check_config -c /config"
}

Write-Host ""
Write-Host "Hecho. Pendiente manual:"
Write-Host "  1. Reiniciar HA (docker restart homeassistant o UI)"
Write-Host "  2. Ajustes -> Anadir integracion -> 'Deye Smart Energy Manager'"
Write-Host "  3. Validar checklist en docs/DEPLOYMENT.md seccion 6"
