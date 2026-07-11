"""Unit-тесты чистой логики infra/metrics: нормализация пути и обёртка джобы."""

from __future__ import annotations

import pytest

from vpnhub.infra import metrics as mx

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/v1/servers/abc123def456/traffic", "/api/v1/servers/{id}/traffic"),
        ("/api/v1/servers", "/api/v1/servers"),
        ("/api/v1/admin/users/42", "/api/v1/admin/users/{id}"),
        ("/healthz", "/healthz"),
        ("/", "/"),
    ],
)
def test__path_group__normalizes_ids(path: str, expected: str) -> None:
    assert mx.path_group(path) == expected


async def test__instrument_job__records_success_and_reraises_error() -> None:
    calls: list[str] = []

    async def ok() -> int:
        calls.append("ok")
        return 7

    async def boom() -> int:
        raise RuntimeError("kaboom")

    wrapped_ok = mx.instrument_job("job-ok", ok)
    assert await wrapped_ok() == 7
    assert calls == ["ok"]

    wrapped_boom = mx.instrument_job("job-boom", boom)
    with pytest.raises(RuntimeError, match="kaboom"):
        await wrapped_boom()
    # ошибка не проглочена, но метрика падения снялась (счётчик > 0)
    err = _counter_value(mx.scheduler_tick_errors_total, "vpnhub_scheduler_tick_errors_total", job="job-boom")
    assert err >= 1


def _counter_value(counter: object, name: str, **labels: str) -> float:
    for metric in counter.collect():  # type: ignore[attr-defined]
        for s in metric.samples:
            if s.name == name and all(s.labels.get(k) == v for k, v in labels.items()):
                return float(s.value)
    return 0.0
