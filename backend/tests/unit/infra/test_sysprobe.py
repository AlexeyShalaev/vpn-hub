"""Зонды системы для админ-дашборда: детект деплоя, размеры рабочих папок и тома."""

from __future__ import annotations

import pytest

from vpnhub.infra import sysprobe

pytestmark = pytest.mark.unit


def test__detect_deployment__has_expected_shape() -> None:
    # Act
    dep = sysprobe.detect_deployment()
    # Assert
    assert dep["method"] in {"host", "docker", "kubernetes"}
    for key in ("methodLabel", "container", "hostname", "pid", "python", "platform", "cpuCount", "cwd", "tz"):
        assert key in dep
    assert isinstance(dep["pid"], int)


def test__detect_deployment__explicit_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange / Act / Assert — явный VPNHUB_DEPLOY перебивает авто-детект, k8s нормализуется
    monkeypatch.setenv("VPNHUB_DEPLOY", "compose")
    dep = sysprobe.detect_deployment()
    assert dep["method"] == "compose"
    assert dep["methodLabel"] == "Docker Compose"
    monkeypatch.setenv("VPNHUB_DEPLOY", "k8s")
    assert sysprobe.detect_deployment()["method"] == "kubernetes"


def test__dir_usage__sums_file_sizes_recursively(tmp_path) -> None:
    # Arrange
    (tmp_path / "a.txt").write_bytes(b"x" * 100)
    (tmp_path / "b.txt").write_bytes(b"y" * 50)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.txt").write_bytes(b"z" * 25)
    # Act
    usage = sysprobe.dir_usage("Test", str(tmp_path), kind="data")
    # Assert
    assert usage["exists"] is True
    assert usage["files"] == 3
    assert usage["sizeBytes"] == 175
    assert usage["writable"] is True


def test__dir_usage__missing_path_is_zero(tmp_path) -> None:
    # Act
    usage = sysprobe.dir_usage("Gone", str(tmp_path / "nope"), kind="data")
    # Assert
    assert usage["exists"] is False
    assert usage["sizeBytes"] == 0
    assert usage["files"] == 0


def test__volume_usage__reports_totals_and_dedups_by_mount(tmp_path) -> None:
    # Act — оба пути на одном томе (второй не существует → пробим по родителю)
    vols = sysprobe.volume_usage([str(tmp_path), str(tmp_path / "sub")])
    # Assert
    assert len(vols) == 1  # дедуп по device id
    v = vols[0]
    assert v["totalBytes"] > 0
    assert v["freeBytes"] >= 0
    assert v["usedBytes"] <= v["totalBytes"]
