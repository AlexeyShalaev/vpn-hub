"""Синтетический demo-seed для скриншотов документации VPN Hub.

Наполняет ЧИСТУЮ (после alembic upgrade head) БД правдоподобными, но полностью
ВЫМЫШЛЕННЫМИ данными: пользователи, серверы, протоколы, устройства, группы, финансы,
временные ряды трафика/метрик — чтобы каждый экран рендерился «живым».

Никаких реальных данных: IP из TEST-NET (203.0.113.0/24), телефоны из выделенного
диапазона, фейковые ключи. Креды шифруются эффективным data-ключом = data_secret(master)
из backend/.env — тем же, что использует запущенный бэкенд, чтобы экраны конфигов не падали.

Запуск:  cd backend && DATABASE_URL=<demo> uv run python /path/seed_demo.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import random
import time
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from vpnhub.api.config import get_settings
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.security import data_secret, encrypt_secret, hash_password, normalize_phone
from vpnhub.services.limits import period_start

NOW = time.time()
DAY = 86400.0
HOUR = 3600.0
RND = random.Random(20260712)

S = get_settings()
# эффективный ключ шифрования секретов = тот же, что выведет бэкенд из мастер-ключа .env
SECRET = data_secret(S.master_key) if S.master_key else S.secret_key


# ----------------------------------------------------------------------------- helpers
def _b64(nbytes: int) -> str:
    return base64.b64encode(bytes(RND.getrandbits(8) for _ in range(nbytes))).decode()


def _b64url(nbytes: int) -> str:
    return base64.urlsafe_b64encode(bytes(RND.getrandbits(8) for _ in range(nbytes))).decode().rstrip("=")


def _hex(nbytes: int) -> str:
    return "".join(f"{RND.getrandbits(8):02x}" for _ in range(nbytes))


def _uuid() -> str:
    return str(uuid.UUID(int=RND.getrandbits(128)))


def _enc(payload: dict) -> str:
    return encrypt_secret(SECRET, json.dumps(payload))


def diurnal(t: float, peak_hour: float = 21.0) -> float:
    """Суточный коэффициент 0.2..1.0 с пиком вечером (peak_hour) и провалом ночью."""
    hod = (t % DAY) / HOUR
    ang = (hod - peak_hour) / 24.0 * 2 * math.pi
    return 0.25 + 0.75 * (0.5 * (1 + math.cos(ang)))


def server_material(protos: list[str]) -> str:
    """ServerMaterial JSON с фейковыми, но well-formed ключами под нужные протоколы."""
    mat: dict[str, str] = {}
    if any(p in ("awg", "awg_legacy") for p in protos):
        mat["server_public_key"] = _b64(32)
        mat["psk"] = _b64(32)
    if any(p in ("xray", "xray_xhttp") for p in protos):
        mat["xray_public_key"] = _b64url(32)
        mat["short_id"] = _hex(4)
        mat["bootstrap_uuid"] = _uuid()
        mat["site"] = "www.googletagmanager.com"
    if "xray_xhttp" in protos:
        mat["xhttp_path"] = "/" + _hex(4)
    if "hysteria2" in protos:
        mat["hysteria_obfs_password"] = _b64(16)
        mat["hysteria_cert_sha256"] = ":".join(_hex(1) for _ in range(32))
    if "outline" in protos:
        mat["outline_api_url"] = f"https://203.0.113.14:12345/{_hex(8)}"
        mat["outline_cert_sha256"] = _hex(32)
    if "openvpn" in protos:
        mat["ca_cert"] = "-----BEGIN CERTIFICATE-----\n" + _b64(48) + "\n-----END CERTIFICATE-----"
        mat["ta_key"] = _b64(64)
        mat["transport"] = "udp"
    return _enc(mat)


PORTS = {"awg": "55424", "awg_legacy": "55425", "xray": "443", "xray_xhttp": "2087",
         "openvpn": "1194", "outline": "8443", "hysteria2": "443"}
CONTAINERS = {"awg": "amnezia-awg2", "awg_legacy": "amnezia-awg", "xray": "amnezia-xray",
              "xray_xhttp": "amnezia-xray-xhttp", "openvpn": "amnezia-openvpn",
              "outline": "shadowbox", "hysteria2": "amnezia-hysteria2"}
VENDOR = {"awg": "amnezia", "awg_legacy": "amnezia", "xray": "amnezia", "xray_xhttp": "amnezia",
          "openvpn": "openvpn", "outline": "outline", "hysteria2": "hysteria2"}
IS_WG = {"awg", "awg_legacy"}
IS_XRAY = {"xray", "xray_xhttp"}


# ----------------------------------------------------------------------------- scenario
# (name, provider, ip, location, status, latency, quota_bytes|None, billing_day, protos, err_proto|None)
GB = 1024 ** 3
TB = 1024 ** 4
# id-слаги детерминированы (не uuid4) — чтобы URL в capture.mjs были стабильны между ре-сидами
SERVERS = [
    ("demo-ams", "Амстердам-1", "FirstByte", "203.0.113.11", "Нидерланды (Амстердам)", "online", 32, 2 * TB, 1,
     ["awg", "xray", "openvpn"], None),
    ("demo-fra", "Франкфурт-1", "UltaHost", "203.0.113.12", "Германия (Франкфурт)", "online", 41, 5 * TB, 5,
     ["awg", "xray_xhttp", "hysteria2"], None),
    ("demo-hel", "Хельсинки-1", "62YUN", "203.0.113.13", "Финляндия (Хельсинки)", "online", 27, None, 10,
     ["awg", "xray"], None),
    ("demo-nyc", "Нью-Йорк-1", "ISHOSTING", "203.0.113.14", "США (Нью-Йорк)", "online", 96, 3 * TB, 15,
     ["outline", "awg"], None),
    ("demo-sgp", "Сингапур-1", "Serverspace", "203.0.113.15", "Сингапур", "offline", None, 1 * TB, 20,
     ["awg"], None),
    ("demo-msk", "Москва-1", "FirstByte", "203.0.113.16", "Россия (Москва)", "online", 12, 10 * TB, 1,
     ["xray", "hysteria2"], "hysteria2"),
]

# (name, phone, status, admin)
USERS = [
    ("Алексей Смирнов", "+79990000101", "active", True),   # владелец+админ, основной вход
    ("Мария Иванова", "+79990000102", "active", False),
    ("Дмитрий Козлов", "+79990000103", "active", False),
    ("Ольга Петрова", "+79990000104", "active", False),
    ("Иван Соколов", "+79990000105", "pending", False),
    ("Пётр Морозов", "+79990000106", "blocked", False),
]

PLATFORMS = ["ios", "android", "mac", "windows", "linux", "router"]
CURRENCY_BY_PROVIDER = {"FirstByte": "RUB", "62YUN": "RUB", "UltaHost": "USD",
                        "ISHOSTING": "USD", "Serverspace": "EUR"}
PRICE_BY_PROVIDER = {"FirstByte": 490, "62YUN": 350, "UltaHost": 9, "ISHOSTING": 12, "Serverspace": 8}


async def main() -> None:
    engine = create_async_engine(S.async_dsn)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as db:
        # --- users ---
        users: list[m.User] = []
        for i, (name, phone, status, is_admin) in enumerate(USERS):
            u = m.User(phone=normalize_phone(phone), name=name,
                       password_hash=hash_password("DemoPass123!"), status=status)
            db.add(u)
            await db.flush()
            if is_admin:
                db.add(m.Admin(user_id=u.id))
            # активная сессия (для экрана Профиль)
            db.add(m.Session(id=uuid.uuid4().hex, subject_kind="user", subject_id=u.id,
                             expires_at=NOW + 30 * DAY, ip=f"198.51.100.{20 + i}",
                             user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/17.4"))
            users.append(u)
        owner = users[0]
        await db.flush()

        # --- servers + vpns + protocols + prices ---
        servers: list[m.Server] = []
        sp_index: dict[tuple[str, str], m.ServerProtocol] = {}
        for (sid_slug, name, prov, ip, loc, status, lat, quota, bday, protos, err_proto) in SERVERS:
            srv = m.Server(id=sid_slug, owner_user_id=owner.id, name=name, provider=prov, ip=ip,
                           ssh_user="root", ssh_port="22", ssh_auth="key",
                           ssh_secret_encrypted=_enc({"private_key": "FAKE-DEMO-KEY-" + _hex(8)}),
                           location=loc, status=status, latency_ms=lat,
                           last_check_at=NOW - RND.uniform(30, 180),
                           bandwidth_quota_bytes=quota, billing_day=bday,
                           provider_metadata={"plan": f"{prov} VPS", "source": "demo"})
            db.add(srv)
            await db.flush()
            servers.append(srv)

            vendors = {VENDOR[p] for p in protos}
            for v in vendors:
                vport = PORTS[next(p for p in protos if VENDOR[p] == v)]
                db.add(m.ServerVpn(server_id=srv.id, type=v, installed=True,
                                   running=(status == "online"), port=vport))
            for p in protos:
                is_err = (p == err_proto)
                sp = m.ServerProtocol(
                    server_id=srv.id, vendor=VENDOR[p], proto=p, container=CONTAINERS[p], port=PORTS[p],
                    state="error" if is_err else ("installed" if status != "offline" else "installed"),
                    installed=True, running=(status == "online" and not is_err),
                    error="Контейнер hysteria2 не запустился: порт занят" if is_err else None,
                    error_code="docker_service_not_running" if is_err else None,
                    external_clients=RND.randint(0, 2) if p in IS_WG else 0,
                    max_clients=(50 if p in IS_WG else None),
                    image_version=("25.9.11" if p in IS_XRAY else ("2.6.2" if p == "hysteria2" else None)),
                    material_encrypted=server_material([p]),
                    params_json=None,
                    traffic_collected_at=(NOW - RND.uniform(60, 300)) if (status == "online" and not is_err) else None,
                    traffic_status="ok" if (status == "online" and not is_err) else ("container_down" if is_err else None),
                )
                db.add(sp)
                await db.flush()
                sp_index[(srv.id, p)] = sp

            # price history: закрытый старый сегмент + текущий (для одного сервера — рост цены)
            cur = CURRENCY_BY_PROVIDER[prov]
            price = PRICE_BY_PROVIDER[prov]
            if name == "Амстердам-1":
                db.add(m.ServerPrice(server_id=srv.id, amount_micros=int((price - 50) * 1e6), currency=cur,
                                     period="month", anchor_day=bday,
                                     effective_from=NOW - 120 * DAY, effective_to=NOW - 40 * DAY))
            db.add(m.ServerPrice(server_id=srv.id, amount_micros=int(price * 1e6), currency=cur,
                                 period="month", anchor_day=bday,
                                 effective_from=NOW - 40 * DAY, effective_to=None))
        await db.flush()

        # --- pools ---
        pool_eu = m.Pool(owner_user_id=owner.id, name="Европа")
        pool_world = m.Pool(owner_user_id=owner.id, name="Весь мир")
        db.add_all([pool_eu, pool_world])
        await db.flush()
        for sid in [servers[0].id, servers[1].id, servers[2].id]:
            db.add(m.PoolServer(pool_id=pool_eu.id, server_id=sid))
        for sid in [servers[3].id, servers[5].id]:
            db.add(m.PoolServer(pool_id=pool_world.id, server_id=sid))

        # --- groups + members ---
        g_family = m.Group(id="demo-family", owner_user_id=owner.id, name="Семья",
                           token="demo-family-" + _hex(4), max_devices=5)
        g_friends = m.Group(id="demo-friends", owner_user_id=owner.id, name="Друзья",
                            token="demo-friends-" + _hex(4), max_devices=3)
        db.add_all([g_family, g_friends])
        await db.flush()
        # владелец сам — участник «Семьи» (чтобы у него были доступные серверы на экране Available)
        db.add(m.GroupMember(group_id=g_family.id, user_id=owner.id, display_name=owner.name,
                             phone=owner.phone, role="admin", status="active"))
        db.add(m.GroupMember(group_id=g_family.id, user_id=users[1].id, display_name=users[1].name,
                             phone=users[1].phone, role="member", status="active"))
        db.add(m.GroupMember(group_id=g_family.id, user_id=users[2].id, display_name=users[2].name,
                             phone=users[2].phone, role="member", status="active", max_devices=2))
        db.add(m.GroupMember(group_id=g_family.id, user_id=None, display_name="Бабушка",
                             phone="+79990000110", role="member", status="invited"))
        db.add(m.GroupMember(group_id=g_friends.id, user_id=users[3].id, display_name=users[3].name,
                             phone=users[3].phone, role="member", status="active"))
        db.add(m.GroupMember(group_id=g_friends.id, user_id=users[5].id, display_name=users[5].name,
                             phone=users[5].phone, role="member", status="active"))
        await db.flush()
        # access
        db.add(m.GroupPoolAccess(group_id=g_family.id, pool_id=pool_eu.id))
        db.add(m.GroupPoolAccess(group_id=g_friends.id, pool_id=pool_world.id))
        db.add(m.GroupServerAccess(group_id=g_family.id, server_id=servers[5].id, vpn_type="amnezia"))
        await db.flush()

        # --- devices + configs ---  собираем поток клиентов для трафика
        # client stream: (server_id, proto, client_id, device_config_id|None, user_id|None, name, online)
        streams: list[tuple] = []
        # серверы с рабочими клиентскими протоколами (wg/xray) — куда реально раздаём конфиги
        client_servers = [s for s in servers if s.status == "online"
                          and any(p in (IS_WG | IS_XRAY) for (sid, p) in sp_index if sid == s.id
                                  and sp_index[(sid, p)].running)]

        def _mk_client(tsrv, proto, dcid, uid, cname):
            spmat = sp_index.get((tsrv.id, proto))
            if not (spmat and spmat.running):
                return None
            cid = _b64(32) if proto in IS_WG else _uuid()
            online = RND.random() < 0.5
            streams.append((tsrv.id, proto, cid, dcid, uid, cname, online))
            return cid

        # раздаём конфиги на устройства активных участников (владелец + ещё несколько)
        member_users = [owner, users[1], users[2], users[3]]
        for u in member_users:
            ndev = 4 if u is owner else RND.randint(2, 3)
            for d in range(ndev):
                plat = PLATFORMS[(hash(u.id) + d) % len(PLATFORMS)]
                dev = m.Device(user_id=u.id, name=f"{plat.capitalize()} {u.name.split()[0]}", platform=plat)
                db.add(dev)
                await db.flush()
                for tsrv in RND.sample(client_servers, k=min(len(client_servers), RND.randint(1, 3))):
                    cand = [p for (sid, p) in sp_index if sid == tsrv.id and p in (IS_WG | IS_XRAY)
                            and sp_index[(sid, p)].running]
                    if not cand:
                        continue
                    proto = RND.choice(cand)
                    cid = _b64(32) if proto in IS_WG else _uuid()
                    cip = f"10.8.1.{RND.randint(2, 250)}" if proto in IS_WG else None
                    status = RND.choices(["active", "active", "active", "active", "revoked"], k=1)[0]
                    cname = f"{u.name.split()[0]}-{dev.platform}"
                    cfg = m.DeviceConfig(device_id=dev.id, server_id=tsrv.id, vpn_type=VENDOR[proto], proto=proto,
                                         status=status, client_id=cid, client_ip=cip,
                                         client_public_key=(cid if proto in IS_WG else ""),
                                         client_secret_encrypted=_enc({"private_key": _b64(32)}),
                                         client_name=cname)
                    db.add(cfg)
                    await db.flush()
                    if status == "active" and sp_index[(tsrv.id, proto)].running:
                        streams.append((tsrv.id, proto, cid, cfg.id, u.id, cname, RND.random() < 0.5))
        # external-клиенты (заведены мимо панели) — по несколько на каждый рабочий протокол
        for tsrv in client_servers:
            for p in [p for (sid, p) in sp_index if sid == tsrv.id
                      and p in (IS_WG | IS_XRAY) and sp_index[(sid, p)].running]:
                for _ in range(RND.randint(2, 5)):
                    _mk_client(tsrv, p, None, None, f"external-{_hex(3)}")
        await db.flush()

        # --- traffic time-series per stream ---
        peer_rows, sample_rows, hourly_rows, daily_rows = [], [], [], []
        for (sid, proto, cid, dcid, uid, cname, online) in streams:
            r = random.Random(hash((sid, proto, cid)) & 0xFFFFFFFF)
            scale = r.uniform(0.4, 3.0)  # «тяжесть» клиента
            rx_cum = int(r.uniform(2, 40) * GB)
            tx_cum = int(r.uniform(8, 160) * GB)
            # raw: последние 24ч, шаг 15 мин
            step = 900.0
            n = int(DAY / step)
            prev_rx, prev_tx = None, None
            base_rx, base_tx = rx_cum - int(2 * GB * scale), tx_cum - int(8 * GB * scale)
            for k in range(n + 1):
                t = NOW - (n - k) * step
                f = diurnal(t) * scale
                d_tx = int(f * r.uniform(2, 9) * 1024 * 1024 * (step / 60))  # download тяжелее
                d_rx = int(f * r.uniform(0.5, 3) * 1024 * 1024 * (step / 60))
                base_rx += d_rx
                base_tx += d_tx
                is_on = online and (k > n - 6)  # онлайн — в последние ~1.5ч
                sample_rows.append(m.TrafficSample(
                    server_id=sid, proto=proto, client_id=cid, device_config_id=dcid, at=t,
                    rx_bytes=base_rx, tx_bytes=base_tx, rx_delta=d_rx, tx_delta=d_tx,
                    last_handshake=(t if is_on else (NOW - r.uniform(HOUR, DAY))),
                    online=is_on, ext_name=(cname if dcid is None else None)))
                prev_rx, prev_tx = base_rx, base_tx
            rx_cum, tx_cum = base_rx, base_tx
            # hourly: последние 14 дней
            for k in range(14 * 24):
                bucket = int((NOW - k * HOUR) // HOUR * HOUR)
                f = diurnal(bucket) * scale
                rx = int(f * r.uniform(20, 90) * 1024 * 1024)
                tx = int(f * r.uniform(80, 400) * 1024 * 1024)
                st = r.randint(3, 6)
                hourly_rows.append(m.TrafficHourly(
                    server_id=sid, proto=proto, client_id=cid, device_config_id=dcid, bucket=bucket,
                    rx=rx, tx=tx, samples_total=st, samples_online=r.randint(0, st),
                    last_handshake=bucket, ext_name=(cname if dcid is None else None)))
            # daily: последние 30 дней
            for k in range(30):
                bucket = int((NOW - k * DAY) // DAY * DAY)
                rx = int(scale * r.uniform(0.5, 3) * GB)
                tx = int(scale * r.uniform(2, 12) * GB)
                daily_rows.append(m.TrafficDaily(
                    server_id=sid, proto=proto, client_id=cid, device_config_id=dcid, bucket=bucket,
                    rx=rx, tx=tx, samples_total=r.randint(60, 96), samples_online=r.randint(10, 60),
                    last_handshake=bucket, ext_name=(cname if dcid is None else None)))
            peer_rows.append(m.TrafficPeerState(
                server_id=sid, proto=proto, client_id=cid, device_config_id=dcid,
                ext_name=(cname if dcid is None else None),
                rx_bytes=rx_cum, tx_bytes=tx_cum,
                rx_speed=(r.uniform(0.1, 2) * 1024 * 1024 if online else 0.0),
                tx_speed=(r.uniform(0.5, 6) * 1024 * 1024 if online else 0.0),
                last_at=NOW - r.uniform(10, 120),
                last_handshake=(NOW - r.uniform(10, 200)) if online else (NOW - r.uniform(HOUR, DAY)),
                online=online))
        db.add_all(peer_rows)
        db.add_all(sample_rows)
        db.add_all(hourly_rows)
        db.add_all(daily_rows)
        await db.flush()

        # --- traffic_usage за текущий период (агрегат сервера + по пользователям) ---
        for srv in servers:
            if srv.status == "offline":
                continue
            # период ДОЛЖЕН совпасть с finance/limits.period_start(now, billing_day),
            # иначе KPI «использование трафика» читает 0 Б
            pstart = period_start(NOW, srv.billing_day)
            agg_rx = agg_tx = 0
            by_user: dict[str, list[int]] = {}
            for (sid, proto, cid, dcid, uid, cname, online) in streams:
                if sid != srv.id:
                    continue
                rx = RND.randint(1, 20) * GB
                tx = RND.randint(5, 80) * GB
                agg_rx += rx
                agg_tx += tx
                if uid:
                    b = by_user.setdefault(uid, [0, 0])
                    b[0] += rx
                    b[1] += tx
            db.add(m.TrafficUsage(server_id=srv.id, user_id=None, period_start=pstart,
                                  rx_bytes=agg_rx, tx_bytes=agg_tx, updated_at=NOW - 120))
            for uid, (rx, tx) in by_user.items():
                db.add(m.TrafficUsage(server_id=srv.id, user_id=uid, period_start=pstart,
                                      rx_bytes=rx, tx_bytes=tx, updated_at=NOW - 120))
        await db.flush()

        # --- server_metrics (raw 24ч) + hourly (14д) ---
        for srv in servers:
            if srv.status == "offline":
                continue
            r = random.Random(hash(srv.id) & 0xFFFFFFFF)
            mem_total = r.choice([2, 4, 8]) * GB
            disk_total = r.choice([40, 80, 160]) * GB
            protos_here = [p for (sid, p) in sp_index if sid == srv.id]
            on_streams = [s for s in streams if s[0] == srv.id]
            # raw 24ч, шаг 10 мин
            step = 600.0
            n = int(DAY / step)
            for k in range(n + 1):
                t = NOW - (n - k) * step
                f = diurnal(t)
                cpu = round(min(95, 12 + 55 * f + r.uniform(-6, 6)), 1)
                onl = {}
                for p in protos_here:
                    if p in IS_WG or p in IS_XRAY or p == "hysteria2":
                        onl[p] = max(0, int(len([s for s in on_streams if s[1] == p and s[6]]) * (0.6 + 0.8 * f)))
                    else:
                        onl[p] = None
                oc = sum(v for v in onl.values() if v is not None)
                db.add(m.ServerMetric(
                    server_id=srv.id, at=t, cpu_pct=cpu, load1=round(cpu / 25, 2),
                    mem_used=int(mem_total * (0.4 + 0.25 * f)), mem_total=mem_total,
                    disk_used=int(disk_total * (0.42 + 0.0004 * (n - k))), disk_total=disk_total,
                    tcp_estab=int(oc * 4 + r.uniform(5, 20)), uptime_s=int(35 * DAY + t - NOW + 35 * DAY),
                    online_clients=oc, online_by_proto=json.dumps(onl)))
            # hourly 14д
            for k in range(14 * 24):
                bucket = int((NOW - k * HOUR) // HOUR * HOUR)
                f = diurnal(bucket)
                cpu = min(95, 12 + 55 * f)
                oc = int(len([s for s in on_streams if s[6]]) * (0.5 + 0.9 * f))
                db.add(m.ServerMetricHourly(
                    server_id=srv.id, bucket=bucket,
                    cpu_pct_avg=round(cpu, 1), cpu_pct_max=round(min(99, cpu + 12), 1),
                    load1_avg=round(cpu / 25, 2), load1_max=round(cpu / 20, 2),
                    mem_used_avg=int(mem_total * (0.4 + 0.25 * f)), mem_total=mem_total,
                    disk_used=int(disk_total * 0.5), disk_total=disk_total,
                    tcp_estab_avg=oc * 4.0, tcp_estab_max=oc * 5,
                    online_clients_avg=float(oc), online_clients_max=oc + 2, samples_total=r.randint(4, 6)))
        await db.flush()

        # --- metric_samples (admin-дашборд «Система»): серверы по статусу + http-счётчик ---
        online_n = sum(1 for s in SERVERS if s[5] == "online")
        offline_n = sum(1 for s in SERVERS if s[5] == "offline")
        http = 128000
        for k in range(7 * 24, -1, -1):
            t = NOW - k * HOUR
            http += int(diurnal(t) * RND.uniform(200, 900))
            db.add(m.MetricSample(name="vpnhub_servers", labels="status=online", at=t, value=float(online_n)))
            db.add(m.MetricSample(name="vpnhub_servers", labels="status=offline", at=t, value=float(offline_n)))
            db.add(m.MetricSample(name="vpnhub_servers", labels="status=unknown", at=t, value=0.0))
            db.add(m.MetricSample(name="vpnhub_http_total", labels="", at=t, value=float(http)))
        await db.flush()

        # --- chain_link (мультихоп Москва → Амстердам) ---
        db.add(m.ChainLink(owner_user_id=owner.id, entry_server_id=servers[5].id,
                           exit_server_id=servers[0].id, proto="xray",
                           exit_client_id=_uuid(), state="linked"))
        await db.flush()

        # --- audit_events (30 дней, читаемые типы) ---
        ev_types = [("auth.login", "user"), ("config.download", "user"),
                    ("group.join", "user"), ("access.revoke", "user"),
                    ("auth.login", "admin")]
        for k in range(60):
            t = NOW - RND.uniform(0, 30 * DAY)
            code, kind = RND.choice(ev_types)
            actor = owner if kind == "admin" else RND.choice(users)
            db.add(m.AuditEvent(
                at=t, actor_kind=("admin" if kind == "admin" else "user"),
                actor_id=actor.id, actor_name=actor.name, type=code,
                target_kind=RND.choice(["server", "device", "group", "config"]),
                target_id=_hex(8), owner_user_id=owner.id,
                meta_json=json.dumps({"ip": f"198.51.100.{RND.randint(2, 250)}"})))
        await db.flush()

        # --- settings (дефолтные лимиты для экрана «Система») ---
        db.add(m.Setting(key="default_devices_per_user", value="5"))
        await db.commit()

    await engine.dispose()
    print("SEED_OK: users=%d servers=%d streams=%d" % (len(USERS), len(SERVERS), len(streams)))


if __name__ == "__main__":
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("set DATABASE_URL")
    asyncio.run(main())
