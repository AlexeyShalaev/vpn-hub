#!/usr/bin/env bash
#
# VPN Hub — обновление (Docker Compose). Тянет новый образ и пересоздаёт контейнеры.
# .env и тома (БД, бэкапы) НЕ трогаются.
#
#   curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/update.sh | bash
#
# Опции:
#   --dir PATH   каталог установки   (INSTALL_DIR, по умолч. $HOME/vpn-hub)
#   --tag TAG    переключить тег образа (запишет VPNHUB_TAG в .env)
#   --no-pull    не тянуть образы (CI/air-gapped) — только пересоздать контейнеры
#   -h|--help
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/vpn-hub}"
NEW_TAG=""
NO_PULL="${VPNHUB_NO_PULL:-0}"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_GRN=$'\033[32m'; C_YLW=$'\033[33m'; C_BLU=$'\033[34m'; C_RED=$'\033[31m'; C_RST=$'\033[0m'
else C_GRN=; C_YLW=; C_BLU=; C_RED=; C_RST=; fi
info()  { printf '%s[ .. ]%s %s\n' "$C_BLU" "$C_RST" "$*"; }
ok()    { printf '%s[ ok ]%s %s\n' "$C_GRN" "$C_RST" "$*"; }
fatal() { printf '%s[fail]%s %s\n' "$C_RED" "$C_RST" "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --tag) NEW_TAG="$2"; shift 2 ;;
    --no-pull) NO_PULL=1; shift ;;
    -h|--help) if [ -f "$0" ] && head -n3 "$0" 2>/dev/null | grep -q 'VPN Hub'; then
                 grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
               else
                 printf 'VPN Hub — обновление. Флаги: --dir PATH, --tag TAG, --no-pull.\n'
               fi; exit 0 ;;
    *) fatal "неизвестная опция: $1" ;;
  esac
done

main() {
  command -v docker >/dev/null 2>&1 || fatal "Docker не найден"
  docker compose version >/dev/null 2>&1 || fatal "нет Docker Compose v2"
  [ -f "$INSTALL_DIR/.env" ] || fatal "нет $INSTALL_DIR/.env (установлено ли сюда? задайте --dir)"

  # Набор compose-файлов задаёт COMPOSE_FILE в .env (пишется install.sh); её отсутствие —
  # legacy-раскладка с одним compose.yaml.
  local compose_file
  compose_file="$(grep -E '^COMPOSE_FILE=' "$INSTALL_DIR/.env" | tail -n1 | cut -d= -f2- || true)"
  local first_file="${compose_file%%:*}"; [ -n "$first_file" ] || first_file="compose.yaml"
  [ -f "$INSTALL_DIR/$first_file" ] || fatal "нет $INSTALL_DIR/$first_file (установлено ли сюда? задайте --dir)"

  if [ -z "$compose_file" ] && [ -f "$INSTALL_DIR/caddy.compose.yaml" ]; then
    printf '%s[warn]%s найден Caddy-оверлей, но COMPOSE_FILE в .env не задан — это обновление пересоздаст app БЕЗ Caddy-настроек.\n' "$C_YLW" "$C_RST" >&2
    printf '%s[warn]%s закрепите оверлей одной строкой в %s/.env:  COMPOSE_FILE=compose.yaml:caddy.compose.yaml\n' "$C_YLW" "$C_RST" "$INSTALL_DIR" >&2
  fi

  local DC="docker compose"

  if [ -n "$NEW_TAG" ]; then
    info "Переключаю тег образа на ${NEW_TAG}…"
    # без sed: разделители в значении (|, /) не должны ломать запись
    tmp="$(mktemp)"
    grep -vE '^VPNHUB_TAG=' "$INSTALL_DIR/.env" > "$tmp" || true
    printf 'VPNHUB_TAG=%s\n' "$NEW_TAG" >> "$tmp"
    cat "$tmp" > "$INSTALL_DIR/.env"; rm -f "$tmp"
  fi

  info "⚠ Рекомендуется сделать бэкап БД перед обновлением (админка → Резервные копии)."
  if [ "$NO_PULL" != 1 ]; then
    info "Тяну новые образы…"
    ( cd "$INSTALL_DIR" && $DC --env-file .env pull )
  fi
  info "Пересоздаю изменившиеся контейнеры (миграции накатятся на старте под advisory-lock)…"
  ( cd "$INSTALL_DIR" && $DC --env-file .env up -d )
  docker image prune -f >/dev/null 2>&1 || true
  ok "Обновление завершено. Статус:"
  ( cd "$INSTALL_DIR" && $DC ps )
}

main "$@"
