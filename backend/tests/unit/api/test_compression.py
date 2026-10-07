"""Gzip только для публичных справочников (/api/providers…), остальной API — без сжатия."""

from __future__ import annotations

import gzip
import json

import pytest
from fastapi import FastAPI

from vpnhub.api.compression import CatalogGZipMiddleware

pytestmark = pytest.mark.unit

_BIG = [{"id": f"p{i}", "blurb": "Облачные VPS в Москве и Амстердаме"} for i in range(200)]


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/providers")
    async def providers() -> list[dict]:
        return _BIG

    @app.get("/api/me")
    async def me() -> list[dict]:
        return _BIG

    app.add_middleware(CatalogGZipMiddleware)
    return app


async def _get(app: FastAPI, path: str) -> tuple[dict[str, str], bytes]:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "headers": [(b"accept-encoding", b"gzip")],
        "query_string": b"",
        "client": ("1.2.3.4", 0),
        "server": ("test", 80),
        "scheme": "http",
        "http_version": "1.1",
        "app": app,
    }
    headers: dict[str, str] = {}
    chunks: list[bytes] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: dict) -> None:
        if msg["type"] == "http.response.start":
            headers.update({k.decode(): v.decode() for k, v in msg["headers"]})
        elif msg["type"] == "http.response.body":
            chunks.append(msg.get("body", b""))

    await app(scope, receive, send)
    return headers, b"".join(chunks)


async def test__catalog__is_gzipped() -> None:
    headers, body = await _get(_app(), "/api/providers")

    assert headers.get("content-encoding") == "gzip"
    assert json.loads(gzip.decompress(body)) == _BIG


async def test__other_api__is_not_compressed() -> None:
    headers, body = await _get(_app(), "/api/me")

    assert "content-encoding" not in headers
    assert json.loads(body) == _BIG
