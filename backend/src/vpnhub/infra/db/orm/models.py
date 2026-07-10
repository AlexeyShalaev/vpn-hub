"""ORM-модели (SQLAlchemy 2.0) на базе sqlalchemy-foundation-kit.

Все таблицы по доменной модели спеки §5.4. PK — строковые (uuid hex), чтобы совпадать с
сид-данными прототипа (`s1`, `g1`, ...) и просто генерироваться для новых записей.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy_foundation_kit import BaseTable, DatetimeColumnsMixin


def _id() -> str:
    return uuid.uuid4().hex[:16]


class User(BaseTable, DatetimeColumnsMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|active|blocked


class Admin(BaseTable, DatetimeColumnsMixin):
    """Признак того, что пользователь — администратор.

    Учётные данные (телефон, имя, пароль) не дублируются, а берутся из связанной
    строки `users`. PK == FK на users.id (одна запись-админ на пользователя).
    """

    __tablename__ = "admins"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    user: Mapped[User] = relationship(lazy="selectin")


class Session(BaseTable, DatetimeColumnsMixin):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # token hash
    subject_kind: Mapped[str] = mapped_column(String(8))  # admin|user
    subject_id: Mapped[str] = mapped_column(String(32), index=True)
    expires_at: Mapped[float] = mapped_column()  # epoch seconds
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class Server(BaseTable, DatetimeColumnsMixin):
    __tablename__ = "servers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    owner_user_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str] = mapped_column(String(64))
    ssh_user: Mapped[str] = mapped_column(String(64), default="root")
    ssh_port: Mapped[str] = mapped_column(String(8), default="22")
    ssh_auth: Mapped[str] = mapped_column(String(16), default="key")  # key|password
    ssh_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # online|offline|unknown
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_check_at: Mapped[float | None] = mapped_column(nullable=True)  # epoch seconds
    # Байт-бюджет (квота трафика тарифа) на биллинг-период, NULL = без квоты (безлимитный тариф).
    bandwidth_quota_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # День сброса биллинг-периода (1..31); NULL → считать с 1-го числа месяца.
    billing_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Провайдерская метадата: исходный тариф из письма/панели, id внешней услуги и т.п.
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=dict)

    vpns: Mapped[list[ServerVpn]] = relationship(back_populates="server", cascade="all, delete-orphan", lazy="selectin")
    protocols: Mapped[list[ServerProtocol]] = relationship(
        back_populates="server", cascade="all, delete-orphan", lazy="selectin"
    )


class ServerPrice(BaseTable):
    """Сегмент истории цены сервера (финансовый учёт). Цена меняется во времени, поэтому храним
    историю: при смене закрываем текущий сегмент (effective_to=now) и открываем новый. Расход
    считается по СЕГМЕНТАМ (accrual: сумма по каждому сегменту = цена × длительность/период), а не
    текущей ценой × всё время. Валюты не конвертируем — суммируем раздельно.

    amount_micros — цена в «микроединицах» валюты (сумма × 1e6), чтобы не терять точность на float.
    period — minute|day|month; anchor_day — день обновления (для month, 1..31; справочно/для UI).
    Открытый (текущий) сегмент — тот, у кого effective_to IS NULL.
    """

    __tablename__ = "server_prices"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    server_id: Mapped[str] = mapped_column(String(32), index=True)
    amount_micros: Mapped[int] = mapped_column(BigInteger)  # цена × 1e6 в валюте currency
    currency: Mapped[str] = mapped_column(String(8))  # RUB | USD | EUR | ... (не конвертируем)
    period: Mapped[str] = mapped_column(String(8))  # minute | day | month
    anchor_day: Mapped[int | None] = mapped_column(Integer, nullable=True)  # день обновления (month)
    effective_from: Mapped[float] = mapped_column()  # epoch начала действия сегмента
    effective_to: Mapped[float | None] = mapped_column(nullable=True)  # epoch конца; NULL = текущий

    __table_args__ = (Index("server_prices_scope_idx", "server_id", "effective_from"),)


class ServerVpn(BaseTable):
    __tablename__ = "server_vpns"
    __table_args__ = (UniqueConstraint("server_id", "type", name="server_vpns_uq"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # amnezia|openvpn|outline
    installed: Mapped[bool] = mapped_column(Boolean, default=False)
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    port: Mapped[str] = mapped_column(String(8), default="")

    server: Mapped[Server] = relationship(back_populates="vpns")


class ServerProtocol(BaseTable, DatetimeColumnsMixin):
    """Состояние одного протокола Amnezia на сервере = один docker-контейнер.

    Вендор `ServerVpn.type` (amnezia) раскладывается на протоколы (awg/awg_legacy/xray),
    у каждого — свой контейнер, порт, ключевой материал и (для awg) obfuscation-параметры.
    """

    __tablename__ = "server_protocols"
    __table_args__ = (UniqueConstraint("server_id", "proto", name="server_protocols_uq"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    vendor: Mapped[str] = mapped_column(String(16))  # amnezia
    proto: Mapped[str] = mapped_column(String(24))  # awg | awg_legacy | xray
    container: Mapped[str] = mapped_column(String(64), default="")
    port: Mapped[str] = mapped_column(String(8), default="")
    state: Mapped[str] = mapped_column(String(16), default="absent")  # absent|installing|installed|error
    installed: Mapped[bool] = mapped_column(Boolean, default=False)
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)  # стабильный код (ProvisioningError.code)
    external_clients: Mapped[int] = mapped_column(Integer, default=0)  # клиенты, заведённые внешним клиентом
    # мягкий (панельный) лимит числа конфигов-клиентов на этом протоколе, задаётся владельцем.
    # None = без лимита. Это НЕ физический потолок: у AmneziaWG адресов /24 растёт намеренно, а
    # выдача сверх лимита просто блокируется в services/configs. Занятость = active configs + external.
    max_clients: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # версия бинарника компонента в запущенном контейнере (xray/hysteria2), читается sync по SSH.
    # Сравнивается с эталоном релиза панели (component_versions) → флаг «доступно обновление».
    # None = не читалась/детект не поддержан для протокола.
    image_version: Mapped[str | None] = mapped_column(String(48), nullable=True)
    params_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # AwgParams (для awg/awg_legacy)
    material_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet(JSON ServerMaterial)
    # долг на снятие: JSON list[str] client_id, которые обязаны снять на этом (server, proto).
    # Пишется при удалении устройства/потере доступа, дренится фоновым sync (идемпотентно). None = долгов нет.
    pending_revoke_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # здоровье сбора трафика (monitor-тик, services/traffic.ProtoTraffic): даёт UI честный диагноз
    # вместо общей фразы «нет данных». collected_at обновляется только при успешном сборе (status=ok).
    traffic_collected_at: Mapped[float | None] = mapped_column(nullable=True)  # epoch последнего ok-сбора
    traffic_status: Mapped[str | None] = mapped_column(String(24), nullable=True)  # ok|stats_disabled|…
    traffic_error: Mapped[str | None] = mapped_column(Text, nullable=True)  # причина не-ok статуса

    server: Mapped[Server] = relationship(back_populates="protocols")


class ChainLink(BaseTable, DatetimeColumnsMixin):
    """Мультихоп-цепочка: entry-сервер выпускает трафик через exit-сервер (Xray outbound chaining).

    Клиент подключается к entry (например, российский IP), а его xray-контейнер на entry получает
    outbound не «freedom», а vless-коннект на exit — то есть entry сам становится обычным
    vless-клиентом exit. `exit_client_id` — uuid, заведённый на exit через штатный add_client
    (его снимаем при удалении связки). Один entry-протокол = один outbound, поэтому связка уникальна
    по (entry_server_id, proto).
    """

    __tablename__ = "chain_links"
    __table_args__ = (UniqueConstraint("entry_server_id", "proto", name="chain_links_uq"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    owner_user_id: Mapped[str] = mapped_column(String(32), index=True)
    entry_server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    exit_server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    proto: Mapped[str] = mapped_column(String(24), default="xray")  # xray (VLESS+Reality tcp)
    exit_client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # uuid на exit (add_client)
    state: Mapped[str] = mapped_column(String(16), default="absent")  # absent|linked|error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Pool(BaseTable, DatetimeColumnsMixin):
    __tablename__ = "pools"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    owner_user_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))


class PoolServer(BaseTable):
    __tablename__ = "pool_servers"
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id", ondelete="CASCADE"), primary_key=True)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True)


class Group(BaseTable, DatetimeColumnsMixin):
    __tablename__ = "groups"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    owner_user_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))
    token: Mapped[str] = mapped_column(String(64), unique=True)
    # override глобального лимита устройств на участника этой группы; NULL = наследовать глобал
    max_devices: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # override лимита байт per (участник, сервер) за период; NULL = наследовать глобал (без лимита)
    max_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    members: Mapped[list[GroupMember]] = relationship(
        back_populates="group", cascade="all, delete-orphan", lazy="selectin"
    )


class GroupMember(BaseTable):
    __tablename__ = "group_members"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="member")  # admin|member
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|invited
    # персональный override лимита устройств; NULL = наследовать лимит группы/глобал
    max_devices: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # персональный override лимита байт per (участник, сервер) за период; NULL = наследовать группу/глобал
    max_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    group: Mapped[Group] = relationship(back_populates="members")


class GroupPoolAccess(BaseTable):
    __tablename__ = "group_pool_access"
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id", ondelete="CASCADE"), primary_key=True)


class GroupServerAccess(BaseTable):
    __tablename__ = "group_server_access"
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True)
    vpn_type: Mapped[str] = mapped_column(String(16), primary_key=True)


class Device(BaseTable, DatetimeColumnsMixin):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(16))  # ios|android|mac|windows|linux|router

    configs: Mapped[list[DeviceConfig]] = relationship(
        back_populates="device", cascade="all, delete-orphan", lazy="selectin"
    )


class DeviceConfig(BaseTable):
    __tablename__ = "device_configs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    server_id: Mapped[str] = mapped_column(String(32))
    vpn_type: Mapped[str] = mapped_column(String(16))
    proto: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | revoked (снят на сервере)

    # реальный клиентский материал (заполняется после add_client на сервере)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # pubkey (wg/awg) | uuid (xray)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)  # wg/awg
    client_public_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet(client priv key)
    client_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    device: Mapped[Device] = relationship(back_populates="configs")


class TrafficSample(BaseTable):
    """Дельта-сэмпл трафика/подключений одного клиента по протоколу за один sync-тик.

    Пишется в sync-тике (best-effort) для установленных wireguard-протоколов из `wg/awg show dump`.
    `rx_bytes`/`tx_bytes` — кумулятивные счётчики (как отдаёт wg), `rx_delta`/`tx_delta` — прирост от
    прошлого сэмпла (для графика; при рестарте счётчиков curr<prev дельта = curr). Онлайн-статус
    вычисляется из свежести `last_handshake` (now - last_handshake < online-окно).
    external-клиенты (без нашего DeviceConfig) пишутся с `device_config_id=None`.

    Ретеншн — ярусная rollup-джоба (`traffic_raw_retention_days`): сырьё сворачивается в
    `traffic_hourly`/`traffic_daily` и затем чистится (см. services/traffic_rollup).
    """

    __tablename__ = "traffic_samples"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    server_id: Mapped[str] = mapped_column(String(32), index=True)
    proto: Mapped[str] = mapped_column(String(24))  # id протокола (awg | awg_legacy | ...)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # pubkey/uuid; None — агрегат
    device_config_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # None → external-клиент
    at: Mapped[float] = mapped_column(index=True)  # epoch seconds (как AuditEvent.at)
    # BigInteger: реальные счётчики wg легко превышают int32 (>2 ГБ трафика)
    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)  # кумулятивно (как отдаёт wg)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    rx_delta: Mapped[int] = mapped_column(BigInteger, default=0)  # прирост от прошлого сэмпла
    tx_delta: Mapped[int] = mapped_column(BigInteger, default=0)
    last_handshake: Mapped[float | None] = mapped_column(nullable=True)  # epoch; None — рукопожатий не было
    # активна ли сессия сейчас (из stats движка: xray statsUserOnline / hysteria /online). None —
    # неизвестно из движка (wg — онлайн вычисляется по свежести last_handshake на чтении).
    online: Mapped[bool | None] = mapped_column(nullable=True)
    # имя клиента из Amnezia clientsTable (clientName). Нужно, чтобы показывать имя external-клиента
    # (заведённого мимо панели — без нашего DeviceConfig). Для нон-external имя берётся из device_config.
    ext_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (Index("traffic_samples_scope_idx", "server_id", "proto", "client_id"),)


class TrafficPeerState(BaseTable):
    """Последний кумулятив счётчиков per (server, proto, client) — O(1)-дельты и «сейчас»-состояние.

    Обновляется на каждый `TrafficService.record` и переживает purge сырых сэмплов: дельта после
    простоя клиента считается от последнего известного кумулятива, а не заново от нуля (иначе —
    ложный всплеск на весь кумулятив). Заодно хранит последние скорость/онлайн/handshake — показ
    «онлайн сейчас / скорость» не зависит от выбранного периода дашборда и яруса хранения.
    """

    __tablename__ = "traffic_peer_state"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    server_id: Mapped[str] = mapped_column(String(32), index=True)
    proto: Mapped[str] = mapped_column(String(24))
    client_id: Mapped[str] = mapped_column(String(64))
    device_config_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # None → external
    ext_name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # имя из clientsTable
    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)  # последний кумулятив
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    rx_speed: Mapped[float] = mapped_column(default=0.0)  # байт/с из последней дельты
    tx_speed: Mapped[float] = mapped_column(default=0.0)
    last_at: Mapped[float] = mapped_column(default=0.0)  # epoch последнего замера
    last_handshake: Mapped[float | None] = mapped_column(nullable=True)  # epoch (wg); max за историю
    online: Mapped[bool | None] = mapped_column(nullable=True)  # из stats движка; None — по handshake

    __table_args__ = (UniqueConstraint("server_id", "proto", "client_id", name="traffic_peer_state_uq"),)


class _TrafficRollup:
    """Общие колонки ярусных агрегатов трафика (hourly/daily). Не таблица — миксин полей.

    Ярусное хранение: сырьё `traffic_samples` (дни) → `traffic_hourly` (недели/месяцы) →
    `traffic_daily` (годы). Свежие периоды быстро читаются из сырья, старые — из агрегатов
    (на порядки меньше строк). Заполняются фоновой rollup-джобой (см. services/traffic_rollup).
    `bucket` — epoch начала часа/суток (UTC-сетка); `samples_online/samples_total` дают долю
    онлайна (честно переживает смену интервала сбора). Уникум по (server, proto, client, bucket).
    """

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    server_id: Mapped[str] = mapped_column(String(32), index=True)
    proto: Mapped[str] = mapped_column(String(24))
    client_id: Mapped[str] = mapped_column(String(64))
    device_config_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # None → external
    ext_name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # имя из clientsTable
    bucket: Mapped[int] = mapped_column(BigInteger, index=True)  # epoch начала бакета (UTC-сетка)
    rx: Mapped[int] = mapped_column(BigInteger, default=0)  # сумма rx_delta за бакет
    tx: Mapped[int] = mapped_column(BigInteger, default=0)  # сумма tx_delta за бакет
    samples_total: Mapped[int] = mapped_column(Integer, default=0)  # число сэмплов в бакете
    samples_online: Mapped[int] = mapped_column(Integer, default=0)  # из них с активной сессией
    last_handshake: Mapped[float | None] = mapped_column(nullable=True)  # max за бакет (wg)


class TrafficHourly(_TrafficRollup, BaseTable):
    """Почасовые агрегаты трафика per (server, proto, client). Досчитываются rollup-джобой из сырья."""

    __tablename__ = "traffic_hourly"
    __table_args__ = (
        UniqueConstraint("server_id", "proto", "client_id", "bucket", name="traffic_hourly_uq"),
        Index("traffic_hourly_scope_idx", "server_id", "proto", "client_id", "bucket"),
    )


class TrafficDaily(_TrafficRollup, BaseTable):
    """Посуточные агрегаты трафика per (server, proto, client). Досчитываются из traffic_hourly."""

    __tablename__ = "traffic_daily"
    __table_args__ = (
        UniqueConstraint("server_id", "proto", "client_id", "bucket", name="traffic_daily_uq"),
        Index("traffic_daily_scope_idx", "server_id", "proto", "client_id", "bucket"),
    )


class TrafficUsage(BaseTable):
    """Персистентный накопитель трафика за биллинг-период (переживает purge сырых сэмплов).

    Инкрементится в TrafficService.record из тех же дельт, что и traffic_samples. Две роли строк:
    - `user_id` задан — трафик конкретного пользователя на сервере (для пер-user лимита);
    - `user_id IS NULL` — суммарный трафик сервера за период (все клиенты + external), для квоты тарифа.
    `period_start` — epoch начала текущего периода сервера (зависит от `Server.billing_day`); смена
    периода = новая строка (эффективный сброс счётчика). Уникум по (server, user, period).
    """

    __tablename__ = "traffic_usage"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    server_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # NULL = агрегат сервера
    period_start: Mapped[float] = mapped_column()  # epoch начала биллинг-периода
    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[float] = mapped_column(default=0.0)  # epoch последнего инкремента

    __table_args__ = (
        UniqueConstraint("server_id", "user_id", "period_start", name="traffic_usage_uq"),
        Index("traffic_usage_scope_idx", "server_id", "user_id", "period_start"),
    )


class MetricSample(BaseTable):
    """Точка временного ряда прикладной метрики инстанса панели (для admin-дашборда).

    Фоновая джоба `metrics-tick` раз в интервал снимает текущие значения счётчиков/гейджей
    из in-process реестра prometheus-client (`infra/metrics.py`) и из БД (серверы по статусу,
    ошибки provisioning) и дописывает сюда строки. Это переживает рестарт контейнера (реестр
    prometheus-client живёт только в памяти процесса). `labels` — компактная строка ключей
    лейблов (напр. `status=online`), чтобы не плодить кардинальность. Ретеншн — `purge_old`
    по `metrics_retention_days`. НЕ путать с owner-трафиком (`traffic_samples`).
    """

    __tablename__ = "metric_samples"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String(64), index=True)  # имя метрики (vpnhub_*)
    labels: Mapped[str] = mapped_column(String(160), default="")  # сериализованные лейблы (k=v,...)
    at: Mapped[float] = mapped_column(index=True)  # epoch seconds
    value: Mapped[float] = mapped_column()

    __table_args__ = (Index("metric_samples_scope_idx", "name", "at"),)


class ServerMetric(BaseTable):
    """Точка временного ряда ресурсов хоста одного сервера (per-server host monitoring).

    Пишется в monitor-тике (best-effort, отдельной короткой SSH-сессией) для онлайн-серверов:
    CPU%, load average, RAM (used/total), диск `/` (used/total), число TCP established, uptime и
    (опционально) число онлайн-VPN-клиентов. Значения памяти/диска — BigInteger: >2 ГБ легко
    переполнят int32 (реальный баг, уже ловили в traffic_samples). Все метрики nullable —
    поле, которое не удалось прочитать по SSH, пишется NULL и не роняет тик.

    Ретеншн — фоновой purge-джобой (`server_metrics_retention_days`).
    """

    __tablename__ = "server_metrics"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    at: Mapped[float] = mapped_column(index=True)  # epoch seconds (как TrafficSample.at)
    cpu_pct: Mapped[float | None] = mapped_column(nullable=True)  # 0..100
    load1: Mapped[float | None] = mapped_column(nullable=True)  # 1-минутный load average
    # BigInteger: RAM/диск легко >2 ГБ (int32 overflow) — как rx_bytes в traffic_samples
    mem_used: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # байт
    mem_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # байт
    disk_used: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # байт (/)
    disk_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # байт (/)
    tcp_estab: Mapped[int | None] = mapped_column(Integer, nullable=True)  # TCP established
    uptime_s: Mapped[int | None] = mapped_column(Integer, nullable=True)  # аптайм хоста, сек
    online_clients: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # суммарно онлайн (сумма известных по протоколам)
    # честный online по протоколам: JSON {proto: int|null}. null = «неизвестно» (stats не включён/
    # протокол без счётчика, напр. outline). Сумма известных значений идёт в online_clients.
    online_by_proto: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("server_metrics_scope_idx", "server_id", "at"),)


class ServerMetricHourly(BaseTable):
    """Почасовые агрегаты ресурсов хоста (avg/max) — ярусное хранение как у трафика.

    Досчитываются rollup-джобой из `server_metrics`: свежее (сутки) читается из сырья, длинные
    периоды (недели/месяцы) — отсюда (24 строки/сутки/сервер). avg — по непустым сэмплам бакета;
    *_total/*_used берутся из последнего сэмпла бакета (моментальные, не усредняются). Daily-ярус
    не нужен. `bucket` — epoch начала часа (UTC-сетка). Уникум по (server, bucket).
    """

    __tablename__ = "server_metrics_hourly"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    server_id: Mapped[str] = mapped_column(String(32), index=True)
    bucket: Mapped[int] = mapped_column(BigInteger, index=True)  # epoch начала часа
    cpu_pct_avg: Mapped[float | None] = mapped_column(nullable=True)
    cpu_pct_max: Mapped[float | None] = mapped_column(nullable=True)
    load1_avg: Mapped[float | None] = mapped_column(nullable=True)
    load1_max: Mapped[float | None] = mapped_column(nullable=True)
    mem_used_avg: Mapped[float | None] = mapped_column(nullable=True)  # байт (avg)
    mem_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # байт (last)
    disk_used: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # байт (last)
    disk_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # байт (last)
    tcp_estab_avg: Mapped[float | None] = mapped_column(nullable=True)
    tcp_estab_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    online_clients_avg: Mapped[float | None] = mapped_column(nullable=True)
    online_clients_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    samples_total: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("server_id", "bucket", name="server_metrics_hourly_uq"),
        Index("server_metrics_hourly_scope_idx", "server_id", "bucket"),
    )


class Setting(BaseTable):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class AuditEvent(BaseTable, DatetimeColumnsMixin):
    """Событие аудит-лога: кто (актор), что (type), над чем (target), у кого (owner).

    Актор и его имя денормализованы (снимок), чтобы событие читалось после удаления/переименования
    пользователя. `owner_user_id` — владелец затронутого ресурса, проставляется на записи ради
    ролевой фильтрации owner без джойнов. `meta_json` — доп. детали (ip/ua/имя устройства/статусы).
    """

    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    at: Mapped[float] = mapped_column(index=True)  # epoch seconds (как Server.last_check_at)
    actor_kind: Mapped[str] = mapped_column(String(8))  # admin|user|system
    actor_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    actor_name: Mapped[str] = mapped_column(String(120), default="")  # снимок имени актора
    type: Mapped[str] = mapped_column(String(48), index=True)  # стабильный код события (реестр audit_types)
    target_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
