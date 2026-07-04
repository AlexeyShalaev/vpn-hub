"""Юнит-тесты чистых частей provisioning: ключи, awg-параметры, выделение IP, vpn:// / vless://, шаблоны.

Только детерминированная/чистая логика — SSH и контейнеры не задействованы (фейковые ssh-клиенты
для list_*_ids отдают заранее заданный ответ).
"""

from __future__ import annotations

import base64
import json
import random
import string
import struct
import zlib

import pytest
from cryptography import x509
from cryptography.x509.oid import NameOID

from vpnhub.infra.provisioning import awg_params, ipalloc, keys, templates, vpn_uri
from vpnhub.infra.provisioning import constants as c
from vpnhub.infra.provisioning.awg_params import AwgParams
from vpnhub.infra.provisioning.errors import ProvisioningError
from vpnhub.infra.provisioning.provisioners.awg import AwgProvisioner
from vpnhub.infra.provisioning.provisioners.base import ClientMaterial, ServerMaterial
from vpnhub.infra.provisioning.provisioners.hysteria2 import HysteriaProvisioner
from vpnhub.infra.provisioning.provisioners.openvpn import OpenVpnProvisioner, _sanitize_static_key
from vpnhub.infra.provisioning.provisioners.xray import XrayProvisioner
from vpnhub.infra.provisioning.ssh import SshResult

pytestmark = pytest.mark.unit


# ------------------------------------------------------------------- keys ---


def test__gen_wg_keypair__generated__is_valid_and_pubkey_derives_from_priv() -> None:
    """Ключевая пара WireGuard — 32-байтные base64, публичный детерминированно выводится из приватного."""
    # Arrange / Act
    priv, pub = keys.gen_wg_keypair()
    # Assert
    assert len(base64.b64decode(priv)) == 32
    assert len(base64.b64decode(pub)) == 32
    assert keys.wg_pubkey(priv) == pub


def test__gen_wg_keypair__called_twice__private_keys_differ() -> None:
    """Каждая генерация даёт новый приватный ключ (не константа)."""
    # Arrange / Act / Assert
    assert keys.gen_wg_keypair()[0] != keys.gen_wg_keypair()[0]


def test__gen_psk_short_id_uuid__generated__match_expected_shapes() -> None:
    """psk — 32 байта base64; short_id — 16 hex-символов; uuid — без фигурных скобок, с 4 дефисами."""
    # Arrange / Act
    psk = keys.gen_psk()
    short_id = keys.gen_short_id()
    uuid_str = keys.gen_uuid()
    # Assert
    assert len(base64.b64decode(psk)) == 32
    assert len(short_id) == 16 and all(ch in "0123456789abcdef" for ch in short_id)
    assert uuid_str.count("-") == 4 and "{" not in uuid_str


# -------------------------------------------------------------- awg params ---


@pytest.mark.parametrize("seed", range(50))
def test__awg_params_generate__awg2__satisfies_constraints(seed: int) -> None:
    """AWG2-параметры укладываются в диапазоны, уникальны и помечены версией протокола «2»."""
    # Arrange / Act
    p = awg_params.generate(is_awg2=True, rng=random.Random(seed))
    # Assert
    assert 4 <= int(p.jc) <= 6
    assert p.jmin == "10" and p.jmax == "50"
    s1, s2, s3, s4 = int(p.s1), int(p.s2), int(p.s3), int(p.s4)
    assert 15 <= s1 <= 149 and 15 <= s2 <= 149
    assert 0 <= s3 <= 63 and 0 <= s4 <= 19
    assert len({s1, s2, s3, s4}) == 4  # все уникальны
    assert s1 + 148 != s2 + 92
    assert s1 + 148 != s3 + 64 and s2 + 92 != s3 + 64
    # awg2: заголовки — возрастающие диапазоны "first-second"
    for h in (p.h1, p.h2, p.h3, p.h4):
        a, b = h.split("-")
        assert int(a) <= int(b)
    assert p.protocol_version == "2"


@pytest.mark.parametrize("seed", range(50))
def test__awg_params_generate__legacy__has_unique_single_headers(seed: int) -> None:
    """Legacy-параметры: одиночные уникальные заголовки (без диапазонов), без версии протокола."""
    # Arrange / Act
    p = awg_params.generate(is_awg2=False, rng=random.Random(seed))
    # Assert
    headers = [p.h1, p.h2, p.h3, p.h4]
    for h in headers:
        assert "-" not in h and int(h) >= 5
    assert len(set(headers)) == 4
    assert p.protocol_version == ""


def test__awg_params_config_json__awg2_vs_legacy__s3s4_only_in_awg2() -> None:
    """config_json для awg2 содержит S3/S4 и обязательные поля; для legacy — без S3/S4."""
    # Arrange
    p = awg_params.generate(is_awg2=True, rng=random.Random(1))
    # Act
    j2 = p.config_json(is_awg2=True)
    jl = p.config_json(is_awg2=False)
    # Assert
    assert "S3" in j2 and "S4" in j2
    assert "S3" not in jl and "S4" not in jl
    assert {"Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4", "I1", "I5"} <= set(j2)


def test__awg_params_from_dict__roundtrip__preserves_values() -> None:
    """AwgParams.from_dict(as_dict()) восстанавливает исходные параметры без потерь."""
    # Arrange
    p = awg_params.generate(is_awg2=True, rng=random.Random(7))
    # Act
    restored = AwgParams.from_dict(p.as_dict())
    # Assert
    assert restored.as_dict() == p.as_dict()


# ---------------------------------------------------------------- ipalloc ---


def test__next_client_ip__empty_config__returns_first_address() -> None:
    """Пустой конфиг → первый клиентский адрес 10.8.1.1."""
    # Arrange / Act / Assert
    assert ipalloc.next_client_ip("") == "10.8.1.1"


def test__next_client_ip__existing_peers__increments_from_last() -> None:
    """Адрес выдаётся следующим за максимальным AllowedIPs существующих пиров."""
    # Arrange
    conf = """[Interface]
Address = 10.8.1.0/24
[Peer]
AllowedIPs = 10.8.1.1/32
[Peer]
AllowedIPs = 10.8.1.5/32
"""
    # Act / Assert
    assert ipalloc.next_client_ip(conf) == "10.8.1.6"


@pytest.mark.parametrize(("last_octet", "expected"), [("254", "10.8.2.1"), ("255", "10.8.2.1")])
def test__next_client_ip__octet_overflow__wraps_to_next_subnet(last_octet: str, expected: str) -> None:
    """При переполнении последнего октета адрес переносится в следующую /24-подсеть."""
    # Arrange / Act / Assert
    assert ipalloc.next_client_ip(f"AllowedIPs = 10.8.1.{last_octet}/32") == expected


# ------------------------------------------------------ vpn:// (qCompress) ---


def test__qcompress__output__prefixes_be_length_then_zlib_stream() -> None:
    """qcompress: первые 4 байта — BE-длина несжатых данных, остаток — валидный zlib-поток."""
    # Arrange
    raw = b"hello amnezia" * 10
    # Act
    packed = vpn_uri.qcompress(raw)
    # Assert
    assert struct.unpack(">I", packed[:4])[0] == len(raw)
    assert zlib.decompress(packed[4:]) == raw


@pytest.mark.parametrize("level", [0, 1, 6, 8, 9])
def test__qcompress__any_level__roundtrips_through_quncompress(level: int) -> None:
    """quncompress(qcompress(raw, level)) возвращает исходные данные при любом уровне сжатия."""
    # Arrange
    raw = b'{"a":1,"junk":"' + b"x" * 500 + b'"}'
    # Act / Assert
    assert vpn_uri.quncompress(vpn_uri.qcompress(raw, level)) == raw


def test__encode_vpn_url__roundtrip__decodes_back_to_config() -> None:
    """encode_vpn_url даёт vpn://-строку без паддинга, decode_vpn_url возвращает исходный конфиг."""
    # Arrange
    cfg = {"hostName": "1.2.3.4", "containers": [{"container": "amnezia-awg2"}], "описание": "тест"}
    # Act
    url = vpn_uri.encode_vpn_url(cfg)
    # Assert
    assert url.startswith("vpn://")
    assert "=" not in url  # без паддинга
    assert vpn_uri.decode_vpn_url(url) == cfg


def test__build_awg_native_config__awg2__has_expected_structure_and_roundtrips() -> None:
    """AWG2 native-конфиг: контейнер, порт, версия «2», клиентский last_config и полный vpn://-roundtrip."""
    # Arrange
    params = awg_params.generate(is_awg2=True, rng=random.Random(3))
    # Act
    cfg = vpn_uri.build_awg_native_config(
        container="amnezia-awg2",
        is_awg2=True,
        server_ip="203.0.113.7",
        server_name="Мой сервер",
        port="55424",
        params=params,
        conf_text="[Interface]\nPrivateKey = X\n",
        client_ip="10.8.1.2",
        client_priv_key="PRIV==",
        client_pub_key="PUB==",
        server_pub_key="SRVPUB==",
        psk="PSK==",
    )
    # Assert
    assert cfg["defaultContainer"] == "amnezia-awg2"
    assert cfg["hostName"] == "203.0.113.7"
    container = cfg["containers"][0]
    assert container["container"] == "amnezia-awg2"
    awg = container["awg"]
    assert awg["protocol_version"] == "2"
    assert awg["port"] == "55424"
    # last_config — компактная JSON-строка с клиентским конфигом
    client = json.loads(awg["last_config"])
    assert client["client_ip"] == "10.8.1.2"
    assert client["server_pub_key"] == "SRVPUB=="
    assert client["psk_key"] == "PSK=="
    assert client["clientId"] == "PUB=="
    assert client["allowed_ips"] == ["0.0.0.0/0", "::/0"]
    assert client["mtu"] == c.DEFAULT_MTU
    assert client["isObfuscationEnabled"] is False
    assert client["S3"] and client["S4"]  # awg2 → S3/S4 присутствуют
    # весь native-конфиг кодируется/декодируется без потерь
    assert vpn_uri.decode_vpn_url(vpn_uri.encode_vpn_url(cfg)) == cfg


def test__build_awg_native_config__legacy__omits_protocol_version_and_s3s4() -> None:
    """Legacy native-конфиг не содержит protocol_version и S3/S4 (ни в awg, ни в last_config)."""
    # Arrange
    params = awg_params.generate(is_awg2=False, rng=random.Random(4))
    # Act
    cfg = vpn_uri.build_awg_native_config(
        container="amnezia-awg",
        is_awg2=False,
        server_ip="203.0.113.8",
        server_name="legacy",
        port="55424",
        params=params,
        conf_text="[Interface]\n",
        client_ip="10.8.1.2",
        client_priv_key="p",
        client_pub_key="P",
        server_pub_key="S",
        psk="K",
    )
    # Assert
    awg = cfg["containers"][0]["awg"]
    assert "protocol_version" not in awg
    assert "S3" not in awg and "S4" not in awg
    assert "S3" not in json.loads(awg["last_config"])


# -------------------------------------------------------------- vless:// ---


def test__build_vless_url__reality_params__formats_expected_uri() -> None:
    """vless://-URL содержит reality-параметры, flow, pbk/sid/sni, метку и опускает type=tcp."""
    # Arrange / Act
    url = vpn_uri.build_vless_url(
        uuid="11111111-2222-3333-4444-555555555555",
        host="203.0.113.9",
        port="443",
        public_key="PBK",
        short_id="abcdef0123456789",
        sni="www.googletagmanager.com",
    )
    # Assert
    assert url.startswith("vless://11111111-2222-3333-4444-555555555555@203.0.113.9:443?")
    assert "security=reality" in url
    assert "flow=xtls-rprx-vision" in url
    assert "pbk=PBK" in url
    assert "sid=abcdef0123456789" in url
    assert "sni=www.googletagmanager.com" in url
    assert url.endswith("#AmneziaVPN")
    assert "type=" not in url  # tcp опускается


def test__build_vless_url__xhttp__adds_transport_and_omits_flow() -> None:
    """XHTTP: type=xhttp + path/mode присутствуют, flow (Vision) опущен, security=reality сохранён."""
    # Arrange / Act
    url = vpn_uri.build_vless_url(
        uuid="11111111-2222-3333-4444-555555555555",
        host="203.0.113.9",
        port="2087",
        public_key="PBK",
        short_id="abcdef0123456789",
        sni="www.googletagmanager.com",
        flow="",
        network="xhttp",
        path="/secretpath",
        mode="auto",
    )
    # Assert
    assert "type=xhttp" in url
    assert "path=%2Fsecretpath" in url  # слэш экранирован
    assert "mode=auto" in url
    assert "security=reality" in url
    assert "flow=" not in url  # Vision не применяется на XHTTP


def test__build_hysteria2_url__formats_expected_uri() -> None:
    """hysteria2://<pass>@host:port/?sni&obfs&obfs-password&pinSHA256#alias; двоеточия pinSHA256 не экранируются."""
    # Arrange / Act
    url = vpn_uri.build_hysteria2_url(
        password="secretpass",
        host="203.0.113.9",
        port="443",
        sni="www.bing.com",
        obfs_password="obf123",
        pin_sha256="AB:CD:EF",
        alias="My Server",
    )
    # Assert
    assert url.startswith("hysteria2://secretpass@203.0.113.9:443/?")
    assert "sni=www.bing.com" in url
    assert "obfs=salamander" in url
    assert "obfs-password=obf123" in url
    assert "pinSHA256=AB:CD:EF" in url  # hex-двоеточия сохранены (safe=':')
    assert url.endswith("#My%20Server")


# -------------------------------------------------------------- templates ---


def test__replace_vars__overlapping_names__replaces_longest_first() -> None:
    """При пересекающихся именах ($PRIMARY_DNS ⊂ $PRIMARY_SERVER_DNS) подстановка идёт длинными сначала."""
    # Arrange
    text = "a=$PRIMARY_DNS b=$PRIMARY_SERVER_DNS"
    # Act
    out = templates.replace_vars(text, {"$PRIMARY_DNS": "1.1.1.1", "$PRIMARY_SERVER_DNS": "8.8.8.8"})
    # Assert
    assert out == "a=1.1.1.1 b=8.8.8.8"


def test__awg_client_template__rendered__has_no_leftover_tokens() -> None:
    """Шаблон awg-клиента после подстановки не содержит незакрытых $-токенов и верных значений."""
    # Arrange
    spec = c.AWG
    tpl = templates.load_protocol(spec.script_folder, "template.conf")
    params = awg_params.generate(is_awg2=True, rng=random.Random(11))
    variables = {
        "$WIREGUARD_CLIENT_IP": "10.8.1.2",
        "$WIREGUARD_CLIENT_PRIVATE_KEY": "PRIV",
        "$WIREGUARD_SERVER_PUBLIC_KEY": "SRVPUB",
        "$WIREGUARD_PSK": "PSK",
        "$PRIMARY_DNS": c.CLIENT_PRIMARY_DNS,
        "$SECONDARY_DNS": c.CLIENT_SECONDARY_DNS,
        "$SERVER_IP_ADDRESS": "203.0.113.7",
        "$AWG_SERVER_PORT": spec.default_port,
        **params.script_vars(),
    }
    # Act
    out = templates.replace_vars(tpl, variables)
    # Assert
    assert "$" not in out
    assert "PrivateKey = PRIV" in out
    assert "Endpoint = 203.0.113.7:55424" in out
    assert "PersistentKeepalive = 25" in out


# --------------------------------------------------------------- openvpn ---


def test__constants_registry__openvpn__is_standalone_vendor() -> None:
    """openvpn известен реестру как отдельный вендор (не входит в amnezia-набор)."""
    # Arrange / Act
    spec = c.spec_by_id("openvpn")
    # Assert
    assert spec.vendor == "openvpn" and spec.kind == "openvpn"
    assert spec.container == "amnezia-openvpn"
    assert c.spec_by_label("OpenVPN") is spec
    assert c.clients_table_path(spec) == "/opt/amnezia/openvpn/clientsTable"
    assert "openvpn" not in c.AMNEZIA_PROTOCOLS
    assert c.VENDOR_PROTOS["openvpn"] == ("openvpn",)


def test__gen_client_cn__generated__is_random_32_char_alphanumeric() -> None:
    """CN клиента — 32 случайных буквенно-цифровых символа, каждый раз новый."""
    # Arrange / Act
    cn = keys.gen_client_cn()
    # Assert
    assert len(cn) == 32
    assert set(cn) <= set(string.ascii_letters + string.digits)
    assert cn != keys.gen_client_cn()


def test__gen_openvpn_client_request__generated__is_valid_rsa2048_csr() -> None:
    """Запрос клиента OpenVPN — PKCS#8 приватный ключ + валидный RSA-2048 CSR с нужным CN."""
    # Arrange
    cn = keys.gen_client_cn()
    # Act
    priv, csr = keys.gen_openvpn_client_request(cn)
    # Assert
    assert priv.startswith("-----BEGIN PRIVATE KEY-----")  # PKCS#8
    req = x509.load_pem_x509_csr(csr.encode())
    assert req.is_signature_valid
    assert req.public_key().key_size == 2048
    assert req.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == cn


def test__sanitize_static_key__with_comments__strips_them_and_ensures_newline() -> None:
    """_sanitize_static_key убирает #-комментарии, сохраняет тело ключа и завершает переводом строки."""
    # Arrange
    raw = "#\n# 2048 bit OpenVPN static key\n#\n-----BEGIN OpenVPN Static key V1-----\nDEAD\n-----END OpenVPN Static key V1-----"  # noqa: E501
    # Act
    out = _sanitize_static_key(raw)
    # Assert
    assert "#" not in out
    assert out.endswith("\n")
    assert "-----BEGIN OpenVPN Static key V1-----" in out and "DEAD" in out


def _ovpn_setup(transport: str = "udp") -> tuple[OpenVpnProvisioner, ClientMaterial, str, str, str]:
    """Собрать провизионер OpenVPN + клиентский материал для теста сборки .ovpn."""
    spec = c.spec_by_id("openvpn")
    material = ServerMaterial(
        ca_cert="-----BEGIN CERTIFICATE-----\nCAAA\n-----END CERTIFICATE-----",
        ta_key="#\n# key\n#\n-----BEGIN OpenVPN Static key V1-----\nBEEF\n-----END OpenVPN Static key V1-----",
        transport=transport,
    )
    prov = OpenVpnProvisioner(spec, material=material)
    cn = keys.gen_client_cn()
    priv, _ = keys.gen_openvpn_client_request(cn)
    cert = "-----BEGIN CERTIFICATE-----\nCLIENTAAA\n-----END CERTIFICATE-----"
    client = ClientMaterial(client_id=cn, client_private_key=json.dumps({"priv": priv, "cert": cert}))
    return prov, client, cn, priv, cert


def test__openvpn_build_artifact__udp__renders_complete_config_with_all_material() -> None:
    """UDP .ovpn: все плейсхолдеры подставлены, вложены ca/cert/key/tls-auth, ta.key без #-комментариев."""
    # Arrange
    prov, client, _cn, priv, cert = _ovpn_setup("udp")
    # Act
    art = prov.build_artifact(server_ip="203.0.113.7", port="1194", server_name="My Server", client=client)
    # Assert
    conf = art.conf_text
    assert "$" not in conf  # все плейсхолдеры подставлены
    assert art.filename == "My_Server-openvpn-udp.ovpn"
    assert "proto udp" in conf
    assert "remote 203.0.113.7 1194" in conf
    assert "cipher AES-256-GCM" in conf and "auth SHA512" in conf
    assert "key-direction 1" in conf
    for tag in ("<ca>", "</ca>", "<cert>", "</cert>", "<key>", "</key>", "<tls-auth>", "</tls-auth>"):
        assert tag in conf
    assert priv in conf and cert in conf and prov.material.ca_cert in conf
    assert "BEEF" in conf and "# key" not in conf  # ta.key без #-комментариев


def test__openvpn_build_artifact__tcp__uses_tcp_transport_and_filename() -> None:
    """TCP-транспорт: в конфиге proto tcp, remote с портом, а имя файла оканчивается на -openvpn-tcp.ovpn."""
    # Arrange
    prov, client, *_ = _ovpn_setup("tcp")
    # Act
    art = prov.build_artifact(server_ip="198.51.100.9", port="443", server_name="srv", client=client)
    # Assert
    assert "proto tcp" in art.conf_text
    assert art.filename.endswith("-openvpn-tcp.ovpn")
    assert "remote 198.51.100.9 443" in art.conf_text


def test__openvpn_install_vars__cover_all_script_tokens() -> None:
    """install_vars закрывает ВСЕ $OPENVPN-токены скриптов установки (иначе server.conf сломан)."""
    # Arrange
    spec = c.spec_by_id("openvpn")
    prov = OpenVpnProvisioner(spec)
    # Act
    variables = prov.install_vars("203.0.113.7", "1194", "udp")
    # Assert
    for name in ("configure_container.sh", "run_container.sh", "start.sh"):
        rendered = templates.replace_vars(templates.load_protocol(spec.script_folder, name), variables)
        leftover = [tok for tok in rendered.split() if tok.startswith("$OPENVPN")]
        assert not leftover, f"{name}: незакрытые токены {leftover}"
    conf = templates.replace_vars(templates.load_protocol(spec.script_folder, "configure_container.sh"), variables)
    assert "proto udp" in conf
    assert "port 1194" in conf
    assert "tls-auth /opt/amnezia/openvpn/ta.key 0" in conf
    assert "cipher AES-256-GCM" in conf


@pytest.mark.parametrize(
    "bad",
    ["", "a b", "a;b", "a$(x)", "../../etc", "a`b`", "a&b", "a|b", "'x'", "abc\n", "\nabc", "abc\ninjected"],
)
def test__openvpn_check_cn__injection_attempt__raises(bad: str) -> None:
    """_check_cn отвергает пустые, пробельные и «инъекционные» CN (в т.ч. с переводом строки)."""
    # Arrange / Act / Assert
    # \n-варианты: fullmatch (не ^…$) не пропускает завершающий перевод строки
    with pytest.raises(ProvisioningError):
        OpenVpnProvisioner._check_cn(bad)


def test__openvpn_check_cn__generated_cn__is_accepted() -> None:
    """Сгенерированный CN проходит проверку и возвращается как есть."""
    # Arrange
    cn = keys.gen_client_cn()
    # Act / Assert
    assert OpenVpnProvisioner._check_cn(cn) == cn


class _FakeRunSsh:
    """Фейковый ssh-клиент с .run(cmd), отдающий заранее заданный SshResult."""

    def __init__(self, result: SshResult) -> None:
        self._result = result

    async def run(self, cmd: str) -> SshResult:
        return self._result


def _openvpn_prov() -> OpenVpnProvisioner:
    return OpenVpnProvisioner(
        c.spec_by_id("openvpn"), material=ServerMaterial(ca_cert="x", ta_key="y", transport="udp")
    )


async def test__openvpn_list_client_ids__nonzero_exit__raises() -> None:
    """Ненулевой код возврата (контейнер недоступен) → ошибка, а не «нет клиентов»."""
    # Arrange
    prov = _openvpn_prov()
    ssh = _FakeRunSsh(SshResult(stdout="", stderr="err", exit_status=1))
    # Act / Assert
    with pytest.raises(ProvisioningError):
        await prov.list_client_ids(ssh)


async def test__openvpn_list_client_ids__no_server_cert__raises() -> None:
    """rc==0, но нет серверного AmneziaReq.crt → это сбой чтения (пустой ls невозможен на живом контейнере)."""
    # Arrange
    prov = _openvpn_prov()
    ssh = _FakeRunSsh(SshResult(stdout="", stderr="", exit_status=0))
    # Act / Assert
    with pytest.raises(ProvisioningError):
        await prov.list_client_ids(ssh)


async def test__openvpn_list_client_ids__valid_listing__returns_only_client_cns() -> None:
    """Нормальный ответ (серверный AmneziaReq + два клиента) → возвращаются только клиентские CN."""
    # Arrange
    prov = _openvpn_prov()
    ssh = _FakeRunSsh(SshResult(stdout="AmneziaReq.crt\nAAAA.crt\nBBBB.crt\n", stderr="", exit_status=0))
    # Act
    result = await prov.list_client_ids(ssh)
    # Assert
    assert result == {"AAAA", "BBBB"}


class _FakeReadSsh:
    """Фейковый ssh-клиент с read_container_text(container, path), отдающий заданный текст awg0.conf."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def read_container_text(self, container: str, path: str) -> str:
        return self._text


async def test__awg_list_peer_ids__empty_read__raises() -> None:
    """Пустой ответ (сбой чтения awg0.conf) → нет [Interface] → ошибка (иначе sync ложно revoke-ает)."""
    # Arrange
    prov = AwgProvisioner(c.spec_by_id("awg"))  # list_peer_ids не трогает params/material
    ssh = _FakeReadSsh("")
    # Act / Assert
    with pytest.raises(ProvisioningError):
        await prov.list_peer_ids(ssh)


async def test__awg_list_peer_ids__zero_peers__returns_empty_set() -> None:
    """Валидный конфиг с секцией [Interface] и без пиров → пустое множество (легитимно, не ошибка)."""
    # Arrange
    prov = AwgProvisioner(c.spec_by_id("awg"))
    ssh = _FakeReadSsh("[Interface]\nPrivateKey = X\nAddress = 10.8.1.0/24\nListenPort = 55424\n")
    # Act
    result = await prov.list_peer_ids(ssh)
    # Assert
    assert result == set()


async def test__awg_list_peer_ids__two_peers__returns_their_public_keys() -> None:
    """Конфиг с двумя [Peer] → множество их публичных ключей."""
    # Arrange
    prov = AwgProvisioner(c.spec_by_id("awg"))
    conf = "[Interface]\nPrivateKey = X\nAddress = 10.8.1.0/24\nListenPort = 55424\n"
    conf += "[Peer]\nPublicKey = AAA\n\n[Peer]\nPublicKey = BBB\n"
    ssh = _FakeReadSsh(conf)
    # Act
    result = await prov.list_peer_ids(ssh)
    # Assert
    assert result == {"AAA", "BBB"}


# ----------------------------------------------------------- xray xhttp ---


def test__constants_registry__xray_xhttp__is_amnezia_variant_of_xray() -> None:
    """xray_xhttp — отдельный протокол Amnezia (свой контейнер/порт/network), reuse XrayProvisioner."""
    # Arrange / Act
    spec = c.spec_by_id("xray_xhttp")
    # Assert
    assert spec.vendor == "amnezia" and spec.kind == "xray"
    assert spec.container == "amnezia-xray-xhttp"  # отдельный контейнер, не дерётся с amnezia-xray
    assert spec.default_port != c.XRAY.default_port  # разные host-порты
    assert spec.xray_network == "xhttp"
    assert c.spec_by_label("Xray XHTTP") is spec
    assert "xray_xhttp" in c.AMNEZIA_PROTOCOLS
    assert "xray_xhttp" in c.VENDOR_PROTOS["amnezia"]
    # clientsTable внутри своего контейнера — путь как у xray, но namespace отдельный
    assert c.clients_table_path(spec) == "/opt/amnezia/xray/clientsTable"


def test__xray_build_artifact__xhttp__vless_url_has_transport_and_no_flow() -> None:
    """build_artifact для xray_xhttp: vless-ссылка с type=xhttp + path из материала, без flow."""
    # Arrange
    spec = c.spec_by_id("xray_xhttp")
    material = ServerMaterial(xray_public_key="PBK", short_id="sid123", site="www.bing.com", xhttp_path="/p9")
    prov = XrayProvisioner(spec, material=material)
    # Act
    art = prov.build_artifact(
        server_ip="203.0.113.9", port="2087", server_name="srv", client=ClientMaterial(client_id="uuid-1")
    )
    # Assert
    assert "type=xhttp" in art.vless_url
    assert "path=%2Fp9" in art.vless_url
    assert "flow=" not in art.vless_url
    assert art.filename == "srv-xray_xhttp.txt"


def test__xray_build_artifact__tcp__keeps_vision_flow() -> None:
    """build_artifact для обычного xray (tcp): flow=xtls-rprx-vision присутствует, type= опущен."""
    # Arrange
    spec = c.spec_by_id("xray")
    material = ServerMaterial(xray_public_key="PBK", short_id="sid123", site="www.bing.com")
    prov = XrayProvisioner(spec, material=material)
    # Act
    art = prov.build_artifact(
        server_ip="203.0.113.9", port="443", server_name="srv", client=ClientMaterial(client_id="uuid-1")
    )
    # Assert
    assert "flow=xtls-rprx-vision" in art.vless_url
    assert "type=" not in art.vless_url


# ------------------------------------------------------------- hysteria2 ---


class _FilesSsh:
    """Фейк ssh: read по конкретному пути, upload_to_container записывает (append учитывается)."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = dict(files)
        self.uploads: list[tuple[str, str, bool]] = []  # (path, text, append)

    async def read_container_text(self, container: str, path: str) -> str:
        return self.files.get(path, "")

    async def upload_to_container(self, container: str, text: str, path: str, append: bool = False) -> None:
        self.uploads.append((path, text, append))
        self.files[path] = (self.files.get(path, "") + text) if append else text


def _hysteria_prov() -> HysteriaProvisioner:
    spec = c.spec_by_id("hysteria2")
    material = ServerMaterial(hysteria_obfs_password="OBF", hysteria_cert_sha256="AB:CD", site="www.bing.com")
    return HysteriaProvisioner(spec, material=material)


def test__constants_registry__hysteria2__is_standalone_vendor() -> None:
    """hysteria2 — отдельный вендор с одним протоколом; свой контейнер и clientsTable."""
    # Arrange / Act
    spec = c.spec_by_id("hysteria2")
    # Assert
    assert spec.vendor == "hysteria2" and spec.kind == "hysteria2"
    assert spec.container == "amnezia-hysteria2"
    assert c.spec_by_label("Hysteria2") is spec
    assert c.VENDOR_PROTOS["hysteria2"] == ("hysteria2",)
    assert "hysteria2" not in c.AMNEZIA_PROTOCOLS
    assert c.clients_table_path(spec) == "/opt/amnezia/hysteria2/clientsTable"


def test__hysteria2_build_artifact__formats_hysteria2_url_from_material() -> None:
    """build_artifact: hysteria2://<password>@ip:port с obfs/pinSHA256 из материала."""
    # Arrange
    prov = _hysteria_prov()
    client = ClientMaterial(client_id="CID", client_private_key="PASSWORD")
    # Act
    art = prov.build_artifact(server_ip="203.0.113.9", port="443", server_name="srv", client=client)
    # Assert
    assert art.vpn_url.startswith("hysteria2://PASSWORD@203.0.113.9:443/?")
    assert "obfs-password=OBF" in art.vpn_url
    assert "pinSHA256=AB:CD" in art.vpn_url
    assert art.filename == "srv-hysteria2.txt"


async def test__hysteria2_add_client__appends_token_line_and_returns_split_material() -> None:
    """add_client: в файл users дописывается «<client_id> <password>»; id и секрет разведены."""
    # Arrange
    prov = _hysteria_prov()
    spec = prov.spec
    ssh = _FilesSsh({spec.hysteria_users_path: "", c.clients_table_path(spec): "[]"})
    # Act
    cm = await prov.add_client(ssh, "203.0.113.9", "443", "dev")
    # Assert
    assert ssh.files[spec.hysteria_users_path].strip() == f"{cm.client_id} {cm.client_private_key}"
    assert cm.client_id and cm.client_private_key and cm.client_id != cm.client_private_key


async def test__hysteria2_revoke_client__removes_only_target_token_line() -> None:
    """revoke_client: из users вычищается строка ровно с этим client_id, остальные сохранены."""
    # Arrange
    prov = _hysteria_prov()
    spec = prov.spec
    ssh = _FilesSsh(
        {spec.hysteria_users_path: "AAAA passA\nBBBB passB\nCCCC passC\n", c.clients_table_path(spec): "[]"}
    )
    # Act
    await prov.revoke_client(ssh, "BBBB")
    # Assert
    assert ssh.files[spec.hysteria_users_path] == "AAAA passA\nCCCC passC\n"


async def test__hysteria2_list_client_ids__healthy_config__parses_first_column() -> None:
    """list_client_ids: при живом config.yaml (sentinel listen:) возвращает id из первого столбца users."""
    # Arrange
    prov = _hysteria_prov()
    spec = prov.spec
    ssh = _FilesSsh(
        {spec.hysteria_config_path: "listen: :443\ntls:\n", spec.hysteria_users_path: "AAAA passA\nBBBB passB\n"}
    )
    # Act
    result = await prov.list_client_ids(ssh)
    # Assert
    assert result == {"AAAA", "BBBB"}


async def test__hysteria2_list_client_ids__empty_users_healthy_config__returns_empty_set() -> None:
    """Пустой users при живом config — легитимный «ноль клиентов», не ошибка."""
    # Arrange
    prov = _hysteria_prov()
    spec = prov.spec
    ssh = _FilesSsh({spec.hysteria_config_path: "listen: :443\n", spec.hysteria_users_path: ""})
    # Act
    result = await prov.list_client_ids(ssh)
    # Assert
    assert result == set()


async def test__hysteria2_list_client_ids__unreadable_config__raises() -> None:
    """Нечитаемый config.yaml (нет sentinel listen:) → ошибка, чтобы sync не сделал ложный revoke."""
    # Arrange
    prov = _hysteria_prov()
    spec = prov.spec
    ssh = _FilesSsh({spec.hysteria_config_path: "", spec.hysteria_users_path: "AAAA passA\n"})
    # Act / Assert
    with pytest.raises(ProvisioningError):
        await prov.list_client_ids(ssh)


def test__xray_xhttp_install_vars__cover_script_tokens_and_render_xhttp() -> None:
    """install_vars закрывает install-токены скриптов xray_xhttp; server.json — network xhttp, порт открыт."""
    # Arrange
    spec = c.spec_by_id("xray_xhttp")
    prov = XrayProvisioner(spec)
    # Act
    variables = prov.install_vars("203.0.113.7", "2087", "www.bing.com")
    # Assert: install-токены (не шелл-переменные) подставлены во всех скриптах
    for name in ("configure_container.sh", "run_container.sh", "start.sh"):
        rendered = templates.replace_vars(templates.load_protocol(spec.script_folder, name), variables)
        for tok in ("$XRAY_SERVER_PORT", "$XRAY_SITE_NAME", "$CONTAINER_NAME", "$DOCKERFILE_FOLDER"):
            assert tok not in rendered, f"{name}: незакрытый токен {tok}"
    conf = templates.replace_vars(templates.load_protocol(spec.script_folder, "configure_container.sh"), variables)
    assert '"network": "xhttp"' in conf
    assert "$XRAY_XHTTP_PATH" in conf  # шелл-переменная контейнера (её install не подставляет)
    start = templates.replace_vars(templates.load_protocol(spec.script_folder, "start.sh"), variables)
    assert "--dport 2087 -j ACCEPT" in start  # нестандартный порт открыт внутри контейнера


def test__hysteria2_install_vars__cover_script_tokens_and_render_config() -> None:
    """install_vars закрывает install-токены скриптов hysteria2; config.yaml — listen/obfs/masquerade."""
    # Arrange
    spec = c.spec_by_id("hysteria2")
    prov = HysteriaProvisioner(spec)
    # Act
    variables = prov.install_vars("203.0.113.7", "443")
    # Assert
    for name in ("configure_container.sh", "run_container.sh", "start.sh"):
        rendered = templates.replace_vars(templates.load_protocol(spec.script_folder, name), variables)
        for tok in ("$HYSTERIA_PORT", "$HYSTERIA_SNI", "$CONTAINER_NAME", "$DOCKERFILE_FOLDER"):
            assert tok not in rendered, f"{name}: незакрытый токен {tok}"
    conf = templates.replace_vars(templates.load_protocol(spec.script_folder, "configure_container.sh"), variables)
    assert "listen: :443" in conf
    assert "CN=www.bing.com" in conf
    assert "type: salamander" in conf
    assert "$HYSTERIA_OBFS" in conf  # шелл-переменная контейнера (не install-токен)
    start = templates.replace_vars(templates.load_protocol(spec.script_folder, "start.sh"), variables)
    assert "-p udp --dport 443 -j ACCEPT" in start
