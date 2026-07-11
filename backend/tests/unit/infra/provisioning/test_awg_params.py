"""Юнит-тесты чистого ядра obfuscation-параметров AmneziaWG (без SSH/БД).

Покрываем: validate (диапазоны/уникальность/равные размеры пакетов/заголовки),
merge_editable (правит только редактируемые поля, сохраняет subnet/i-junk),
rewrite_interface_params (переписывает [Interface], не трогает [Peer]).
"""

from __future__ import annotations

import random

import pytest

from vpnhub.infra.provisioning import awg_params
from vpnhub.infra.provisioning.awg_params import (
    PRESETS,
    AwgParams,
    generate,
    merge_editable,
    rewrite_interface_params,
    validate,
)
from vpnhub.infra.provisioning.errors import ProvisioningError

pytestmark = pytest.mark.unit


def _valid_awg2() -> AwgParams:
    # детерминированный генератор → воспроизводимый валидный набор
    return generate(is_awg2=True, rng=random.Random(42))


def _valid_legacy() -> AwgParams:
    return generate(is_awg2=False, rng=random.Random(7))


# ---- validate ------------------------------------------------------------


def test__validate__generated_awg2__passes() -> None:
    validate(_valid_awg2(), is_awg2=True)  # не должно бросать


def test__validate__generated_legacy__passes() -> None:
    validate(_valid_legacy(), is_awg2=False)


def test__validate__presets_are_valid() -> None:
    base = _valid_awg2()
    for name in ("aggressive", "mobile"):
        validate(merge_editable(base, PRESETS[name]), is_awg2=True)


def test__validate__jmin_ge_jmax__raises() -> None:
    p = merge_editable(_valid_awg2(), {"jmin": "60", "jmax": "50"})
    with pytest.raises(ProvisioningError) as ei:
        validate(p, is_awg2=True)
    assert ei.value.code == "invalid_params"


def test__validate__duplicate_sizes__raises() -> None:
    # S1=S2 → одинаковый размер запрещён (и дубль значения)
    p = merge_editable(_valid_awg2(), {"s1": "50", "s2": "50"})
    with pytest.raises(ProvisioningError):
        validate(p, is_awg2=True)


def test__validate__equal_packet_sizes_s1_s2__raises() -> None:
    # S1+148 == S2+92  =>  S2 == S1+56.  S1=20 -> S2=76 (значения различны, но размеры равны)
    p = merge_editable(_valid_awg2(), {"s1": "20", "s2": "76"})
    with pytest.raises(ProvisioningError):
        validate(p, is_awg2=True)


def test__validate__bad_header_too_small__raises() -> None:
    p = merge_editable(_valid_legacy(), {"h1": "3"})  # <=4 запрещён
    with pytest.raises(ProvisioningError):
        validate(p, is_awg2=False)


def test__validate__non_integer__raises() -> None:
    p = merge_editable(_valid_awg2(), {"jc": "abc"})
    with pytest.raises(ProvisioningError):
        validate(p, is_awg2=True)


def test__validate__awg2_header_range_ok() -> None:
    p = merge_editable(_valid_awg2(), {"h1": "100-200", "h2": "300-400", "h3": "500-600", "h4": "700-800"})
    validate(p, is_awg2=True)


def test__validate__awg2_header_descending_range__raises() -> None:
    p = merge_editable(_valid_awg2(), {"h1": "200-100"})
    with pytest.raises(ProvisioningError):
        validate(p, is_awg2=True)


# ---- merge_editable ------------------------------------------------------


def test__merge_editable__only_editable_fields_change() -> None:
    cur = _valid_awg2()
    merged = merge_editable(cur, {"jc": "9", "subnet_address": "10.9.9.1", "i1": "HACKED"})
    assert merged.jc == "9"
    # subnet/i1 НЕ редактируемые — берутся из текущего, патч игнорируется
    assert merged.subnet_address == cur.subnet_address
    assert merged.i1 == cur.i1
    # прочие редактируемые не тронуты
    assert merged.s1 == cur.s1


def test__merge_editable__preserves_protocol_version() -> None:
    cur = _valid_awg2()
    merged = merge_editable(cur, {"jmin": "12"})
    assert merged.protocol_version == "2"


# ---- rewrite_interface_params -------------------------------------------


SAMPLE_CONF = """[Interface]
Address = 10.8.1.1/24
ListenPort = 51820
PrivateKey = SERVER_PRIV
Jc = 4
Jmin = 10
Jmax = 50
S1 = 30
S2 = 40
S3 = 5
S4 = 3
H1 = 1000000
H2 = 2000000
H3 = 3000000
H4 = 4000000
# I1 = <junk>

[Peer]
PublicKey = PEER_PUBKEY_AAA
PresharedKey = PSK_AAA
AllowedIPs = 10.8.1.2/32

[Peer]
PublicKey = PEER_PUBKEY_BBB
PresharedKey = PSK_BBB
AllowedIPs = 10.8.1.3/32
"""


def test__rewrite_interface_params__replaces_interface_and_keeps_peers() -> None:
    new = merge_editable(
        AwgParams.from_server_conf(SAMPLE_CONF, is_awg2=True),
        {"jc": "6", "s1": "120", "h1": "9999999"},
    )
    out = rewrite_interface_params(SAMPLE_CONF, new, is_awg2=True)

    assert "Jc = 6" in out
    assert "S1 = 120" in out
    assert "H1 = 9999999" in out
    # старые значения obfuscation ушли
    assert "Jc = 4" not in out
    assert "S1 = 30" not in out
    # пиры не тронуты
    assert "PEER_PUBKEY_AAA" in out
    assert "PEER_PUBKEY_BBB" in out
    assert out.count("[Peer]") == 2


def test__rewrite_interface_params__does_not_touch_peer_sections() -> None:
    # даже если бы у пира была строка с именем как у ключа — правим только внутри [Interface]
    conf = "[Interface]\nJc = 4\n\n[Peer]\nS1 = 999\nPublicKey = KEEP\n"
    new = merge_editable(AwgParams.from_server_conf(conf, is_awg2=False), {"jc": "6"})
    out = rewrite_interface_params(conf, new, is_awg2=False)
    assert "Jc = 6" in out
    # строка S1 внутри [Peer] не заменена (она не наша, но проверяем что раздел нетронут)
    assert "S1 = 999" in out
    assert "PublicKey = KEEP" in out


def test__rewrite_interface_params__adds_missing_key() -> None:
    conf = "[Interface]\nAddress = 10.8.1.1/24\nJc = 4\n"
    new = AwgParams.from_server_conf(conf, is_awg2=False)
    new = awg_params.merge_editable(new, {"jc": "6", "jmin": "10", "jmax": "50", "s1": "20", "s2": "35"})
    # заполнить заголовки, чтобы объект был целостным (не требуется для rewrite, но реалистично)
    out = rewrite_interface_params(conf, new, is_awg2=False)
    assert "Jc = 6" in out
    # Jmin/S1 отсутствовали в конфиге — добавлены
    assert "Jmin = 10" in out
    assert "S1 = 20" in out
