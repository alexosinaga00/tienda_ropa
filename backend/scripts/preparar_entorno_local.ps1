# Prepara el entorno local para ensayar los seeds antes de producción:
#   1. enciende el PostgreSQL local (servicio postgresql-x64-17);
#   2. pide, sin mostrarlas, la contraseña del usuario postgres local y la
#      contraseña inicial de los usuarios demo;
#   3. crea (o reemplaza, si confirmas) la base fashionstore_dev;
#   4. copia en ella la base de producción de Railway (solo lectura sobre
#      producción: pg_dump), para ensayar sobre los mismos datos;
#   5. escribe backend\.env con esas contraseñas y una JWT_SECRET_KEY aleatoria;
#   6. aplica las migraciones pendientes (alembic upgrade head).
#
# Ninguna contraseña se muestra en pantalla ni queda en este archivo: solo en
# backend\.env, que está en .gitignore.
#
# Uso, en PowerShell abierto como Administrador (para encender el servicio):
#   powershell -ExecutionPolicy Bypass -File "<ruta>\backend\scripts\preparar_entorno_local.ps1"
$ErrorActionPreference = "Stop"
$backend = Split-Path -Parent $PSScriptRoot
Set-Location $backend

function Plano([Security.SecureString]$s) {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}

# ---------------------------------------------------------------- 1. PostgreSQL local
$servicio = Get-Service -Name "postgresql-x64-17"
if ($servicio.Status -ne "Running") {
    Write-Host "Encendiendo PostgreSQL local..."
    Start-Service -Name "postgresql-x64-17"
}
$bin = @("C:\Program Files\PostgreSQL\18\bin", "C:\Program Files\PostgreSQL\17\bin") | Where-Object { Test-Path "$_\pg_dump.exe" } | Select-Object -First 1
if (-not $bin) { throw "No encuentro pg_dump en C:\Program Files\PostgreSQL" }

# ---------------------------------------------------------------- 2. contraseñas
# psql con -w: nunca pide la contraseña por su cuenta; usa solo PGPASSWORD.
function Psql-Local([string[]]$argumentos) {
    $ErrorActionPreference = "Continue"
    $salida = & "$bin\psql.exe" -w -h localhost -p 5432 -U postgres @argumentos 2>&1 | ForEach-Object { "$_" }
    return @{ ok = ($LASTEXITCODE -eq 0); texto = ($salida -join "`n") }
}

$intentos = 0
while ($true) {
    $pgLocal = Plano (Read-Host "Contraseña del usuario postgres de tu PostgreSQL local (la que usas en pgAdmin)" -AsSecureString)
    if ($pgLocal.Length -eq 0) { Write-Host "  Está vacía: escríbela y luego presiona Enter."; continue }
    $env:PGPASSWORD = $pgLocal
    $prueba = Psql-Local @("-d", "postgres", "-tAc", "SELECT 1")
    if ($prueba.ok) { Write-Host "  Contraseña correcta."; break }
    $intentos += 1
    Write-Host "  PostgreSQL rechazó esa contraseña."
    if ($intentos -ge 3) { throw "Tres intentos fallidos. Si no la recuerdas, avisa en Claude para restablecerla." }
}
do {
    $seed = Plano (Read-Host "Contraseña inicial para los usuarios demo (mínimo 8 caracteres)" -AsSecureString)
    if ($seed.Length -lt 8) { Write-Host "  Debe tener al menos 8 caracteres." }
} while ($seed.Length -lt 8)

# ---------------------------------------------------------------- 3. base local
$existe = (Psql-Local @("-d", "postgres", "-tAc", "SELECT 1 FROM pg_database WHERE datname='fashionstore_dev'")).texto.Trim()
if ($existe -eq "1") {
    $r = Read-Host "La base local fashionstore_dev ya existe. ¿Reemplazarla por la copia de producción? (s/n)"
    if ($r -ne "s") { throw "Cancelado: no se tocó la base local" }
    $x = Psql-Local @("-d", "postgres", "-c", "DROP DATABASE fashionstore_dev WITH (FORCE)")
    if (-not $x.ok) { throw "No pude borrar fashionstore_dev: $($x.texto)" }
}
$x = Psql-Local @("-d", "postgres", "-c", "CREATE DATABASE fashionstore_dev")
if (-not $x.ok) { throw "No pude crear fashionstore_dev: $($x.texto)" }
Write-Host "Base local fashionstore_dev lista."

# ---------------------------------------------------------------- 4. copia de producción
Write-Host "Leyendo la conexión pública de la base de Railway..."
$vars = @{}
foreach ($linea in (railway variables --service Postgres --kv)) {
    $i = $linea.IndexOf("=")
    if ($i -gt 0) { $vars[$linea.Substring(0, $i)] = $linea.Substring($i + 1) }
}
foreach ($k in "PGUSER", "PGPASSWORD", "PGDATABASE", "RAILWAY_TCP_PROXY_DOMAIN", "RAILWAY_TCP_PROXY_PORT") {
    if (-not $vars.ContainsKey($k)) { throw "Falta $k en las variables del servicio Postgres de Railway" }
}
# Railway usa PostgreSQL 18 y el pg_dump local es 17, que se niega a copiar de un
# servidor más nuevo. Se usa el pg_dump 18 de la imagen oficial postgres:18 en
# Docker, en formato SQL plano, que el psql local sí puede cargar.
function Docker-Listo { docker info --format "{{.ServerVersion}}" 2>$null | Out-Null; return $LASTEXITCODE -eq 0 }
if (-not (Docker-Listo)) {
    Write-Host "Abriendo Docker Desktop (puede tardar un par de minutos)..."
    $dd = @("$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe", "C:\Program Files\Docker\Docker\Docker Desktop.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $dd) { throw "No encuentro Docker Desktop: ábrelo a mano y vuelve a correr este script" }
    Start-Process $dd
    $t = 0
    while (-not (Docker-Listo)) { Start-Sleep -Seconds 5; $t += 5; if ($t -ge 240) { throw "Docker no arrancó en 4 minutos" } }
}
$archivo = "fashionstore_produccion.sql"
$dump = Join-Path $env:TEMP $archivo
Write-Host "Copiando producción (pg_dump 18 en Docker, solo lectura)..."
docker run --rm -e "PGPASSWORD=$($vars['PGPASSWORD'])" -v "${env:TEMP}:/salida" postgres:18 `
    pg_dump -h $vars["RAILWAY_TCP_PROXY_DOMAIN"] -p $vars["RAILWAY_TCP_PROXY_PORT"] -U $vars["PGUSER"] `
    -d $vars["PGDATABASE"] --no-owner --no-privileges -f "/salida/$archivo"
if ($LASTEXITCODE -ne 0) { throw "pg_dump falló" }
$env:PGPASSWORD = $pgLocal
Write-Host "Cargando la copia en fashionstore_dev..."
$carga = Psql-Local @("-d", "fashionstore_dev", "-q", "-f", $dump)
$carga.texto -split "`n" | Where-Object { $_ -match "ERROR" } | Select-Object -First 15 | ForEach-Object { Write-Host "  aviso: $_" }
Remove-Item $dump -Force
$tablas = (Psql-Local @("-d", "fashionstore_dev", "-tAc", "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")).texto.Trim()
Write-Host "Tablas copiadas: $tablas (se esperan 61)"
if ($tablas -ne "61") { throw "La copia no quedó completa; pega en Claude los avisos de arriba" }
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
$vars = $null

# ---------------------------------------------------------------- 5. backend\.env
$jwt = -join ((1..48) | ForEach-Object { "{0:x2}" -f (Get-Random -Maximum 256) })
$pgUrl = [Uri]::EscapeDataString($pgLocal)
$contenido = @"
DATABASE_URL=postgresql+psycopg://postgres:$pgUrl@localhost:5432/fashionstore_dev
JWT_SECRET_KEY=$jwt
JWT_ALGORITHM=HS256
CORS_ORIGINS=http://localhost:4200
ENVIRONMENT=local
SEED_PASSWORD_INICIAL=$seed
VENTA_PENDIENTE_MINUTOS=30
TAREAS_AUTOMATICAS=false
"@
[IO.File]::WriteAllText((Join-Path $backend ".env"), $contenido, (New-Object Text.UTF8Encoding $false))
$pgLocal = $null; $seed = $null; $pgUrl = $null; $contenido = $null
Write-Host "backend\.env escrito."

# ---------------------------------------------------------------- 6. migraciones
python -m alembic upgrade head
Write-Host ""
Write-Host "Listo. Avisa en Claude: listo el .env"
