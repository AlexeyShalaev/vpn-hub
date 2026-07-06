"""Серверы и VPN-ПО.

Мониторинг (статус/латентность): TCP-зонд по SSH-порту (см. infra.probe).
Provisioning VPN-ПО — реальный, по SSH (см. services.provisioning / infra.provisioning).
"""

from __future__ import annotations

import asyncio
import builtins
import json
import time

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy import update as sa_update

from vpnhub.api.config import Settings
from vpnhub.common.catalog import DEFAULT_PORTS
from vpnhub.common.net import is_valid_host
from vpnhub.common.serializers import server_to_dict
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra import metrics
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.events import TOPIC_SERVER, EventBus, get_event_bus
from vpnhub.infra.probe import ProbeResult, probe_tcp
from vpnhub.infra.provisioning import awg_params, component_versions, reality, remediation
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.awg_params import AwgParams
from vpnhub.infra.provisioning.errors import ProvisioningError
from vpnhub.infra.provisioning.provisioners.awg import AwgProvisioner
from vpnhub.infra.provisioning.provisioners.base import ServerMaterial
from vpnhub.infra.provisioning.ssh import SshError
from vpnhub.infra.security import decrypt_secret, encrypt_secret
from vpnhub.infra.uow import Uow, UowTransaction
from vpnhub.services.provisioning import PROVISIONED_VENDORS, ProvisioningService

log = structlog.get_logger(__name__)

VPN_TYPES = ("amnezia", "openvpn", "outline", "hysteria2")


def _parse_port(raw: str | None, default: int = 22) -> int:
    try:
        port = int(str(raw).strip())
    except ValueError:
        return default
    return port if 1 <= port <= 65535 else default


def _apply_probe(s: m.Server, r: ProbeResult) -> None:
    s.status = "online" if r.ok else "offline"
    s.latency_ms = r.latency_ms if r.ok else None
    s.last_check_at = time.time()


# Верхняя граница синхронной синхронизации при добавлении сервера: POST /servers ждёт синк,
# поэтому держим его ограниченным по времени, даже если сессия зависнет после подключения
# (keepalive в ssh.py — общая страховка; здесь — жёсткий потолок именно на путь создания).
POST_CREATE_SYNC_TIMEOUT = 30.0


class ServerService:
    def __init__(self, uow: Uow, settings: Settings, bus: EventBus | None = None) -> None:
        self.uow = uow
        self.settings = settings
        self.bus = bus or get_event_bus()  # realtime-сигналы (см. infra/events)

    def _secret(self, s: m.Server) -> str:
        return decrypt_secret(self.settings.secret_key, s.ssh_secret_encrypted) if s.ssh_secret_encrypted else ""

    async def list(self, owner_id: str) -> list[dict]:
        async with self.uow.query() as tx:
            return [server_to_dict(s, self._secret(s)) for s in await tx.servers.for_owner(owner_id)]

    async def _owned(self, tx: UowTransaction, owner_id: str, sid: str) -> m.Server:
        s: m.Server | None = await tx.servers.get(sid)
        if not s or s.owner_user_id != owner_id:
            raise NotFound("Сервер не найден")
        return s

    async def get(self, owner_id: str, sid: str) -> dict:
        async with self.uow.query() as tx:
            s = await self._owned(tx, owner_id, sid)
            return server_to_dict(s, self._secret(s))

    async def create(self, owner_id: str, data: dict) -> dict:
        name = (data.get("name") or "").strip()
        ip = (data.get("ip") or "").strip()
        location = (data.get("location") or "").strip()
        if not name or not ip or not location:
            raise BadRequest("Название, IP и локация обязательны")
        if not is_valid_host(ip):
            raise BadRequest("Некорректный IP или хост сервера")
        async with self.uow.transaction() as tx:
            s = m.Server(
                owner_user_id=owner_id,
                name=name,
                provider=data.get("provider") or "Другой",
                ip=ip,
                ssh_user=data.get("sshUser") or "root",
                ssh_port=str(data.get("sshPort") or "22"),
                ssh_auth=data.get("auth") or "key",
                ssh_secret_encrypted=encrypt_secret(self.settings.secret_key, data.get("secret") or ""),
                location=location,
                status="unknown",
            )
            tx.servers.add(s)
            await tx.session.flush()
            for t in VPN_TYPES:
                tx.session.add(m.ServerVpn(server_id=s.id, type=t, port=DEFAULT_PORTS[t]))
            await tx.session.flush()
            await tx.session.refresh(s)
            return server_to_dict(s, self._secret(s))

    async def update(self, owner_id: str, sid: str, data: dict) -> dict:
        if data.get("ip") is not None:
            ip = str(data["ip"]).strip()
            if not is_valid_host(ip):
                raise BadRequest("Некорректный IP или хост сервера")
            data = {**data, "ip": ip}  # хранить обрезанное значение (валидатор строг к пробелам)
        if data.get("location") is not None:
            location = str(data["location"]).strip()
            if not location:
                raise BadRequest("Локация обязательна")
            data = {**data, "location": location}  # хранить обрезанное значение
        async with self.uow.transaction() as tx:
            s = await self._owned(tx, owner_id, sid)
            for field, key in [
                ("name", "name"),
                ("provider", "provider"),
                ("ip", "ip"),
                ("ssh_user", "sshUser"),
                ("ssh_port", "sshPort"),
                ("ssh_auth", "auth"),
                ("location", "location"),
            ]:
                if key in data and data[key] is not None:
                    setattr(s, field, str(data[key]))
            if data.get("secret"):
                s.ssh_secret_encrypted = encrypt_secret(self.settings.secret_key, data["secret"])
            await tx.session.flush()
            await tx.session.refresh(s)
            return server_to_dict(s, self._secret(s))

    async def migrate(self, owner_id: str, sid: str, data: dict) -> dict:
        """Миграция сервера на новый VPS (старый недоступен/заблокирован).

        Сценарий: у сервера меняются SSH-реквизиты (новый IP/порт/юзер/секрет), затем все
        установленные provisioned-протоколы переустанавливаются на новом хосте существующими
        install-путями (фоново, прогресс — через state=installing, как обычная установка).

        ЧЕСТНОСТЬ (матрица — tasks/07-server-migration.md): material_encrypted хранит только
        ПУБЛИЧНЫЙ материал (pubkey/psk/CA cert/apiUrl/cert-pin) — приватная identity сервера
        (awg-приватник, Reality privateKey, CA-ключ, состояние shadowbox) генерится внутри
        контейнера при install и НЕ персистится, поэтому ни один вендор сегодня не умеет
        переустановку «с тем же материалом»: переустановка даёт новую identity. Плюс endpoint
        клиентских конфигов содержит IP старого сервера — при смене IP их пришлось бы
        перескачивать в любом случае. Поэтому все выданные конфиги честно помечаются
        revoked → участник переиздаёт конфиг в один клик (существующий flow: revoked
        переиздаётся заново, уже с новым адресом). Ledger отзыва (pending_revoke_json)
        обнуляется — долг относился к контейнерам старого хоста, которых больше нет.
        """
        ip = str(data.get("ip") or "").strip()
        if not ip:
            raise BadRequest("Укажите IP нового сервера")
        if not is_valid_host(ip):
            raise BadRequest("Некорректный IP или хост сервера")

        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.transaction() as tx:
            s = await self._owned(tx, owner_id, sid)
            s.ip = ip
            if data.get("sshUser"):
                s.ssh_user = str(data["sshUser"])
            if data.get("sshPort"):
                s.ssh_port = str(data["sshPort"])
            if data.get("auth"):
                s.ssh_auth = str(data["auth"])
            if data.get("secret"):  # пусто → оставить текущий секрет (тот же ключ подходит к новому VPS)
                s.ssh_secret_encrypted = encrypt_secret(self.settings.secret_key, data["secret"])
            s.status, s.latency_ms = "unknown", None

            # что переустанавливаем на новом хосте: все установленные provisioned-протоколы
            reinstall: dict[str, builtins.list[str]] = {}
            for p in s.protocols:
                if p.vendor in PROVISIONED_VENDORS and p.installed:
                    reinstall.setdefault(p.vendor, []).append(p.proto)
                p.pending_revoke_json = None  # долг отзыва — про контейнеры старого хоста

            # выданные конфиги: клиентов на новом хосте нет → помечаем revoked (требуют перевыдачи)
            marked = await tx.session.execute(
                sa_update(m.DeviceConfig)
                .where(m.DeviceConfig.server_id == sid, m.DeviceConfig.status == "active")
                .values(status="revoked")
            )
            for vendor, proto_ids in reinstall.items():
                await prov.mark_installing(tx, sid, vendor, proto_ids)
            await tx.session.flush()
            await tx.session.refresh(s)
            result = server_to_dict(s, self._secret(s))

        for vendor, proto_ids in reinstall.items():
            prov.schedule_install(sid, vendor, proto_ids)  # долгая переустановка — в фоне
        log.info("server_migration_started", server_id=sid, reinstall=reinstall)
        return {
            "server": result,
            "reinstall": reinstall,  # вендор → протоколы, переустанавливаемые на новом хосте
            # конфигов помечено к перевыдаче (rowcount типизирован только у CursorResult)
            "configsRevoked": int(marked.rowcount or 0),  # type: ignore[attr-defined]
        }

    async def delete(self, owner_id: str, sid: str) -> None:
        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            s = await self._owned(tx, owner_id, sid)
            vendors = {p.vendor for p in s.protocols if p.installed and p.vendor in PROVISIONED_VENDORS}
            server = s
        for vendor in vendors:
            await prov.remove_vendor(server, vendor)  # снести контейнеры (пиры уйдут вместе с ними), best-effort
        async with self.uow.transaction() as tx:
            s = await self._owned(tx, owner_id, sid)
            await tx.session.execute(sa_delete(m.DeviceConfig).where(m.DeviceConfig.server_id == sid))
            await tx.session.delete(s)

    async def check(self, owner_id: str, sid: str) -> dict:
        """Проверить один сервер по запросу (TCP-зонд по SSH-порту)."""
        async with self.uow.transaction() as tx:
            s = await self._owned(tx, owner_id, sid)
            result = await probe_tcp(s.ip, _parse_port(s.ssh_port), self.settings.monitor_timeout)
            _apply_probe(s, result)
            await tx.session.flush()
            await tx.session.refresh(s)
            return server_to_dict(s, self._secret(s))

    async def sync(self, owner_id: str, sid: str) -> dict:
        """Сверить реальное состояние сервера (контейнеры/клиенты) с нашей БД по запросу."""
        from vpnhub.services.sync import SyncService  # noqa: PLC0415 — избегаем цикла import

        async with self.uow.query() as tx:
            await self._owned(tx, owner_id, sid)
        await SyncService(self.uow, self.settings).sync_server(sid)
        async with self.uow.query() as tx:
            s = await self._owned(tx, owner_id, sid)
            return server_to_dict(s, self._secret(s))

    async def check_and_sync(self, owner_id: str, sid: str) -> None:
        """Сразу после добавления сервера: пинг, и если онлайн — синхронизация состояния.

        Best-effort: сбой проверки/синка не должен ничего ломать (сервер может быть офлайн
        или недоступен по SSH) — просто логируем.
        """
        try:
            res = await self.check(owner_id, sid)
        except Exception as e:
            log.warning("post_create_check_failed", server_id=sid, error=str(e))
            return
        if res.get("status") != "online":
            return
        try:
            async with asyncio.timeout(POST_CREATE_SYNC_TIMEOUT):
                await self.sync(owner_id, sid)
        except Exception as e:  # включая TimeoutError — синк best-effort, создание сервера не ломаем
            log.warning("post_create_sync_failed", server_id=sid, error=str(e))

    async def run_tick(self) -> int:
        """Фоновая проверка всех серверов (вызывается планировщиком и на старте).

        Зонды выполняются вне транзакции и конкурентно (с ограничением семафором),
        затем результаты пишутся одной короткой транзакцией — чтобы не держать
        соединение к БД открытым на время сетевых таймаутов.
        """
        async with self.uow.query() as tx:
            targets = [(s.id, s.ip, _parse_port(s.ssh_port)) for s in await tx.servers.all()]
        if not targets:
            return 0

        timeout = self.settings.monitor_timeout
        sem = asyncio.Semaphore(max(1, self.settings.monitor_concurrency))

        async def run_one(sid: str, host: str, port: int) -> tuple[str, ProbeResult]:
            async with sem:
                try:
                    return sid, await probe_tcp(host, port, timeout)
                except Exception as e:  # одна сбойная проверка не должна ронять весь тик
                    log.warning("server_probe_failed", server_id=sid, error=str(e))
                    return sid, ProbeResult(False, None, "ошибка зонда")

        results = await asyncio.gather(*(run_one(sid, host, port) for sid, host, port in targets))

        changed = False
        async with self.uow.transaction() as tx:
            for sid, result in results:
                s = await tx.servers.get(sid)
                if s is not None:  # мог быть удалён между снимком и записью
                    prev = s.status
                    _apply_probe(s, result)
                    if s.status != prev:
                        changed = True
            await tx.session.flush()

        if changed:  # пуш только при смене статуса — не спамим шину каждый тик
            self.bus.publish(TOPIC_SERVER)

        online = sum(1 for _, r in results if r.ok)
        await self._update_metrics()  # прикладные гейджи для admin-дашборда (best-effort)
        online_ids = [sid for sid, r in results if r.ok]
        await self._collect_host_metrics(online_ids)  # per-server ресурсы (best-effort, не влияет на статус)
        log.info("server_monitor_tick", total=len(results), online=online, offline=len(results) - online)
        return len(results)

    async def _collect_host_metrics(self, online_ids: builtins.list[str]) -> None:
        """Собрать ресурсы хоста (CPU/RAM/диск/…) с онлайн-серверов отдельными SSH-сессиями.

        Строго best-effort: гоняется ПОСЛЕ записи статусов, каждый сервер изолирован (сбой одного не
        трогает остальных), общий сбой глотается — мониторинг online/offline от этого не зависит.
        """
        if not online_ids:
            return
        try:
            from vpnhub.services.hostmetrics import HostMetricsService  # noqa: PLC0415 — избегаем цикла import

            svc = HostMetricsService(self.uow, self.settings)
            async with self.uow.query() as tx:
                servers = [s for sid in online_ids if (s := await tx.servers.get(sid)) is not None]

            sem = asyncio.Semaphore(max(1, self.settings.monitor_concurrency))

            async def one(server: m.Server) -> None:
                async with sem:
                    try:
                        await svc.collect_for(server)
                    except Exception as e:  # изоляция: один сервер не роняет сбор остальных
                        log.warning("host_metrics_collect_failed", server_id=server.id, error=str(e))

            await asyncio.gather(*(one(s) for s in servers))
        except Exception:
            log.warning("host_metrics_tick_failed", exc_info=True)

    async def _update_metrics(self) -> None:
        """Обновить прикладные гейджи (серверы по статусу/latency, ошибки provisioning).

        Best-effort: сбой метрик не должен ронять мониторинг-тик.
        """
        try:
            async with self.uow.query() as tx:
                servers = await tx.servers.all()
                protocols = list(
                    (await tx.session.execute(select(m.ServerProtocol).where(m.ServerProtocol.state == "error")))
                    .scalars()
                    .all()
                )
            counts: dict[str, int] = {"online": 0, "offline": 0, "unknown": 0}
            latencies: list[int] = []
            for s in servers:
                counts[s.status] = counts.get(s.status, 0) + 1
                if s.status == "online" and s.latency_ms is not None:
                    latencies.append(s.latency_ms)
            avg = sum(latencies) / len(latencies) if latencies else None
            by_code: dict[str, int] = {}
            for p in protocols:
                code = p.error_code or "unknown"
                by_code[code] = by_code.get(code, 0) + 1
            metrics.set_server_gauges(counts, avg)
            metrics.set_provisioning_errors(by_code)
        except Exception:
            log.warning("server_metrics_update_failed", exc_info=True)

    async def vpn_op(
        self, owner_id: str, sid: str, vtype: str, op: str, protos: builtins.list[str] | None = None
    ) -> dict:
        if vtype not in VPN_TYPES:
            raise BadRequest("Неизвестный тип VPN")
        if op == "fix":
            return await self.apply_fix(owner_id, sid, vtype)
        if op not in ("install", "remove", "start", "stop"):
            raise BadRequest("Неизвестная операция")
        # все вендоры (amnezia/openvpn/outline/hysteria2) — реальный provisioning
        return await self._provisioned_op(owner_id, sid, vtype, op, protos)

    async def apply_fix(self, owner_id: str, sid: str, vtype: str) -> dict:
        """Автофикс ошибки установки вендора: устранить причину по SSH и переустановить.

        Работает только для kind="auto"-ошибок (см. remediation): подбираем подсказку по
        error_code/error первого сбойного протокола вендора, гоняем идемпотентный фикс-скрипт
        (если есть), затем запускаем обычную фоновую переустановку вендора.
        """
        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            s = await self._owned(tx, owner_id, sid)
            errored = next((p for p in s.protocols if p.vendor == vtype and p.state == "error"), None)
            if errored is None:
                raise BadRequest("Нет ошибки для исправления")
            rem = remediation.resolve(errored.error_code, errored.error)
            if rem is None or rem.kind != "auto" or rem.fix_id is None:
                raise BadRequest("Эту ошибку нельзя исправить автоматически")
            fix_id = rem.fix_id
        # SSH-фикс — вне транзакции (может занять время)
        try:
            await prov.run_fix(s, fix_id)
        except (SshError, ProvisioningError) as e:
            raise BadRequest(f"Не удалось выполнить исправление: {e}") from e
        # авто-переустановка вендора (как install): помечаем installing и уходим в фон
        async with self.uow.transaction() as tx:
            s = await self._owned(tx, owner_id, sid)
            await prov.mark_installing(tx, sid, vtype)
            await tx.session.flush()
            await tx.session.refresh(s)
            result = server_to_dict(s, self._secret(s))
        prov.schedule_install(sid, vtype)
        return result

    async def _provisioned_op(
        self, owner_id: str, sid: str, vendor: str, op: str, protos: builtins.list[str] | None = None
    ) -> dict:
        """Реальный provisioning вендора: install(фон, выбранные протоколы)/remove/start/stop."""
        prov = ProvisioningService(self.uow, self.settings)

        if op == "install":
            # выбранное подмножество протоколов вендора (пусто/None → все); докачка = install части
            proto_ids = ProvisioningService.resolve_proto_ids(vendor, protos)
            if not proto_ids:
                raise BadRequest("Не выбрано ни одного протокола для установки")
            async with self.uow.transaction() as tx:
                s = await self._owned(tx, owner_id, sid)
                vpn = next((v for v in s.vpns if v.type == vendor), None)
                if vpn is None:
                    vpn = m.ServerVpn(server_id=sid, type=vendor, port=DEFAULT_PORTS[vendor])
                    tx.session.add(vpn)
                await prov.mark_installing(tx, sid, vendor, proto_ids)
                await tx.session.flush()
                await tx.session.refresh(s)
                result = server_to_dict(s, self._secret(s))
            prov.schedule_install(sid, vendor, proto_ids)  # долгая установка — в фоне
            return result

        if op == "remove":
            async with self.uow.query() as tx:
                s = await self._owned(tx, owner_id, sid)
            await prov.remove_vendor(s, vendor)
            async with self.uow.transaction() as tx:
                s = await self._owned(tx, owner_id, sid)
                for sp in s.protocols:
                    if sp.vendor == vendor:
                        sp.state, sp.installed, sp.running = "absent", False, False
                vpn = next((v for v in s.vpns if v.type == vendor), None)
                if vpn:
                    vpn.installed = vpn.running = False
                # снять доступ групп и удалить выданные конфиги (контейнеры снесены — пиров нет)
                await tx.session.execute(
                    sa_delete(m.GroupServerAccess).where(
                        m.GroupServerAccess.server_id == sid, m.GroupServerAccess.vpn_type == vendor
                    )
                )
                await tx.session.execute(
                    sa_delete(m.DeviceConfig).where(m.DeviceConfig.server_id == sid, m.DeviceConfig.vpn_type == vendor)
                )
                await tx.session.flush()
                await tx.session.refresh(s)
                return server_to_dict(s, self._secret(s))

        # start / stop
        async with self.uow.query() as tx:
            s = await self._owned(tx, owner_id, sid)
            if s.status != "online":
                raise BadRequest("Сервер должен быть онлайн")
        try:
            await prov.lifecycle_vendor(s, vendor, op)
        except (SshError, ProvisioningError) as e:
            raise BadRequest(f"Не удалось выполнить операцию на сервере: {e}") from e
        async with self.uow.transaction() as tx:
            s = await self._owned(tx, owner_id, sid)
            running = op == "start"
            for sp in s.protocols:
                if sp.vendor == vendor and sp.installed:
                    sp.running = running
            vpn = next((v for v in s.vpns if v.type == vendor), None)
            if vpn:
                vpn.running = running
            await tx.session.flush()
            await tx.session.refresh(s)
            return server_to_dict(s, self._secret(s))

    async def protocol_op(self, owner_id: str, sid: str, proto_id: str, op: str) -> dict:
        """Операция над ОДНИМ протоколом: remove (снос+отзыв) / start / stop (свитчер контейнера)."""
        if proto_id not in pc.PROTOCOLS:
            raise BadRequest("Неизвестный протокол")
        if op == "remove":
            return await self.remove_protocol(owner_id, sid, proto_id)
        if op == "update":
            return await self.update_protocol(owner_id, sid, proto_id)
        if op not in ("start", "stop"):
            raise BadRequest("Неизвестная операция")
        return await self._lifecycle_protocol(owner_id, sid, proto_id, op)

    async def update_protocol(self, owner_id: str, sid: str, proto_id: str) -> dict:
        """Обновить серверный компонент протокола до эталонной версии релиза панели.

        Идемпотентная пересборка контейнера: install гоняет `docker build --no-cache --pull`,
        то есть тянет свежий образ/бинарник и пересоздаёт контейнер. Разрешаем только когда
        детект реально видит доступное обновление (иначе — no-op, не трогаем рабочий контейнер).

        ВАЖНО (см. tasks/04): пересоздание контейнера теряет заведённых внутри клиентов —
        их переустановку после rebuild выполняет фоновый sync-дренаж/reconcile не полностью.
        Полное сохранение клиентов при обновлении ведётся отдельно (registry/recreate) и
        размечено как remaining; здесь — безопасный скелет пересборки под явным флагом обновления.
        """
        if proto_id not in pc.PROTOCOLS:
            raise BadRequest("Неизвестный протокол")
        spec = pc.spec_by_id(proto_id)
        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.transaction() as tx:
            s = await self._owned(tx, owner_id, sid)
            if s.status != "online":
                raise BadRequest("Сервер должен быть онлайн")
            sp = next((p for p in s.protocols if p.proto == proto_id), None)
            if not sp or not sp.installed:
                raise BadRequest("Протокол не установлен")
            if not component_versions.update_available(proto_id, sp.image_version):
                raise BadRequest("Обновление недоступно: компонент уже актуальной версии")
            await prov.mark_installing(tx, sid, spec.vendor, (proto_id,))
            await tx.session.flush()
            await tx.session.refresh(s)
            result = server_to_dict(s, self._secret(s))
        prov.schedule_install(sid, spec.vendor, (proto_id,))  # rebuild --no-cache --pull → фон
        return result

    async def _lifecycle_protocol(self, owner_id: str, sid: str, proto_id: str, op: str) -> dict:
        """Временно остановить/снова запустить контейнер одного протокола (docker start/stop)."""
        spec = pc.spec_by_id(proto_id)
        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            s = await self._owned(tx, owner_id, sid)
            if s.status != "online":
                raise BadRequest("Сервер должен быть онлайн")
            sp = next((p for p in s.protocols if p.proto == proto_id), None)
            if not sp or not sp.installed:
                raise BadRequest("Протокол не установлен")
        try:
            await prov.lifecycle_protocol(s, proto_id, op)
        except (SshError, ProvisioningError) as e:
            raise BadRequest(f"Не удалось выполнить операцию на сервере: {e}") from e
        async with self.uow.transaction() as tx:
            s = await self._owned(tx, owner_id, sid)
            sp = next((p for p in s.protocols if p.proto == proto_id), None)
            if sp is not None:
                sp.running = op == "start"
            await ProvisioningService._refresh_vendor_flags(tx, sid, spec.vendor)
            await tx.session.flush()
            await tx.session.refresh(s)
            return server_to_dict(s, self._secret(s))

    async def set_protocol_params(
        self,
        owner_id: str,
        sid: str,
        proto_id: str,
        preset: str | None = None,
        values: dict[str, str] | None = None,
    ) -> dict:
        """Сменить obfuscation-параметры AmneziaWG: переписать живой awg0.conf по SSH + записать params_json.

        Порядок важен: сначала SSH-применение, затем запись в БД — при SSH-ошибке params_json не меняется
        (иначе рассинхрон сторон и все клиенты отвалятся). Пиры сохраняются (syncconf).
        """
        if proto_id not in pc.PROTOCOLS:
            raise BadRequest("Неизвестный протокол")
        spec = pc.spec_by_id(proto_id)
        if spec.kind != "wireguard":
            raise BadRequest("Параметры обфускации доступны только для AmneziaWG")

        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            s = await self._owned(tx, owner_id, sid)
            if s.status != "online":
                raise BadRequest("Сервер должен быть онлайн")
            sp = next((p for p in s.protocols if p.proto == proto_id), None)
            if not sp or not sp.installed or not sp.running:
                raise BadRequest("Протокол не установлен или остановлен")

            current = AwgParams.from_dict(json.loads(sp.params_json)) if sp.params_json else None
            if current is None:
                raise BadRequest("Нет текущих параметров обфускации")

            if preset == "default":
                fresh = AwgProvisioner.new_params(spec.is_awg2)
                # сохранить subnet/i-junk текущего сервера, обновить только obfuscation-поля
                target = awg_params.merge_editable(current, fresh.as_dict())
            elif preset in ("aggressive", "mobile"):
                target = awg_params.merge_editable(current, awg_params.PRESETS[preset])
            elif values:
                target = awg_params.merge_editable(current, values)
            else:
                raise BadRequest("Укажите preset или values")

        try:
            awg_params.validate(target, spec.is_awg2)
        except ProvisioningError as e:
            raise BadRequest(e.message) from e

        try:
            await prov.set_protocol_params(s, sp, target)
        except (SshError, ProvisioningError) as e:
            raise BadRequest(f"Не удалось применить параметры на сервере: {e}") from e

        async with self.uow.transaction() as tx:
            s = await self._owned(tx, owner_id, sid)
            sp2 = next((p for p in s.protocols if p.proto == proto_id), None)
            if sp2 is not None:
                sp2.params_json = json.dumps(target.as_dict())
            await tx.session.flush()
            await tx.session.refresh(s)
            return server_to_dict(s, self._secret(s))

    async def set_protocol_limit(self, owner_id: str, sid: str, proto_id: str, max_clients: int | None) -> dict:
        """Мягкий лимит числа конфигов на протоколе (панельный soft-cap; None = без лимита).

        Только запись в БД, без SSH/reprovision. Лимит меньше текущей занятости задать можно —
        это просто запретит выдавать НОВЫЕ конфиги; уже выданные не трогаются.
        """
        if proto_id not in pc.PROTOCOLS:
            raise BadRequest("Неизвестный протокол")
        async with self.uow.transaction() as tx:
            s = await self._owned(tx, owner_id, sid)
            sp = next((p for p in s.protocols if p.proto == proto_id), None)
            if sp is None:
                raise BadRequest("Протокол не установлен на сервере")
            sp.max_clients = max_clients if (max_clients is not None and max_clients > 0) else None
            await tx.session.flush()
            await tx.session.refresh(s)
            return server_to_dict(s, self._secret(s))

    async def set_reality(
        self,
        owner_id: str,
        sid: str,
        proto_id: str,
        *,
        rotate_short_id: bool = False,
        short_id: str | None = None,
        sni: str | None = None,
    ) -> dict:
        """Управление Xray-Reality: ротация shortId и/или смена SNI/dest с reprovision (рестарт контейнера).

        Порядок как у set_protocol_params: validate → SSH-применение → запись материала. При SSH-ошибке
        material_encrypted не меняется (иначе панель разойдётся с сервером). Клиенты (uuid) сохраняются.
        """
        if proto_id not in pc.PROTOCOLS:
            raise BadRequest("Неизвестный протокол")
        spec = pc.spec_by_id(proto_id)
        if spec.kind != "xray":
            raise BadRequest("Параметры Reality доступны только для Xray")

        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            s = await self._owned(tx, owner_id, sid)
            if s.status != "online":
                raise BadRequest("Сервер должен быть онлайн")
            sp = next((p for p in s.protocols if p.proto == proto_id), None)
            if not sp or not sp.installed or not sp.running:
                raise BadRequest("Протокол не установлен или остановлен")
            material = ServerMaterial.from_dict(prov._dec(sp.material_encrypted))

        try:
            if rotate_short_id:
                target_short_id = reality.gen_short_id()
            elif short_id is not None:
                target_short_id = reality.validate_short_id(short_id)
            else:
                target_short_id = material.short_id or reality.gen_short_id()
            target_sni = reality.validate_sni(sni) if sni is not None else (material.site or pc.XRAY_DEFAULT_SITE)
        except ProvisioningError as e:
            raise BadRequest(e.message) from e

        try:
            new_material = await prov.set_reality(s, sp, short_id=target_short_id, sni=target_sni)
        except (SshError, ProvisioningError) as e:
            raise BadRequest(f"Не удалось применить параметры Reality на сервере: {e}") from e

        async with self.uow.transaction() as tx:
            s = await self._owned(tx, owner_id, sid)
            sp2 = next((p for p in s.protocols if p.proto == proto_id), None)
            if sp2 is not None:
                sp2.material_encrypted = prov._enc(new_material.as_dict())
            await tx.session.flush()
            await tx.session.refresh(s)
            return server_to_dict(s, self._secret(s))

    async def remove_protocol(self, owner_id: str, sid: str, proto_id: str) -> dict:
        """Снять ОДИН протокол: снести контейнер + отозвать (удалить) выданные конфиги этого протокола.

        Групповой доступ (GroupServerAccess) — вендор-уровневый и остаётся, пока у вендора есть
        хоть один протокол; config-gen всё равно не отдаст конфиг по неустановленному протоколу.
        """
        if proto_id not in pc.PROTOCOLS:
            raise BadRequest("Неизвестный протокол")
        spec = pc.spec_by_id(proto_id)
        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            s = await self._owned(tx, owner_id, sid)
        await prov.remove_protocol(s, proto_id)  # docker rm контейнера (пиры уходят вместе с ним)
        async with self.uow.transaction() as tx:
            s = await self._owned(tx, owner_id, sid)
            sp = next((p for p in s.protocols if p.proto == proto_id), None)
            if sp is not None:
                sp.state, sp.installed, sp.running, sp.error, sp.error_code = "absent", False, False, None, None
            # отзыв конфигов: контейнер снесён → удаляем DeviceConfig этого протокола (server, vendor, label)
            await tx.session.execute(
                sa_delete(m.DeviceConfig).where(
                    m.DeviceConfig.server_id == sid,
                    m.DeviceConfig.vpn_type == spec.vendor,
                    m.DeviceConfig.proto == spec.label,
                )
            )
            await ProvisioningService._refresh_vendor_flags(tx, sid, spec.vendor)
            await tx.session.flush()
            await tx.session.refresh(s)
            return server_to_dict(s, self._secret(s))
