"""Декодер SSR-payload Nuxt 3 (`<script id="__NUXT_DATA__">`) для провайдеров на Nuxt.

Nuxt сериализует состояние страницы библиотекой devalue: плоский JSON-массив, где объекты и массивы
хранят не значения, а ИНДЕКСЫ других элементов (так переиспользуются общие ссылки), а особые типы
закодированы массивом с тегом первым элементом (`["Reactive", 5]`, `["Set", ...]`, `["Date", "..."]`).
Тарифы Timeweb, Beget и других Nuxt-сайтов лежат в этом состоянии целиком — без JS-рендера страницы.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from typing import Any

_PAYLOAD_RE = re.compile(r"<script\b[^>]*\bid=[\"']__NUXT_DATA__[\"'][^>]*>(.*?)</script>", re.I | re.S)

# обёртки реактивности Nuxt: значение — по индексу во втором элементе
_WRAPPERS = frozenset({"Reactive", "ShallowReactive", "Ref", "ShallowRef", "NuxtError"})
# специальные числа devalue (отрицательные «индексы»): undefined, дырка массива, NaN, ±Infinity, -0
_SPECIAL: dict[int, Any] = {
    -1: None,
    -2: None,
    -3: float("nan"),
    -4: float("inf"),
    -5: float("-inf"),
    -6: -0.0,
}


def _unflatten(values: list[Any]) -> Any:
    memo: dict[int, Any] = {}

    def hydrate(index: int) -> Any:
        if index < 0:
            return _SPECIAL.get(index)
        if index in memo:
            return memo[index]
        value = values[index]
        if isinstance(value, list):
            if value and isinstance(value[0], str):
                tag = value[0]
                if tag in _WRAPPERS:
                    memo[index] = hydrate(value[1])
                elif tag == "Set":
                    memo[index] = [hydrate(i) for i in value[1:]]
                elif tag in {"Map", "null"}:
                    obj: dict[str, Any] = {}
                    memo[index] = obj
                    for k in range(1, len(value) - 1, 2):
                        key = hydrate(value[k]) if tag == "Map" else value[k]
                        obj[str(key)] = hydrate(value[k + 1])
                elif tag in {"Date", "BigInt", "Object"}:
                    memo[index] = value[1]
                else:
                    memo[index] = None  # RegExp, EmptyRef, Island и прочее — данным тарифов не нужны
                return memo[index]
            arr: list[Any] = []
            memo[index] = arr
            arr.extend(hydrate(i) for i in value)
            return arr
        if isinstance(value, dict):
            obj = {}
            memo[index] = obj
            for key, i in value.items():
                obj[key] = hydrate(i)
            return obj
        memo[index] = value
        return value

    return hydrate(0) if values else None


def parse_nuxt_payload(html: str) -> Any:
    """Восстановить состояние Nuxt-страницы из её HTML (None, если payload нет или он битый)."""
    m = _PAYLOAD_RE.search(html)
    if m is None:
        return None
    try:
        values = json.loads(m.group(1))
    except ValueError:
        return None
    if not isinstance(values, list):
        return None
    try:
        return _unflatten(values)
    except (IndexError, TypeError, RecursionError):
        return None


def iter_dict_lists(obj: Any, *, max_depth: int = 12) -> Iterator[list[dict[str, Any]]]:
    """Все непустые списки словарей в дереве состояния (обход в глубину, циклы/повторы пропускаются)."""
    seen: set[int] = set()

    def walk(node: Any, depth: int) -> Iterator[list[dict[str, Any]]]:
        if depth > max_depth or id(node) in seen:
            return
        if isinstance(node, dict):
            seen.add(id(node))
            for v in node.values():
                yield from walk(v, depth + 1)
        elif isinstance(node, list):
            seen.add(id(node))
            if node and all(isinstance(x, dict) for x in node):
                yield node
            for v in node:
                yield from walk(v, depth + 1)

    yield from walk(obj, 0)


def find_dict_list(obj: Any, accept: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
    """Самый длинный список словарей, первый элемент которого проходит `accept` (иначе пустой список)."""
    best: list[dict[str, Any]] = []
    for items in iter_dict_lists(obj):
        if len(items) > len(best) and accept(items[0]):
            best = items
    return best
