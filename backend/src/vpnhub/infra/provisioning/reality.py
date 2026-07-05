"""Чистое ядро управления параметрами Xray-Reality: shortId, SNI/dest, валидация домена.

Здесь только детерминированная логика без SSH/IO: генерация/валидация shortId, проверка формата
маскировочного домена (SNI) и переписывание realitySettings в server.json. Применение на сервере
(рестарт контейнера) и сетевая проверка TLS живут в провизионере/сервисе.
"""

from __future__ import annotations

import re
import secrets
from typing import Any, cast

from vpnhub.infra.provisioning import errors

# shortId Reality — hex-строка чётной длины 2..16 символов (0..8 байт). Amnezia по умолчанию 16 hex (8 байт).
_SHORT_ID_RE = re.compile(r"^[0-9a-f]{2,16}$")
# метка домена: буквы/цифры/дефис, не начинается/заканчивается дефисом, до 63 символов
_LABEL_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def gen_short_id() -> str:
    """Новый shortId Reality: 8 случайных байт → 16 hex-символов (как configure_container.sh)."""
    return secrets.token_hex(8)


def validate_short_id(short_id: str) -> str:
    sid = str(short_id).strip().lower()
    if not _SHORT_ID_RE.fullmatch(sid) or len(sid) % 2 != 0:
        raise errors.make("invalid_reality", f"shortId должен быть hex чётной длины 2..16, получено {short_id!r}")
    return sid


def validate_sni(sni: str) -> str:
    """Проверить формат маскировочного домена (FQDN). Сетевую доступность/TLS проверяет сервис отдельно."""
    host = str(sni).strip().lower().rstrip(".")
    if not host or len(host) > 253 or "." not in host:
        raise errors.make("invalid_reality", f"SNI должен быть доменным именем (FQDN), получено {sni!r}")
    labels = host.split(".")
    if any(not _LABEL_RE.fullmatch(lbl) for lbl in labels):
        raise errors.make("invalid_reality", f"SNI содержит недопустимые символы: {sni!r}")
    if labels[-1].isdigit():
        raise errors.make("invalid_reality", f"SNI должен оканчиваться доменной зоной, а не числом: {sni!r}")
    return host


def rewrite_reality(server_json: dict, *, short_id: str, sni: str) -> dict:
    """Вернуть КОПИЮ server.json с обновлёнными realitySettings.dest/serverNames/shortIds.

    Клиенты (inbounds[0].settings.clients) не трогаются. dest = <sni>:443 (маскируемся под 443/TLS).
    """
    doc = cast("dict[str, Any]", server_json)
    reality = doc["inbounds"][0]["streamSettings"]["realitySettings"]
    reality["dest"] = f"{sni}:443"
    reality["serverNames"] = [sni]
    reality["shortIds"] = [short_id]
    return doc


def reality_of(server_json: dict) -> dict:
    return cast("dict[str, Any]", server_json["inbounds"][0]["streamSettings"]["realitySettings"])
