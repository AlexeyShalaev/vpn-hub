"""Серверы и VPN-ПО.

Мониторинг (статус/латентность): TCP-зонд по SSH-порту (см. infra.probe).
Provisioning VPN-ПО — реальный, по SSH (см. services.provisioning / infra.provisioning).
"""

from __future__ import annotations

import asyncio
import time

import structlog
from sqlalchemy import delete as sa_delete

from vpnhub.api.config import Settings
from vpnhub.common.catalog import DEFAULT_PORTS
from vpnhub.common.net import is_valid_host
from vpnhub.common.serializers import server_to_dict
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.probe import ProbeResult, probe_tcp
from vpnhub.infra.provisioning import remediation
from vpnhub.infra.provisioning.errors import ProvisioningError
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
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

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

        async with self.uow.transaction() as tx:
            for sid, result in results:
                s = await tx.servers.get(sid)
                if s is not None:  # мог быть удалён между снимком и записью
                    _apply_probe(s, result)
            await tx.session.flush()

        online = sum(1 for _, r in results if r.ok)
        log.info("server_monitor_tick", total=len(results), online=online, offline=len(results) - online)
        return len(results)

    async def vpn_op(self, owner_id: str, sid: str, vtype: str, op: str) -> dict:
        if vtype not in VPN_TYPES:
            raise BadRequest("Неизвестный тип VPN")
        if op == "fix":
            return await self.apply_fix(owner_id, sid, vtype)
        if op not in ("install", "remove", "start", "stop"):
            raise BadRequest("Неизвестная операция")
        # все вендоры (amnezia/openvpn/outline) — реальный provisioning
        return await self._provisioned_op(owner_id, sid, vtype, op)

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

    async def _provisioned_op(self, owner_id: str, sid: str, vendor: str, op: str) -> dict:
        """Реальный provisioning вендора (amnezia/openvpn/outline): install(фон)/remove/start/stop."""
        prov = ProvisioningService(self.uow, self.settings)

        if op == "install":
            async with self.uow.transaction() as tx:
                s = await self._owned(tx, owner_id, sid)
                vpn = next((v for v in s.vpns if v.type == vendor), None)
                if vpn is None:
                    vpn = m.ServerVpn(server_id=sid, type=vendor, port=DEFAULT_PORTS[vendor])
                    tx.session.add(vpn)
                await prov.mark_installing(tx, sid, vendor)
                await tx.session.flush()
                await tx.session.refresh(s)
                result = server_to_dict(s, self._secret(s))
            prov.schedule_install(sid, vendor)  # долгая установка — в фоне
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
