"""Загрузка забандленных server_scripts Amnezia и подстановка переменных.

Скрипты лежат как есть в `scripts/` (скопированы 1:1 из amnezia-client) — мы их НЕ
переписываем, только рендерим $-плейсхолдеры (порт SshSession::replaceVars).
"""

from __future__ import annotations

from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent / "scripts"


def load_shared(name: str) -> str:
    """Общий скрипт (install_docker.sh, prepare_host.sh, ...). \\r убираются."""
    return (_SCRIPTS_DIR / name).read_text(encoding="utf-8").replace("\r", "")


def load_protocol(script_folder: str, name: str) -> str:
    """Скрипт/шаблон протокола (server_scripts/<folder>/<name>)."""
    return (_SCRIPTS_DIR / script_folder / name).read_text(encoding="utf-8").replace("\r", "")


def replace_vars(text: str, variables: dict[str, str]) -> str:
    """Плоская подстановка $TOKEN → value.

    В отличие от Amnezia (list-order replace) заменяем от самого длинного ключа к короткому,
    чтобы префиксные токены (напр. $PRIMARY_DNS ⊂ $PRIMARY_SERVER_DNS) не портили друг друга.
    """
    for key in sorted(variables, key=len, reverse=True):
        text = text.replace(key, str(variables[key]))
    return text
