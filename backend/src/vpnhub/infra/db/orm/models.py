"""ORM-модели (SQLAlchemy 2.0) на базе sqlalchemy-foundation-kit.

Все таблицы по доменной модели спеки §5.4. PK — строковые (uuid hex), чтобы совпадать с
сид-данными прототипа (`s1`, `g1`, ...) и просто генерироваться для новых записей.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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

    vpns: Mapped[list[ServerVpn]] = relationship(back_populates="server", cascade="all, delete-orphan", lazy="selectin")
    protocols: Mapped[list[ServerProtocol]] = relationship(
        back_populates="server", cascade="all, delete-orphan", lazy="selectin"
    )


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
    params_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # AwgParams (для awg/awg_legacy)
    material_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet(JSON ServerMaterial)
    # долг на снятие: JSON list[str] client_id, которые обязаны снять на этом (server, proto).
    # Пишется при удалении устройства/потере доступа, дренится фоновым sync (идемпотентно). None = долгов нет.
    pending_revoke_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    server: Mapped[Server] = relationship(back_populates="protocols")


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

    Ретеншн — фоновой purge-джобой (`traffic_retention_days`). Будущее: даунсэмплинг агрегатов.
    """

    __tablename__ = "traffic_samples"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    server_id: Mapped[str] = mapped_column(String(32), index=True)
    proto: Mapped[str] = mapped_column(String(24))  # id протокола (awg | awg_legacy | ...)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # pubkey/uuid; None — агрегат
    device_config_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # None → external-клиент
    at: Mapped[float] = mapped_column(index=True)  # epoch seconds (как AuditEvent.at)
    rx_bytes: Mapped[int] = mapped_column(Integer, default=0)  # кумулятивно (как отдаёт wg)
    tx_bytes: Mapped[int] = mapped_column(Integer, default=0)
    rx_delta: Mapped[int] = mapped_column(Integer, default=0)  # прирост от прошлого сэмпла
    tx_delta: Mapped[int] = mapped_column(Integer, default=0)
    last_handshake: Mapped[float | None] = mapped_column(nullable=True)  # epoch; None — рукопожатий не было

    __table_args__ = (Index("traffic_samples_scope_idx", "server_id", "proto", "client_id"),)


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
