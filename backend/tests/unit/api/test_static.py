"""Юнит-тесты SPA-статики: containment против path traversal + корректная отдача/фолбэк.

Гоняем ASGI-приложение напрямую (собственный scope), без TestClient/httpx: %2e%2e/… приходит
в scope["path"] уже как "../…" (ASGI-сервер декодирует ПОСЛЕ нормализации) — ровно тот вектор,
что раньше отдавал файлы вне STATIC_DIR.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI

import vpnhub.api.static as static

pytestmark = pytest.mark.unit


def _build_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    static_dir = tmp_path / "static"
    (static_dir / "sub").mkdir(parents=True)
    (static_dir / "index.html").write_text("INDEX")
    (static_dir / "app.js").write_text("APPJS")
    (static_dir / "sub" / "page.txt").write_text("SUBPAGE")
    (tmp_path / "secret.txt").write_text("SECRET-OUTSIDE")  # рядом с каталогом, вне него
    monkeypatch.setattr(static, "STATIC_DIR", static_dir)
    monkeypatch.setattr(static, "_STATIC_ROOT", static_dir.resolve())
    app = FastAPI()
    static.add_static(app)
    return app


async def _get(app: FastAPI, path: str) -> tuple[int, bytes]:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "headers": [],
        "query_string": b"",
        "client": ("1.2.3.4", 0),
        "server": ("test", 80),
        "scheme": "http",
        "http_version": "1.1",
        "app": app,
    }
    chunks: list[bytes] = []
    status = {"code": 0}

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: dict) -> None:
        if msg["type"] == "http.response.start":
            status["code"] = msg["status"]
        elif msg["type"] == "http.response.body":
            chunks.append(msg.get("body", b""))

    await app(scope, receive, send)
    return status["code"], b"".join(chunks)


@pytest.mark.parametrize(
    "path",
    [
        "/../secret.txt",
        "/sub/../../secret.txt",
        "/../../../../../../etc/passwd",
        "/..%2fsecret.txt",  # если сервер не декодирует — просто не найдётся
    ],
)
async def test__spa__traversal__does_not_leak_outside_static(tmp_path, monkeypatch, path) -> None:
    app = _build_app(tmp_path, monkeypatch)
    _, body = await _get(app, path)
    assert b"SECRET-OUTSIDE" not in body
    assert b"/etc/passwd" not in body or b"root:" not in body


async def test__spa__legit_files__served(tmp_path, monkeypatch) -> None:
    app = _build_app(tmp_path, monkeypatch)
    assert (await _get(app, "/app.js"))[1] == b"APPJS"
    assert (await _get(app, "/sub/page.txt"))[1] == b"SUBPAGE"


async def test__spa__unknown_route__falls_back_to_index(tmp_path, monkeypatch) -> None:
    app = _build_app(tmp_path, monkeypatch)
    code, body = await _get(app, "/some/client/route")
    assert code == 200
    assert body == b"INDEX"
