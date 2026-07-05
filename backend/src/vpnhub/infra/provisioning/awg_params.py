"""Генерация obfuscation-параметров AmneziaWG (порт awgInstaller::generateAwgParameters).

Параметры генерятся ОДИН раз на сервер (на этапе install), пишутся и в серверный конфиг,
и в каждый клиентский — поэтому ДОЛЖНЫ совпадать на обеих сторонах. Мы храним их в БД
(ServerProtocol.params) и подставляем в оба шаблона.

Ограничения из исходника (awgInstaller.cpp:47-72):
- Jc ∈ [4,6]; Jmin=10; Jmax=50 (жёстко, не рандом).
- S1,S2 ∈ [15,149]; S3 ∈ [0,63]; S4 ∈ [0,19]; все Sx уникальны;
  запрещены равные размеры пакетов: S1+148 ≠ S2+92, S1+148 ≠ S3+64, S2+92 ≠ S3+64.
- AWG 2.0: заголовки H1-H4 — диапазоны "first-second" (возрастающие). Legacy: одиночные уникальные числа.
- I1 — DNS-подобный junk-блоб (дефолт), I2-I5 пустые.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, replace

from vpnhub.infra.provisioning import constants as c
from vpnhub.infra.provisioning import errors

INT32_MAX = 2**31 - 1

# awgProtocolConfig.h:14-16 (AwgConstant)
MSG_INITIATION_SIZE = 148
MSG_RESPONSE_SIZE = 92
MSG_COOKIE_REPLY_SIZE = 64

# protocolConstants.h awg::defaultSpecialJunk1
DEFAULT_I1 = "<r 2><b 0x858000010001000000000669636c6f756403636f6d0000010001c00c000100010000105a00044d583737>"


@dataclass
class AwgParams:
    """Полный набор obfuscation-параметров (значения — строки, как в конфиге)."""

    jc: str
    jmin: str
    jmax: str
    s1: str
    s2: str
    s3: str
    s4: str
    h1: str
    h2: str
    h3: str
    h4: str
    i1: str = DEFAULT_I1
    i2: str = ""
    i3: str = ""
    i4: str = ""
    i5: str = ""
    subnet_address: str = c.DEFAULT_SUBNET_ADDRESS
    subnet_cidr: str = c.DEFAULT_SUBNET_CIDR
    protocol_version: str = ""  # "2" для awg2, "" для legacy

    def script_vars(self) -> dict[str, str]:
        """$-токены для genAwgVars (scriptsRegistry.cpp)."""
        return {
            "$JUNK_PACKET_COUNT": self.jc,
            "$JUNK_PACKET_MIN_SIZE": self.jmin,
            "$JUNK_PACKET_MAX_SIZE": self.jmax,
            "$INIT_PACKET_JUNK_SIZE": self.s1,
            "$RESPONSE_PACKET_JUNK_SIZE": self.s2,
            "$COOKIE_REPLY_PACKET_JUNK_SIZE": self.s3,
            "$TRANSPORT_PACKET_JUNK_SIZE": self.s4,
            "$INIT_PACKET_MAGIC_HEADER": self.h1,
            "$RESPONSE_PACKET_MAGIC_HEADER": self.h2,
            "$UNDERLOAD_PACKET_MAGIC_HEADER": self.h3,
            "$TRANSPORT_PACKET_MAGIC_HEADER": self.h4,
            "$SPECIAL_JUNK_1": self.i1,
            "$SPECIAL_JUNK_2": self.i2,
            "$SPECIAL_JUNK_3": self.i3,
            "$SPECIAL_JUNK_4": self.i4,
            "$SPECIAL_JUNK_5": self.i5,
            "$AWG_SUBNET_IP": self.subnet_address,
            "$WIREGUARD_SUBNET_CIDR": self.subnet_cidr,
        }

    def config_json(self, is_awg2: bool) -> dict[str, str]:
        """Ключи AWG для native-конфига (AwgServerConfig/AwgClientConfig toJson)."""
        obj = {
            "Jc": self.jc,
            "Jmin": self.jmin,
            "Jmax": self.jmax,
            "S1": self.s1,
            "S2": self.s2,
            "H1": self.h1,
            "H2": self.h2,
            "H3": self.h3,
            "H4": self.h4,
            "I1": self.i1,
            "I2": self.i2,
            "I3": self.i3,
            "I4": self.i4,
            "I5": self.i5,
        }
        if is_awg2:
            obj["S3"] = self.s3
            obj["S4"] = self.s4
        return obj

    def as_dict(self) -> dict[str, str]:
        return {
            "jc": self.jc, "jmin": self.jmin, "jmax": self.jmax,
            "s1": self.s1, "s2": self.s2, "s3": self.s3, "s4": self.s4,
            "h1": self.h1, "h2": self.h2, "h3": self.h3, "h4": self.h4,
            "i1": self.i1, "i2": self.i2, "i3": self.i3, "i4": self.i4, "i5": self.i5,
            "subnet_address": self.subnet_address, "subnet_cidr": self.subnet_cidr,
            "protocol_version": self.protocol_version,
        }  # fmt: skip

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> AwgParams:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_server_conf(cls, text: str, is_awg2: bool) -> AwgParams:
        """Разобрать параметры из живого серверного конфига (порт extractConfigFromContainer).

        I1-I5 в серверном конфиге закомментированы (`# I1 = ...`) — читаем и их.
        """
        kv: dict[str, str] = {}
        commented: dict[str, str] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or (line.startswith("[") and line.endswith("]")):
                continue
            if line.startswith("#"):
                body = line.lstrip("#").strip()
                if "=" in body:
                    k, v = body.split("=", 1)
                    commented[k.strip()] = v.strip()
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                kv.setdefault(k.strip(), v.strip())

        subnet_address, subnet_cidr = c.DEFAULT_SUBNET_ADDRESS, c.DEFAULT_SUBNET_CIDR
        if kv.get("Address"):
            parts = kv["Address"].split("/")
            subnet_address = parts[0].strip()
            if len(parts) > 1:
                subnet_cidr = parts[1].strip()

        return cls(
            jc=kv.get("Jc", ""),
            jmin=kv.get("Jmin", ""),
            jmax=kv.get("Jmax", ""),
            s1=kv.get("S1", ""),
            s2=kv.get("S2", ""),
            s3=kv.get("S3", "") if is_awg2 else "",
            s4=kv.get("S4", "") if is_awg2 else "",
            h1=kv.get("H1", ""),
            h2=kv.get("H2", ""),
            h3=kv.get("H3", ""),
            h4=kv.get("H4", ""),
            i1=commented.get("I1", DEFAULT_I1),
            i2=commented.get("I2", ""),
            i3=commented.get("I3", ""),
            i4=commented.get("I4", ""),
            i5=commented.get("I5", ""),
            subnet_address=subnet_address,
            subnet_cidr=subnet_cidr,
            protocol_version="2" if is_awg2 else "",
        )


def _rand(lo: int, hi: int, rng: random.Random) -> int:
    """Аналог QRandomGenerator::bounded(lo, hi) — [lo, hi)."""
    return rng.randrange(lo, hi)


def generate(is_awg2: bool, rng: random.Random | None = None) -> AwgParams:
    rng = rng or random.SystemRandom()

    jc = str(_rand(4, 7, rng))
    jmin, jmax = "10", "50"

    s1 = _rand(15, 150, rng)
    s2 = _rand(15, 150, rng)
    s3 = _rand(0, 64, rng)
    s4 = _rand(0, 20, rng)

    used = {s1}
    while s2 in used or s1 + MSG_INITIATION_SIZE == s2 + MSG_RESPONSE_SIZE:
        s2 = _rand(15, 150, rng)
    used.add(s2)
    while (
        s3 in used
        or s1 + MSG_INITIATION_SIZE == s3 + MSG_COOKIE_REPLY_SIZE
        or s2 + MSG_RESPONSE_SIZE == s3 + MSG_COOKIE_REPLY_SIZE
    ):
        s3 = _rand(0, 64, rng)
    used.add(s3)
    while s4 in used:
        s4 = _rand(0, 20, rng)

    if is_awg2:
        headers: list[str] = []
        lo = 5
        while len(headers) != 4:
            if lo >= INT32_MAX - 1:  # защита от вырождения диапазона (в C++ не встречается на 4 итерациях)
                lo = 5
            first = _rand(lo, INT32_MAX, rng)
            second = _rand(first, INT32_MAX, rng) if first < INT32_MAX - 1 else first
            lo = second
            headers.append(f"{first}-{second}")
        h1, h2, h3, h4 = headers
    else:
        hs: set[str] = set()
        while len(hs) != 4:
            hs.add(str(_rand(5, INT32_MAX, rng)))
        h1, h2, h3, h4 = list(hs)

    return AwgParams(
        jc=jc, jmin=jmin, jmax=jmax,
        s1=str(s1), s2=str(s2), s3=str(s3), s4=str(s4),
        h1=h1, h2=h2, h3=h3, h4=h4,
        protocol_version="2" if is_awg2 else "",
    )  # fmt: skip


# --------------------------------------------------------------- пресеты ---

# Редактируемые obfuscation-поля (subnet/i-junk/protocol_version НЕ трогаем — иначе слетит адресация).
EDITABLE_FIELDS = ("jc", "jmin", "jmax", "s1", "s2", "s3", "s4", "h1", "h2", "h3", "h4")

# Только редактируемые поля; остальное (subnet/i1-i5/protocol_version) берётся из текущего AwgParams.
# H1-H4 для legacy — одиночные числа; для awg2 форма/бэкенд принимают диапазоны "a-b" при ручном вводе,
# в пресетах держим одиночные значения (валидны и для awg2 как вырожденный диапазон "n-n" после нормализации).
PRESETS: dict[str, dict[str, str]] = {
    # default — «сгенерировать заново» (спецкейс, значения не из этого словаря; см. build_target_params)
    "default": {},
    # aggressive — больший объём junk (сильнее маскировка, выше оверхед)
    "aggressive": {"jc": "6", "jmin": "40", "jmax": "70", "s1": "120", "s2": "140", "s3": "40", "s4": "15"},
    # mobile — минимальный оверхед под мобильные сети
    "mobile": {"jc": "4", "jmin": "10", "jmax": "30", "s1": "20", "s2": "35", "s3": "5", "s4": "3"},
}


def _as_int(name: str, value: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as e:
        raise errors.make("invalid_params", f"{name}: ожидается целое число, получено {value!r}") from e


def _parse_header(name: str, value: str, is_awg2: bool) -> tuple[int, int]:
    """H1-H4: legacy — одиночное число >4; awg2 — диапазон 'a-b' (a≤b) либо одиночное число."""
    raw = str(value).strip()
    if is_awg2 and "-" in raw:
        a_s, b_s = raw.split("-", 1)
        a, b = _as_int(name, a_s), _as_int(name, b_s)
        if a > b:
            raise errors.make("invalid_params", f"{name}: диапазон '{raw}' должен быть возрастающим (a≤b)")
        lo, hi = a, b
    else:
        lo = hi = _as_int(name, raw)
    if lo <= 4:
        raise errors.make("invalid_params", f"{name}: значение заголовка должно быть > 4")
    return lo, hi


def validate(params: AwgParams, is_awg2: bool) -> None:
    """Проверить obfuscation-параметры; при нарушении — errors.make('invalid_params', ...)."""
    jc = _as_int("Jc", params.jc)
    if not 1 <= jc <= 10:
        raise errors.make("invalid_params", "Jc должно быть в диапазоне [1, 10]")
    jmin, jmax = _as_int("Jmin", params.jmin), _as_int("Jmax", params.jmax)
    if jmin >= jmax:
        raise errors.make("invalid_params", "Jmin должно быть меньше Jmax")

    s1, s2 = _as_int("S1", params.s1), _as_int("S2", params.s2)
    for nm, val in (("S1", s1), ("S2", s2)):
        if not 1 <= val <= 1000:
            raise errors.make("invalid_params", f"{nm} должно быть в диапазоне [1, 1000]")
    sizes = {"S1": s1, "S2": s2}
    if s1 + MSG_INITIATION_SIZE == s2 + MSG_RESPONSE_SIZE:
        raise errors.make("invalid_params", "S1 и S2 дают одинаковый размер пакета — запрещено")
    if is_awg2:
        s3, s4 = _as_int("S3", params.s3), _as_int("S4", params.s4)
        sizes["S3"], sizes["S4"] = s3, s4
        if s1 + MSG_INITIATION_SIZE == s3 + MSG_COOKIE_REPLY_SIZE:
            raise errors.make("invalid_params", "S1 и S3 дают одинаковый размер пакета — запрещено")
        if s2 + MSG_RESPONSE_SIZE == s3 + MSG_COOKIE_REPLY_SIZE:
            raise errors.make("invalid_params", "S2 и S3 дают одинаковый размер пакета — запрещено")
    if len(set(sizes.values())) != len(sizes):
        raise errors.make("invalid_params", "Значения S1..S4 должны быть уникальными")

    headers = [_parse_header(nm, getattr(params, nm.lower()), is_awg2) for nm in ("H1", "H2", "H3", "H4")]
    if len({h[0] for h in headers}) != len(headers):
        raise errors.make("invalid_params", "Заголовки H1..H4 должны быть попарно различны")


def merge_editable(current: AwgParams, patch: dict[str, str]) -> AwgParams:
    """Наложить только редактируемые ключи на копию текущего (subnet/i-junk/protocol_version сохраняются)."""
    updates = {k: str(v) for k, v in patch.items() if k in EDITABLE_FIELDS}
    return replace(current, **updates)


def rewrite_interface_params(conf_text: str, params: AwgParams, is_awg2: bool) -> str:
    """Переписать obfuscation-строки в секции [Interface] живого awg0.conf; [Peer]-секции нетронуты.

    Работает построчно только внутри [Interface]; строки Jc/Jmin/Jmax/S1..S4/H1..H4 (и закомментированные
    # I1..) заменяются на актуальные значения из params. Отсутствующие в конфиге ключи добавляются в конец
    секции [Interface].
    """
    replacements: dict[str, str] = {
        "Jc": params.jc, "Jmin": params.jmin, "Jmax": params.jmax,
        "S1": params.s1, "S2": params.s2,
        "H1": params.h1, "H2": params.h2, "H3": params.h3, "H4": params.h4,
    }  # fmt: skip
    if is_awg2:
        replacements["S3"] = params.s3
        replacements["S4"] = params.s4

    lines = conf_text.splitlines()
    out: list[str] = []
    in_interface = False
    seen: set[str] = set()
    section_re = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
    kv_re = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9]+)(?P<sp>\s*=\s*).*$")

    def flush_missing(dst: list[str]) -> None:
        for key, val in replacements.items():
            if key not in seen:
                dst.append(f"{key} = {val}")
                seen.add(key)

    for raw in lines:
        m = section_re.match(raw)
        if m is not None:
            if in_interface:
                flush_missing(out)  # добавить недостающие ключи перед закрытием [Interface]
            in_interface = m.group("name").strip().lower() == "interface"
            out.append(raw)
            continue
        if in_interface:
            km = kv_re.match(raw)
            if km is not None and km.group("key") in replacements:
                key = km.group("key")
                out.append(f"{km.group('indent')}{key}{km.group('sp')}{replacements[key]}")
                seen.add(key)
                continue
        out.append(raw)

    if in_interface:
        flush_missing(out)

    trailing = "\n" if conf_text.endswith("\n") else ""
    return "\n".join(out) + trailing
