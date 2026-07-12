"""Юнит-тесты маппинга маркеров вывода install_docker.sh в коды ошибок provisioning.

Скрипт установки печатает диагностические маркеры (напр. «Docker package not installed»),
а `_install_docker` превращает их в конкретный ProvisioningError.code — от этого зависит,
какую подсказку-ремедиацию увидит пользователь.
"""

from __future__ import annotations

import pytest

from vpnhub.infra.provisioning import errors, script_runner
from vpnhub.infra.provisioning.ssh import SshResult

pytestmark = pytest.mark.unit


class _FakeSsh:
    """Мини-заглушка SshClient: возвращает заранее заданный вывод install_docker.sh."""

    def __init__(self, output: str) -> None:
        self._out = output

    async def run_script(self, script: str) -> SshResult:
        assert script.strip()  # реальный скрипт подгрузился
        return SshResult(stdout=self._out, stderr="", exit_status=0)


@pytest.mark.parametrize(
    ("marker", "code"),
    [
        ("Docker package not installed", "docker_install_failed"),
        ("Container runtime service not running", "docker_service_not_running"),
        ("Container runtime is not supported", "docker_runtime_not_supported"),
    ],
)
async def test__install_docker__maps_marker_to_error(marker: str, code: str) -> None:
    ssh = _FakeSsh(f"Dist: debian ...\n{marker}\n")
    with pytest.raises(errors.ProvisioningError) as ei:
        await script_runner._install_docker(ssh)  # type: ignore[arg-type]
    assert ei.value.code == code


async def test__install_docker__install_failed_takes_priority_over_service() -> None:
    # без установленного пакета скрипт печатает ОБА маркера — код должен быть об установке, не о службе
    ssh = _FakeSsh("Docker package not installed\nContainer runtime service not running\n")
    with pytest.raises(errors.ProvisioningError) as ei:
        await script_runner._install_docker(ssh)  # type: ignore[arg-type]
    assert ei.value.code == "docker_install_failed"


async def test__install_docker__clean_output__no_error() -> None:
    ssh = _FakeSsh("Dist: debian\nDocker pkg selected: docker-ce docker-ce-cli\nDocker version 27.0\nLinux 6.8\n")
    await script_runner._install_docker(ssh)  # type: ignore[arg-type]  # не бросает
