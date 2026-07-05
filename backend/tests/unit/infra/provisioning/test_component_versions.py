"""Юнит-тесты детекта устаревших версий серверных компонентов (component_versions).

Проверяем парсинг вывода `<bin> version` (xray/hysteria2), чистую функцию update_available
(эталон строго новее → True; неизвестная/актуальная → False) и совпадение эталонов-констант
с ARG-версиями в bundled-Dockerfile'ах (иначе «доступно обновление» врало бы).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vpnhub.infra.provisioning import component_versions as cv

pytestmark = pytest.mark.unit

_SCRIPTS = Path(cv.__file__).resolve().parent / "scripts"


def test__parse_component_version__xray_real_output() -> None:
    raw = "Xray 25.8.3 (Xray, Penetrates Everything.) Custom (go1.22)\nA unified platform..."
    assert cv.parse_component_version("xray", raw) == "25.8.3"


def test__parse_component_version__hysteria_app_prefixed() -> None:
    # apernet/hysteria печатает 'app/v2.6.2' — берём часть после '/'
    raw = "hysteria version\nVersion:\tapp/v2.6.2\nBuildDate:\t2024-..."
    assert cv.parse_component_version("hysteria2", raw) == "v2.6.2"


def test__parse_component_version__garbage_returns_none() -> None:
    assert cv.parse_component_version("xray", "command not found") is None
    assert cv.parse_component_version("xray", "") is None


def test__update_available__older_running_true() -> None:
    assert cv.update_available("xray", "25.8.1") is True
    assert cv.update_available("hysteria2", "v2.6.1") is True


def test__update_available__equal_or_newer_false() -> None:
    assert cv.update_available("xray", "25.8.3") is False  # ровно эталон
    assert cv.update_available("xray", "25.9.0") is False  # новее эталона (не откатываем)


def test__update_available__unknown_or_unsupported_false() -> None:
    assert cv.update_available("xray", None) is False  # версия не прочитана
    assert cv.update_available("awg", "1.0") is False  # детект не поддержан для протокола


def test__latest_version__unsupported_is_none() -> None:
    assert cv.latest_version("openvpn") is None
    assert cv.latest_version("xray") == "v25.8.3"


@pytest.mark.parametrize(
    ("proto_id", "dockerfile_arg"),
    [("xray", "XRAY_RELEASE"), ("xray_xhttp", "XRAY_RELEASE"), ("hysteria2", "HYSTERIA_VERSION")],
)
def test__latest_constant_matches_dockerfile_arg(proto_id: str, dockerfile_arg: str) -> None:
    # эталон-константа обязана совпадать с версией, которую соберёт bundled-Dockerfile
    folder = {"xray": "xray", "xray_xhttp": "xray_xhttp", "hysteria2": "hysteria2"}[proto_id]
    text = (_SCRIPTS / folder / "Dockerfile").read_text()
    m = re.search(rf'ARG {dockerfile_arg}="([^"]+)"', text)
    assert m is not None, f"ARG {dockerfile_arg} не найден в {folder}/Dockerfile"
    built = m.group(1).rsplit("/", 1)[-1]  # 'app/v2.6.2' → 'v2.6.2'
    assert cv.latest_version(proto_id) == built
