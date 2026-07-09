"""Нормализация id провайдеров для каталога тарифов."""

from __future__ import annotations

import re


def _provider_key(provider_id: str) -> str:
    raw = (provider_id or "").strip().lower()
    compact = re.sub(r"[\s_-]+", "", raw)
    if compact == "firstbyte":
        return "firstbyte"
    if compact in {"ufo", "ufohosting"}:
        return "ufo"
    if compact in {"ishosting", "ishostingcom"}:
        return "ishosting"
    if compact in {"ahost", "ahosteu"}:
        return "ahost"
    if compact in {"serverspace", "serverspaceru", "serverspaceio"}:
        return "serverspace"
    return raw
