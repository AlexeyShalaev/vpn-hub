"""Синхронизация состояния серверов ↔ нашей БД (двунаправленно).

Сервер (контейнеры Amnezia + clientsTable/peers) — источник правды о реальном состоянии;
наша БД — зеркало + доменная модель (юзеры/устройства/доступы). Сверка ловит дрейф,
возникающий когда сервером управляют и через официальный клиент Amnezia:
- протокол удалён/остановлен на сервере → у нас installed/running/state обновятся;
- протокол установлен внешне → адаптируем (читаем ключи/параметры) и берём под управление;
- клиент отозван внешне → наш DeviceConfig помечается revoked;
- клиенты, заведённые внешне → считаются как external (не трогаем).

Безопасность: при недоступности SSH сервер пропускается целиком (никаких ложных revoke).
Протоколы в состоянии installing не трогаются (идёт фоновая установка).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select

from vpnhub.api.config import Settings
from vpnhub.common.retry import with_retries
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.events import TOPIC_SERVER, TOPIC_SYNC, EventBus, get_event_bus
from vpnhub.infra.provisioning import component_versions
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.provisioners.awg import AwgProvisioner
from vpnhub.infra.provisioning.provisioners.hysteria2 import HysteriaProvisioner
from vpnhub.infra.provisioning.provisioners.openvpn import OpenVpnProvisioner
from vpnhub.infra.provisioning.provisioners.outline import OutlineProvisioner
from vpnhub.infra.provisioning.provisioners.xray import XrayProvisioner
from vpnhub.infra.provisioning.script_runner import list_known_containers
from vpnhub.infra.provisioning.ssh import SshClient, SshError
from vpnhub.infra.security import encrypt_secret
from vpnhub.infra.uow import Uow
from vpnhub.services.provisioning import PROVISIONED_PROTO_IDS, PROVISIONED_VENDORS, ProvisioningService
from vpnhub.services.sync_logic import (
    ConfigRow,
    ProtocolObservation,
    desired_config_status,
    dump_pending,
    external_client_ids,
    parse_pending,
    plan_drain,
)
from vpnhub.services.traffic import PeerStat, TrafficCollector, TrafficService

log = structlog.get_logger()

# Сколько ждём идущую установку, прежде чем считать «installing» зависшим и сверять его.
# Фоновая asyncio-задача не переживает рестарт приложения — иначе протокол завис бы навсегда.
INSTALLING_GRACE_SECONDS = 600


class SyncService:
    def __init__(self, uow: Uow, settings: Settings, bus: EventBus | None = None) -> None:
        self.uow = uow
        self.settings = settings
        self.bus = bus or get_event_bus()  # realtime-сигналы (см. infra/events)

    async def sync_server(self, server_id: str) -> dict:
        prov = ProvisioningService(self.uow, self.settings)

        # ── фаза 1: снимок нашего состояния + провизионеры с материалом ──
        async with self.uow.query() as tx:
            server = await tx.servers.get(server_id)
            if not server:
                return {"server": server_id, "reachable": False, "error": "not found"}
            creds = prov.creds(server)
            now = datetime.now(UTC)
            # пропускаем только СВЕЖИЕ installing (идёт установка); зависшие — сверяем
            installing = {
                p.proto
                for p in server.protocols
                if p.state == "installing"
                and p.updated_at is not None
                and (now - p.updated_at).total_seconds() < INSTALLING_GRACE_SECONDS
            }
            provs = {}  # proto_id -> provisioner (с материалом, если есть)
            for p in server.protocols:
                if p.proto in pc.PROTOCOLS and p.material_encrypted:
                    provs[p.proto] = prov.loaded_provisioner(p)
            # долг на снятие (ledger): что обязаны снять на этом сервере по протоколам
            pending_by_proto = {
                p.proto: parse_pending(p.pending_revoke_json) for p in server.protocols if p.pending_revoke_json
            }

        # ── фаза 2: чтение реального состояния сервера по SSH (best-effort) ──
        adopted: dict[str, tuple[dict, str | None]] = {}
        observations: dict[str, ProtocolObservation] = {}
        drained_by_proto: dict[str, set[str]] = {}  # погашенный долг на снятие (для записи в фазе 3)
        traffic_by_proto: dict[str, list[PeerStat]] = {}  # собранная статистика трафика (best-effort)
        version_by_proto: dict[str, str] = {}  # версия бинарника компонента в контейнере (best-effort)
        try:
            async with SshClient(creds, connect_timeout=self.settings.monitor_timeout) as ssh:
                containers = await list_known_containers(ssh)
                for pid in PROVISIONED_PROTO_IDS:
                    if pid in installing:
                        continue  # не мешаем идущей установке
                    spec = pc.spec_by_id(pid)
                    present = spec.container in containers
                    running = containers.get(spec.container, False)
                    client_ids: set[str] = set()
                    readable = False
                    if present and running:
                        try:
                            provo = await self._ensure_provisioner(ssh, spec, provs.get(pid), adopted)
                            provs[pid] = provo
                            if spec.kind == "wireguard":
                                client_ids = await provo.list_peer_ids(ssh)
                            else:
                                client_ids = await provo.list_client_ids(ssh)
                            readable = True
                        except Exception as e:  # чтение клиентов не удалось — не рискуем revoke
                            log.warning("sync: read clients failed", server=server_id, proto=pid, error=str(e))
                        try:  # сбор трафика строго best-effort: НЕ влияет на решения sync/revoke
                            stats = await TrafficCollector.collect(ssh, spec)
                            if stats:
                                traffic_by_proto[pid] = stats
                        except Exception as e:
                            log.warning("sync: traffic collect failed", server=server_id, proto=pid, error=str(e))
                        try:  # версия компонента: best-effort, поддержано только для xray/hysteria2
                            ver = await component_versions.read_running_version(ssh, spec)
                            if ver:
                                version_by_proto[pid] = ver
                        except Exception as e:
                            log.warning("sync: version read failed", server=server_id, proto=pid, error=str(e))
                    obs = ProtocolObservation(pid, present, running, readable, client_ids)
                    observations[pid] = obs
                    # гасим долг на снятие для протокола в рамках уже открытой SSH-сессии
                    pending = pending_by_proto.get(pid)
                    if pending:
                        drained = await self._drain_pending(ssh, server_id, pid, pending, obs, provs.get(pid))
                        if drained:
                            drained_by_proto[pid] = drained
                            obs.client_ids -= drained  # снятые не считаем external в этом же тике
        except (SshError, OSError) as e:
            log.info("sync: server unreachable", server=server_id, error=str(e))
            return {"server": server_id, "reachable": False, "error": str(e)}

        # ── фаза 3: сверка и запись в БД ──
        result = await self._apply(server_id, installing, observations, adopted, drained_by_proto, version_by_proto)

        # ── фаза 4: запись сэмплов трафика ОТДЕЛЬНОЙ транзакцией (изолируем от sync-инвариантов) ──
        if traffic_by_proto:
            traffic = TrafficService(self.uow, self.settings)
            for pid, stats in traffic_by_proto.items():
                try:
                    await traffic.record(server_id, pid, stats)
                except Exception as e:  # запись статистики не должна ронять результат sync
                    log.warning("sync: traffic record failed", server=server_id, proto=pid, error=str(e))
        return result

    async def _drain_pending(
        self, ssh: SshClient, server_id: str, pid: str, pending: set[str], obs: ProtocolObservation, provo: Any
    ) -> set[str]:
        """Погасить долг на снятие для протокола → множество погашенных client_id.

        revoke идемпотентен (снятие отсутствующего — no-op), поэтому ретраи безопасны;
        снимаем только client_id из нашего ledger → внешних клиентов не трогаем.
        """
        to_revoke, drained = plan_drain(pending, obs)
        drained = set(drained)
        for cid in to_revoke:
            if provo is None:
                break  # нечем снимать (нет материала) — оставляем долг до следующего тика
            try:
                await with_retries(lambda cid=cid: provo.revoke_client(ssh, cid), retry_on=(SshError, OSError))  # type: ignore[misc]  # mypy не выводит тип default-параметра lambda
                drained.add(cid)
            except Exception as e:  # один сбойный клиент не роняет остальных; долг остаётся
                log.warning("sync: drain revoke failed", server=server_id, proto=pid, client=cid, error=str(e))
        if pending - drained:
            log.info("sync: revoke debt outstanding", server=server_id, proto=pid, remaining=len(pending - drained))
        return drained

    async def _ensure_provisioner(self, ssh: SshClient, spec: Any, existing: Any, adopted: Any) -> Any:
        """Вернуть провизионер с материалом; при отсутствии — адаптировать (прочитать с сервера)."""
        if existing is not None:
            return existing
        if spec.kind == "wireguard":
            material, params = await AwgProvisioner(spec).adopt(ssh)
            adopted[spec.id] = (material.as_dict(), json.dumps(params.as_dict()))
            return AwgProvisioner(spec, params=params, material=material)
        if spec.kind == "openvpn":
            material = await OpenVpnProvisioner(spec).adopt(ssh)
            adopted[spec.id] = (material.as_dict(), None)
            return OpenVpnProvisioner(spec, material=material)
        if spec.kind == "outline":
            material = await OutlineProvisioner(spec).adopt(ssh)
            adopted[spec.id] = (material.as_dict(), None)
            return OutlineProvisioner(spec, material=material)
        if spec.kind == "hysteria2":
            material = await HysteriaProvisioner(spec).adopt(ssh)
            adopted[spec.id] = (material.as_dict(), None)
            return HysteriaProvisioner(spec, material=material)
        material = await XrayProvisioner(spec).adopt(ssh)
        adopted[spec.id] = (material.as_dict(), None)
        return XrayProvisioner(spec, material=material)

    async def _apply(
        self,
        server_id: str,
        installing: set[str],
        observations: dict[str, ProtocolObservation],
        adopted: dict,
        drained_by_proto: dict[str, set[str]],
        version_by_proto: dict[str, str],
    ) -> dict:
        revoked = active = external = 0
        async with self.uow.transaction() as tx:
            server = await tx.servers.get(server_id)
            if not server:
                return {"server": server_id, "reachable": True, "error": "deleted mid-sync"}

            rows = list(
                (
                    await tx.session.execute(
                        select(m.DeviceConfig).where(
                            m.DeviceConfig.server_id == server_id,
                            m.DeviceConfig.vpn_type.in_(list(PROVISIONED_VENDORS)),
                        )
                    )
                )
                .scalars()
                .all()
            )
            our_ids_by_proto: dict[str, set[str]] = defaultdict(set)
            for c in rows:
                spec = pc.spec_by_label(c.proto or "")
                if spec and c.client_id:
                    our_ids_by_proto[spec.id].add(c.client_id)

            sp_by_proto = {p.proto: p for p in server.protocols}
            for pid, obs in observations.items():
                spec = pc.spec_by_id(pid)
                sp = sp_by_proto.get(pid)
                if obs.present:
                    if sp is None:
                        sp = m.ServerProtocol(
                            server_id=server_id, vendor=spec.vendor, proto=pid,
                            container=spec.container, port=spec.default_port,
                        )  # fmt: skip
                        tx.session.add(sp)
                        await tx.session.flush()
                    sp.installed = True
                    sp.running = obs.running
                    if pid in adopted:
                        material_dict, params_json = adopted[pid]
                        sp.material_encrypted = encrypt_secret(self.settings.secret_key, json.dumps(material_dict))
                        if params_json:
                            sp.params_json = params_json
                        sp.state = "installed"
                    else:
                        sp.state = "installed" if sp.material_encrypted else "external"
                    ext = external_client_ids(obs, our_ids_by_proto.get(pid, set()))
                    sp.external_clients = len(ext)
                    external += len(ext)
                    if pid in version_by_proto:  # прочитанную версию компонента сохраняем как есть
                        sp.image_version = version_by_proto[pid]
                elif sp is not None:
                    sp.installed = sp.running = False
                    sp.state = "absent"
                    sp.external_clients = 0

            # гасим погашенный долг на снятие: перечитываем из свежей строки и вычитаем только
            # снятое в этом тике → конкурентные enqueue (между фазой 1 и 3) не теряются
            for pid, drained in drained_by_proto.items():
                sp = sp_by_proto.get(pid)
                if sp is not None:
                    sp.pending_revoke_json = dump_pending(parse_pending(sp.pending_revoke_json) - drained)

            for c in rows:
                spec = pc.spec_by_label(c.proto or "")
                if not spec:
                    continue
                new = desired_config_status(ConfigRow(c.id, spec.id, c.client_id or ""), observations)
                if new and c.status != new:
                    c.status = new
                if (new or c.status) == "revoked":
                    revoked += 1
                elif (new or c.status) == "active":
                    active += 1

            for vendor in PROVISIONED_VENDORS:
                vpn = next((v for v in server.vpns if v.type == vendor), None)
                protos = [p for p in server.protocols if p.vendor == vendor]
                if vpn and protos:
                    vpn.installed = any(p.installed for p in protos)
                    vpn.running = any(p.running for p in protos)
            await tx.session.flush()

        return {
            "server": server_id,
            "reachable": True,
            "protocols": {pid: {"present": o.present, "running": o.running} for pid, o in observations.items()},
            "configs": {"active": active, "revoked": revoked},
            "external": external,
            "drained": sum(len(v) for v in drained_by_proto.values()),
        }

    async def run_tick(self) -> int:
        async with self.uow.query() as tx:
            ids = [s.id for s in await tx.servers.all()]
        done = 0
        for sid in ids:
            try:
                await self.sync_server(sid)
                done += 1
            except Exception as e:  # один сбойный сервер не должен ронять тик
                log.warning("sync tick: server failed", server=sid, error=str(e))
        if ids:
            log.info("sync tick", total=len(ids), done=done)
        if done:
            # сверка могла изменить installed/running/state и статусы конфигов — пуш сигнала.
            # Сигнал коарс-грейн (без id): фронт инвалидирует ["servers"] и активный ["server", id].
            self.bus.publish(TOPIC_SYNC)
            self.bus.publish(TOPIC_SERVER)
        return done
