"""Общие нормализаторы и конвертеры для каталогов провайдеров."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

TIB = 1024**4  # 1 ТБ (бинарно, как в UI: ГБ = 1024³)
_SPACE_RE = re.compile(r"[\s ]+")


def _norm(text: str) -> str:
    return _SPACE_RE.sub(" ", text.replace("\xa0", " ")).strip()


def _int(text: str) -> int | None:
    if m := re.search(r"\d+", text.replace(" ", "")):
        return int(m.group(0))
    return None


def _tariff_name(text: str) -> str:
    name = _norm(text).replace("- ", "-").replace(" -", "-")
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def _quantity_gb(text: str) -> float | None:
    low = text.lower().replace(",", ".")
    if not (m := re.search(r"(\d+(?:\.\d+)?)\s*(tb|тб|gb|гб|g\b|mb|мб)", low)):
        return None
    value = float(m.group(1))
    unit = m.group(2)
    if unit in {"tb", "тб"}:
        value *= 1024
    elif unit in {"mb", "мб"}:
        value /= 1024
    return int(value) if value.is_integer() else round(value, 2)


def _storage_type_from_text(text: str) -> str:
    up = text.upper()
    if "NVME" in up:
        return "NVMe"
    if "SSD" in up:
        return "SSD"
    if "HDD" in up:
        return "HDD"
    if "SAS" in up:
        return "SAS"
    return ""


def _traffic_tb_any(text: str) -> float | None:
    low = text.lower()
    if "безлим" in low or "unmetered" in low or "unlimited" in low:
        return None
    if m := re.search(r"(\d+(?:[.,]\d+)?)\s*(?:тб|tb)", low):
        tb = float(m.group(1).replace(",", "."))
        return int(tb) if tb.is_integer() else tb
    if m := re.search(r"(\d+(?:[.,]\d+)?)\s*(?:gb|гб)", low):
        tb = float(m.group(1).replace(",", ".")) / 1024
        return int(tb) if tb.is_integer() else round(tb, 3)
    return None


def _speed_mbps(text: str) -> int | None:
    low = text.lower().replace(",", ".")
    if m := re.search(r"(\d+(?:\.\d+)?)\s*(?:gbps|gbit|гбит|гб/с)", low):
        return int(float(m.group(1)) * 1000)
    if m := re.search(r"(\d+(?:\.\d+)?)\s*(?:mbps|mbit|мбит|мб/с|мб|mb)", low):
        return int(float(m.group(1)))
    return None


def _clone_plans(plans: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(p) for p in plans]


def plan_bandwidth_bytes(plan: dict) -> int | None:
    """Квота трафика плана в байтах (None = безлимит/не указано)."""
    tb = plan.get("trafficTb")
    return int(tb * TIB) if tb else None
