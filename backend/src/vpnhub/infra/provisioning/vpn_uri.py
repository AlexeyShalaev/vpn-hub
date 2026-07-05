"""Форматы конфигов Amnezia: vpn:// (native), vless:// (Xray), ss:// (Shadowsocks).

vpn:// (exportController.cpp:105-108):
    JSON(indented) → qCompress(zlib, level 8) → base64url без паддинга → префикс "vpn://".

Ключевой нюанс Qt qCompress: перед zlib-потоком идёт 4-байтовый BIG-ENDIAN uint32 —
несжатая длина. Именно префикс критичен для qUncompress (уровень сжатия — нет).
Воспроизводим байт-в-байт: struct.pack(">I", len(raw)) + zlib.compress(raw).

Схема native-конфига и имена ключей — из configKeys.h / *ProtocolConfig::toJson.
"""

from __future__ import annotations

import base64
import json
import struct
import zlib
from typing import Any, cast
from urllib.parse import quote

from vpnhub.infra.provisioning import constants as c
from vpnhub.infra.provisioning.awg_params import AwgParams

# ---------------------------------------------------------------- qCompress ---


def qcompress(data: bytes, level: int = 8) -> bytes:
    """Аналог Qt qCompress: 4-байтовый BE-префикс длины + стандартный zlib-поток."""
    return struct.pack(">I", len(data)) + zlib.compress(data, level)


def quncompress(blob: bytes) -> bytes:
    """Аналог Qt qUncompress (толерантный: при неудаче пробует поток целиком)."""
    if len(blob) >= 4:
        try:
            return zlib.decompress(blob[4:])
        except zlib.error:
            pass
    return zlib.decompress(blob)


# ------------------------------------------------------------------- vpn:// ---


def encode_vpn_url(config: dict) -> str:
    raw = json.dumps(config, ensure_ascii=False, indent=4).encode("utf-8")
    packed = qcompress(raw, 8)
    b64 = base64.urlsafe_b64encode(packed).rstrip(b"=").decode("ascii")
    return "vpn://" + b64


def decode_vpn_url(url: str) -> dict:
    s = url.replace("vpn://", "", 1)
    pad = "=" * (-len(s) % 4)
    blob = base64.urlsafe_b64decode(s + pad)
    return cast("dict[Any, Any]", json.loads(quncompress(blob)))


# ----------------------------------------------------- native config builders ---


def _compact(obj: dict) -> str:
    """Компактный JSON без пробелов (аналог QJsonDocument::Compact) — для last_config."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def build_awg_client_json(
    *,
    conf_text: str,
    server_ip: str,
    port: str,
    client_ip: str,
    client_priv_key: str,
    client_pub_key: str,
    server_pub_key: str,
    psk: str,
    params: AwgParams,
    is_awg2: bool,
    mtu: str = c.DEFAULT_MTU,
) -> dict:
    """AwgClientConfig::toJson (содержимое last_config)."""
    obj: dict = {
        "config": conf_text,
        "hostName": server_ip,
        "port": int(port),
        "client_ip": client_ip,
        "client_priv_key": client_priv_key,
        "client_pub_key": client_pub_key,
        "server_pub_key": server_pub_key,
        "psk_key": psk,
        "clientId": client_pub_key,
        "allowed_ips": list(c.CLIENT_ALLOWED_IPS),
        "persistent_keep_alive": c.PERSISTENT_KEEPALIVE,
        "mtu": mtu,
    }
    obj.update(params.config_json(is_awg2))
    obj["isObfuscationEnabled"] = False
    return obj


def build_awg_container(
    *,
    container: str,
    is_awg2: bool,
    server_ip: str,
    port: str,
    params: AwgParams,
    conf_text: str,
    client_ip: str,
    client_priv_key: str,
    client_pub_key: str,
    server_pub_key: str,
    psk: str,
    mtu: str = c.DEFAULT_MTU,
) -> dict:
    """Один элемент containers[] для AmneziaWG/Legacy: {"container": ..., "awg": proto_obj}."""
    proto_obj: dict = {
        "port": port,
        "subnet_address": params.subnet_address,
        "subnet_cidr": params.subnet_cidr,
    }
    if is_awg2:
        proto_obj["protocol_version"] = "2"
    proto_obj.update(params.config_json(is_awg2))
    client_json = build_awg_client_json(
        conf_text=conf_text,
        server_ip=server_ip,
        port=port,
        client_ip=client_ip,
        client_priv_key=client_priv_key,
        client_pub_key=client_pub_key,
        server_pub_key=server_pub_key,
        psk=psk,
        params=params,
        is_awg2=is_awg2,
        mtu=mtu,
    )
    proto_obj["last_config"] = _compact(client_json)
    return {"container": container, "awg": proto_obj}


def build_awg_native_config(
    *,
    container: str,
    is_awg2: bool,
    server_ip: str,
    server_name: str,
    port: str,
    params: AwgParams,
    conf_text: str,
    client_ip: str,
    client_priv_key: str,
    client_pub_key: str,
    server_pub_key: str,
    psk: str,
    mtu: str = c.DEFAULT_MTU,
) -> dict:
    """Полный native-конфиг Amnezia для AmneziaWG/Legacy (готов к encode_vpn_url) — один контейнер."""
    element = build_awg_container(
        container=container,
        is_awg2=is_awg2,
        server_ip=server_ip,
        port=port,
        params=params,
        conf_text=conf_text,
        client_ip=client_ip,
        client_priv_key=client_priv_key,
        client_pub_key=client_pub_key,
        server_pub_key=server_pub_key,
        psk=psk,
        mtu=mtu,
    )
    return {
        "containers": [element],
        "defaultContainer": container,
        "description": server_name,
        "hostName": server_ip,
    }


def build_xray_container(
    *,
    container: str,
    host: str,
    port: str,
    uuid: str,
    public_key: str,
    short_id: str,
    sni: str,
    flow: str = c.XRAY_DEFAULT_FLOW,
    fingerprint: str = c.XRAY_DEFAULT_FINGERPRINT,
) -> dict:
    """Один элемент containers[] для Xray (VLESS+Reality, tcp): {"container": ..., "xray": {last_config}}.

    last_config — строка с КЛИЕНТСКИМ xray-JSON (socks-inbound → vless-outbound), порт xrayConfigurator.
    Только tcp-Reality: xray_xhttp в бандл не входит (в клиенте нет контейнера amnezia-xray-xhttp).
    """
    last_config = {
        "inbounds": [{"listen": "127.0.0.1", "port": 10808, "protocol": "socks", "settings": {"udp": True}}],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": host,
                            "port": int(port),
                            "users": [{"id": uuid, "encryption": "none", "flow": flow}],
                        }
                    ]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": c.XRAY_DEFAULT_SECURITY,
                    "realitySettings": {
                        "publicKey": public_key,
                        "shortId": short_id,
                        "serverName": sni,
                        "fingerprint": fingerprint,
                        "spiderX": "",
                    },
                },
            }
        ],
    }
    return {"container": container, "xray": {"last_config": _compact(last_config)}}


CHAIN_OUTBOUND_TAG = "chain-exit"
FREEDOM_OUTBOUND: dict = {"protocol": "freedom"}


def build_chain_outbound(
    *,
    host: str,
    port: str,
    uuid: str,
    public_key: str,
    short_id: str,
    sni: str,
    flow: str = c.XRAY_DEFAULT_FLOW,
    fingerprint: str = c.XRAY_DEFAULT_FINGERPRINT,
) -> dict:
    """Outbound entry-сервера для мультихопа: vless+Reality-коннект на exit-сервер.

    Ставится в inbounds/outbounds server.json entry-контейнера ВМЕСТО `freedom`, так что трафик
    клиентов entry выходит в интернет через exit (entry = обычный vless-клиент exit). Структура —
    как клиентский xray-outbound (build_xray_container), но живёт на сервере, а не у клиента.
    tag="chain-exit" — стабильная метка, по ней снимаем цепочку (clear → freedom).
    """
    return {
        "tag": CHAIN_OUTBOUND_TAG,
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": host,
                    "port": int(port),
                    "users": [{"id": uuid, "encryption": "none", "flow": flow}],
                }
            ]
        },
        "streamSettings": {
            "network": "tcp",
            "security": c.XRAY_DEFAULT_SECURITY,
            "realitySettings": {
                "publicKey": public_key,
                "shortId": short_id,
                "serverName": sni,
                "fingerprint": fingerprint,
                "spiderX": "",
            },
        },
    }


def build_bundle_vpn_url(*, containers: list[dict], host: str, description: str, default_container: str) -> str:
    """Один vpn:// на весь сервер: несколько контейнеров-протоколов в одном объекте (переключатель клиента)."""
    return encode_vpn_url(
        {
            "containers": containers,
            "defaultContainer": default_container,
            "description": description,
            "hostName": host,
        }
    )


# -------------------------------------------------------------------- vless:// ---


def _clean_alias(alias: str) -> str:
    """Имя сервера для fragment (#) share-ссылки.

    Клиент Amnezia (и другие на QUrl) показывает fragment в режиме PrettyDecoded: `%20`
    декодируется в пробел, а gen-delims `[ ] @ #` остаются экранированными — из-за чего
    «Paris [FirstByte]» видно как «Paris %5BFirstByte%5D». Меняем скобки на круглые
    (sub-delim — декодируется), прочие проблемные gen-delims — на дефис.
    """
    return alias.translate(str.maketrans("[]@#", "()--"))


def build_vless_url(
    *,
    uuid: str,
    host: str,
    port: str,
    public_key: str,
    short_id: str,
    sni: str,
    flow: str = c.XRAY_DEFAULT_FLOW,
    fingerprint: str = c.XRAY_DEFAULT_FINGERPRINT,
    network: str = "tcp",
    path: str = "",
    mode: str = "",
    alias: str = "AmneziaVPN",
) -> str:
    """VLESS+REALITY ссылка (порт vless.cpp::Serialize).

    Порядок и guards: type(tcp — опускаем) / encryption / security / flow / sni / fp / pbk / sid.
    spiderX (spx) пуст — опускаем.

    network="xhttp": транспорт задаётся type=xhttp + path/mode; flow (xtls-rprx-vision) не
    применяется (работает только с raw/tcp), поэтому вызывающий передаёт flow="".
    """
    params = [
        ("encryption", "none"),
        ("security", c.XRAY_DEFAULT_SECURITY),
        ("flow", flow),
        ("sni", sni),
        ("fp", fingerprint),
        ("pbk", public_key),
        ("sid", short_id),
    ]
    if network and network != "tcp":
        params += [("type", network), ("path", path), ("mode", mode)]
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params if v)
    return f"vless://{uuid}@{host}:{port}?{query}#{quote(_clean_alias(alias))}"


# ------------------------------------------------------------- hysteria2:// ---


def build_hysteria2_url(
    *,
    password: str,
    host: str,
    port: str,
    sni: str,
    obfs_password: str = "",
    pin_sha256: str = "",
    alias: str = "VPNHub",
) -> str:
    """Hysteria2 ссылка: hysteria2://<password>@host:port/?sni=&obfs=&obfs-password=&pinSHA256=#alias.

    pinSHA256 (hex с двоеточиями) закрепляет self-signed серт вместо публичного CA — двоеточия
    оставляем как есть (safe=':'), их формат ждут клиенты Hysteria2.
    """
    params = [("sni", sni)]
    if obfs_password:
        params += [("obfs", "salamander"), ("obfs-password", obfs_password)]
    if pin_sha256:
        params.append(("pinSHA256", pin_sha256))

    def _q(k: str, v: str) -> str:
        return f"{k}={quote(str(v), safe=':' if k == 'pinSHA256' else '')}"

    query = "&".join(_q(k, v) for k, v in params if v)
    tail = f"/?{query}" if query else "/"
    return f"hysteria2://{quote(password, safe='')}@{host}:{port}{tail}#{quote(_clean_alias(alias))}"


# ---------------------------------------------------------------------- ss:// ---


def build_ss_url(
    *, method: str, password: str, host: str, port: str, alias: str = "VPNHub", outline: bool = False
) -> str:
    """Shadowsocks SIP002: ss://base64url(method:password)@host:port[/?outline=1]#alias.

    outline=True добавляет метку `/?outline=1` — так ключ помечает Outline-сервер (совпадает
    с форматом accessUrl, который отдаёт shadowbox), и приложение Outline берёт его без правок.
    """
    userinfo = base64.urlsafe_b64encode(f"{method}:{password}".encode()).rstrip(b"=").decode()
    tail = "/?outline=1" if outline else ""
    return f"ss://{userinfo}@{host}:{port}{tail}#{quote(_clean_alias(alias))}"
