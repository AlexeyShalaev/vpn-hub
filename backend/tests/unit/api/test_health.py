"""Юнит-тесты операционных эндпоинтов: авторизация /metrics и статус /readyz."""

from __future__ import annotations

import pytest
from fastapi.responses import Response
from starlette.requests import Request

from vpnhub.api.config import Settings
from vpnhub.api.routers.health import metrics, metrics_authorized, readyz

pytestmark = pytest.mark.unit


# ---- metrics_authorized (чистая логика) ----------------------------------


def test__metrics_authorized__no_token_configured__open():
    """Токен не задан → эндпоинт открыт (совместимость)."""
    assert metrics_authorized("", None, None) is True


def test__metrics_authorized__bearer_matches__allowed():
    """Совпадение Bearer-токена → доступ."""
    assert metrics_authorized("s3cret", "Bearer s3cret", None) is True


def test__metrics_authorized__query_token_matches__allowed():
    """Совпадение ?token= → доступ."""
    assert metrics_authorized("s3cret", None, "s3cret") is True


@pytest.mark.parametrize(
    ("header", "qs"),
    [("Bearer nope", None), (None, "nope"), (None, None), ("s3cret", None)],  # последний — без 'Bearer '
)
def test__metrics_authorized__wrong_or_missing_token__denied(header, qs):
    """Неверный/отсутствующий токен при заданном конфиге → отказ."""
    assert metrics_authorized("s3cret", header, qs) is False


# ---- readyz (фейковый uow) -----------------------------------------------


class _FakeSession:
    async def execute(self, _q):
        return None


class _FakeTx:
    def __init__(self):
        self.session = _FakeSession()


class _AsyncCM:
    def __init__(self, tx):
        self._tx = tx

    async def __aenter__(self):
        return self._tx

    async def __aexit__(self, *_a):
        return False


class _OkUow:
    def query(self):
        return _AsyncCM(_FakeTx())


class _FailUow:
    def query(self):
        raise RuntimeError("db down")


async def test__readyz__db_ok__ready_200():
    """БД отвечает → {'status': 'ready'} и статус остаётся 200."""
    resp = Response()
    body = await readyz(resp, _OkUow())
    assert body == {"status": "ready"}
    assert resp.status_code == 200


async def test__readyz__db_down__not_ready_503():
    """БД недоступна → 503, чтобы k8s вывел под из Service."""
    resp = Response()
    body = await readyz(resp, _FailUow())
    assert body == {"status": "not-ready"}
    assert resp.status_code == 503


# ---- /metrics endpoint (тонкая обёртка над helper) -----------------------


def _req(headers=None, qs=""):
    hdrs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/metrics", "headers": hdrs, "query_string": qs.encode()})


async def test__metrics_endpoint__token_required_but_missing__403():
    """VPNHUB_METRICS_TOKEN задан, токена в запросе нет → 403."""
    settings = Settings(_env_file=None, metrics_token="tok")
    resp = await metrics(_req(), settings)
    assert resp.status_code == 403


async def test__metrics_endpoint__no_token_configured__200():
    """Токен не задан → метрики отдаются (200)."""
    settings = Settings(_env_file=None, metrics_token="")
    resp = await metrics(_req(), settings)
    assert resp.status_code == 200
