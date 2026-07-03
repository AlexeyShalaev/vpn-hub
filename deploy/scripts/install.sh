#!/usr/bin/env bash
#
# VPN Hub — установщик (Docker Compose).
#
#   Локально попробовать:   curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.sh | bash
#   VPS с доменом + HTTPS:  curl -fsSL .../install.sh | bash -s -- --domain vpn.example.com
#   Безопаснее:  скачайте, прочитайте, запустите:
#                curl -fsSL .../install.sh -o install.sh && less install.sh && bash install.sh
#
# Что делает: проверяет Docker + Compose v2, кладёт compose-файлы в каталог установки,
# генерирует .env со случайными секретами, поднимает стек и ждёт готовности панели.
# Повторный запуск С ФЛАГАМИ меняет конфигурацию существующей установки (секреты не трогаются).
#
# Профили (взаимоисключающие; или переменные окружения):
#   --local             панель только на этой машине: 127.0.0.1:8000 (по умолчанию)
#   --lan               доступ по IP без HTTPS: 0.0.0.0:8000     (VPNHUB_LAN=1)
#   --domain DOMAIN     домен + автоматический HTTPS через Caddy (VPNHUB_DOMAIN)
# Модификаторы:
#   --external-db DSN   не поднимать свой Postgres; postgresql+asyncpg://…  (DATABASE_URL)
#   --tag TAG           тег образа: latest / 1.2.3 / 1.2        (VPNHUB_TAG, по умолч. latest)
#   --master-key HEX    свой мастер-ключ (перенос/восстановление; только новая установка)
#   --admin-phone P --admin-password W   создать администратора при старте (строго парой)
#   --base-url URL      публичный адрес вручную                 (VPNHUB_BASE_URL)
#   --http-addr ADDR    куда публиковать порт хоста             (VPNHUB_HTTP_ADDR)
#   --dir PATH          каталог установки            (INSTALL_DIR, по умолч. $HOME/vpn-hub)
#   --ref REF           ветка/тег репозитория         (VPNHUB_REF, по умолч. master)
# Служебные:
#   --no-pull           не тянуть образы заранее (CI/air-gapped)  (VPNHUB_NO_PULL=1)
#   --dry-run           показать действия, ничего не выполняя     (VPNHUB_DRY_RUN=1)
#   -h | --help         эта справка
set -euo pipefail

REPO="AlexeyShalaev/vpn-hub"
INSTALL_DIR="${INSTALL_DIR:-$HOME/vpn-hub}"
VPNHUB_REF="${VPNHUB_REF:-master}"
VPNHUB_TAG="${VPNHUB_TAG:-latest}"
VPNHUB_BASE_URL="${VPNHUB_BASE_URL:-}"
VPNHUB_HTTP_ADDR="${VPNHUB_HTTP_ADDR:-}"
DOMAIN="${VPNHUB_DOMAIN:-}"
LAN="${VPNHUB_LAN:-0}"
EXTERNAL_DB="${DATABASE_URL:-}"
MASTER_KEY="${VPNHUB_MASTER_KEY:-}"
ADMIN_PHONE="${VPNHUB_ADMIN_PHONE:-}"
ADMIN_PASSWORD="${VPNHUB_ADMIN_PASSWORD:-}"
NO_PULL="${VPNHUB_NO_PULL:-0}"
DRY_RUN="${VPNHUB_DRY_RUN:-0}"

# Явно переданные CLI-флаги: на существующей установке конфигурацию меняют ТОЛЬКО они
# (env-переменные могли «прилипнуть» в профиле шелла — их учитываем лишь при новой установке).
CLI_PROFILE=""      # local | lan | domain — если профиль задан флагом
CLI_TAG=0 CLI_BASE_URL=0 CLI_HTTP_ADDR=0 CLI_ADMIN=0 CLI_EXTERNAL_DB=0 CLI_MASTER_KEY=0

# ── вывод ─────────────────────────────────────────────────────────────────────
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'; C_BLU=$'\033[34m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_RED=; C_GRN=; C_YLW=; C_BLU=; C_DIM=; C_RST=
fi
info()  { printf '%s[ .. ]%s %s\n' "$C_BLU" "$C_RST" "$*"; }
ok()    { printf '%s[ ok ]%s %s\n' "$C_GRN" "$C_RST" "$*"; }
warn()  { printf '%s[warn]%s %s\n' "$C_YLW" "$C_RST" "$*" >&2; }
fatal() { printf '%s[fail]%s %s\n' "$C_RED" "$C_RST" "$*" >&2; exit 1; }

command_exists() { command -v "$@" >/dev/null 2>&1; }

usage() {
  # при `curl … | bash -s -- --help` $0 — это «bash», текст шапки оттуда не достать
  if [ -f "$0" ] && head -n 3 "$0" 2>/dev/null | grep -q 'VPN Hub'; then
    sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; s/^#//' | sed '$d'
  else
    printf 'VPN Hub — установщик. Профили: --local (по умолч.) | --lan | --domain D.\n'
    printf 'Прочее: --external-db DSN, --tag, --master-key, --admin-phone/--admin-password,\n'
    printf '        --base-url, --http-addr, --dir, --ref, --no-pull, --dry-run.\n'
    printf 'Полная справка: https://alexeyshalaev.github.io/vpn-hub/deploy/scripts/\n'
  fi
}

# ── разбор аргументов и валидация ввода (ДО каких-либо изменений на диске) ────
parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --dir)            INSTALL_DIR="$2"; shift 2 ;;
      --ref)            VPNHUB_REF="$2"; shift 2 ;;
      --tag)            VPNHUB_TAG="$2"; CLI_TAG=1; shift 2 ;;
      --local)          [ -n "$CLI_PROFILE" ] && fatal "профили --local/--lan/--domain взаимоисключающие"
                        CLI_PROFILE="local"; shift ;;
      --lan)            [ -n "$CLI_PROFILE" ] && fatal "профили --local/--lan/--domain взаимоисключающие"
                        CLI_PROFILE="lan"; LAN=1; shift ;;
      --domain)         [ -n "$CLI_PROFILE" ] && fatal "профили --local/--lan/--domain взаимоисключающие"
                        CLI_PROFILE="domain"; DOMAIN="$2"; shift 2 ;;
      --external-db)    EXTERNAL_DB="$2"; CLI_EXTERNAL_DB=1; shift 2 ;;
      --master-key)     MASTER_KEY="$2"; CLI_MASTER_KEY=1; shift 2 ;;
      --admin-phone)    ADMIN_PHONE="$2"; CLI_ADMIN=1; shift 2 ;;
      --admin-password) ADMIN_PASSWORD="$2"; CLI_ADMIN=1; shift 2 ;;
      --base-url)       VPNHUB_BASE_URL="$2"; CLI_BASE_URL=1; shift 2 ;;
      --http-addr)      VPNHUB_HTTP_ADDR="$2"; CLI_HTTP_ADDR=1; shift 2 ;;
      --no-pull)        NO_PULL=1; shift ;;
      --dry-run)        DRY_RUN=1; shift ;;
      -h|--help)        usage; exit 0 ;;
      *) fatal "неизвестная опция: $1 (см. --help)" ;;
    esac
  done

  # env-заданный профиль (для новой установки / cloud-init): домен приоритетнее LAN.
  # На существующей установке plan_config пересчитает профиль из .env — env там не считается.
  if [ -z "$CLI_PROFILE" ]; then
    if [ -n "$DOMAIN" ]; then PROFILE="domain"
    elif [ "$LAN" = 1 ];  then PROFILE="lan"
    else PROFILE="local"; fi
  else
    PROFILE="$CLI_PROFILE"
  fi
}

sanitize_domain() {
  local d="$1" orig="$1"
  d="${d#http://}"; d="${d#https://}"; d="${d%%/*}"
  d="$(printf '%s' "$d" | tr '[:upper:]' '[:lower:]')"
  [ "$d" != "$orig" ] && warn "домен нормализован: «${orig}» → «${d}»"
  [ "$d" = "vpn.example.com" ] && fatal "vpn.example.com — пример из документации; укажите ВАШ домен: --domain vpn.мойдомен.ру"
  printf '%s' "$d" | grep -Eq '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$' \
    || fatal "«${d}» не похоже на домен (ожидается вид vpn.mydomain.com, без схемы и пути; кириллический домен укажите в punycode: xn--…)"
  DOMAIN="$d"
}

normalize_dsn() {
  case "$EXTERNAL_DB" in
    postgresql+asyncpg://*) : ;;
    postgres://*)
      EXTERNAL_DB="postgresql+asyncpg://${EXTERNAL_DB#postgres://}"
      warn "драйвер DSN переписан: postgres:// → postgresql+asyncpg:// (обязателен для панели)" ;;
    postgresql://*)
      EXTERNAL_DB="postgresql+asyncpg://${EXTERNAL_DB#postgresql://}"
      warn "драйвер DSN переписан: postgresql:// → postgresql+asyncpg:// (обязателен для панели)" ;;
    *) fatal "DSN внешней БД должен начинаться с postgresql+asyncpg:// (формат: postgresql+asyncpg://user:pass@host:5432/db)" ;;
  esac
  case "$EXTERNAL_DB" in
    *ssl=*) : ;;
    *@localhost*|*@127.0.0.1*|*@host.docker.internal*) : ;;
    *) warn "в DSN нет ssl= — managed-БД (RDS/Cloud SQL/Neon) обычно требуют ?ssl=require" ;;
  esac
  case "$EXTERNAL_DB" in
    *" "*) fatal "DSN содержит пробел — спецсимволы пароля URL-кодируйте (@→%40, :→%3A, /→%2F, пробел→%20)" ;;
  esac
}

validate_pairs() {
  if [ -n "$ADMIN_PHONE$ADMIN_PASSWORD" ]; then
    { [ -n "$ADMIN_PHONE" ] && [ -n "$ADMIN_PASSWORD" ]; } \
      || fatal "--admin-phone и --admin-password работают только ПАРОЙ (одиночный телефон скрывает setup-экран, но админа не создаёт)"
    case "$ADMIN_PHONE$ADMIN_PASSWORD" in *[\ \"\']*) fatal "телефон/пароль админа не должны содержать пробелов и кавычек (сложный пароль задайте на setup-экране)" ;; esac
    [ "${#ADMIN_PASSWORD}" -ge 8 ] || fatal "пароль администратора: минимум 8 символов"
  fi
  if [ -n "$MASTER_KEY" ]; then
    case "$MASTER_KEY" in *[\ \"\'\$]*) fatal "мастер-ключ не должен содержать пробелов, кавычек и \$" ;; esac
    [ "${#MASTER_KEY}" -ge 8 ] || fatal "мастер-ключ: минимум 8 символов (рекомендуется openssl rand -hex 32)"
    [ "${#MASTER_KEY}" -lt 32 ] && warn "мастер-ключ короче 32 символов — для нового ключа лучше openssl rand -hex 32"
  fi
  if [ -n "$VPNHUB_HTTP_ADDR" ]; then
    case "$VPNHUB_HTTP_ADDR" in
      *:[0-9]*) : ;;
      *) fatal "--http-addr ожидает вид host:port, например 127.0.0.1:8000 или 0.0.0.0:9000" ;;
    esac
  fi
}

# ── платформа и Docker ────────────────────────────────────────────────────────
detect_platform() {
  local arch; arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64|arm64|aarch64) : ;;
    *) warn "архитектура $arch: образ собран под amd64/arm64, возможна эмуляция" ;;
  esac
  case "$(uname -s)" in
    Linux)  : ;;
    Darwin) warn "macOS — годится для локального теста; прод разворачивайте на Linux" ;;
    *)      fatal "неподдерживаемая ОС. На Windows используйте install.ps1 (или WSL2)" ;;
  esac
}

require_docker() {
  # В dry-run живой демон не нужен — показываем шаги без запуска (так CI гоняет скрипт на любой ОС).
  if [ "$DRY_RUN" = 1 ]; then
    command_exists docker || warn "Docker не найден — dry-run продолжает без него"
    ok "dry-run: проверки Docker пропущены"
    return 0
  fi
  command_exists docker || fatal "Docker не найден. Установите: https://docs.docker.com/engine/install/"
  docker info >/dev/null 2>&1 || fatal "демон Docker недоступен (запущен? нужен sudo / группа docker?)"
  docker compose version >/dev/null 2>&1 \
    || fatal "нет плагина Docker Compose v2. Установите: https://docs.docker.com/compose/install/"
  ok "Docker и Compose на месте (docker compose)"
}

# ── помощники: секреты, сеть, http ────────────────────────────────────────────
gen_secret() {
  if command_exists openssl; then openssl rand -hex 32
  elif [ -r /dev/urandom ]; then LC_ALL=C tr -dc 'a-f0-9' < /dev/urandom | head -c 64; echo
  else fatal "нет openssl и /dev/urandom — не могу сгенерировать секрет"; fi
}

http_get() { # http_get URL  → stdout (пусто/код!=0 при неудаче)
  if command_exists curl; then curl -fsS --max-time 5 "$1" 2>/dev/null
  elif command_exists wget; then wget -qO- --timeout=5 "$1" 2>/dev/null
  else return 1; fi
}

download() { # download URL DEST
  if [ "$DRY_RUN" = 1 ]; then info "скачал бы $1 → $2"; return 0; fi
  if command_exists curl; then
    curl -fsSL "$1" -o "$2" || fatal "не удалось скачать $1 (нет сети? опечатка в --ref?)"
  elif command_exists wget; then
    wget -qO "$2" "$1" || { rm -f "$2"; fatal "не удалось скачать $1 (нет сети? опечатка в --ref?)"; }
  else fatal "нужен curl или wget"; fi
}

PUBLIC_IP=""
detect_public_ip() {
  [ -n "$PUBLIC_IP" ] && return 0
  local svc ip
  for svc in "https://icanhazip.com" "https://api.ipify.org" "https://checkip.amazonaws.com"; do
    ip="$(http_get "$svc" | tr -d '[:space:]')" || ip=""
    case "$ip" in
      "") continue ;;
      *[!0-9.]*) continue ;;
      *) PUBLIC_IP="$ip"; return 0 ;;
    esac
  done
  return 1
}

port_busy() { # port_busy PORT — 0, если кто-то уже слушает на 127.0.0.1:PORT
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

resolve_domain() { # resolve_domain DOMAIN → первый A-адрес или пусто
  if command_exists getent; then getent hosts "$1" 2>/dev/null | awk '{print $1; exit}'
  elif command_exists dig; then dig +short A "$1" 2>/dev/null | awk '/^[0-9.]+$/{print; exit}'
  elif command_exists host; then host -t A "$1" 2>/dev/null | awk '/has address/{print $NF; exit}'
  fi
}

# ── работа с .env: чтение и точечный upsert (без sed — значения с любыми символами) ──
ENV_FILE=""   # задаётся в main
env_get() { # env_get KEY → значение (последнее вхождение) или пусто
  [ -f "$ENV_FILE" ] || return 0
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

env_upsert() { # env_upsert KEY VALUE — записывает с печатью диффа «старое → новое»
  local key="$1" val="$2" old tmp shown_old shown_new
  old="$(env_get "$key")"
  [ "$old" = "$val" ] && return 0
  # значения секретов не печатаем (пароли/DSN попали бы в stdout и логи CI)
  case "$key" in
    *PASSWORD*|*_KEY*|*TOKEN*|DATABASE_URL) shown_old="${old:+(скрыто)}"; shown_new="(обновлено)" ;;
    *) shown_old="$old"; shown_new="$val" ;;
  esac
  if [ "$DRY_RUN" = 1 ]; then
    info "записал бы в .env: $key=$shown_new${shown_old:+  (было: $shown_old)}"
    return 0
  fi
  tmp="$(mktemp)"
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$val" >> "$tmp"
  cat "$tmp" > "$ENV_FILE"; rm -f "$tmp"
  if [ -n "$old" ]; then ok "$key: $shown_old → $shown_new"; else ok "$key = $shown_new"; fi
}

escape_env_value() { # $ → $$ (иначе docker compose интерполирует значение при чтении .env)
  printf '%s' "$1" | sed 's/\$/$$/g'
}

# ── compose из каталога установки (.env оттуда же ⇒ COMPOSE_FILE учитывается) ──
compose() {
  if [ "$DRY_RUN" = 1 ]; then
    printf '%s+ (cd %s && docker compose %s)%s\n' "$C_DIM" "$INSTALL_DIR" "$*" "$C_RST"
    return 0
  fi
  ( cd "$INSTALL_DIR" && docker compose --env-file .env "$@" )
}

# ── конфигурация: профиль → файлы и переменные ────────────────────────────────
MAIN_COMPOSE="compose.yaml"
COMPOSE_FILES=""
FRESH=1

plan_config() {
  ENV_FILE="$INSTALL_DIR/.env"
  [ -f "$ENV_FILE" ] && FRESH=0

  if [ "$FRESH" = 0 ]; then
    # Существующая установка: env-переменные «явными» не считаем — сбрасываем всё, что пришло
    # не из CLI-флагов («прилипший» в профиле шелла VPNHUB_DOMAIN не должен молча переключать профиль).
    [ "$CLI_MASTER_KEY" = 1 ]  || MASTER_KEY=""
    [ "$CLI_EXTERNAL_DB" = 1 ] || EXTERNAL_DB=""
    [ "$CLI_ADMIN" = 1 ]       || { ADMIN_PHONE=""; ADMIN_PASSWORD=""; }
    [ "$CLI_BASE_URL" = 1 ]    || VPNHUB_BASE_URL=""
    [ "$CLI_HTTP_ADDR" = 1 ]   || VPNHUB_HTTP_ADDR=""
    if [ -z "$CLI_PROFILE" ]; then
      # профиль существующей установки — строго из .env
      case "$(env_get COMPOSE_FILE)" in
        *caddy*) PROFILE="domain"; DOMAIN="$(env_get VPNHUB_DOMAIN)" ;;
        *)
          DOMAIN=""
          case "$(env_get VPNHUB_HTTP_ADDR)" in 0.0.0.0:*) PROFILE="lan" ;; *) PROFILE="local" ;; esac
          ;;
      esac
    fi
    # Неизменяемые параметры: громкий отказ вместо молчаливого игнора
    [ "$CLI_MASTER_KEY" = 1 ] && [ "$MASTER_KEY" != "$(env_get VPNHUB_MASTER_KEY)" ] \
      && fatal "мастер-ключ существующей установки не меняется (это сломает расшифровку секретов). Для переноса на НОВУЮ машину используйте --master-key при чистой установке."
    if [ "$CLI_EXTERNAL_DB" = 1 ] && [ -z "$(env_get DATABASE_URL)" ]; then
      fatal "смена БД у существующей установки не поддерживается: данные не переносятся. Снимите .vhb-бэкап, разверните чистую установку с --external-db и восстановитесь из бэкапа."
    fi
    # Текущее состояние из .env
    [ -n "$(env_get DATABASE_URL)" ] && MAIN_COMPOSE="compose.external-db.yaml"
    # Наследуем legacy-раскладку: старый install.sh сохранял external-файл под именем compose.yaml
    if [ "$MAIN_COMPOSE" = "compose.external-db.yaml" ] && [ ! -f "$INSTALL_DIR/compose.external-db.yaml" ] \
       && [ -z "$(env_get COMPOSE_FILE)" ] && [ -f "$INSTALL_DIR/compose.yaml" ]; then
      info "существующая установка с внешней БД: обновляю раскладку файлов (compose.external-db.yaml)"
    fi
  else
    [ -n "$EXTERNAL_DB" ] && MAIN_COMPOSE="compose.external-db.yaml"
  fi

  # Валидации ввода — после сброса «прилипших» env, до каких-либо изменений на диске.
  # Домен из .env существующей установки уже был провалидирован при записи — не трогаем.
  if [ "$PROFILE" = "domain" ] && { [ "$FRESH" = 1 ] || [ -n "$CLI_PROFILE" ]; }; then
    sanitize_domain "$DOMAIN"
  fi
  [ -n "$EXTERNAL_DB" ] && normalize_dsn
  validate_pairs

  COMPOSE_FILES="$MAIN_COMPOSE"
  [ "$PROFILE" = "domain" ] && COMPOSE_FILES="$MAIN_COMPOSE:caddy.compose.yaml"

  # Адреса по профилю (явные --base-url/--http-addr сильнее)
  case "$PROFILE" in
    domain)
      [ -n "$DOMAIN" ] || fatal "профиль domain без домена (--domain vpn.мойдомен.ру)"
      [ "$CLI_BASE_URL" = 1 ]  || VPNHUB_BASE_URL="https://$DOMAIN"
      [ "$CLI_HTTP_ADDR" = 1 ] || VPNHUB_HTTP_ADDR="127.0.0.1:8000"
      ;;
    lan)
      [ "$CLI_HTTP_ADDR" = 1 ] || VPNHUB_HTTP_ADDR="0.0.0.0:8000"
      if [ "$CLI_BASE_URL" != 1 ]; then
        if [ "$DRY_RUN" != 1 ] && detect_public_ip; then
          VPNHUB_BASE_URL="http://$PUBLIC_IP:${VPNHUB_HTTP_ADDR##*:}"
        else
          VPNHUB_BASE_URL="http://localhost:${VPNHUB_HTTP_ADDR##*:}"
          [ "$DRY_RUN" = 1 ] || warn "не удалось определить публичный IP — VPNHUB_BASE_URL укажет на localhost, поправьте при необходимости (--base-url)"
        fi
      fi
      ;;
    local)
      if [ "$FRESH" = 1 ]; then
        [ "$CLI_HTTP_ADDR" = 1 ] || { [ -n "$VPNHUB_HTTP_ADDR" ] || VPNHUB_HTTP_ADDR="127.0.0.1:8000"; }
        [ "$CLI_BASE_URL" = 1 ]  || { [ -n "$VPNHUB_BASE_URL" ]  || VPNHUB_BASE_URL="http://localhost:${VPNHUB_HTTP_ADDR##*:}"; }
      else
        # переключение на local — только явным флагом
        if [ "$CLI_PROFILE" = "local" ]; then
          [ "$CLI_HTTP_ADDR" = 1 ] || VPNHUB_HTTP_ADDR="127.0.0.1:8000"
          [ "$CLI_BASE_URL" = 1 ]  || VPNHUB_BASE_URL="http://localhost:${VPNHUB_HTTP_ADDR##*:}"
        fi
      fi
      ;;
  esac
}

# ── preflight (только предупреждения; строго ДО записи на диск) ───────────────
preflight() {
  [ "$DRY_RUN" = 1 ] && return 0
  if [ "$PROFILE" = "domain" ]; then
    detect_public_ip || true
    local resolved; resolved="$(resolve_domain "$DOMAIN")"
    if [ -z "$resolved" ]; then
      warn "домен $DOMAIN пока не резолвится — Caddy не выпустит сертификат, пока не появится A-запись${PUBLIC_IP:+ → $PUBLIC_IP}"
    elif [ -n "$PUBLIC_IP" ] && [ "$resolved" != "$PUBLIC_IP" ]; then
      warn "домен $DOMAIN резолвится в $resolved, а публичный IP этой машины — $PUBLIC_IP (если домен за Cloudflare-прокси — это нормально)"
    else
      ok "DNS: $DOMAIN → $resolved"
    fi
    # порты Caddy — если наш стек с Caddy уже поднят, они заняты нами, это не ошибка
    local caddy_ours=0
    if [ "$FRESH" = 0 ]; then
      case "$(env_get COMPOSE_FILE)" in *caddy*) caddy_ours=1 ;; esac
    fi
    if [ "$caddy_ours" = 0 ]; then
      local p
      for p in 80 443; do
        port_busy "$p" && warn "порт $p уже занят — Caddy не сможет привязаться. Если там ваш nginx/Traefik, используйте его как прокси (docs → HTTPS и домен), а не --domain"
      done
    fi
    info "не забудьте открыть 80 и 443 на файрволе (пример: ufw allow 80,443/tcp)"
  elif [ "$FRESH" = 1 ]; then
    local port="${VPNHUB_HTTP_ADDR##*:}"
    port_busy "$port" && warn "порт $port уже занят — up может упасть; смените порт: --http-addr 127.0.0.1:9000"
  fi
  return 0
}

# ── файлы стека ───────────────────────────────────────────────────────────────
fetch_compose() {
  # VPNHUB_RAW_BASE — переопределение источника файлов (CI/локальная проверка): поддерживает file://
  local raw="${VPNHUB_RAW_BASE:-https://raw.githubusercontent.com/$REPO/$VPNHUB_REF/deploy/compose}"
  if [ "$DRY_RUN" != 1 ]; then mkdir -p "$INSTALL_DIR"; fi
  info "Скачиваю $MAIN_COMPOSE ($VPNHUB_REF)…"
  download "$raw/$MAIN_COMPOSE" "$INSTALL_DIR/$MAIN_COMPOSE"
  if [ "$PROFILE" = "domain" ]; then
    info "Скачиваю Caddy-оверлей (автоматический HTTPS)…"
    download "$raw/caddy.compose.yaml" "$INSTALL_DIR/caddy.compose.yaml"
    download "$raw/Caddyfile"          "$INSTALL_DIR/Caddyfile"
  fi
  ok "файлы стека: $INSTALL_DIR"
}

write_env_fresh() {
  if [ "$DRY_RUN" = 1 ]; then
    info "сгенерировал бы $ENV_FILE с новыми секретами (0600): COMPOSE_FILE=$COMPOSE_FILES, профиль $PROFILE"
    return 0
  fi
  ( umask 177; : > "$ENV_FILE" )   # 0600 до записи секретов
  {
    echo "# Сгенерировано install.sh $(date -u +%FT%TZ). Секретно — держите 0600."
    echo "# Изменить конфигурацию: повторный запуск install.sh с флагами (--domain/--lan/--local/--tag …)."
    echo "COMPOSE_FILE=$COMPOSE_FILES"
    echo "VPNHUB_MASTER_KEY=${MASTER_KEY:-$(gen_secret)}"
    if [ -n "$EXTERNAL_DB" ]; then
      echo "DATABASE_URL=$(escape_env_value "$EXTERNAL_DB")"
    else
      echo "POSTGRES_PASSWORD=$(gen_secret)"
    fi
    echo "VPNHUB_BASE_URL=$VPNHUB_BASE_URL"
    echo "VPNHUB_HTTP_ADDR=$VPNHUB_HTTP_ADDR"
    echo "VPNHUB_TAG=$VPNHUB_TAG"
    echo "# Токен доступа к /metrics (Prometheus): Authorization: Bearer <токен>."
    echo "VPNHUB_METRICS_TOKEN=$(gen_secret)"
    [ -n "$DOMAIN" ] && echo "VPNHUB_DOMAIN=$DOMAIN"
    if [ -n "$ADMIN_PHONE" ]; then
      echo "VPNHUB_ADMIN_PHONE=$ADMIN_PHONE"
      echo "VPNHUB_ADMIN_PASSWORD=$(escape_env_value "$ADMIN_PASSWORD")"
    fi
  } >> "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok "Записал $ENV_FILE (0600) со свежими секретами"
}

reconfigure_env() {
  local changed=0
  # Миграция legacy-установок: закрепляем набор файлов в COMPOSE_FILE (update.sh перестанет
  # «разбирать» оверлей). Рукописный Caddy-оверлей без флага --domain усыновляем как есть.
  if [ -z "$(env_get COMPOSE_FILE)" ] && [ "$CLI_PROFILE" = "" ] \
     && [ -f "$INSTALL_DIR/caddy.compose.yaml" ]; then
    COMPOSE_FILES="$MAIN_COMPOSE:caddy.compose.yaml"
    info "найден Caddy-оверлей без COMPOSE_FILE — закрепляю его в .env (обновления перестанут его терять)"
  fi
  env_upsert COMPOSE_FILE "$COMPOSE_FILES"

  if [ -n "$CLI_PROFILE" ]; then
    env_upsert VPNHUB_BASE_URL  "$VPNHUB_BASE_URL"
    env_upsert VPNHUB_HTTP_ADDR "$VPNHUB_HTTP_ADDR"
    [ "$PROFILE" = "domain" ] && env_upsert VPNHUB_DOMAIN "$DOMAIN"
    changed=1
  fi
  [ "$CLI_BASE_URL" = 1 ]  && { env_upsert VPNHUB_BASE_URL  "$VPNHUB_BASE_URL";  changed=1; }
  [ "$CLI_HTTP_ADDR" = 1 ] && { env_upsert VPNHUB_HTTP_ADDR "$VPNHUB_HTTP_ADDR"; changed=1; }
  [ "$CLI_TAG" = 1 ]       && { env_upsert VPNHUB_TAG "$VPNHUB_TAG"; changed=1; }
  # Ротация реквизитов той же внешней БД (смена типа БД отсечена fatal'ом в plan_config)
  [ "$CLI_EXTERNAL_DB" = 1 ] && { env_upsert DATABASE_URL "$(escape_env_value "$EXTERNAL_DB")"; changed=1; }
  if [ "$CLI_ADMIN" = 1 ]; then
    env_upsert VPNHUB_ADMIN_PHONE "$ADMIN_PHONE"
    env_upsert VPNHUB_ADMIN_PASSWORD "$(escape_env_value "$ADMIN_PASSWORD")"
    changed=1
  fi
  if [ "$changed" = 0 ]; then
    ok ".env уже существует — секреты и настройки сохранены (изменить: повторный запуск с флагами)"
  fi
}

# ── запуск и проверка ─────────────────────────────────────────────────────────
start_stack() {
  if [ "$NO_PULL" != 1 ]; then
    info "Тяну образы…"
    compose pull
  fi
  info "Поднимаю стек…"
  compose up -d --remove-orphans
  ok "Контейнеры запущены"
}

wait_healthy() {
  local timeout="${VPNHUB_HEALTH_TIMEOUT:-120}"
  [ "$DRY_RUN" = 1 ] && return 0
  [ "$timeout" = 0 ] && return 0
  if ! command_exists curl && ! command_exists wget; then
    info "нет curl/wget — пропускаю проверку готовности (посмотрите docker compose logs -f app)"
    return 0
  fi
  local addr waited=0
  addr="$(env_get VPNHUB_HTTP_ADDR)"
  [ -n "$addr" ] || addr="$VPNHUB_HTTP_ADDR"
  [ -n "$addr" ] || addr="127.0.0.1:8000"
  local port="${addr##*:}" host="${addr%:*}"
  case "$host" in ""|0.0.0.0|"[::]") host="127.0.0.1" ;; esac
  info "Жду готовности панели (миграции на первом старте занимают до минуты)…"
  while [ "$waited" -lt "$timeout" ]; do
    if http_get "http://$host:$port/healthz" >/dev/null; then
      ok "Панель отвечает (${waited}s)"
      return 0
    fi
    sleep 3; waited=$((waited + 3))
  done
  warn "панель не ответила за ${timeout}s — контейнеры оставлены для диагностики"
  warn "логи:  cd $INSTALL_DIR && docker compose logs -f app"
  exit 1
}

# ── финальный вывод ───────────────────────────────────────────────────────────
json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

print_next_steps() {
  local url="$VPNHUB_BASE_URL"
  [ "$FRESH" = 0 ] && { url="$(env_get VPNHUB_BASE_URL)"; [ -n "$url" ] || url="$VPNHUB_BASE_URL"; }
  cat <<EOF

${C_GRN}VPN Hub установлен (профиль: $PROFILE).${C_RST}

  Каталог:   $INSTALL_DIR
  Секреты:   $ENV_FILE
  Адрес:     $url
EOF
  printf '\n%s⚠ Мастер-ключ:%s скопируйте VPNHUB_MASTER_KEY из .env в менеджер паролей ПРЯМО СЕЙЧАС —\n  им зашифрованы SSH-доступы и бэкапы, потеря необратима.\n' "$C_YLW" "$C_RST"

  case "$PROFILE" in
    domain)
      cat <<EOF

Дальше:
  1. DNS: A-запись $DOMAIN → ${PUBLIC_IP:-IP этого сервера} (если ещё нет).
  2. Файрвол: откройте 80 и 443 (пример: ufw allow 80,443/tcp).
  3. Откройте https://$DOMAIN — первичная настройка (админ${MASTER_KEY:+ уже с вашим ключом}).
     Сертификат выпускается автоматически после появления DNS-записи.
EOF
      ;;
    lan)
      cat <<EOF

${C_YLW}⚠ Панель открыта по HTTP без шифрования (0.0.0.0).${C_RST} Это нормально для теста/LAN,
  но не для интернета: для публичного доступа используйте --domain (HTTPS автоматически).

Дальше: откройте $url — первичная настройка (создание администратора).
EOF
      ;;
    *)
      cat <<EOF

Дальше: откройте $url — первичная настройка (создание администратора).
EOF
      if [ -n "${SSH_CONNECTION:-}" ]; then
        local ssh_host; ssh_host="$(printf '%s' "$SSH_CONNECTION" | awk '{print $3}')"
        cat <<EOF

${C_YLW}⚠ Вы установили панель по SSH: порт слушает только 127.0.0.1 —
  с вашего компьютера адрес не откроется.${C_RST} Варианты:
    - SSH-туннель:      ssh -L 8000:127.0.0.1:8000 ${USER}@${ssh_host:-<сервер>}   # затем http://localhost:8000
    - Домен и HTTPS:    bash install.sh --domain vpn.мойдомен.ру
    - По IP без HTTPS:  bash install.sh --lan   (только для теста)
EOF
      fi
      ;;
  esac

  cat <<EOF

Управление (из $INSTALL_DIR):
  docker compose ps / logs -f app / down
  Обновление:   curl -fsSL https://raw.githubusercontent.com/$REPO/master/deploy/scripts/update.sh | bash
  Удаление:     curl -fsSL https://raw.githubusercontent.com/$REPO/master/deploy/scripts/uninstall.sh | bash
  Настройка:    повторный запуск install.sh с флагами (--domain / --lan / --local / --tag …)
EOF
  # машиночитаемый итог — всегда последней строкой (для оркестрации/marketplace)
  local tag; tag="$(env_get VPNHUB_TAG)"; [ -n "$tag" ] || tag="$VPNHUB_TAG"
  printf '{"url":"%s","dir":"%s","profile":"%s","composeFiles":"%s","tag":"%s"}\n' \
    "$(json_escape "$url")" "$(json_escape "$INSTALL_DIR")" "$PROFILE" \
    "$(json_escape "$COMPOSE_FILES")" "$(json_escape "$tag")"
}

main() {
  parse_args "$@"
  detect_platform
  require_docker
  plan_config
  preflight
  fetch_compose
  if [ "$FRESH" = 1 ]; then write_env_fresh; else reconfigure_env; fi
  start_stack
  wait_healthy
  print_next_steps
}

main "$@"
