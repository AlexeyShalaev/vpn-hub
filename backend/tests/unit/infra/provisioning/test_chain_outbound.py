"""Юнит-тест чистого билдера мультихоп-outbound (без SSH/БД).

build_chain_outbound строит vless+Reality-outbound entry-контейнера, направленный на exit-сервер —
именно он заменяет `freedom` в server.json entry при постановке цепочки.
"""

from __future__ import annotations

import pytest

from vpnhub.infra.provisioning import vpn_uri

pytestmark = pytest.mark.unit


def test__build_chain_outbound__vless_reality_to_exit():
    ob = vpn_uri.build_chain_outbound(
        host="203.0.113.2",
        port="443",
        uuid="exit-uuid",
        public_key="PBK",
        short_id="deadbeef",
        sni="ex.example.com",
    )
    assert ob["tag"] == vpn_uri.CHAIN_OUTBOUND_TAG
    assert ob["protocol"] == "vless"
    vnext = ob["settings"]["vnext"][0]
    assert vnext["address"] == "203.0.113.2"
    assert vnext["port"] == 443  # int, как ждёт xray
    assert vnext["users"][0]["id"] == "exit-uuid"
    reality = ob["streamSettings"]["realitySettings"]
    assert reality["publicKey"] == "PBK"
    assert reality["shortId"] == "deadbeef"
    assert reality["serverName"] == "ex.example.com"


def test__build_chain_outbound__tcp_exit__tcp_stream_and_vision_flow():
    ob = vpn_uri.build_chain_outbound(host="h", port="443", uuid="u", public_key="P", short_id="s", sni="x")
    assert ob["streamSettings"]["network"] == "tcp"
    assert "xhttpSettings" not in ob["streamSettings"]
    assert ob["settings"]["vnext"][0]["users"][0]["flow"]  # непустой vision-flow для tcp-Reality


def test__build_chain_outbound__xhttp_exit__xhttp_stream_path_and_no_flow():
    ob = vpn_uri.build_chain_outbound(
        host="203.0.113.2",
        port="2087",
        uuid="exit-uuid",
        public_key="PBK",
        short_id="deadbeef",
        sni="ex.example.com",
        flow="",
        network="xhttp",
        path="/xh",
    )
    stream = ob["streamSettings"]
    assert stream["network"] == "xhttp"
    assert stream["xhttpSettings"] == {"path": "/xh", "mode": "auto"}
    assert stream["realitySettings"]["publicKey"] == "PBK"  # Reality остаётся и на xhttp
    assert ob["settings"]["vnext"][0]["users"][0]["flow"] == ""  # Vision на XHTTP не применяется


def test__freedom_outbound__is_direct():
    assert vpn_uri.FREEDOM_OUTBOUND == {"protocol": "freedom"}
