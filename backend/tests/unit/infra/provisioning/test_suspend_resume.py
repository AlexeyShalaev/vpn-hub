"""Этап 3b: команды suspend_client/resume_client каждого провизионера (fake SSH, без сети).

Проверяем, что механизм отсечки СОХРАНЯЕТ материал/слот и обратим:
- awg: iptables DROP/удаление клиентского /32 (peer НЕ трогаем);
- xray: убрать/вернуть ТОТ ЖЕ uuid в живом server.json;
- hysteria2: убрать/вернуть строку `cid password`;
- outline: per-key data-limit 0 / снятие лимита (ключ цел);
- openvpn: ccd/<CN> disable / удаление (серт цел).
"""

from __future__ import annotations

import json

import pytest

from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.provisioners.awg import AwgProvisioner
from vpnhub.infra.provisioning.provisioners.base import ClientMaterial, ServerMaterial
from vpnhub.infra.provisioning.provisioners.hysteria2 import HysteriaProvisioner
from vpnhub.infra.provisioning.provisioners.openvpn import OpenVpnProvisioner
from vpnhub.infra.provisioning.provisioners.outline import OutlineProvisioner
from vpnhub.infra.provisioning.provisioners.xray import XrayProvisioner

pytestmark = pytest.mark.unit


class _Res:
    def __init__(self, exit_status: int = 0, stdout: str = "") -> None:
        self.exit_status = exit_status
        self.stdout = stdout
        self.output = stdout


class RecSsh:
    """Записывает run-команды и загрузки файлов; отдаёт заготовленное содержимое файлов."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.cmds: list[str] = []
        self.uploads: list[tuple[str, str, str]] = []  # (container|host, path, text)
        self.files = files or {}

    async def run(self, cmd: str) -> _Res:
        self.cmds.append(cmd)
        return _Res(0, "")

    async def read_container_text(self, container: str, path: str) -> str:
        if path in self.files:
            return self.files[path]
        raise FileNotFoundError(path)

    async def upload_to_container(self, container: str, text: str, path: str, append: bool = False) -> None:
        self.uploads.append((container, path, text))

    async def upload_to_host(self, text: str, path: str) -> None:
        self.uploads.append(("host", path, text))


# ---- awg: firewall ----


async def test__awg_suspend_resume__firewall_by_client_ip() -> None:
    prov = AwgProvisioner(pc.spec_by_id("awg"))
    mat = ClientMaterial(client_id="PUBKEY", client_ip="10.8.1.5")
    ssh = RecSsh()
    await prov.suspend_client(ssh, mat)
    joined = "\n".join(ssh.cmds)
    assert "-I FORWARD -s 10.8.1.5/32 -j DROP" in joined
    assert "-I FORWARD -d 10.8.1.5/32 -j DROP" in joined
    assert "-C FORWARD -s 10.8.1.5/32 -j DROP" in joined  # идемпотентная проверка перед вставкой

    ssh2 = RecSsh()
    await prov.resume_client(ssh2, mat)
    joined2 = "\n".join(ssh2.cmds)
    assert "-D FORWARD -s 10.8.1.5/32 -j DROP" in joined2
    assert "-D FORWARD -d 10.8.1.5/32 -j DROP" in joined2


async def test__awg_suspend__no_ip__noop() -> None:
    prov = AwgProvisioner(pc.spec_by_id("awg"))
    ssh = RecSsh()
    await prov.suspend_client(ssh, ClientMaterial(client_id="PUBKEY", client_ip=""))
    assert ssh.cmds == []  # без client_ip нечего блокировать


# ---- xray: убрать/вернуть тот же uuid ----

_XRAY_JSON = "/opt/amnezia/xray/server.json"


async def test__xray_suspend__removes_uuid_from_live_config() -> None:
    doc = {"inbounds": [{"settings": {"clients": [{"id": "UUID-A"}, {"id": "UUID-B"}]}}]}
    ssh = RecSsh({_XRAY_JSON: json.dumps(doc)})
    prov = XrayProvisioner(pc.spec_by_id("xray"))
    await prov.suspend_client(ssh, ClientMaterial(client_id="UUID-A"))
    written = json.loads(ssh.uploads[-1][2])
    ids = [x["id"] for x in written["inbounds"][0]["settings"]["clients"]]
    assert ids == ["UUID-B"]  # UUID-A убран, остальные целы


async def test__xray_resume__readds_same_uuid() -> None:
    doc = {"inbounds": [{"settings": {"clients": [{"id": "UUID-B"}]}}]}
    ssh = RecSsh({_XRAY_JSON: json.dumps(doc)})
    prov = XrayProvisioner(pc.spec_by_id("xray"))
    await prov.resume_client(ssh, ClientMaterial(client_id="UUID-A"))
    written = json.loads(ssh.uploads[-1][2])
    ids = {x["id"] for x in written["inbounds"][0]["settings"]["clients"]}
    assert ids == {"UUID-A", "UUID-B"}  # тот же uuid возвращён


async def test__xray_resume__already_present__noop() -> None:
    doc = {"inbounds": [{"settings": {"clients": [{"id": "UUID-A"}]}}]}
    ssh = RecSsh({_XRAY_JSON: json.dumps(doc)})
    prov = XrayProvisioner(pc.spec_by_id("xray"))
    await prov.resume_client(ssh, ClientMaterial(client_id="UUID-A"))
    assert ssh.uploads == []  # уже на месте — контейнер не трогаем


# ---- hysteria2: убрать/вернуть строку ----


async def test__hysteria_suspend_resume__line() -> None:
    spec = pc.spec_by_id("hysteria2")
    users = spec.hysteria_users_path
    ssh = RecSsh({users: "AAA passA\nBBB passB\n"})
    prov = HysteriaProvisioner(spec)
    await prov.suspend_client(ssh, ClientMaterial(client_id="AAA", client_private_key="passA"))
    assert ssh.uploads[-1][2] == "BBB passB\n"  # строка AAA убрана

    ssh2 = RecSsh({users: "BBB passB\n"})
    await prov.resume_client(ssh2, ClientMaterial(client_id="AAA", client_private_key="passA"))
    # resume дописывает ТУ ЖЕ пару (append) — грузим строку с cid и паролем
    assert ssh2.uploads[-1][2] == "AAA passA\n"


# ---- outline: data-limit 0 / снять ----


def _outline() -> OutlineProvisioner:
    return OutlineProvisioner(
        pc.spec_by_id("outline"), material=ServerMaterial(outline_api_url="https://1.2.3.4:9000/abcDEF")
    )


async def test__outline_suspend__sets_zero_data_limit() -> None:
    ssh = RecSsh()
    await _outline().suspend_client(ssh, ClientMaterial(client_id="key1"))
    # тело с limit.bytes=0 грузится файлом, PUT на /access-keys/<id>/data-limit
    assert any('"bytes": 0' in text for _c, _p, text in ssh.uploads)
    assert any("-X PUT" in c and "/access-keys/key1/data-limit" in c for c in ssh.cmds)


async def test__outline_resume__removes_data_limit() -> None:
    ssh = RecSsh()
    await _outline().resume_client(ssh, ClientMaterial(client_id="key1"))
    assert any("-X DELETE" in c and "/access-keys/key1/data-limit" in c for c in ssh.cmds)


# ---- openvpn: ccd disable / снять ----

_OVPN_CONF = "/opt/amnezia/openvpn/server.conf"


async def test__openvpn_suspend__enables_ccd_and_writes_disable() -> None:
    ssh = RecSsh({_OVPN_CONF: "port 1194\nproto udp\n"})  # ccd ещё не включён
    prov = OpenVpnProvisioner(pc.spec_by_id("openvpn"))
    await prov.suspend_client(ssh, ClientMaterial(client_id="CN1"))
    # включили client-config-dir в server.conf
    assert any(path == _OVPN_CONF and "client-config-dir" in text for _c, path, text in ssh.uploads)
    # записали ccd/<CN> с disable
    assert any(path.endswith("/ccd/CN1") and text.strip() == "disable" for _c, path, text in ssh.uploads)
    assert any("restart" in c for c in ssh.cmds)  # первый раз — рестарт контейнера


async def test__openvpn_suspend__ccd_already_on__no_restart() -> None:
    ssh = RecSsh({_OVPN_CONF: "port 1194\nclient-config-dir /opt/amnezia/openvpn/ccd\n"})
    prov = OpenVpnProvisioner(pc.spec_by_id("openvpn"))
    await prov.suspend_client(ssh, ClientMaterial(client_id="CN1"))
    assert not any("restart" in c for c in ssh.cmds)  # уже включён — не рестартим
    assert any(path.endswith("/ccd/CN1") and "disable" in text for _c, path, text in ssh.uploads)


async def test__openvpn_resume__removes_disable_file() -> None:
    ssh = RecSsh()
    prov = OpenVpnProvisioner(pc.spec_by_id("openvpn"))
    await prov.resume_client(ssh, ClientMaterial(client_id="CN1"))
    assert any("rm -f" in c and "/ccd/CN1" in c for c in ssh.cmds)
