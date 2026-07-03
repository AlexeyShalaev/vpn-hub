"""Общие фикстуры для всего набора тестов.

Здесь — только то, что переиспользуется несколькими модулями (по гайду):
`settings` — детерминированный конфиг с фиксированным secret_key, чтобы не тянуть env/.env.
Тяжёлые фикстуры БД живут в tests/integration/conftest.py.
"""

from __future__ import annotations

import pytest

from vpnhub.api.config import Settings

# фиксированный ключ шифрования — иначе тесты зависели бы от окружения/.env
TEST_SECRET_KEY = "test-secret-key-fixed-for-tests-0123456789"


@pytest.fixture
def settings() -> Settings:
    """Настройки с явными значениями (без чтения env), общие для сервисов."""
    s = Settings(
        _env_file=None,
        master_key=None,
        admin_phone=None,
        session_ttl_days=30,
        monitor_timeout=0.05,
        monitor_concurrency=4,
    )
    # secret_key не читается из env (только из мастер-ключа при старте) — в тестах фиксируем
    # детерминированный data-ключ присваиванием, чтобы шифрование было воспроизводимым.
    s.secret_key = TEST_SECRET_KEY
    return s
