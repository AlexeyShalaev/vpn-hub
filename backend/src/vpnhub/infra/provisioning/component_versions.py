"""Детект устаревших версий серверных VPN-компонентов (Xray, Hysteria2).

Панель собирает контейнеры протоколов из bundled-Dockerfile'ов с ПРИБИТОЙ версией
бинарника (`ARG XRAY_RELEASE`, `ARG HYSTERIA_VERSION`). Значит эталон «актуальной»
версии компонента — это версия, которую соберёт ТЕКУЩИЙ релиз панели. Поэтому эталон
держим КОНСТАНТОЙ здесь (vendor/proto → тег), а не ходим в registry:

  • это ровно та версия, что реально приедет при обновлении (rebuild с этого Dockerfile),
    так что «доступно обновление» = «на сервере крутится бинарник старее, чем соберёт панель»;
  • без внешних зависимостей и сетевых обращений к Docker Hub / GitHub при каждом sync;
  • обновление эталона = обновление Dockerfile + этой константы в одном релизе (сверять их
    легко: обе величины в дереве панели).

Registry API (узнавать самый свежий апстрим-тег на лету) — осознанно отложено (см. tasks/04).

Версии читаются с сервера по SSH из уже запущенного контейнера (`<bin> version`) в фазе
чтения состояния sync — тем же best-effort каналом, что и клиенты/трафик.

AmneziaWG/OpenVPN/Outline собираются из образов с тегом `:latest` (амнезия так и делает),
понятного «номера версии» у них нет — детект версий для них не имеет смысла и не заявляется.
"""

from __future__ import annotations

from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.ssh import SshClient
from vpnhub.infra.updates import parse_version

# proto_id → эталонная (актуальная для этого релиза панели) версия компонента.
# ДОЛЖНО совпадать с ARG в соответствующем scripts/<proto>/Dockerfile.
#   xray/xray_xhttp → ARG XRAY_RELEASE в scripts/xray*/Dockerfile
#   hysteria2       → ARG HYSTERIA_VERSION в scripts/hysteria2/Dockerfile
LATEST_COMPONENT_VERSIONS: dict[str, str] = {
    "xray": "v25.8.3",
    "xray_xhttp": "v25.8.3",
    "hysteria2": "v2.6.2",
}

# proto_id → команда внутри контейнера, печатающая версию бинарника.
_VERSION_COMMANDS: dict[str, str] = {
    "xray": "xray version",
    "xray_xhttp": "xray version",
    "hysteria2": "hysteria version",
}


def latest_version(proto_id: str) -> str | None:
    """Эталонная версия компонента для протокола (None — если детект не поддержан)."""
    return LATEST_COMPONENT_VERSIONS.get(proto_id)


def parse_component_version(proto_id: str, raw: str) -> str | None:
    """Достать голую версию из вывода `<bin> version`.

    xray: 'Xray 25.8.3 (Xray, Penetrates ...) ...' → '25.8.3'
    hysteria2: 'hysteria version ...\\nVersion: app/v2.6.2 ...' или 'v2.6.2' → 'v2.6.2'
    Возвращает первую токен-версию, содержащую цифру и точку; иначе None.
    """
    text = (raw or "").strip()
    if not text:
        return None
    for token in text.replace("\n", " ").replace(",", " ").replace("(", " ").replace(")", " ").split():
        # apernet/hysteria печатает 'app/v2.6.2' — берём часть после последнего '/'
        cand = token.rsplit("/", 1)[-1].strip()
        core = cand.lstrip("vV")
        if "." in core and core[0].isdigit():
            return cand
    return None


def update_available(proto_id: str, running_version: str | None) -> bool:
    """True, если известна и текущая, и эталонная версия, и эталон строго новее.

    Чистая функция (без SSH/БД) — сравнение через updates.parse_version (semver-подобное).
    Неизвестная текущая версия → False (не пугаем ложным бейджем).
    """
    latest = LATEST_COMPONENT_VERSIONS.get(proto_id)
    if not latest or not running_version:
        return False
    return parse_version(latest) > parse_version(running_version)


async def read_running_version(ssh: SshClient, spec: pc.ProtoSpec) -> str | None:
    """Прочитать версию бинарника из запущенного контейнера протокола (best-effort).

    None — если детект для протокола не поддержан, команда упала или вывод не распознан.
    """
    cmd = _VERSION_COMMANDS.get(spec.id)
    if cmd is None:
        return None
    try:
        res = await ssh.container_exec(spec.container, cmd)
    except Exception:
        return None
    return parse_component_version(spec.id, f"{res.stdout}\n{res.stderr}")
