"""Каталог тарифных планов провайдеров."""

from __future__ import annotations

import pytest

from vpnhub.infra.provider_plans import TIB, plan_bandwidth_bytes, plans_for

pytestmark = pytest.mark.unit


def test__plans_for__firstbyte_has_plans() -> None:
    plans = plans_for("firstbyte")
    assert len(plans) > 0
    p = plans[0]
    assert {
        "id",
        "name",
        "region",
        "cpu",
        "ramGb",
        "diskGb",
        "portMbps",
        "trafficTb",
        "price",
        "currency",
        "period",
    } <= set(p)
    assert p["currency"] == "RUB" and p["period"] == "month"


def test__plans_for__case_insensitive_and_unknown_empty() -> None:
    assert plans_for("FirstByte") == plans_for("firstbyte")
    assert plans_for("nonexistent") == []
    assert plans_for("") == []


def test__plan_bandwidth_bytes() -> None:
    assert plan_bandwidth_bytes({"trafficTb": 5}) == 5 * TIB
    assert plan_bandwidth_bytes({"trafficTb": None}) is None  # безлимит
    assert plan_bandwidth_bytes({}) is None
