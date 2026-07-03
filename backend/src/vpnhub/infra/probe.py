"""TCP health-зонд для серверов: проверка доступности и замер латентности.

Без внешних зависимостей: открываем TCP-соединение к SSH-порту сервера и
измеряем время хендшейка. Если на порту отвечает SSH (баннер «SSH-...»),
помечаем это в detail — так отличаем «живой управляемый сервер» от «просто
открытого порта». ICMP-пинг намеренно не используем: он требует root/raw-socket
и часто режется на хостингах, тогда как SSH-порт VPN-сервера всегда открыт.
"""

from __future__ import annotations

import asyncio
import errno
from dataclasses import dataclass

_BANNER_BYTES = 64  # SSH-баннер вида «SSH-2.0-OpenSSH_9.6» заметно короче
_BANNER_TIMEOUT = 2.0  # сколько ждём баннер (необязательная деталь, не статус)


@dataclass(frozen=True)
class ProbeResult:
    """Итог одной проверки. detail — короткая причина для логов (в БД не пишется)."""

    ok: bool
    latency_ms: int | None
    detail: str


async def probe_tcp(host: str, port: int, timeout: float) -> ProbeResult:
    """Открыть TCP-соединение к host:port и измерить латентность.

    ok=True — соединение установилось за timeout секунд; latency_ms — время
    TCP-хендшейка в миллисекундах (минимум 1).
    """
    host = (host or "").strip()
    if not host:
        return ProbeResult(False, None, "адрес не задан")

    loop = asyncio.get_running_loop()
    start = loop.time()
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        latency_ms = max(1, round((loop.time() - start) * 1000))
        banner = await _read_banner(reader, timeout)
        detail = "SSH" if banner.startswith("SSH-") else "порт открыт"
        return ProbeResult(True, latency_ms, detail)
    except TimeoutError:
        return ProbeResult(False, None, "таймаут")
    except OSError as e:
        return ProbeResult(False, None, _os_error_detail(e))
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:  # TimeoutError — подкласс OSError
                pass


async def _read_banner(reader: asyncio.StreamReader, timeout: float) -> str:
    """Прочитать первые байты ответа: SSH шлёт баннер сразу после коннекта.

    Тайм-аут ограничен сверху, чтобы «молчаливый» открытый порт не тормозил тик.
    """
    try:
        data = await asyncio.wait_for(reader.read(_BANNER_BYTES), min(timeout, _BANNER_TIMEOUT))
    except OSError:  # включая TimeoutError (подкласс OSError)
        return ""
    return data.decode("latin-1", "replace").strip()


def _os_error_detail(e: OSError) -> str:
    if isinstance(e, ConnectionRefusedError):
        return "соединение отклонено"
    if getattr(e, "errno", None) in (errno.EHOSTUNREACH, errno.ENETUNREACH):
        return "хост недоступен"
    return "ошибка соединения"  # socket.gaierror (DNS), reset и прочее
