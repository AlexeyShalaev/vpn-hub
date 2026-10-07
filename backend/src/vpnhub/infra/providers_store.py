"""Файловый стор каталога провайдеров (YAML).

Дефолт в образе (`data/providers.default.yaml`) копируется в `VPNHUB_PROVIDERS_FILE` при первом
старте; дальше файл — источник правды, редактируется руками или из админки (один процесс).

Чтобы новые дефолтные провайдеры доезжали до существующих пользователей после обновления версии,
на старте вызывается `sync_default_providers()`: он ДОЛИВАЕТ новые дефолты по id (в конец), не трогая
правки/добавления/удаления пользователя. Уже «сиженные» дефолтные id хранит sibling-маркер
`<providers>.seeded.json`; для установок, поставленных ДО этой фичи (маркера нет), стартовый набор
берётся из `_PRE_MERGE_DEFAULT_IDS`, чтобы удалённые пользователем дефолты не воскресали.

Метаданные для поиска/фильтров каталога (`hq`, `countries`, `payments`, `blurbEn`) появились позже
базовых полей: у дефолтных провайдеров, записанных старой версией без этих КЛЮЧЕЙ, sync доливает их
из дефолта. Ключ, который уже есть в файле (даже пустой — значит, его очистил пользователь), не трогаем.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from vpnhub.api.config import Settings
from vpnhub.core.errors import BadRequest, NotFound

_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "providers.default.yaml"

# Дефолтные провайдеры, поставлявшиеся ДО фичи мерджа-на-обновлении (до v0.10.0). Для существующих
# установок без маркера считаем их уже сиженными: тогда доливаются только более новые дефолты, а
# удалённые пользователем старые провайдеры не воскресают.
_PRE_MERGE_DEFAULT_IDS = frozenset({"firstbyte", "ufo", "ishosting", "ahost", "serverspace"})


# Способы оплаты, которые понимает UI каталога (фильтр и бейджи). Неизвестные значения отбрасываются.
PAYMENT_METHODS = ("ru_card", "sbp", "ru_wallet", "crypto", "card", "paypal", "bank", "local")
_META_FIELDS = ("hq", "countries", "payments", "blurbEn")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _str_list(value: object) -> list[str]:
    """Список строк из YAML-списка или строки через запятую (форма админки)."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = [str(v) for v in value]
    else:
        parts = [str(value)]
    return [p.strip() for p in parts if p.strip()]


def _countries(value: object) -> list[str]:
    # YAML 1.1 читает голый `NO` (Норвегия) в руками правленом файле как false — возвращаем код страны.
    if isinstance(value, (list, tuple)):
        value = ["NO" if v is False else v for v in value]
    out: list[str] = []
    for code in _str_list(value):
        up = code.upper()
        if _COUNTRY_RE.match(up) and up not in out:
            out.append(up)
    return out


def _payments(value: object) -> list[str]:
    wanted = {p.lower() for p in _str_list(value)}
    return [m for m in PAYMENT_METHODS if m in wanted]


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "provider"


class ProviderStore:
    def __init__(self, settings: Settings) -> None:
        self.path = Path(settings.providers_file)
        self._seeded_path = self.path.with_name(f"{self.path.stem}.seeded.json")
        self._ensure()

    def _ensure(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            default = _DEFAULT.read_text(encoding="utf-8") if _DEFAULT.exists() else "[]\n"
            self.path.write_text(default, encoding="utf-8")

    def _default_items(self) -> list[dict]:
        try:
            data = yaml.safe_load(_DEFAULT.read_text(encoding="utf-8")) or []
        except Exception:
            data = []
        return [self._norm(p) for p in data if isinstance(p, dict)]

    def _read_seeded(self) -> set[str]:
        try:
            return {str(x) for x in json.loads(self._seeded_path.read_text(encoding="utf-8"))}
        except Exception:
            return set()

    def _write_seeded(self, ids: set[str]) -> None:
        try:
            self._seeded_path.write_text(json.dumps(sorted(ids)), encoding="utf-8")
        except OSError:
            pass

    def sync_default_providers(self) -> int:
        """Домердж новых дефолтных провайдеров (по id) в пользовательский файл. Возвращает число
        добавленных. Вызывать один раз на старте. Существующие/кастомные/удалённые записи не трогаем.
        """
        defaults = self._default_items()
        if not defaults:
            return 0
        all_ids = {d["id"] for d in defaults}
        # маркер есть → сиженные из него; маркера нет (установка до фичи) → берём базовый набор
        seeded = self._read_seeded() if self._seeded_path.exists() else set(_PRE_MERGE_DEFAULT_IDS)
        new_ids = all_ids - seeded
        items, backfilled = self._backfill_metadata(defaults)
        have = {p["id"] for p in items}
        appended = [d for d in defaults if d["id"] in new_ids and d["id"] not in have]
        if appended or backfilled:
            self._write(items + appended)
        self._write_seeded(all_ids | seeded)  # фиксируем маркер (в т.ч. первый раз)
        return len(appended)

    def _backfill_metadata(self, defaults: list[dict]) -> tuple[list[dict], bool]:
        """Долить метаданные дефолтов в записи, где этих КЛЮЧЕЙ ещё нет (файл от старой версии)."""
        by_id = {d["id"]: d for d in defaults}
        items: list[dict] = []
        changed = False
        for raw in self._read_raw():
            item = self._norm(raw)
            default = by_id.get(item["id"])
            if default is not None:
                for field in _META_FIELDS:
                    if field not in raw and default[field]:
                        item[field] = default[field]
                        changed = True
            items.append(item)
        return items, changed

    @staticmethod
    def _norm(p: dict) -> dict:
        hq = str(p.get("hq") or "").strip().upper()
        return {
            "id": str(p.get("id") or _slug(str(p.get("name", "")))),
            "name": str(p.get("name", "")),
            "url": str(p.get("url", "")),
            "blurb": str(p.get("blurb", "")),
            "blurbEn": str(p.get("blurbEn") or ""),
            "tags": [str(t) for t in (p.get("tags") or [])],
            "hq": hq if _COUNTRY_RE.match(hq) else "",
            "countries": _countries(p.get("countries")),
            "payments": _payments(p.get("payments")),
        }

    def _read_raw(self) -> list[dict]:
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or []
        except Exception:
            data = []
        return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []

    def _read(self) -> list[dict]:
        return [self._norm(p) for p in self._read_raw()]

    def _write(self, items: list[dict]) -> None:
        self.path.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def list(self) -> list[dict]:
        return self._read()

    def create(self, data: dict) -> dict:
        if not (data.get("name") or "").strip():
            raise BadRequest(key="provider.name_required")
        items = self._read()
        pid = (data.get("id") or _slug(str(data["name"]))).strip()
        if any(p["id"] == pid for p in items):
            pid = f"{pid}-{len(items) + 1}"
        item = self._norm({**data, "id": pid})
        items.append(item)
        self._write(items)
        return item

    def update(self, pid: str, data: dict) -> dict:
        items = self._read()
        for i, p in enumerate(items):
            if p["id"] == pid:
                items[i] = self._norm({**p, **data, "id": pid})
                self._write(items)
                return items[i]
        raise NotFound(key="provider.not_found")

    def delete(self, pid: str) -> None:
        items = self._read()
        kept = [p for p in items if p["id"] != pid]
        if len(kept) == len(items):
            raise NotFound(key="provider.not_found")
        self._write(kept)
