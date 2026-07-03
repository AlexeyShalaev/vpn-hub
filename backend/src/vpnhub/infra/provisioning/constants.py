"""Константы provisioning Amnezia (порт из amnezia-client).

Здесь — реестр протоколов Amnezia и все дефолты, взятые 1:1 из исходников клиента
(`core/utils/constants/protocolConstants.h`, `scriptsRegistry.cpp`, `containerUtils.cpp`).

vpn-hub оперирует «вендором» (amnezia/openvpn/outline) и «протоколом» (label из
`catalog.PROTOS`). Один протокол Amnezia = один docker-контейнер на сервере.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- сетевые дефолты (protocolConstants.h) ---
DEFAULT_SUBNET_ADDRESS = "10.8.1.0"
DEFAULT_SUBNET_CIDR = "24"
DEFAULT_MTU = "1376"  # desktop; на мобильных Amnezia ставит 1280
PERSISTENT_KEEPALIVE = "25"
CLIENT_ALLOWED_IPS = ["0.0.0.0/0", "::/0"]

# DNS клиента: Amnezia по умолчанию CloudFlare (secureAppSettings cloudFlareNs1).
CLIENT_PRIMARY_DNS = "1.1.1.1"
CLIENT_SECONDARY_DNS = "1.0.0.1"
# DNS сервера (genBaseVars): 8.8.8.8 / 8.8.4.4
SERVER_PRIMARY_DNS = "8.8.8.8"
SERVER_SECONDARY_DNS = "8.8.4.4"

# docker-сеть Amnezia (prepare_host.sh)
DNS_NET_NAME = "amnezia-dns-net"

VENDOR_AMNEZIA = "amnezia"
VENDOR_OPENVPN = "openvpn"
VENDOR_OUTLINE = "outline"

# --- OpenVPN дефолты (protocolConstants.h namespace openvpn) ---
OPENVPN_SUBNET_IP = "10.8.0.0"
OPENVPN_SUBNET_MASK = "255.255.255.0"
OPENVPN_SUBNET_CIDR = "24"
OPENVPN_DEFAULT_CIPHER = "AES-256-GCM"
OPENVPN_DEFAULT_HASH = "SHA512"
# tls-auth включён по умолчанию (defaultTlsAuth=true); строка серверного конфига и путь ta.key
OPENVPN_TLS_AUTH_LINE = "tls-auth /opt/amnezia/openvpn/ta.key 0"


@dataclass(frozen=True)
class ProtoSpec:
    """Описание одного протокола Amnezia (контейнер + пути + бинарники)."""

    id: str  # внутренний id: awg | awg_legacy | xray | openvpn
    label: str  # человекочитаемый label из catalog.PROTOS
    vendor: str  # amnezia | openvpn
    kind: str  # wireguard | xray | openvpn  (семейство для выбора логики)
    container: str  # имя docker-контейнера (amnezia-*)
    script_folder: str  # папка в server_scripts/
    proto_key: str  # ключ протокола в native-конфиге (awg | xray)
    default_port: str
    transport: str  # udp | tcp

    # --- поля семейства wireguard/awg ---
    interface: str = ""  # awg0 | wg0
    bin: str = ""  # awg | wg
    server_config_path: str = ""  # /opt/amnezia/awg/awg0.conf
    server_pubkey_path: str = ""
    server_psk_path: str = ""
    is_awg2: bool = False  # современный AmneziaWG (range-заголовки, S3/S4)

    # --- поля xray ---
    xray_public_key_path: str = ""
    xray_short_id_path: str = ""
    xray_uuid_path: str = ""

    # --- поля openvpn ---
    openvpn_ca_path: str = ""  # /opt/amnezia/openvpn/pki/ca.crt
    openvpn_ta_path: str = ""  # /opt/amnezia/openvpn/ta.key
    openvpn_issued_dir: str = ""  # /opt/amnezia/openvpn/pki/issued (<cn>.crt)
    openvpn_clients_dir: str = ""  # /opt/amnezia/openvpn/clients (<cn>.req)

    # --- поля outline (Jigsaw shadowbox) ---
    outline_state_dir: str = ""  # SHADOWBOX_DIR (/opt/outline)
    outline_access_config: str = ""  # access.txt со строками apiUrl:/certSha256: (для adopt)


_AWG_PUBKEY = "/opt/amnezia/awg/wireguard_server_public_key.key"
_AWG_PSK = "/opt/amnezia/awg/wireguard_psk.key"

AWG = ProtoSpec(
    id="awg",
    label="AmneziaWG",
    vendor=VENDOR_AMNEZIA,
    kind="wireguard",
    container="amnezia-awg2",
    script_folder="awg",
    proto_key="awg",
    default_port="55424",
    transport="udp",
    interface="awg0",
    bin="awg",
    server_config_path="/opt/amnezia/awg/awg0.conf",
    server_pubkey_path=_AWG_PUBKEY,
    server_psk_path=_AWG_PSK,
    is_awg2=True,
)

AWG_LEGACY = ProtoSpec(
    id="awg_legacy",
    label="AmneziaWG Legacy",
    vendor=VENDOR_AMNEZIA,
    kind="wireguard",
    container="amnezia-awg",
    script_folder="awg_legacy",
    proto_key="awg",
    # ВАЖНО: отличается от awg (55424) — иначе оба контейнера дерутся за один host-порт
    # и второй остаётся в статусе "Created" (см. диагностику KVM-SSD-1-PAR).
    default_port="55425",
    transport="udp",
    interface="wg0",
    bin="wg",
    server_config_path="/opt/amnezia/awg/wg0.conf",
    server_pubkey_path=_AWG_PUBKEY,
    server_psk_path=_AWG_PSK,
    is_awg2=False,
)

XRAY = ProtoSpec(
    id="xray",
    label="Xray",
    vendor=VENDOR_AMNEZIA,
    kind="xray",
    container="amnezia-xray",
    script_folder="xray",
    proto_key="xray",
    default_port="443",
    transport="tcp",
    xray_public_key_path="/opt/amnezia/xray/xray_public.key",
    xray_short_id_path="/opt/amnezia/xray/xray_short_id.key",
    xray_uuid_path="/opt/amnezia/xray/xray_uuid.key",
)

OPENVPN = ProtoSpec(
    id="openvpn",
    label="OpenVPN",
    vendor=VENDOR_OPENVPN,
    kind="openvpn",
    container="amnezia-openvpn",
    script_folder="openvpn",
    proto_key="openvpn",
    default_port="1194",
    transport="udp",
    server_config_path="/opt/amnezia/openvpn/server.conf",
    openvpn_ca_path="/opt/amnezia/openvpn/pki/ca.crt",
    openvpn_ta_path="/opt/amnezia/openvpn/ta.key",
    openvpn_issued_dir="/opt/amnezia/openvpn/pki/issued",
    openvpn_clients_dir="/opt/amnezia/openvpn/clients",
)

# Outline = один контейнер shadowbox (Jigsaw), управляется через Management REST API
# (не правкой файлов, как Amnezia/OpenVPN). Один вендор = один протокол «Shadowsocks».
# default_port = keys-port (общий порт всех access-key), совпадает с DEFAULT_PORTS["outline"].
OUTLINE = ProtoSpec(
    id="outline",
    label="Shadowsocks",  # совпадает с catalog.PROTOS["outline"][0]
    vendor=VENDOR_OUTLINE,
    kind="outline",
    container="shadowbox",
    script_folder="outline",
    proto_key="outline",
    default_port="8443",
    transport="tcp",
    outline_state_dir="/opt/outline",
    outline_access_config="/opt/outline/access.txt",
)

# протоколы одного вендора Amnezia (клиент Amnezia = 3 контейнера)
AMNEZIA_PROTOCOLS: dict[str, ProtoSpec] = {p.id: p for p in (AWG, AWG_LEGACY, XRAY)}
# глобальный реестр всех протоколов (для spec_by_id / spec_by_label поверх всех вендоров)
PROTOCOLS: dict[str, ProtoSpec] = {p.id: p for p in (AWG, AWG_LEGACY, XRAY, OPENVPN, OUTLINE)}
# id протоколов по вендору — для установки/сверки всего вендора разом
VENDOR_PROTOS: dict[str, tuple[str, ...]] = {
    VENDOR_AMNEZIA: (AWG.id, AWG_LEGACY.id, XRAY.id),
    VENDOR_OPENVPN: (OPENVPN.id,),
    VENDOR_OUTLINE: (OUTLINE.id,),
}
# label (как в catalog.PROTOS) -> ProtoSpec
_BY_LABEL: dict[str, ProtoSpec] = {p.label: p for p in PROTOCOLS.values()}

# xray defaults (protocolConstants.h namespace xray)
XRAY_DEFAULT_SITE = "www.googletagmanager.com"
XRAY_DEFAULT_FLOW = "xtls-rprx-vision"
XRAY_DEFAULT_FINGERPRINT = "chrome"
XRAY_DEFAULT_SECURITY = "reality"

# файл clientsTable внутри контейнера: /opt/amnezia/<proto>/clientsTable
# <proto> = openvpn|wireguard|awg|xray (awg2 и awg legacy оба — "awg")
# outline не использует clientsTable (членство хранит сам shadowbox), сюда не входит.
CLIENTS_TABLE_PROTO = {"awg": "awg", "awg_legacy": "awg", "xray": "xray", "openvpn": "openvpn"}


def spec_by_id(proto_id: str) -> ProtoSpec:
    if proto_id not in PROTOCOLS:
        raise KeyError(f"Неизвестный протокол: {proto_id}")
    return PROTOCOLS[proto_id]


def spec_by_label(label: str) -> ProtoSpec | None:
    return _BY_LABEL.get(label)


def clients_table_path(spec: ProtoSpec) -> str:
    return f"/opt/amnezia/{CLIENTS_TABLE_PROTO[spec.id]}/clientsTable"
