"""Интеграционные тесты ConfigService: объединение amnezia-протоколов в один vpn:// (бандл).

SSH не задействован — конфиги устройства заранее существуют, поэтому _build_amnezia_bundle
только читает состояние и собирает containers[]. Крипто/формат ссылки покрыты в test_provisioning_pure.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from tests.factories.orm import make_device, make_device_config, make_server, make_server_protocol, make_user, seed
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import vpn_uri
from vpnhub.infra.provisioning.awg_params import generate as gen_awg_params
from vpnhub.infra.provisioning.provisioners.base import ServerMaterial
from vpnhub.infra.security import encrypt_secret
from vpnhub.services.configs import ConfigService

pytestmark = pytest.mark.integration


async def test__build_amnezia_bundle__awg_and_xray_installed__one_vpn_url_two_containers(uow, settings, session_maker):
    """Установлены awg2 + xray с готовыми конфигами устройства → один vpn:// с двумя containers[]."""
    # Arrange
    key = settings.secret_key
    awg_material = encrypt_secret(key, json.dumps(ServerMaterial(server_public_key="SPUB", psk="PSK").as_dict()))
    awg_params = json.dumps(gen_awg_params(is_awg2=True).as_dict())
    xray_material = encrypt_secret(
        key,
        json.dumps(ServerMaterial(xray_public_key="XPBK", short_id="0123456789abcdef", site="www.bing.com").as_dict()),
    )
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id, status="online")
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="awg",
            vendor="amnezia",
            container="amnezia-awg2",
            state="installed",
            installed=True,
            running=True,
            material_encrypted=awg_material,
            params_json=awg_params,
        )
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="xray",
            vendor="amnezia",
            container="amnezia-xray",
            state="installed",
            installed=True,
            running=True,
            material_encrypted=xray_material,
        )
        dev = await make_device(s, user_id=owner.id)
        # готовые конфиги устройства (proto хранит LABEL): AmneziaWG и Xray
        await make_device_config(
            s,
            device_id=dev.id,
            server_id=server.id,
            vpn_type="amnezia",
            proto="AmneziaWG",
            client_id="WGPUB",
            client_ip="10.8.1.2",
        )
        await make_device_config(
            s,
            device_id=dev.id,
            server_id=server.id,
            vpn_type="amnezia",
            proto="Xray",
            client_id="xray-uuid-1",
        )
    svc = ConfigService(uow, settings)

    # Act
    bundle = await svc._build_amnezia_bundle(owner.id, server.id, dev.id)

    # Assert — один vpn:// с двумя контейнерами в каталожном порядке, defaultContainer = xray
    assert bundle is not None and bundle.startswith("vpn://")
    doc = vpn_uri.decode_vpn_url(bundle)
    assert doc["hostName"] == server.ip
    assert doc["defaultContainer"] == "amnezia-xray"
    assert [c["container"] for c in doc["containers"]] == ["amnezia-awg2", "amnezia-xray"]
    # xray-контейнер несёт uuid клиента из DeviceConfig
    xr = json.loads(doc["containers"][1]["xray"]["last_config"])
    assert xr["outbounds"][0]["settings"]["vnext"][0]["users"][0]["id"] == "xray-uuid-1"


async def test__build_amnezia_bundle__only_xray_xhttp__returns_none(uow, settings, session_maker):
    """Только xray_xhttp установлен (не бандлится) → бандла нет (отдаётся отдельным vless://)."""
    # Arrange
    xray_material = encrypt_secret(
        settings.secret_key,
        json.dumps(ServerMaterial(xray_public_key="XPBK", short_id="0123456789abcdef", site="www.bing.com").as_dict()),
    )
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id, status="online")
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="xray_xhttp",
            vendor="amnezia",
            container="amnezia-xray-xhttp",
            state="installed",
            installed=True,
            running=True,
            material_encrypted=xray_material,
        )
        dev = await make_device(s, user_id=owner.id)
    svc = ConfigService(uow, settings)

    # Act
    bundle = await svc._build_amnezia_bundle(owner.id, server.id, dev.id)

    # Assert
    assert bundle is None


async def test__generate__peek__lists_protocols_without_provisioning(uow, settings, session_maker):
    """peek=True отдаёт установленные протоколы и приложения, но НЕ создаёт клиента (DeviceConfig)."""
    # Arrange — awg + xray установлены, конфигов на устройстве НЕТ
    awg_material = encrypt_secret(
        settings.secret_key, json.dumps(ServerMaterial(server_public_key="SPUB", psk="PSK").as_dict())
    )
    awg_params = json.dumps(gen_awg_params(is_awg2=True).as_dict())
    xray_material = encrypt_secret(
        settings.secret_key,
        json.dumps(ServerMaterial(xray_public_key="XPBK", short_id="0123456789abcdef", site="www.bing.com").as_dict()),
    )
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id, status="online")
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="awg",
            vendor="amnezia",
            container="amnezia-awg2",
            state="installed",
            installed=True,
            running=True,
            material_encrypted=awg_material,
            params_json=awg_params,
        )
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="xray",
            vendor="amnezia",
            container="amnezia-xray",
            state="installed",
            installed=True,
            running=True,
            material_encrypted=xray_material,
        )
        dev = await make_device(s, user_id=owner.id)
    svc = ConfigService(uow, settings)

    # Act — peek (минуя гейт доступа: вызываем _generate_provisioned напрямую)
    res = await svc._generate_provisioned("amnezia", owner.id, server.id, dev.id, None, "ios", peek=True)

    # Assert — список установленных протоколов и приложения есть, конфига/провижининга нет
    assert res["formats"] == []
    assert res["text"] == "" and res["uri"] == ""
    assert set(res["protos"]) >= {"AmneziaWG", "Xray"}
    # bundle — установленные склеиваемые протоколы (awg/xray), одной кнопкой «все сразу» в UI
    assert set(res["bundle"]) == {"AmneziaWG", "Xray"}
    assert len(res["clients"]) > 0
    # никакого провижининга: DeviceConfig для устройства не создан
    async with uow.query() as tx:
        rows = (
            (await tx.session.execute(select(m.DeviceConfig).where(m.DeviceConfig.device_id == dev.id))).scalars().all()
        )
    assert rows == []


async def test__generate__xray_xhttp_selected__own_config_without_bundle(uow, settings, session_maker):
    """Явно выбран xray_xhttp (в бандл не входит) → отдаём его собственный vless://, БЕЗ формата-бандла,
    даже если рядом установлен склеиваемый awg."""
    key = settings.secret_key
    awg_material = encrypt_secret(key, json.dumps(ServerMaterial(server_public_key="SPUB", psk="PSK").as_dict()))
    awg_params = json.dumps(gen_awg_params(is_awg2=True).as_dict())
    xhttp_material = encrypt_secret(
        key,
        json.dumps(
            ServerMaterial(
                xray_public_key="XPBK", short_id="0123456789abcdef", site="www.bing.com", xhttp_path="/abc"
            ).as_dict()
        ),
    )
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id, status="online")
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="awg",
            vendor="amnezia",
            container="amnezia-awg2",
            state="installed",
            installed=True,
            running=True,
            material_encrypted=awg_material,
            params_json=awg_params,
        )
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="xray_xhttp",
            vendor="amnezia",
            container="amnezia-xray-xhttp",
            state="installed",
            installed=True,
            running=True,
            material_encrypted=xhttp_material,
        )
        dev = await make_device(s, user_id=owner.id)
        # готовые конфиги устройства: awg (склеиваемый) и Xray XHTTP (нет)
        await make_device_config(
            s,
            device_id=dev.id,
            server_id=server.id,
            vpn_type="amnezia",
            proto="AmneziaWG",
            client_id="WGPUB",
            client_ip="10.8.1.2",
        )
        await make_device_config(
            s,
            device_id=dev.id,
            server_id=server.id,
            vpn_type="amnezia",
            proto="Xray XHTTP",
            client_id="xhttp-uuid-1",
        )
    svc = ConfigService(uow, settings)

    # Act — выдаём именно xray_xhttp
    res = await svc._generate_provisioned("amnezia", owner.id, server.id, dev.id, "Xray XHTTP", "ios", peek=False)

    # Assert — формата-бандла (id="amnezia") нет; отдана собственная vless-ссылка с uuid xhttp-клиента
    assert "amnezia" not in [f["id"] for f in res["formats"]]
    assert res["uri"].startswith("vless://") and "xhttp-uuid-1" in res["uri"]
    # имя сервера помечено XHTTP — чтобы в клиенте отличать от обычного Xray/бандла
    assert "XHTTP" in res["uri"]


async def test__generate__single_bundlable_vs_bundle__containers_count(uow, settings, session_maker):
    """bundle=False на склеиваемом протоколе → vpn:// с ОДНИМ контейнером (только он);
    bundle=True → объединённый vpn:// со всеми склеиваемыми (awg+xray). Даёт выдачу «по одному»."""
    key = settings.secret_key
    awg_material = encrypt_secret(key, json.dumps(ServerMaterial(server_public_key="SPUB", psk="PSK").as_dict()))
    awg_params = json.dumps(gen_awg_params(is_awg2=True).as_dict())
    xray_material = encrypt_secret(
        key,
        json.dumps(ServerMaterial(xray_public_key="XPBK", short_id="0123456789abcdef", site="www.bing.com").as_dict()),
    )
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id, status="online")
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="awg",
            vendor="amnezia",
            container="amnezia-awg2",
            state="installed",
            installed=True,
            running=True,
            material_encrypted=awg_material,
            params_json=awg_params,
        )
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="xray",
            vendor="amnezia",
            container="amnezia-xray",
            state="installed",
            installed=True,
            running=True,
            material_encrypted=xray_material,
        )
        dev = await make_device(s, user_id=owner.id)
        await make_device_config(
            s,
            device_id=dev.id,
            server_id=server.id,
            vpn_type="amnezia",
            proto="AmneziaWG",
            client_id="WGPUB",
            client_ip="10.8.1.2",
        )
        await make_device_config(
            s, device_id=dev.id, server_id=server.id, vpn_type="amnezia", proto="Xray", client_id="xray-uuid-1"
        )
    svc = ConfigService(uow, settings)

    # bundle=False на awg → один контейнер (только awg), без склейки с xray
    single = await svc._generate_provisioned(
        "amnezia", owner.id, server.id, dev.id, "AmneziaWG", "ios", peek=False, bundle=False
    )
    assert single["uri"].startswith("vpn://")
    assert len(vpn_uri.decode_vpn_url(single["uri"])["containers"]) == 1

    # bundle=True (без явного протокола) → объединённый vpn:// с двумя контейнерами (awg + xray)
    both = await svc._generate_provisioned("amnezia", owner.id, server.id, dev.id, None, "ios", peek=False, bundle=True)
    assert both["uri"].startswith("vpn://")
    assert len(vpn_uri.decode_vpn_url(both["uri"])["containers"]) == 2
