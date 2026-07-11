#!/usr/bin/env python3
"""Сгенерировать корневой CHANGELOG.md (англ., для GitHub/OSS) из курируемого источника.

Единственный источник правды — `backend/src/vpnhub/infra/changelog.py::RELEASES`
(двуязычный). CHANGELOG.md — производный: не редактируйте его руками, правьте RELEASES
и запускайте `make changelog` (или `python scripts/gen_changelog.py`).

release-please продолжает бампить версию и ставить тег; заметки ведём в RELEASES.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

from vpnhub.infra.changelog import RELEASES  # noqa: E402 — путь к пакету добавлен выше

REPO = "https://github.com/AlexeyShalaev/vpn-hub"


def _header(version: str, date: str, prev: str | None) -> str:
    if prev:
        return f"## [{version}]({REPO}/compare/v{prev}...v{version}) - {date}"
    return f"## {version} - {date}"


def build() -> str:
    lines = [
        "# Changelog",
        "",
        "All notable changes to this project are documented here.",
        "",
        "Generated from `backend/src/vpnhub/infra/changelog.py` via `make changelog` — do not edit by hand.",
        "Release notes are hand-written and bilingual (RU/EN); the panel shows them in the selected language.",
        "",
    ]
    versions = [r["v"] for r in RELEASES]
    for i, r in enumerate(RELEASES):
        prev = versions[i + 1] if i + 1 < len(versions) else None
        lines.append(_header(r["v"], r["date"], prev))
        lines.append("")
        lines.extend(f"- {note['en']}" for note in r["notes"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    out = ROOT / "CHANGELOG.md"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({len(RELEASES)} releases)")  # noqa: T201 — CLI-скрипт


if __name__ == "__main__":
    main()
