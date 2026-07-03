#!/usr/bin/env bash
#
# VPN Hub — удаление (Docker Compose). По умолчанию БЕЗОПАСНО: тома с данными сохраняются.
# Удаление данных (БД, бэкапы) — только по явному подтверждению или с --purge.
#
#   curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/uninstall.sh | bash
#
# Опции:
#   --dir PATH     каталог установки   (INSTALL_DIR, по умолч. $HOME/vpn-hub)
#   --purge        снести и тома с данными (НЕОБРАТИМО), без вопроса
#   --keep-data    только контейнеры, тома оставить (по умолчанию)
#   -h|--help
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/vpn-hub}"
PURGE=0
KEEP=0

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_GRN=$'\033[32m'; C_YLW=$'\033[33m'; C_RED=$'\033[31m'; C_BLU=$'\033[34m'; C_RST=$'\033[0m'
else C_GRN=; C_YLW=; C_RED=; C_BLU=; C_RST=; fi
info()  { printf '%s[ .. ]%s %s\n' "$C_BLU" "$C_RST" "$*"; }
ok()    { printf '%s[ ok ]%s %s\n' "$C_GRN" "$C_RST" "$*"; }
fatal() { printf '%s[fail]%s %s\n' "$C_RED" "$C_RST" "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dir)       INSTALL_DIR="$2"; shift 2 ;;
    --purge)     PURGE=1; shift ;;
    --keep-data) PURGE=0; KEEP=1; shift ;;
    -h|--help)   if [ -f "$0" ] && head -n3 "$0" 2>/dev/null | grep -q 'VPN Hub'; then
                   grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
                 else
                   printf 'VPN Hub — удаление. Флаги: --dir PATH, --purge (снести и данные), --keep-data.\n'
                 fi; exit 0 ;;
    *) fatal "неизвестная опция: $1" ;;
  esac
done

# читаем подтверждение с терминала даже под `curl | bash`
confirm() {
  local reply=""
  if [ -t 0 ]; then read -r -p "$1 " reply || reply=""
  elif [ -e /dev/tty ]; then
    # /dev/tty существует и на машинах без управляющего терминала (CI) — read тогда падает
    read -r -p "$1 " reply < /dev/tty 2>/dev/null || reply=""
  fi
  case "$reply" in [Yy]|[Yy][Ee][Ss]) return 0 ;; *) return 1 ;; esac
}

main() {
  command -v docker >/dev/null 2>&1 || fatal "Docker не найден"
  # Набор compose-файлов задаёт COMPOSE_FILE в .env; без неё — legacy с одним compose.yaml.
  local compose_file=""
  [ -f "$INSTALL_DIR/.env" ] && compose_file="$(grep -E '^COMPOSE_FILE=' "$INSTALL_DIR/.env" | tail -n1 | cut -d= -f2- || true)"
  local first_file="${compose_file%%:*}"; [ -n "$first_file" ] || first_file="compose.yaml"
  [ -f "$INSTALL_DIR/$first_file" ] || fatal "нет $INSTALL_DIR/$first_file (задайте --dir?)"
  local DC="docker compose"
  # bash 3.2 (macOS): "${arr[@]}" на пустом массиве падает под set -u — используем защищённую форму
  local env_args=(); [ -f "$INSTALL_DIR/.env" ] && env_args=(--env-file .env)

  if [ "$PURGE" -eq 0 ] && [ "$KEEP" -eq 0 ] \
     && confirm "Удалить также ВСЕ данные (БД, бэкапы)? Необратимо. [y/N]"; then
    PURGE=1
  fi

  if [ "$PURGE" -eq 1 ]; then
    info "Останавливаю и удаляю контейнеры + тома…"
    ( cd "$INSTALL_DIR" && $DC ${env_args[@]:+"${env_args[@]}"} down --volumes --remove-orphans )
    ok "Контейнеры и тома данных удалены"
    if confirm "Удалить каталог $INSTALL_DIR (в нём .env с секретами)? [y/N]"; then
      rm -rf "$INSTALL_DIR"; ok "Удалён $INSTALL_DIR"
    else
      info "Каталог оставлен: $INSTALL_DIR"
    fi
  else
    info "Останавливаю и удаляю контейнеры (тома данных сохраняются)…"
    ( cd "$INSTALL_DIR" && $DC ${env_args[@]:+"${env_args[@]}"} down --remove-orphans )
    ok "Контейнеры удалены. ${C_YLW}Данные и .env сохранены.${C_RST}"
    info "Полностью снести позже:  $0 --purge  (или добавьте --dir)"
  fi
}

main "$@"
