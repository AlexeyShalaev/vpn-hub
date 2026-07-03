"""Отдача собранной React-статики тем же FastAPI + SPA-fallback."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_STATIC_ROOT = STATIC_DIR.resolve()  # канонический корень для containment-проверки (anti-traversal)


def add_static(app: FastAPI) -> None:
    index = STATIC_DIR / "index.html"
    if not index.exists():

        @app.get("/", include_in_schema=False)
        async def _placeholder() -> HTMLResponse:
            return HTMLResponse("<h1>VPN Hub</h1><p>Фронтенд ещё не собран. API доступен на <code>/api/v1</code>.</p>")

        return

    assets = STATIC_DIR / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path:
            # Защита от path traversal: %2e%2e/… декодируется в "../" уже ПОСЛЕ нормализации
            # ASGI-сервера, поэтому проверяем, что итоговый путь не вышел за пределы STATIC_DIR.
            candidate = (STATIC_DIR / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(_STATIC_ROOT):
                return FileResponse(candidate)
        return FileResponse(index)
