"""Оркестрация реального provisioning Amnezia поверх infra/provisioning.

Связывает БД (ServerProtocol/DeviceConfig) и SSH-библиотеку: установка протоколов,
жизненный цикл контейнеров, проверка статуса, add/revoke клиентов и сборка артефактов.

Установка (3 контейнера, docker build --no-cache --pull) — минуты, поэтому запускается
фоновой задачей; состояние отражается в ServerProtocol.state (installing|installed|error).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Any

import structlog
from sqlalchemy import select

from vpnhub.api.config import Settings
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.events import TOPIC_SERVER, EventBus, get_event_bus
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning import errors, templates
from vpnhub.infra.provisioning.awg_params import AwgParams
from vpnhub.infra.provisioning.provisioners import ClientMaterial, ConfigArtifact, ServerMaterial
from vpnhub.infra.provisioning.provisioners.awg import AwgProvisioner
from vpnhub.infra.provisioning.provisioners.hysteria2 import HysteriaProvisioner
from vpnhub.infra.provisioning.provisioners.openvpn import OpenVpnProvisioner
from vpnhub.infra.provisioning.provisioners.outline import OutlineProvisioner
from vpnhub.infra.provisioning.provisioners.xray import XrayProvisioner
from vpnhub.infra.provisioning.remediation import FIXES
from vpnhub.infra.provisioning.script_runner import already_installed_containers, remove_container
from vpnhub.infra.provisioning.ssh import ServerCreds, SshClient, SshError
from vpnhub.infra.security import decrypt_secret, encrypt_secret
from vpnhub.infra.uow import Uow, UowTransaction

log = structlog.get_logger()

# протоколы по вендору — единый источник в constants.VENDOR_PROTOS
AMNEZIA_PROTO_IDS = pc.VENDOR_PROTOS[pc.VENDOR_AMNEZIA]
OPENVPN_PROTO_IDS = pc.VENDOR_PROTOS[pc.VENDOR_OPENVPN]
OUTLINE_PROTO_IDS = pc.VENDOR_PROTOS[pc.VENDOR_OUTLINE]
HYSTERIA2_PROTO_IDS = pc.VENDOR_PROTOS[pc.VENDOR_HYSTERIA2]
# все протоколы с реальным provisioning (для сверки/reconcile)
PROVISIONED_PROTO_IDS = AMNEZIA_PROTO_IDS + OPENVPN_PROTO_IDS + OUTLINE_PROTO_IDS + HYSTERIA2_PROTO_IDS
PROVISIONED_VENDORS = (pc.VENDOR_AMNEZIA, pc.VENDOR_OPENVPN, pc.VENDOR_OUTLINE, pc.VENDOR_HYSTERIA2)

# держим ссылки на фоновые задачи, чтобы их не собрал GC
_bg_tasks: set[asyncio.Task] = set()


def _spawn(coro: Any) -> None:
    task = asyncio.ensure_future(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


class ProvisioningService:
    def __init__(self, uow: Uow, settings: Settings, bus: EventBus | None = None) -> None:
        self.uow = uow
        self.settings = settings
        # шина realtime-сигналов: ad-hoc-конструкции (uow, settings) берут модульный синглтон,
        # DI прокидывает тот же инстанс — publisher и SSE-subscriber видят одну шину.
        self.bus = bus or get_event_bus()

    # ------------------------------------------------------------ helpers ---

    def creds(self, server: m.Server) -> ServerCreds:
        return ServerCreds(
            host=server.ip,
            port=int(server.ssh_port or 22),
            username=server.ssh_user or "root",
            auth=server.ssh_auth or "key",
            secret=decrypt_secret(self.settings.secret_key, server.ssh_secret_encrypted or ""),
        )

    def _enc(self, obj: dict) -> str:
        return encrypt_secret(self.settings.secret_key, json.dumps(obj))

    def _dec(self, token: str | None) -> dict:
        raw = decrypt_secret(self.settings.secret_key, token or "") if token else ""
        return json.loads(raw) if raw else {}

    def loaded_provisioner(
        self, sp: m.ServerProtocol
    ) -> AwgProvisioner | XrayProvisioner | OpenVpnProvisioner | OutlineProvisioner | HysteriaProvisioner:
        spec = pc.spec_by_id(sp.proto)
        material = ServerMaterial.from_dict(self._dec(sp.material_encrypted))
        if spec.kind == "xray":
            return XrayProvisioner(spec, material=material)
        if spec.kind == "openvpn":
            return OpenVpnProvisioner(spec, material=material)
        if spec.kind == "outline":
            return OutlineProvisioner(spec, material=material)
        if spec.kind == "hysteria2":
            return HysteriaProvisioner(spec, material=material)
        params = AwgParams.from_dict(json.loads(sp.params_json)) if sp.params_json else None
        return AwgProvisioner(spec, params=params, material=material)

    @staticmethod
    async def _get_sp(tx: UowTransaction, server_id: str, proto_id: str) -> m.ServerProtocol | None:
        res = await tx.session.execute(
            select(m.ServerProtocol).where(m.ServerProtocol.server_id == server_id, m.ServerProtocol.proto == proto_id)
        )
        return res.scalar_one_or_none()

    async def _get_or_create_sp(self, tx: UowTransaction, server_id: str, proto_id: str) -> m.ServerProtocol:
        sp = await self._get_sp(tx, server_id, proto_id)
        if sp is None:
            spec = pc.spec_by_id(proto_id)
            sp = m.ServerProtocol(
                server_id=server_id,
                vendor=spec.vendor,
                proto=proto_id,
                container=spec.container,
                port=spec.default_port,
                state="absent",
            )
            tx.session.add(sp)
            await tx.session.flush()
        return sp

    @staticmethod
    async def _refresh_vendor_flags(tx: UowTransaction, server_id: str, vendor: str) -> None:
        """Свести ServerVpn(vendor).installed/running из per-protocol состояния (any)."""
        server = await tx.servers.get(server_id)
        if not server:
            return
        protos = [p for p in server.protocols if p.vendor == vendor]
        vpn = next((v for v in server.vpns if v.type == vendor), None)
        if vpn:
            vpn.installed = any(p.installed for p in protos)
            vpn.running = any(p.running for p in protos)

    # -------------------------------------------------- install (фоново) ---

    @staticmethod
    def resolve_proto_ids(vendor: str, proto_ids: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
        """Подмножество протоколов вендора в каталожном порядке; None/пусто → все протоколы вендора."""
        allowed = pc.VENDOR_PROTOS[vendor]
        if not proto_ids:
            return allowed
        wanted = set(proto_ids)
        return tuple(p for p in allowed if p in wanted)

    async def mark_installing(
        self, tx: UowTransaction, server_id: str, vendor: str, proto_ids: tuple[str, ...] | list[str] | None = None
    ) -> None:
        """Пометить выбранные протоколы вендора как installing (перед фоновой установкой; None → все)."""
        for proto_id in self.resolve_proto_ids(vendor, proto_ids):
            sp = await self._get_or_create_sp(tx, server_id, proto_id)
            sp.state, sp.error, sp.error_code, sp.installed, sp.running = "installing", None, None, False, False

    def schedule_install(
        self, server_id: str, vendor: str, proto_ids: tuple[str, ...] | list[str] | None = None
    ) -> None:
        _spawn(self._install_vendor(server_id, vendor, tuple(proto_ids) if proto_ids else None))

    async def _install_vendor(self, server_id: str, vendor: str, proto_ids: tuple[str, ...] | None = None) -> None:
        async with self.uow.query() as tx:
            server = await tx.servers.get(server_id)
            if not server:
                return
            creds = self.creds(server)
            server_ip, server_name = server.ip, server.name

        for proto_id in self.resolve_proto_ids(vendor, proto_ids):
            await self._install_one(server_id, proto_id, creds, server_ip, server_name)

        async with self.uow.transaction() as tx:
            await self._refresh_vendor_flags(tx, server_id, vendor)

    async def _install_one(self, server_id: str, proto_id: str, creds: ServerCreds, server_ip: str, name: str) -> None:
        spec = pc.spec_by_id(proto_id)
        params = AwgProvisioner.new_params(spec.is_awg2) if spec.kind == "wireguard" else None
        try:
            async with SshClient(creds) as ssh:
                if spec.kind == "wireguard":
                    material = await AwgProvisioner(spec, params=params).install(ssh, server_ip, spec.default_port)
                elif spec.kind == "openvpn":
                    material = await OpenVpnProvisioner(spec).install(ssh, server_ip, spec.default_port)
                elif spec.kind == "outline":
                    material = await OutlineProvisioner(spec).install(ssh, server_ip, spec.default_port)
                elif spec.kind == "hysteria2":
                    material = await HysteriaProvisioner(spec).install(ssh, server_ip, spec.default_port)
                else:
                    material = await XrayProvisioner(spec).install(
                        ssh, server_ip, spec.default_port, pc.XRAY_DEFAULT_SITE
                    )
            async with self.uow.transaction() as tx:
                sp = await self._get_or_create_sp(tx, server_id, proto_id)
                sp.state, sp.installed, sp.running, sp.error, sp.error_code = "installed", True, True, None, None
                sp.container, sp.port = spec.container, spec.default_port
                sp.material_encrypted = self._enc(material.as_dict())
                if params is not None:
                    sp.params_json = json.dumps(params.as_dict())
                await self._refresh_vendor_flags(tx, server_id, spec.vendor)  # видно сразу, не дожидаясь всех
            self.bus.publish(TOPIC_SERVER, server_id)  # пуш: прогресс установки виден без поллинга
            log.info("protocol installed", server=server_id, proto=proto_id)
        except Exception as e:  # фоновая задача: любая ошибка → error-состояние, не роняем loop
            # стабильный код для движка подсказок: ProvisioningError.code, ssh — для транспортных сбоев
            code = getattr(e, "code", None) or ("ssh" if isinstance(e, SshError) else "internal")
            async with self.uow.transaction() as tx:
                sp = await self._get_or_create_sp(tx, server_id, proto_id)
                sp.state, sp.installed, sp.running, sp.error, sp.error_code = "error", False, False, str(e), code
                await self._refresh_vendor_flags(tx, server_id, spec.vendor)
            self.bus.publish(TOPIC_SERVER, server_id)  # пуш: ошибка видна без ожидания поллинга
            log.warning("protocol install failed", server=server_id, proto=proto_id, error=str(e))

    # ------------------------------------------------ remove / lifecycle ---

    async def remove_vendor(self, server: m.Server, vendor: str) -> None:
        """Снести контейнеры всех протоколов вендора (best-effort)."""
        await self._remove_containers(server, pc.VENDOR_PROTOS[vendor], vendor_cleanup=vendor)

    async def remove_protocol(self, server: m.Server, proto_id: str) -> None:
        """Снести контейнер ОДНОГО протокола (best-effort). Пиры уходят вместе с контейнером."""
        spec = pc.spec_by_id(proto_id)
        # для одно-протокольных вендоров (outline) снос протокола = снос вендора (чистим и состояние)
        cleanup = spec.vendor if pc.VENDOR_PROTOS[spec.vendor] == (proto_id,) else None
        await self._remove_containers(server, (proto_id,), vendor_cleanup=cleanup)

    async def _remove_containers(
        self, server: m.Server, proto_ids: tuple[str, ...], *, vendor_cleanup: str | None
    ) -> None:
        creds = self.creds(server)
        try:
            async with SshClient(creds) as ssh:
                for proto_id in proto_ids:
                    spec = pc.spec_by_id(proto_id)
                    await remove_container(ssh, {"$CONTAINER_NAME": spec.container})
                if vendor_cleanup == pc.VENDOR_OUTLINE:
                    # у Outline состояние (ключи) — на хостовом томе, а не в контейнере; чистим для
                    # честного reinstall. Заодно гасим watchtower (следит только за Outline-метками).
                    state_dir = pc.OUTLINE.outline_state_dir
                    await ssh.run("sudo docker rm -f watchtower 2>/dev/null || true")
                    await ssh.run(f"sudo rm -rf {state_dir} 2>/dev/null || true")
        except SshError as e:
            log.warning("container remove failed", server=server.id, protos=proto_ids, error=str(e))

    async def run_fix(self, server: m.Server, fix_id: str) -> None:
        """Выполнить идемпотентный фикс-скрипт по SSH перед авто-переустановкой.

        fix_id="reinstall" (или неизвестный) — пред-скрипт не нужен, чистит переустановка.
        Иначе гоняем scripts/<fix.script> и проверяем маркер успеха в объединённом выводе.
        """
        fx = FIXES.get(fix_id)
        if fx is None:  # reinstall-only
            return
        try:
            async with SshClient(self.creds(server)) as ssh:
                out = (await ssh.run_script(templates.load_shared(fx.script))).output
        except SshError as e:
            raise errors.make("ssh", str(e)) from e
        if fx.ok_marker not in out:
            raise errors.make("internal", fx.fail_hint)

    async def lifecycle_vendor(self, server: m.Server, vendor: str, op: str) -> None:
        """op ∈ {start, stop} — docker start/stop контейнеров протоколов вендора.

        Толерантно к отсутствующим контейнерам (при пер-протокольной установке часть протоколов
        вендора может быть не установлена) — несуществующий контейнер не роняет операцию.
        """
        creds = self.creds(server)
        async with SshClient(creds) as ssh:
            for proto_id in pc.VENDOR_PROTOS[vendor]:
                spec = pc.spec_by_id(proto_id)
                await ssh.run(f"sudo docker {op} {spec.container} 2>/dev/null || true")

    async def lifecycle_protocol(self, server: m.Server, proto_id: str, op: str) -> None:
        """op ∈ {start, stop} — docker start/stop контейнера ОДНОГО протокола (свитчер).

        Контейнер должен существовать (вызывается только для installed-протокола), поэтому строго —
        сбой поднимаем наверх, чтобы UI показал ошибку.
        """
        spec = pc.spec_by_id(proto_id)
        creds = self.creds(server)
        async with SshClient(creds) as ssh:
            await ssh.run(f"sudo docker {op} {spec.container}")

    async def set_protocol_params(self, server: m.Server, sp: m.ServerProtocol, new_params: AwgParams) -> None:
        """Применить новые obfuscation-параметры к живому awg0.conf по SSH (syncconf сохраняет пиров)."""
        creds = self.creds(server)
        async with SshClient(creds) as ssh:
            prov = self.loaded_provisioner(sp)
            if not isinstance(prov, AwgProvisioner):
                raise errors.make("internal", "set_protocol_params вызван для не-AWG протокола")
            await prov.set_params(ssh, new_params)

    async def set_reality(self, server: m.Server, sp: m.ServerProtocol, *, short_id: str, sni: str) -> ServerMaterial:
        """Применить новые shortId/SNI к живому server.json по SSH + рестарт; вернуть обновлённый материал."""
        creds = self.creds(server)
        async with SshClient(creds) as ssh:
            prov = self.loaded_provisioner(sp)
            if not isinstance(prov, XrayProvisioner):
                raise errors.make("internal", "set_reality вызван для не-Xray протокола")
            return await prov.set_reality(ssh, short_id=short_id, sni=sni)

    async def set_chain(
        self,
        entry_server: m.Server,
        entry_sp: m.ServerProtocol,
        *,
        exit_host: str,
        exit_port: str,
        exit_material: ServerMaterial,
        exit_uuid: str,
    ) -> None:
        """Мультихоп: направить outbound entry-контейнера на exit-сервер (vless+Reality) по SSH.

        `exit_uuid` — клиентский uuid, заведённый на exit через add_client: entry предъявляет его
        как обычный vless-клиент exit. Материал exit (pubkey/shortId/SNI) — из ServerProtocol exit.
        """
        prov = self.loaded_provisioner(entry_sp)
        if not isinstance(prov, XrayProvisioner):
            raise errors.make("internal", "set_chain вызван для не-Xray протокола")
        async with SshClient(self.creds(entry_server)) as ssh:
            await prov.set_outbound_chain(
                ssh,
                exit_host=exit_host,
                exit_port=exit_port,
                exit_public_key=exit_material.xray_public_key,
                exit_short_id=exit_material.short_id,
                exit_sni=exit_material.site or pc.XRAY_DEFAULT_SITE,
                exit_uuid=exit_uuid,
            )

    async def clear_chain(self, entry_server: m.Server, entry_sp: m.ServerProtocol) -> None:
        """Снять мультихоп: вернуть outbound entry-контейнера к прямому freedom по SSH."""
        prov = self.loaded_provisioner(entry_sp)
        if not isinstance(prov, XrayProvisioner):
            raise errors.make("internal", "clear_chain вызван для не-Xray протокола")
        async with SshClient(self.creds(entry_server)) as ssh:
            await prov.clear_outbound_chain(ssh)

    async def check_server(self, server: m.Server) -> tuple[bool, int | None, dict[str, str]]:
        """Реальная проверка: (online, latency_ms, {container: port}) через docker ps по SSH."""
        creds = self.creds(server)
        started = time.monotonic()
        try:
            async with SshClient(creds, connect_timeout=self.settings.monitor_timeout) as ssh:
                running = await already_installed_containers(ssh)
        except (SshError, OSError) as e:
            log.info("server check offline", server=server.id, error=str(e))
            return False, None, {}
        else:
            latency = int((time.monotonic() - started) * 1000)
            return True, latency, running

    # ---------------------------------------------------- клиентские ops ---

    async def add_client(self, server: m.Server, sp: m.ServerProtocol, name: str) -> ClientMaterial:
        prov = self.loaded_provisioner(sp)
        async with SshClient(self.creds(server)) as ssh:
            return await prov.add_client(ssh, server.ip, sp.port, name)

    async def revoke_client(self, server: m.Server, sp: m.ServerProtocol, client_id: str) -> None:
        prov = self.loaded_provisioner(sp)
        async with SshClient(self.creds(server)) as ssh:
            await prov.revoke_client(ssh, client_id)

    def build_artifact(self, server: m.Server, sp: m.ServerProtocol, client: ClientMaterial) -> ConfigArtifact:
        prov = self.loaded_provisioner(sp)
        return prov.build_artifact(server_ip=server.ip, port=sp.port, server_name=server.name, client=client)

    # -------------------------------------------------- revoke / reconcile ---

    async def revoke_on_servers(self, refs: list[tuple[str, str, str]]) -> None:
        """Снять клиентов на серверах (best-effort). refs = [(server_id, proto_label, client_id)].

        Работает для любого provisioned-протокола (amnezia/openvpn) с непустым client_id;
        группируется по серверу (одна SSH-сессия на сервер). Провизионер выбирается по
        proto_label (spec_by_label). DB не трогаем — удаление строк DeviceConfig на совести вызывающего.
        """
        by_server: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for server_id, proto_label, client_id in refs:
            if client_id:
                by_server[server_id].append((proto_label, client_id))

        for server_id, items in by_server.items():
            async with self.uow.query() as tx:
                server = await tx.servers.get(server_id)
                if not server:
                    continue
                creds = self.creds(server)
                jobs = []  # (provisioner, client_id)
                for proto_label, client_id in items:
                    spec = pc.spec_by_label(proto_label)
                    if not spec:
                        continue
                    sp = await self._get_sp(tx, server_id, spec.id)
                    if sp and sp.installed and sp.material_encrypted:
                        jobs.append((self.loaded_provisioner(sp), client_id))
            if not jobs:
                continue
            try:
                async with SshClient(creds) as ssh:
                    for prov_obj, client_id in jobs:
                        try:
                            await prov_obj.revoke_client(ssh, client_id)
                        except Exception as e:  # один сбойный клиент не должен ронять остальных
                            log.warning("revoke client failed", server=server_id, client=client_id, error=str(e))
            except SshError as e:
                log.warning("revoke: ssh unavailable", server=server_id, error=str(e))

    async def reconcile_user(self, user_id: str) -> None:
        """Снять и удалить provisioned-конфиги (amnezia/openvpn) пользователя, к которым он потерял доступ."""
        from vpnhub.services.access import effective_access  # noqa: PLC0415 — локальный импорт: избегаем цикла

        async with self.uow.query() as tx:
            access, _ = await effective_access(tx, user_id)
            drop: list[tuple[str, str, str, str]] = []  # (config_id, server_id, proto_label, client_id)
            for d in await tx.devices.for_user(user_id):
                for c in d.configs:
                    if c.vpn_type not in PROVISIONED_VENDORS or not c.client_id:
                        continue
                    if c.vpn_type not in access.get(c.server_id, set()):
                        drop.append((c.id, c.server_id, c.proto or "", c.client_id))
        if not drop:
            return
        await self.revoke_on_servers([(sid, proto, cid) for _cfg, sid, proto, cid in drop])
        async with self.uow.transaction() as tx:
            for cfg_id, *_rest in drop:
                obj = await tx.session.get(m.DeviceConfig, cfg_id)
                if obj is not None:
                    await tx.session.delete(obj)

    async def reconcile_users(self, user_ids: list[str]) -> None:
        for uid in {u for u in user_ids if u}:
            await self.reconcile_user(uid)

    # ---- suspend / resume по лимиту трафика (Этап 3b) ---------------------------

    def material_from_config(self, c: m.DeviceConfig) -> ClientMaterial:
        """Восстановить клиентский материал из DeviceConfig (с расшифровкой секрета)."""
        priv = decrypt_secret(self.settings.secret_key, c.client_secret_encrypted) if c.client_secret_encrypted else ""
        return ClientMaterial(
            client_id=c.client_id or "",
            client_private_key=priv,
            client_public_key=c.client_public_key or "",
            client_ip=c.client_ip or "",
        )

    async def _apply_client_state(self, refs: list[tuple[str, str, ClientMaterial]], *, suspend: bool) -> set[str]:
        """suspend/resume клиентов на серверах (best-effort, одна SSH-сессия на сервер).

        refs = [(server_id, proto_label, material)]. Возвращает множество client_id, для которых
        операция реально применилась (SSH прошёл) — вызывающий по нему обновляет статус в БД.
        """
        by_server: dict[str, list[tuple[str, ClientMaterial]]] = defaultdict(list)
        for server_id, proto_label, mat in refs:
            if mat.client_id:
                by_server[server_id].append((proto_label, mat))
        done: set[str] = set()
        for server_id, items in by_server.items():
            async with self.uow.query() as tx:
                server = await tx.servers.get(server_id)
                if not server:
                    continue
                creds = self.creds(server)
                jobs = []  # (provisioner, material)
                for proto_label, mat in items:
                    spec = pc.spec_by_label(proto_label)
                    if not spec:
                        continue
                    sp = await self._get_sp(tx, server_id, spec.id)
                    if sp and sp.installed and sp.material_encrypted:
                        jobs.append((self.loaded_provisioner(sp), mat))
            if not jobs:
                continue
            try:
                async with SshClient(creds) as ssh:
                    for prov_obj, mat in jobs:
                        try:
                            if suspend:
                                await prov_obj.suspend_client(ssh, mat)
                            else:
                                await prov_obj.resume_client(ssh, mat)
                            done.add(mat.client_id)
                        except Exception as e:  # один сбойный клиент не роняет остальных
                            op = "suspend" if suspend else "resume"
                            log.warning(f"{op} client failed", server=server_id, client=mat.client_id, error=str(e))
            except SshError as e:
                op = "suspend" if suspend else "resume"
                log.warning(f"{op}: ssh unavailable", server=server_id, error=str(e))
        return done

    async def suspend_configs(self, refs: list[tuple[str, str, ClientMaterial]]) -> set[str]:
        return await self._apply_client_state(refs, suspend=True)

    async def resume_configs(self, refs: list[tuple[str, str, ClientMaterial]]) -> set[str]:
        return await self._apply_client_state(refs, suspend=False)
