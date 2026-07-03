#Requires -Version 5.1
#
# VPN Hub — установщик для Windows (Docker Desktop с бэкендом WSL2).
#
#   Локально попробовать:   irm https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.ps1 | iex
#   С параметрами:          скачайте и запустите с флагами:
#                irm ...install.ps1 -OutFile install.ps1
#                powershell -ExecutionPolicy Bypass -File .\install.ps1 -Domain vpn.example.com
#
# Профили и флаги зеркалят install.sh: -Domain (HTTPS через Caddy), -Lan (0.0.0.0 без TLS),
# по умолчанию — только localhost. Повторный запуск С ФЛАГАМИ меняет конфигурацию
# существующей установки; секреты не трогаются. Каждый параметр имеет env-эквивалент
# (INSTALL_DIR, VPNHUB_REF, VPNHUB_TAG, VPNHUB_DOMAIN, VPNHUB_LAN, DATABASE_URL,
# VPNHUB_MASTER_KEY, VPNHUB_BASE_URL, VPNHUB_HTTP_ADDR, VPNHUB_NO_PULL, VPNHUB_DRY_RUN) —
# env учитывается только при НОВОЙ установке.
[CmdletBinding()]
param(
  [string]$InstallDir = $(if ($env:INSTALL_DIR) { $env:INSTALL_DIR } else { Join-Path $env:USERPROFILE 'vpn-hub' }),
  [string]$Ref        = $(if ($env:VPNHUB_REF) { $env:VPNHUB_REF } else { 'master' }),
  [string]$Tag        = $(if ($env:VPNHUB_TAG) { $env:VPNHUB_TAG } else { 'latest' }),
  # Профили (взаимоисключающие): -Domain / -Lan / -LocalOnly (по умолчанию — localhost)
  [string]$Domain     = $(if ($env:VPNHUB_DOMAIN) { $env:VPNHUB_DOMAIN } else { '' }),
  [switch]$Lan        = [bool]($env:VPNHUB_LAN -and $env:VPNHUB_LAN -ne '0'),
  [switch]$LocalOnly,
  [string]$ExternalDb = $(if ($env:DATABASE_URL) { $env:DATABASE_URL } else { '' }),
  [string]$MasterKey  = $(if ($env:VPNHUB_MASTER_KEY) { $env:VPNHUB_MASTER_KEY } else { '' }),
  [string]$AdminPhone    = $(if ($env:VPNHUB_ADMIN_PHONE) { $env:VPNHUB_ADMIN_PHONE } else { '' }),
  [string]$AdminPassword = $(if ($env:VPNHUB_ADMIN_PASSWORD) { $env:VPNHUB_ADMIN_PASSWORD } else { '' }),
  [string]$BaseUrl    = $(if ($env:VPNHUB_BASE_URL) { $env:VPNHUB_BASE_URL } else { '' }),
  [string]$HttpAddr   = $(if ($env:VPNHUB_HTTP_ADDR) { $env:VPNHUB_HTTP_ADDR } else { '' }),
  [switch]$NoPull     = [bool]($env:VPNHUB_NO_PULL -and $env:VPNHUB_NO_PULL -ne '0'),
  # Показать шаги без запуска (проверка/CI): не требует запущенного Docker.
  [switch]$DryRun     = [bool]($env:VPNHUB_DRY_RUN -and $env:VPNHUB_DRY_RUN -ne '0')
)
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$Repo = 'AlexeyShalaev/vpn-hub'

function Write-Info { param($m) Write-Host "[ .. ] $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "[ ok ] $m" -ForegroundColor Green }
function Write-Warn2 { param($m) Write-Host "[warn] $m" -ForegroundColor Yellow }
function Write-Skip { param($m) Write-Host "[dry ] $m" -ForegroundColor DarkGray }
function Die {
  param($m)
  Write-Host "[fail] $m" -ForegroundColor Red
  # exit под `irm | iex` закрыл бы всю консоль пользователя — там бросаем terminating error
  if ($PSCommandPath) { exit 1 } else { throw $m }
}

# ── валидация ввода (до каких-либо изменений) ────────────────────────────────
$profilesChosen = @()
if ($Domain)    { $profilesChosen += 'domain' }
if ($Lan)       { $profilesChosen += 'lan' }
if ($LocalOnly) { $profilesChosen += 'local' }
if ($profilesChosen.Count -gt 1) { Die 'профили -Domain/-Lan/-LocalOnly взаимоисключающие' }

$ProfileName = 'local'
if ($Domain) { $ProfileName = 'domain' } elseif ($Lan) { $ProfileName = 'lan' }

if ($Domain) {
  $orig = $Domain
  $Domain = $Domain -replace '^https?://', '' -replace '/.*$', ''
  $Domain = $Domain.ToLowerInvariant()
  if ($Domain -ne $orig) { Write-Warn2 "домен нормализован: «$orig» → «$Domain»" }
  if ($Domain -eq 'vpn.example.com') { Die 'vpn.example.com — пример из документации; укажите ВАШ домен: -Domain vpn.mydomain.com' }
  if ($Domain -notmatch '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$') {
    Die "«$Domain» не похоже на домен (вид vpn.mydomain.com; кириллический — в punycode: xn--…)"
  }
}

if ($ExternalDb) {
  if ($ExternalDb -match '^postgres(ql)?://') {
    $ExternalDb = $ExternalDb -replace '^postgres(ql)?://', 'postgresql+asyncpg://'
    Write-Warn2 'драйвер DSN переписан на postgresql+asyncpg:// (обязателен для панели)'
  }
  if ($ExternalDb -notmatch '^postgresql\+asyncpg://') { Die 'DSN внешней БД: postgresql+asyncpg://user:pass@host:5432/db' }
  if ($ExternalDb -match '\s') { Die 'DSN содержит пробел — спецсимволы пароля URL-кодируйте (@ → %40, пробел → %20)' }
  if ($ExternalDb -notmatch 'ssl=' -and $ExternalDb -notmatch '@(localhost|127\.0\.0\.1|host\.docker\.internal)') {
    Write-Warn2 'в DSN нет ssl= — managed-БД обычно требуют ?ssl=require'
  }
}

if (($AdminPhone -and -not $AdminPassword) -or ($AdminPassword -and -not $AdminPhone)) {
  Die '-AdminPhone и -AdminPassword работают только ПАРОЙ (иначе setup-экран скроется, а админ не создастся)'
}
if ($AdminPhone -and ("$AdminPhone$AdminPassword" -match '[\s"'']')) {
  Die 'телефон/пароль админа не должны содержать пробелов и кавычек (сложный пароль задайте на setup-экране)'
}
if ($AdminPassword -and $AdminPassword.Length -lt 8) { Die 'пароль администратора: минимум 8 символов' }
if ($MasterKey) {
  if ($MasterKey -match '[\s"''$]') { Die 'мастер-ключ не должен содержать пробелов, кавычек и $' }
  if ($MasterKey.Length -lt 8) { Die 'мастер-ключ: минимум 8 символов (рекомендуется openssl rand -hex 32)' }
  if ($MasterKey.Length -lt 32) { Write-Warn2 'мастер-ключ короче 32 символов — для нового ключа лучше 64 hex-символа' }
}
if ($HttpAddr -and $HttpAddr -notmatch ':[0-9]+$') { Die '-HttpAddr ожидает вид host:port, например 127.0.0.1:8000' }

# ── prerequisites ─────────────────────────────────────────────────────────────
# try/catch вокруг native-команд не работает (ненулевой exit code не бросает
# исключение) — проверяем $LASTEXITCODE явно.
if ($DryRun) { Write-Info 'DRY-RUN: показываю шаги, ничего не запускаю (Docker не требуется)' }
if (-not $DryRun) {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Die 'Docker не найден. Установите Docker Desktop (бэкенд WSL2): https://docs.docker.com/desktop/install/windows-install/'
  }
  docker info *> $null
  if ($LASTEXITCODE) { Die 'демон Docker недоступен — запустите Docker Desktop' }
  docker compose version *> $null
  if ($LASTEXITCODE) { Die 'нет плагина Docker Compose v2 — обновите Docker Desktop' }
  Write-Ok 'Docker и Compose на месте'
} else {
  Write-Skip 'проверки Docker пропущены (dry-run)'
}

# ── crypto-secret (аналог openssl rand -hex 32) ──────────────────────────────
function New-Secret {
  $bytes = New-Object 'System.Byte[]' 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
}

# $ → $$ — иначе docker compose интерполирует значение при чтении .env
function ConvertTo-EnvValue { param([string]$v) $v -replace '\$', '$$$$' }

function Get-PublicIP {
  foreach ($svc in 'https://icanhazip.com', 'https://api.ipify.org', 'https://checkip.amazonaws.com') {
    try {
      $ip = (Invoke-RestMethod -UseBasicParsing -Uri $svc -TimeoutSec 5).ToString().Trim()
      if ($ip -match '^\d{1,3}(\.\d{1,3}){3}$') { return $ip }
    } catch { }
  }
  return ''
}

$EnvFile = Join-Path $InstallDir '.env'
$Fresh   = -not (Test-Path $EnvFile)

# .env читаем/пишем строго UTF-8 без BOM (Get-Content/Set-Content в WinPS 5.1 без BOM
# читают ANSI и портят не-ASCII — комментарии и значения)
function Read-EnvLines {
  if (Test-Path $EnvFile) { [System.IO.File]::ReadAllLines($EnvFile) } else { @() }
}

function Get-EnvKey { param([string]$Key)
  $line = Read-EnvLines | Where-Object { $_ -like "$Key=*" } | Select-Object -Last 1
  if ($line) { return $line.Substring($Key.Length + 1) } else { return '' }
}

$SecretKeyPattern = 'PASSWORD|_KEY|TOKEN|^DATABASE_URL$'
function Set-EnvKey { param([string]$Key, [string]$Value)
  $old = Get-EnvKey $Key
  if ($old -eq $Value) { return }
  # значения секретов не печатаем
  $newShown = if ($Key -match $SecretKeyPattern) { '(обновлено)' } else { $Value }
  $oldShown = if ($Key -match $SecretKeyPattern) { if ($old) { '(скрыто)' } else { '' } } else { $old }
  if ($DryRun) { Write-Skip "записал бы в .env: $Key=$newShown"; return }
  $lines = @(Read-EnvLines | Where-Object { $_ -notlike "$Key=*" })
  $lines += "$Key=$Value"
  [System.IO.File]::WriteAllLines($EnvFile, $lines)
  if ($old) { Write-Ok "${Key}: $oldShown → $newShown" } else { Write-Ok "$Key = $newShown" }
}

# ── реконфигурация существующей установки: только явные параметры ────────────
$Explicit = $PSBoundParameters
$ProfileExplicit = $Explicit.ContainsKey('Domain') -or $Explicit.ContainsKey('Lan') -or $Explicit.ContainsKey('LocalOnly')
if (-not $Fresh) {
  if ($Explicit.ContainsKey('MasterKey') -and $MasterKey -ne (Get-EnvKey 'VPNHUB_MASTER_KEY')) {
    Die 'мастер-ключ существующей установки не меняется. Для переноса используйте -MasterKey при чистой установке.'
  }
  if ($Explicit.ContainsKey('ExternalDb') -and -not (Get-EnvKey 'DATABASE_URL')) {
    Die 'смена БД у существующей установки не поддерживается: снимите .vhb-бэкап, поставьте заново с -ExternalDb и восстановитесь.'
  }
  if (-not $ProfileExplicit) {
    # профиль не меняем — восстанавливаем текущий из .env (env-переменные не считаются)
    if ((Get-EnvKey 'COMPOSE_FILE') -like '*caddy*') { $ProfileName = 'domain'; $Domain = Get-EnvKey 'VPNHUB_DOMAIN' }
    elseif ((Get-EnvKey 'VPNHUB_HTTP_ADDR') -like '0.0.0.0:*') { $ProfileName = 'lan' }
    else { $ProfileName = 'local' }
  }
  if ((Get-EnvKey 'DATABASE_URL') -and -not $Explicit.ContainsKey('ExternalDb')) { $ExternalDb = Get-EnvKey 'DATABASE_URL' }
}

# ── профиль → файлы и адреса ─────────────────────────────────────────────────
$MainCompose = if ($ExternalDb) { 'compose.external-db.yaml' } else { 'compose.yaml' }
# на Windows разделитель путей в COMPOSE_FILE — точка с запятой
$ComposeFiles = if ($ProfileName -eq 'domain') { "$MainCompose;caddy.compose.yaml" } else { $MainCompose }

switch ($ProfileName) {
  'domain' {
    if (-not $Domain) { Die 'профиль domain без домена: в .env есть Caddy-оверлей, но нет VPNHUB_DOMAIN — задайте -Domain vpn.mydomain.com' }
    if (-not $Explicit.ContainsKey('BaseUrl'))  { $BaseUrl  = "https://$Domain" }
    if (-not $Explicit.ContainsKey('HttpAddr')) { $HttpAddr = '127.0.0.1:8000' }
  }
  'lan' {
    if (-not $Explicit.ContainsKey('HttpAddr')) { $HttpAddr = '0.0.0.0:8000' }
    if (-not $Explicit.ContainsKey('BaseUrl')) {
      $port = $HttpAddr.Split(':')[-1]
      $ip = if ($DryRun) { '' } else { Get-PublicIP }
      if ($ip) { $BaseUrl = "http://${ip}:$port" }
      else {
        $BaseUrl = "http://localhost:$port"
        if (-not $DryRun) { Write-Warn2 'не удалось определить публичный IP — VPNHUB_BASE_URL укажет на localhost, поправьте при необходимости (-BaseUrl)' }
      }
    }
  }
  default {
    if (-not $Explicit.ContainsKey('HttpAddr') -and -not ($Fresh -and $HttpAddr)) { $HttpAddr = '127.0.0.1:8000' }
    if (-not $Explicit.ContainsKey('BaseUrl')  -and -not ($Fresh -and $BaseUrl))  { $BaseUrl = 'http://localhost:' + $HttpAddr.Split(':')[-1] }
  }
}

# ── файлы стека ───────────────────────────────────────────────────────────────
if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null }
# VPNHUB_RAW_BASE — переопределение источника файлов (CI/локальная проверка)
$Raw = if ($env:VPNHUB_RAW_BASE) { $env:VPNHUB_RAW_BASE } else { "https://raw.githubusercontent.com/$Repo/$Ref/deploy/compose" }

function Get-StackFile { param([string]$Name)
  if ($DryRun) { Write-Skip "скачал бы $Raw/$Name → $InstallDir\$Name"; return }
  try { Invoke-WebRequest -UseBasicParsing -Uri "$Raw/$Name" -OutFile (Join-Path $InstallDir $Name) }
  catch { Die "не удалось скачать $Raw/$Name (нет сети? опечатка в -Ref?)" }
}

Write-Info "Скачиваю $MainCompose ($Ref)…"
Get-StackFile $MainCompose
if ($ProfileName -eq 'domain') {
  Write-Info 'Скачиваю Caddy-оверлей (автоматический HTTPS)…'
  Get-StackFile 'caddy.compose.yaml'
  Get-StackFile 'Caddyfile'
}

# ── .env: новая установка или точечный upsert ─────────────────────────────────
if ($Fresh) {
  if ($DryRun) {
    Write-Skip "сгенерировал бы $EnvFile со свежими секретами: COMPOSE_FILE=$ComposeFiles, профиль $ProfileName"
  } else {
    $lines = @(
      '# Сгенерировано install.ps1. Секретно.'
      '# Изменить конфигурацию: повторный запуск install.ps1 с параметрами (-Domain/-Lan/-LocalOnly/-Tag ...).'
      "COMPOSE_FILE=$ComposeFiles"
      "VPNHUB_MASTER_KEY=$(if ($MasterKey) { $MasterKey } else { New-Secret })"
    )
    if ($ExternalDb) { $lines += "DATABASE_URL=$(ConvertTo-EnvValue $ExternalDb)" }
    else             { $lines += "POSTGRES_PASSWORD=$(New-Secret)" }
    $lines += @(
      "VPNHUB_BASE_URL=$BaseUrl"
      "VPNHUB_HTTP_ADDR=$HttpAddr"
      "VPNHUB_TAG=$Tag"
      '# Токен доступа к /metrics (Prometheus): Authorization: Bearer <токен>.'
      "VPNHUB_METRICS_TOKEN=$(New-Secret)"
    )
    if ($Domain)     { $lines += "VPNHUB_DOMAIN=$Domain" }
    if ($AdminPhone) { $lines += "VPNHUB_ADMIN_PHONE=$AdminPhone"; $lines += "VPNHUB_ADMIN_PASSWORD=$(ConvertTo-EnvValue $AdminPassword)" }
    [System.IO.File]::WriteAllLines($EnvFile, $lines)
    # NTFS-эквивалент chmod 600: только текущий пользователь
    icacls $EnvFile /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
    Write-Ok "Записал $EnvFile со свежими секретами (доступ только владельцу)"
  }
} else {
  # Миграция legacy: рукописный Caddy-оверлей без COMPOSE_FILE усыновляем как есть
  if (-not (Get-EnvKey 'COMPOSE_FILE') -and -not $ProfileExplicit -and (Test-Path (Join-Path $InstallDir 'caddy.compose.yaml'))) {
    $ComposeFiles = "$MainCompose;caddy.compose.yaml"
    Write-Info 'найден Caddy-оверлей без COMPOSE_FILE — закрепляю его в .env (обновления перестанут его терять)'
  }
  Set-EnvKey 'COMPOSE_FILE' $ComposeFiles
  $changed = $false
  if ($ProfileExplicit) {
    Set-EnvKey 'VPNHUB_BASE_URL' $BaseUrl
    Set-EnvKey 'VPNHUB_HTTP_ADDR' $HttpAddr
    if ($ProfileName -eq 'domain') { Set-EnvKey 'VPNHUB_DOMAIN' $Domain }
    $changed = $true
  }
  if ($Explicit.ContainsKey('BaseUrl'))  { Set-EnvKey 'VPNHUB_BASE_URL' $BaseUrl;  $changed = $true }
  if ($Explicit.ContainsKey('HttpAddr')) { Set-EnvKey 'VPNHUB_HTTP_ADDR' $HttpAddr; $changed = $true }
  if ($Explicit.ContainsKey('Tag'))      { Set-EnvKey 'VPNHUB_TAG' $Tag; $changed = $true }
  # ротация реквизитов той же внешней БД (смена типа БД отсечена Die выше)
  if ($Explicit.ContainsKey('ExternalDb')) { Set-EnvKey 'DATABASE_URL' (ConvertTo-EnvValue $ExternalDb); $changed = $true }
  if ($Explicit.ContainsKey('AdminPhone')) {
    Set-EnvKey 'VPNHUB_ADMIN_PHONE' $AdminPhone
    Set-EnvKey 'VPNHUB_ADMIN_PASSWORD' (ConvertTo-EnvValue $AdminPassword)
    $changed = $true
  }
  if (-not $changed) { Write-Ok '.env уже существует — секреты и настройки сохранены (изменить: повторный запуск с параметрами)' }
}

# ── запуск ────────────────────────────────────────────────────────────────────
if ($DryRun) {
  Write-Skip 'поднял бы стек: docker compose --env-file .env pull; docker compose --env-file .env up -d --remove-orphans'
} else {
  Push-Location $InstallDir
  try {
    if (-not $NoPull) {
      Write-Info 'Тяну образы…'
      docker compose --env-file .env pull
      if ($LASTEXITCODE) { Die 'docker compose pull завершился с ошибкой — см. вывод выше' }
    }
    Write-Info 'Поднимаю стек…'
    docker compose --env-file .env up -d --remove-orphans
    if ($LASTEXITCODE) { Die 'docker compose up завершился с ошибкой — см. вывод выше' }
  } finally { Pop-Location }
  Write-Ok 'Контейнеры запущены'
}

# ── ждём готовности панели ────────────────────────────────────────────────────
$addr = Get-EnvKey 'VPNHUB_HTTP_ADDR'; if (-not $addr) { $addr = $HttpAddr }
$port = $addr.Split(':')[-1]
$probeHost = $addr.Substring(0, $addr.LastIndexOf(':'))
if (-not $probeHost -or $probeHost -eq '0.0.0.0') { $probeHost = '127.0.0.1' }
$timeoutSec = if ($env:VPNHUB_HEALTH_TIMEOUT) { [int]$env:VPNHUB_HEALTH_TIMEOUT } else { 120 }
if (-not $DryRun -and $timeoutSec -gt 0) {
  Write-Info 'Жду готовности панели (миграции на первом старте занимают до минуты)…'
  $deadline = (Get-Date).AddSeconds($timeoutSec); $healthy = $false
  while ((Get-Date) -lt $deadline) {
    try {
      Invoke-WebRequest -UseBasicParsing -Uri "http://${probeHost}:$port/healthz" -TimeoutSec 3 | Out-Null
      $healthy = $true; break
    } catch { Start-Sleep -Seconds 3 }
  }
  if ($healthy) { Write-Ok 'Панель отвечает' }
  else {
    Write-Warn2 "панель не ответила за ${timeoutSec}s — контейнеры оставлены для диагностики"
    Die "логи:  cd $InstallDir; docker compose logs -f app"
  }
}

# ── финальный вывод ───────────────────────────────────────────────────────────
$finalUrl = Get-EnvKey 'VPNHUB_BASE_URL'; if (-not $finalUrl) { $finalUrl = $BaseUrl }
$finalTag = Get-EnvKey 'VPNHUB_TAG'; if (-not $finalTag) { $finalTag = $Tag }
Write-Host ''
if ($DryRun) { Write-Host "dry-run завершён — ничего не запущено (профиль: $ProfileName)." -ForegroundColor Green }
else { Write-Host "VPN Hub установлен (профиль: $ProfileName)." -ForegroundColor Green }
Write-Host "  Каталог:  $InstallDir"
Write-Host "  Секреты:  $EnvFile"
Write-Host "  Адрес:    $finalUrl"
Write-Host ''
Write-Host '⚠ Мастер-ключ: скопируйте VPNHUB_MASTER_KEY из .env в менеджер паролей ПРЯМО СЕЙЧАС —' -ForegroundColor Yellow
Write-Host '  им зашифрованы SSH-доступы и бэкапы, потеря необратима.' -ForegroundColor Yellow
if ($ProfileName -eq 'domain') {
  Write-Host ''
  Write-Host "Дальше: A-запись $Domain → IP этой машины, откройте 80/443, затем https://$Domain"
} else {
  Write-Host ''
  Write-Host "Дальше: откройте $finalUrl — первичная настройка (создание администратора)."
}
Write-Host ''
Write-Host "Управление (из ${InstallDir}): docker compose ps / logs -f app / down"
# машиночитаемый итог — всегда последней строкой (в т.ч. в dry-run)
@{ url = $finalUrl; dir = $InstallDir; profile = $ProfileName; composeFiles = $ComposeFiles; tag = $finalTag } | ConvertTo-Json -Compress
