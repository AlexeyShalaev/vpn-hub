"""Валидация сетевых идентификаторов (host/port).

Общая для service- и infra-слоёв: `server.ip` попадает в скрипты provisioning
($SERVER_IP_ADDRESS/$REMOTE_HOST) и в ssh-команды, поэтому его нужно проверять на
границе доверия — до подстановки в shell. Разрешаем только IP-литералы и RFC-1123
hostname (буквы/цифры/дефис/точка), что исключает shell-метасимволы (" ; $ ` | & …).
"""

from __future__ import annotations

import ipaddress
import re

# RFC-1123 метка: 1..63 символа [A-Za-z0-9-], не начинается/не заканчивается дефисом.
# Длину всего имени (≤253) проверяем в коде, а не через `$`-lookahead: в Python `$` совпадает и
# ПЕРЕД хвостовым \n, поэтому якорь заменён на fullmatch — так значение с переводом строки
# (вектор shell-инъекции) точно не пройдёт. Строку НЕ обрезаем: валидный host не содержит
# окружающих пробелов, а границы (ServerService) обрезают ввод сами до вызова.
_HOSTNAME_RE = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*")


def is_valid_host(host: str | None) -> bool:
    """True, если host — валидный IPv4/IPv6-литерал или RFC-1123 hostname (без окружающих пробелов)."""
    if not host or not isinstance(host, str) or len(host) > 253:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return bool(_HOSTNAME_RE.fullmatch(host))
    return True


def is_valid_port(port: object) -> bool:
    """True, если port — целое 1..65535 без лишних символов (строгий isdigit, чтобы `80\\n` не прошёл)."""
    s = str(port)
    if not s.isdigit():
        return False
    return 1 <= int(s) <= 65535
