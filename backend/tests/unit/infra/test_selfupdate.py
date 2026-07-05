"""Юнит-тесты для vpnhub.infra.selfupdate: выбор драйвера, k8s-запрос, команды, статус."""

from __future__ import annotations

import asyncio
import json

import pytest

import vpnhub.infra.selfupdate as su
from vpnhub.api.config import Settings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_status() -> None:
    """Каждый тест стартует с чистым слотом применения (статус — модульное состояние)."""
    su._status.clear()
    su._status.update({"state": "idle"})


def _settings(**over: object) -> Settings:
    base: dict = {
        "_env_file": None,
        "update_command": "",
        "update_webhook_url": "",
        "update_k8s": False,
    }
    base.update(over)
    return Settings(**base)


# --- detect_mode ------------------------------------------------------------


def test__detect_mode__command_wins_over_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    s = _settings(update_command="echo hi", update_webhook_url="http://wt/v1/update", update_k8s=True)
    assert su.detect_mode(s) == "command"


def test__detect_mode__webhook_when_no_command() -> None:
    s = _settings(update_webhook_url="http://watchtower:8080/v1/update")
    assert su.detect_mode(s) == "webhook"


def test__detect_mode__k8s_requires_incluster_env_and_token(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    token = tmp_path / "token"
    token.write_text("tok")
    monkeypatch.setattr(su, "K8S_TOKEN_FILE", token)
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    assert su.detect_mode(_settings(update_k8s=True)) == "k8s"


def test__detect_mode__k8s_disabled_without_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    assert su.detect_mode(_settings(update_k8s=True)) == "manual"


def test__detect_mode__manual_when_nothing_configured() -> None:
    assert su.detect_mode(_settings()) == "manual"


# --- _k8s_request (чистая функция, без кластера) ----------------------------


def test__k8s_request__patches_own_deployment_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.96.0.1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT", "443")
    s = _settings(image="ghcr.io/alexeyshalaev/vpn-hub")
    req = su._k8s_request(s, "0.5.0", namespace="vpnhub", token="secret-token")

    assert req.method == "PATCH"
    assert req.full_url == (
        "https://10.96.0.1:443/apis/apps/v1/namespaces/vpnhub/deployments/vpnhub?fieldManager=vpnhub-selfupdate"
    )
    assert req.headers["Authorization"] == "Bearer secret-token"
    assert req.headers["Content-type"] == "application/strategic-merge-patch+json"
    body = json.loads(req.data)
    container = body["spec"]["template"]["spec"]["containers"][0]
    assert container == {"name": "vpnhub", "image": "ghcr.io/alexeyshalaev/vpn-hub:0.5.0"}


def test__k8s_request__honours_custom_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.96.0.1")
    s = _settings(update_k8s_deployment="panel", update_k8s_container="app", image="reg/img")
    req = su._k8s_request(s, "1.0.0", namespace="ns", token="t")
    assert "/deployments/panel?" in req.full_url
    body = json.loads(req.data)
    assert body["spec"]["template"]["spec"]["containers"][0]["name"] == "app"


# --- _apply_command ---------------------------------------------------------


async def test__apply_command__substitutes_version_and_reports_success() -> None:
    ok, out = await su._apply_command("echo target={version}", "0.9.1")
    assert ok is True
    assert "target=0.9.1" in out


async def test__apply_command__nonzero_exit_is_failure() -> None:
    ok, out = await su._apply_command("echo boom; exit 3", "1.0.0")
    assert ok is False
    assert "кодом 3" in out
    assert "boom" in out


# --- _apply_webhook: валидация схемы (без сети) ------------------------------


async def test__apply_webhook__rejects_non_http_url() -> None:
    ok, out = await su._apply_webhook("ftp://watchtower/v1/update", token="")
    assert ok is False
    assert "http" in out.lower()


# --- start / status ---------------------------------------------------------


async def test__start__accepts_and_sets_running_status(monkeypatch: pytest.MonkeyPatch) -> None:
    # драйвер command с быстрой успешной командой; ждём завершения фоновой задачи
    s = _settings(update_command="true")
    accepted = su.start(s, "0.5.0")
    assert accepted["accepted"] is True
    assert accepted["mode"] == "command"
    assert accepted["target"] == "0.5.0"
    assert su.status()["state"] == "running"
    await asyncio.sleep(0.05)  # дать _run отработать
    assert su.status()["state"] == "triggered"


async def test__start__rejects_second_run_while_running() -> None:
    # искусственно помечаем слот занятым — второй запуск не должен стартовать
    su._status.update({"state": "running", "mode": "command"})
    res = su.start(_settings(update_command="true"), "0.5.0")
    assert res["ok"] is False
    assert res["state"] == "running"
