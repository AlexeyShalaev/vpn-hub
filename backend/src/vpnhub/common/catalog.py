"""Справочные данные (порт из прототипа): провайдеры, протоколы, клиенты, описания VPN."""

from __future__ import annotations

VPN_LABELS = {"amnezia": "Amnezia", "openvpn": "OpenVPN", "outline": "Outline", "hysteria2": "Hysteria2"}
VPN_DOT = {"amnezia": "#7C6CF0", "openvpn": "#E0833B", "outline": "#3E86E0", "hysteria2": "#28B98A"}
VPN_DESC = {
    "amnezia": "Маскируется под обычный трафик — лучший против блокировок.",
    "openvpn": "Классика, максимальная совместимость с устройствами.",
    "outline": "Один ключ, проще всего для новичков.",
    "hysteria2": "Быстрый QUIC-протокол с обфускацией — хорош на нестабильных и мобильных сетях.",
}
# OpenVPN — один контейнер amnezia-openvpn, транспорт (udp/tcp) — свойство установки,
# поэтому в каталоге один протокол «OpenVPN» (не два UDP/TCP).
# «Xray XHTTP» — отдельный протокол Amnezia (свой контейнер amnezia-xray-xhttp), сосуществует
# с обычным «Xray» (tcp-Reality); транспорт XHTTP обходит троттлинг QUIC и даёт свежий DPI-профиль.
PROTOS = {
    "amnezia": ["AmneziaWG", "AmneziaWG Legacy", "Xray", "Xray XHTTP"],
    "openvpn": ["OpenVPN"],
    "outline": ["Shadowsocks"],
    "hysteria2": ["Hysteria2"],
}

DEFAULT_PORTS = {"amnezia": "51820", "openvpn": "1194", "outline": "8443", "hysteria2": "443"}

PLATFORM_LABEL = {
    "ios": "iPhone / iPad",
    "android": "Android",
    "mac": "macOS",
    "windows": "Windows",
    "linux": "Linux",
    "router": "роутера",
}

# Каталог провайдеров вынесен в YAML (data/providers.default.yaml → VPNHUB_PROVIDERS_FILE),
# редактируется в рантайме через админку — см. infra/providers_store.py.

_A = "https://amnezia.org/downloads"
_O = "https://getoutline.org/get-started/"
_V = "https://openvpn.net/client/"
_H = "https://hiddify.com/"  # универсальный бесплатный клиент под Hysteria2/Xray на всех ОС

CLIENTS: dict[str, dict[str, list[dict]]] = {
    "amnezia": {
        "ios": [
            {"name": "AmneziaVPN", "store": "App Store", "url": "https://apps.apple.com/app/amneziavpn/id1600529900"},
            {
                "name": "AmneziaWG",
                "store": "App Store",
                "note": "облегчённый, только WireGuard",
                "url": "https://apps.apple.com/app/amneziawg/id6478942961",
                "wgOnly": True,
            },
            {
                "name": "DefaultVPN",
                "store": "App Store",
                "note": "альтернативный клиент",
                "url": "https://apps.apple.com/ru/app/defaultvpn/id6744725017",
            },
        ],
        "android": [
            {
                "name": "AmneziaVPN",
                "store": "Google Play",
                "url": "https://play.google.com/store/apps/details?id=org.amnezia.vpn",
            },
            {
                "name": "AmneziaWG",
                "store": "Google Play",
                "note": "облегчённый, только WireGuard",
                "url": "https://play.google.com/store/apps/details?id=org.amnezia.awg",
                "wgOnly": True,
            },
        ],
        "mac": [{"name": "AmneziaVPN", "store": "macOS · .dmg", "url": _A}],
        "windows": [{"name": "AmneziaVPN", "store": "Windows · .exe", "url": _A}],
        "linux": [{"name": "AmneziaVPN", "store": "Linux", "url": _A}],
        "router": [
            {
                "name": "AmneziaWG",
                "store": "OpenWrt / Keenetic",
                "note": "настройка через прошивку",
                "url": "https://amnezia.org/instructions",
                "wgOnly": True,
            }
        ],
    },
    "outline": {
        "ios": [
            {"name": "Outline", "store": "App Store", "url": "https://apps.apple.com/app/outline-app/id1356177741"}
        ],
        "android": [
            {
                "name": "Outline",
                "store": "Google Play",
                "url": "https://play.google.com/store/apps/details?id=org.outline.android.client",
            }
        ],
        "mac": [{"name": "Outline", "store": "macOS", "url": _O}],
        "windows": [{"name": "Outline", "store": "Windows", "url": _O}],
        "linux": [{"name": "Outline", "store": "Linux · AppImage", "url": _O}],
        "router": [],
    },
    "openvpn": {
        "ios": [
            {
                "name": "OpenVPN Connect",
                "store": "App Store",
                "url": "https://apps.apple.com/app/openvpn-connect/id590379981",
            }
        ],
        "android": [
            {
                "name": "OpenVPN Connect",
                "store": "Google Play",
                "url": "https://play.google.com/store/apps/details?id=net.openvpn.openvpn",
            }
        ],
        "mac": [{"name": "OpenVPN Connect", "store": "macOS", "url": _V}],
        "windows": [{"name": "OpenVPN Connect", "store": "Windows", "url": _V}],
        "linux": [
            {"name": "OpenVPN Connect", "store": "Linux", "url": "https://openvpn.net/openvpn-client-for-linux/"}
        ],
        "router": [{"name": "OpenVPN", "store": "прошивка роутера", "url": "https://openvpn.net/community-resources/"}],
    },
    "hysteria2": {
        "ios": [
            {
                "name": "Hiddify",
                "store": "App Store",
                "url": "https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532",
            },
            {"name": "Karing", "store": "App Store", "url": "https://apps.apple.com/app/karing/id6472431552"},
        ],
        "android": [
            {
                "name": "Hiddify",
                "store": "Google Play",
                "url": "https://play.google.com/store/apps/details?id=app.hiddify.com",
            },
            {
                "name": "NekoBox",
                "store": "GitHub",
                "note": "альтернативный клиент",
                "url": "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases",
            },
        ],
        "mac": [{"name": "Hiddify", "store": "macOS · .dmg", "url": _H}],
        "windows": [{"name": "Hiddify", "store": "Windows · .exe", "url": _H}],
        "linux": [{"name": "Hiddify", "store": "Linux · AppImage", "url": _H}],
        "router": [],
    },
}


def clients_for(vpn_type: str, platform: str) -> list[dict]:
    return CLIENTS.get(vpn_type, {}).get(platform, [])
