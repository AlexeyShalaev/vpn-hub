"""Юнит-тесты vpnhub.infra.registry: разбор ссылки на образ и протокол проверки тега (без сети)."""

from __future__ import annotations

import pytest

import vpnhub.infra.registry as reg
from vpnhub.infra.registry import ImageRef, parse_image

pytestmark = pytest.mark.unit

GHCR = ImageRef("ghcr.io", "alexeyshalaev/vpn-hub")
GHCR_CHALLENGE = 'Bearer realm="https://ghcr.io/token",service="ghcr.io",scope="repository:alexeyshalaev/vpn-hub:pull"'


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ("ghcr.io/AlexeyShalaev/vpn-hub", GHCR),
        ("nginx", ImageRef("registry-1.docker.io", "library/nginx")),
        ("bitnami/postgresql", ImageRef("registry-1.docker.io", "bitnami/postgresql")),
        ("docker.io/library/redis", ImageRef("registry-1.docker.io", "library/redis")),
        ("registry.local:5000/team/app", ImageRef("registry.local:5000", "team/app")),
        ("localhost/app", ImageRef("localhost", "app")),
        ("ghcr.io/o/app@sha256:abc", ImageRef("ghcr.io", "o/app")),
    ],
)
def test__parse_image__splits_registry_and_repository(image: str, expected: ImageRef) -> None:
    assert parse_image(image) == expected


def test__token_url__builds_anonymous_token_request_from_challenge() -> None:
    url = reg._token_url(GHCR_CHALLENGE, GHCR)

    assert url == "https://ghcr.io/token?scope=repository%3Aalexeyshalaev%2Fvpn-hub%3Apull&service=ghcr.io"


@pytest.mark.parametrize(
    "challenge",
    ['Basic realm="registry"', 'Bearer realm="http://insecure/token"', "Bearer service=x"],
    ids=["basic-auth", "plain-http-realm", "no-realm"],
)
def test__token_url__unsupported_challenge__none(challenge: str) -> None:
    assert reg._token_url(challenge, GHCR) is None


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch):
    """Подмена HEAD/токена: ответы по наличию Authorization, запись запросов."""
    state: dict = {"anon": (401, GHCR_CHALLENGE), "authed": 200, "token": "t0k", "requests": []}

    def _head(req):
        state["requests"].append(req)
        if req.get_header("Authorization"):
            return state["authed"], ""
        return state["anon"]

    monkeypatch.setattr(reg, "_head", _head)
    monkeypatch.setattr(reg, "_fetch_token", lambda url: state["token"])
    return state


@pytest.mark.parametrize(("code", "expected"), [(200, True), (404, False), (500, None), (403, None)])
def test__check__token_dance_then_verdict(fake_http, code: int, expected: bool | None) -> None:
    fake_http["authed"] = code

    assert reg._check(GHCR, "0.14.0") is expected
    head, retry = fake_http["requests"]
    assert head.get_method() == "HEAD"
    assert head.full_url == "https://ghcr.io/v2/alexeyshalaev/vpn-hub/manifests/0.14.0"
    assert retry.get_header("Authorization") == "Bearer t0k"


def test__check__open_registry__no_token_needed(fake_http) -> None:
    fake_http["anon"] = (200, "")

    assert reg._check(GHCR, "0.13.0") is True
    assert len(fake_http["requests"]) == 1


def test__check__no_anonymous_token__unknown(fake_http) -> None:
    fake_http["token"] = None

    assert reg._check(GHCR, "0.14.0") is None


async def test__tag_exists__network_error__unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(ref, tag):
        raise OSError("network is unreachable")

    monkeypatch.setattr(reg, "_check", _boom)

    assert await reg.tag_exists("ghcr.io/alexeyshalaev/vpn-hub", "0.14.0") is None


@pytest.mark.parametrize(("image", "tag"), [("", "1.0.0"), ("ghcr.io/o/app", "")])
async def test__tag_exists__empty_input__unknown(image: str, tag: str) -> None:
    assert await reg.tag_exists(image, tag) is None
