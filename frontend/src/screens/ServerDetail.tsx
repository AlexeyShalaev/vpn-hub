import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { type ChartLine, LineChart } from "../components/chart";
import { Btn, Field, Icon, Modal, ScreenHeader, Spinner, StatusBadge } from "../components/ui";
import { type TFunc, type TKey, useT } from "../lib/i18n";
import * as q from "../lib/queries";
import {
  bytesToTrafficInput,
  convertTrafficInputUnit,
  TRAFFIC_UNITS,
  type TrafficUnit,
  trafficValueToBytes,
} from "../lib/trafficUnits";
import type { MonitoringClient, Protocol, Server, ServerMetricSample, Vpn, VpnType } from "../lib/types";
import { PROTO_STATE_LABEL, VENDOR_PROTOCOLS, VPN_ICON, VPN_LABEL, vpnDesc } from "../lib/types";
import { vpnLogo } from "../lib/vpnLogos";
import { useNav } from "../nav";
import { copyText, useStore } from "../store";
import { ClientTrafficModal } from "./Monitoring";
import { ServerAccessSections } from "./ServerAccess";
import { VpnAdvancedModal } from "./VpnAdvanced";

const VPN_TYPES: VpnType[] = ["amnezia", "openvpn", "outline", "hysteria2"];
type ServerDetailTab = "connection" | "protocols" | "monitoring" | "access";
const SERVER_TABS: ServerDetailTab[] = ["connection", "protocols", "monitoring", "access"];

// установлен ли на сервере запущенный tcp-Reality Xray (условие мультихопа для entry/exit)
const hasRunningXray = (s: Server): boolean =>
  (s.protocols ?? []).some((p) => p.proto === "xray" && p.installed && p.running);

// человекочитаемые размеры/время для карточки ресурсов
const fmtBytes = (t: TFunc, n: number | null): string => {
  if (n == null) return "—";
  const u = [
    t("srvDetail.unitByte"),
    t("srvDetail.unitKb"),
    t("srvDetail.unitMb"),
    t("srvDetail.unitGb"),
    t("srvDetail.unitTb"),
  ];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
};
const fmtUptime = (t: TFunc, s: number | null): string => {
  if (s == null) return "—";
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return t("srvDetail.uptimeDaysHours", { d, h });
  if (h > 0) return t("srvDetail.uptimeHoursMin", { h, m });
  return t("srvDetail.uptimeMin", { m });
};
const pct = (used: number | null, total: number | null): number | null =>
  used != null && total != null && total > 0 ? Math.round((used / total) * 100) : null;

// плитка-показатель (значение + подпись + опциональный процент)
function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px", minWidth: 0 }}>
      <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, lineHeight: 1.1 }}>{value}</div>
      {sub && (
        <div className="muted-3" style={{ fontSize: 11.5, marginTop: 3 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

// ключи i18n для проколов вендоров (переиспользуем общие proto.* ключи)
const PROTO_LABEL_KEY: Record<string, TKey> = {
  awg: "proto.awg",
  awg_legacy: "proto.awgLegacy",
  xray: "proto.xray",
  xray_xhttp: "proto.xrayXhttp",
  hysteria2: "proto.hysteria2",
  openvpn: "proto.openvpn",
  outline: "proto.outline",
};
const protoLabel = (t: TFunc, proto: string): string => (PROTO_LABEL_KEY[proto] ? t(PROTO_LABEL_KEY[proto]) : proto);
// подсказка, ПОЧЕМУ online неизвестен (—) для протокола
const onlineNaHint = (t: TFunc, proto: string): string | undefined =>
  proto === "outline"
    ? t("srvDetail.onlineNaOutline")
    : proto === "openvpn"
      ? t("srvDetail.onlineNaOpenvpn")
      : undefined;
// протоколы с точной статистикой (Xray Stats API / Hysteria2 trafficStats) — включается автоматически
const STATS_ENABLABLE = ["xray", "xray_xhttp", "hysteria2"];

// Карточка «Ресурсы сервера»: текущие CPU/RAM/диск/load/uptime/TCP + честный online по протоколам + мини-графики.
// Сбор — в monitor-тике по SSH (best-effort); поллинг здесь — как и остальной ServerDetail.
const METRIC_PERIODS = ["24h", "7d", "30d", "180d"] as const;
type MetricPeriod = (typeof METRIC_PERIODS)[number];
const metricPeriodLabel = (t: TFunc, p: MetricPeriod): string =>
  p === "24h"
    ? t("period.24h")
    : p === "7d"
      ? t("period.7d")
      : p === "30d"
        ? t("period.30d")
        : t("srvDetail.period180d");

function ServerMetricsCard({ serverId, online }: { serverId: string; online: boolean }) {
  const t = useT();
  const [period, setPeriod] = useState<MetricPeriod>("24h");
  const mq = useQuery({
    queryKey: ["serverMetrics", serverId, period],
    queryFn: () => q.serverMetrics(serverId, period),
    enabled: !!serverId,
    refetchInterval: 60000, // как страховочный поллинг всего ServerDetail
    retry: 2, // глобально retry=false → разовый сбой оставлял бы карточку пустой
  });

  const label = { fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" as const };
  const cur = mq.data?.current ?? null;
  const samples: ServerMetricSample[] = mq.data?.samples ?? [];

  const line = (pick: (s: ServerMetricSample) => number | null, color: string, name: string): ChartLine => ({
    color,
    label: name,
    points: samples.filter((s) => pick(s) != null).map((s) => ({ at: s.at, value: pick(s) as number })),
  });

  const memPct = cur ? pct(cur.memUsed, cur.memTotal) : null;
  const diskPct = cur ? pct(cur.diskUsed, cur.diskTotal) : null;

  return (
    <div className="card stack">
      <div className="rowflex" style={{ justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <div className="muted-3" style={label}>
          {t("srvDetail.serverResources")}
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {METRIC_PERIODS.map((p) => (
            <Btn key={p} variant={p === period ? "primary" : "ghost"} sm onClick={() => setPeriod(p)}>
              {metricPeriodLabel(t, p)}
            </Btn>
          ))}
        </div>
      </div>

      {mq.isLoading ? (
        <Spinner />
      ) : !cur ? (
        <p className="muted" style={{ fontSize: 13 }}>
          {online ? t("srvDetail.metricsWillAppear") : t("srvDetail.metricsOfflineHint")}
        </p>
      ) : (
        <>
          <div className="grid">
            <Metric label="CPU" value={cur.cpuPct != null ? `${cur.cpuPct}%` : "—"} sub={`load ${cur.load1 ?? "—"}`} />
            <Metric
              label={t("srvDetail.memory")}
              value={memPct != null ? `${memPct}%` : "—"}
              sub={`${fmtBytes(t, cur.memUsed)} / ${fmtBytes(t, cur.memTotal)}`}
            />
            <Metric
              label={t("srvDetail.diskRoot")}
              value={diskPct != null ? `${diskPct}%` : "—"}
              sub={`${fmtBytes(t, cur.diskUsed)} / ${fmtBytes(t, cur.diskTotal)}`}
            />
            <Metric label={t("srvDetail.uptime")} value={fmtUptime(t, cur.uptimeS)} />
            <Metric label={t("srvDetail.tcpConnections")} value={cur.tcpEstab != null ? String(cur.tcpEstab) : "—"} />
            {cur.onlineClients != null && (
              <Metric
                label={t("srvDetail.onlineClients")}
                value={String(cur.onlineClients)}
                sub={t("srvDetail.totalByProtocols")}
              />
            )}
          </div>

          {/* Честный online по протоколам: число — точное; «—» = неизвестно (stats не включён / нет счётчика) */}
          <div className="stack" style={{ gap: 8 }}>
            <div style={{ fontSize: 12.5, color: "var(--text-2)" }}>{t("srvDetail.onlineByProtocol")}</div>
            <div className="rowflex" style={{ gap: 6, flexWrap: "wrap" }}>
              {Object.entries(cur.onlineByProto ?? {}).map(([proto, n]) => (
                <span
                  key={proto}
                  className={`badge ${n == null ? "" : "ok"}`}
                  title={n == null ? (onlineNaHint(t, proto) ?? t("srvDetail.statsAutoEnableHint")) : ""}
                >
                  {protoLabel(t, proto)}: {n == null ? "—" : n}
                </span>
              ))}
              {Object.keys(cur.onlineByProto ?? {}).length === 0 && (
                <span className="muted-3" style={{ fontSize: 12.5 }}>
                  {t("srvDetail.noData")}
                </span>
              )}
            </div>
            {Object.entries(cur.onlineByProto ?? {}).some(([p, n]) => STATS_ENABLABLE.includes(p) && n == null) && (
              <div className="muted-3" style={{ fontSize: 12 }}>
                {t("srvDetail.statsAutoEnableLong")}
              </div>
            )}
          </div>

          {samples.length > 1 && (
            <div className="stack" style={{ gap: 14, marginTop: 4 }}>
              <div>
                <div style={{ fontSize: 12.5, color: "var(--text-2)", marginBottom: 6 }}>
                  {t("srvDetail.cpuMemoryChartTitle")}
                </div>
                <LineChart
                  height={130}
                  lines={[
                    line((s) => s.cpuPct, "#3b82f6", t("srvDetail.cpuPct")),
                    line((s) => pct(s.memUsed, s.memTotal), "#a855f7", t("srvDetail.memoryPct")),
                  ]}
                />
              </div>
              <div>
                <div style={{ fontSize: 12.5, color: "var(--text-2)", marginBottom: 6 }}>
                  {t("srvDetail.tcpConnections")}
                </div>
                <LineChart height={130} lines={[line((s) => s.tcpEstab, "#22c55e", t("srvDetail.tcpEstablished"))]} />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

const clientLabel = (t: TFunc, c: MonitoringClient): string =>
  c.userName || c.deviceName
    ? [c.userName, c.deviceName].filter(Boolean).join(" · ")
    : c.external
      ? // external-клиент (заведён мимо панели) — имя из Amnezia clientsTable, если есть
        c.extName || t("srvDetail.externalClient")
      : (c.clientId ?? "—");
const fmtSpeed = (t: TFunc, bps: number): string => (bps > 0 ? `${fmtBytes(t, bps)}/${t("srvDetail.perSecond")}` : "—");

// Карточка «Клиенты сервера»: per-client трафик+онлайн этого сервера (переиспользует global
// overview через per-server endpoint /servers/{id}/traffic). Онлайн — точка, трафик — за 24ч.
function ServerClientsCard({ serverId, online }: { serverId: string; online: boolean }) {
  const t = useT();
  const tq = useQuery({
    queryKey: ["serverTraffic", serverId],
    queryFn: () => q.serverTraffic(serverId, "24h"),
    enabled: !!serverId,
    refetchInterval: 60000,
    retry: 2, // глобально retry=false → разовый сбой оставлял бы карточку пустой
  });
  // клик по клиенту → та же модалка с графиком трафика, что в общем «Мониторинге».
  // per-server overview не заполняет serverId у клиента — подставляем текущий при открытии.
  const [selected, setSelected] = useState<MonitoringClient | null>(null);
  const label = { fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" as const };
  const clients: MonitoringClient[] = [...(tq.data?.clients ?? [])].sort(
    (a, b) => Number(b.online) - Number(a.online) || b.rxTotal + b.txTotal - (a.rxTotal + a.txTotal),
  );
  const th: React.CSSProperties = {
    textAlign: "left",
    padding: "7px 9px",
    fontSize: 11.5,
    color: "var(--text-3)",
    whiteSpace: "nowrap",
    borderBottom: "1px solid var(--border)",
  };
  const td: React.CSSProperties = { padding: "8px 9px", fontSize: 13, borderBottom: "1px solid var(--border)" };
  const num: React.CSSProperties = {
    ...td,
    textAlign: "right",
    fontVariantNumeric: "tabular-nums",
    whiteSpace: "nowrap",
  };

  return (
    <div className="card stack">
      <div className="muted-3" style={label}>
        {t("srvDetail.clientsTrafficTitle")}
      </div>
      {tq.isLoading ? (
        <Spinner />
      ) : clients.length === 0 ? (
        <p className="muted" style={{ fontSize: 13 }}>
          {online ? t("srvDetail.clientsWillAppear") : t("srvDetail.clientsOfflineHint")}
        </p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={th}>{t("srvDetail.client")}</th>
                <th style={th}>{t("srvDetail.protocol")}</th>
                <th style={{ ...th, textAlign: "center" }}>{t("status.online")}</th>
                <th style={{ ...th, textAlign: "right" }}>{t("srvDetail.downloaded")}</th>
                <th style={{ ...th, textAlign: "right" }}>{t("srvDetail.uploaded")}</th>
                <th style={{ ...th, textAlign: "right" }}>{t("srvDetail.speedDownUp")}</th>
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => (
                <tr
                  key={`${c.proto}:${c.clientId}`}
                  onClick={() => setSelected({ ...c, serverId })}
                  style={{ cursor: "pointer" }}
                  title={t("srvDetail.showTrafficChart")}
                >
                  <td style={td}>
                    <div style={{ fontWeight: 600 }}>{clientLabel(t, c)}</div>
                    {c.external && (
                      <div className="muted-3" style={{ fontSize: 11 }}>
                        {t("srvDetail.outsidePanel")}
                      </div>
                    )}
                  </td>
                  <td style={td}>
                    <span className="badge">{protoLabel(t, c.proto)}</span>
                  </td>
                  <td style={{ ...td, textAlign: "center" }}>
                    <span
                      title={c.online ? t("status.online") : t("status.offline")}
                      style={{
                        display: "inline-block",
                        width: 9,
                        height: 9,
                        borderRadius: "50%",
                        background: c.online ? "#22c55e" : "var(--border-strong, #9ca3af)",
                      }}
                    />
                  </td>
                  <td style={num}>{fmtBytes(t, c.txTotal)}</td>
                  <td style={num}>{fmtBytes(t, c.rxTotal)}</td>
                  <td style={num}>{c.online ? `${fmtSpeed(t, c.txSpeed)} / ${fmtSpeed(t, c.rxSpeed)}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selected && (
        <ClientTrafficModal
          client={selected}
          period="24h"
          periodLabel={t("period.24h")}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

// Карточка «Трафик и квота»: квота трафика тарифа + день сброса периода (настройка владельца) и
// фактическое использование за текущий период — суммарно по серверу и по пользователям (топ-жоры).
// Пер-user превышение честно отсекается на Этапе 3b; здесь — учёт, индикатор и предупреждения.
function ServerTrafficQuotaCard({ server }: { server: Server }) {
  const t = useT();
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();
  const uq = useQuery({
    queryKey: ["serverUsage", server.id],
    queryFn: () => q.serverUsage(server.id),
    enabled: !!server.id,
    refetchInterval: 60000,
  });
  const [editing, setEditing] = useState(false);
  const [quotaValue, setQuotaValue] = useState("");
  const [quotaUnit, setQuotaUnit] = useState<TrafficUnit>("GB");
  const [billingDay, setBillingDay] = useState("");

  const saveMut = useMutation({
    mutationFn: () =>
      q.setBandwidthQuota(
        server.id,
        trafficValueToBytes(quotaValue, quotaUnit),
        billingDay ? Number.parseInt(billingDay, 10) : null,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["server", server.id] });
      qc.invalidateQueries({ queryKey: ["serverUsage", server.id] });
      setEditing(false);
      toast(t("srvDetail.quotaSaved"));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("srvDetail.quotaSaveFailed")),
  });

  const label = { fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" as const };
  const usage = uq.data;
  const quota = server.bandwidthQuota;
  const used = usage?.serverUsed ?? 0;
  const quotaPct = quota && quota > 0 ? Math.round((used / quota) * 100) : null;
  const quotaColor =
    quotaPct == null ? "var(--text-2)" : quotaPct >= 100 ? "var(--danger)" : quotaPct >= 80 ? "#d97706" : "var(--ok)";
  const dayLabel = server.billingDay
    ? t("srvDetail.dayOfMonth", { day: server.billingDay })
    : t("srvDetail.dayOfMonthDefault");

  const openEdit = () => {
    const quotaInput = bytesToTrafficInput(server.bandwidthQuota);
    setQuotaValue(quotaInput.value);
    setQuotaUnit(quotaInput.unit);
    setBillingDay(server.billingDay ? String(server.billingDay) : "");
    setEditing(true);
  };

  return (
    <div className="card stack">
      <div className="rowflex" style={{ justifyContent: "space-between", gap: 12 }}>
        <div className="muted-3" style={label}>
          {t("srvDetail.trafficQuotaTitle")}
        </div>
        <Btn sm onClick={openEdit}>
          <Icon name="edit" size={15} />
          {t("srvDetail.quota")}
        </Btn>
      </div>

      <div className="rowflex" style={{ gap: 14, flexWrap: "wrap" }}>
        <div style={{ minWidth: 160 }}>
          <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 3 }}>
            {t("srvDetail.usedByServer")}
          </div>
          <div style={{ fontSize: 18, fontWeight: 700, color: quotaColor }}>
            {fmtBytes(t, used)}
            {quota ? (
              <span className="muted-3" style={{ fontSize: 13, fontWeight: 500 }}>
                {" "}
                / {fmtBytes(t, quota)}
              </span>
            ) : null}
          </div>
          <div className="muted-3" style={{ fontSize: 11.5, marginTop: 2 }}>
            {quota ? t("srvDetail.pctOfQuota", { pct: quotaPct ?? 0 }) : t("srvDetail.quotaUnlimited")} ·{" "}
            {t("srvDetail.resetLabel", { day: dayLabel })}
          </div>
        </div>
      </div>
      {quota ? (
        <div style={{ height: 7, borderRadius: 999, background: "var(--surface-2)", overflow: "hidden" }}>
          <div style={{ width: `${Math.min(100, quotaPct ?? 0)}%`, height: "100%", background: quotaColor }} />
        </div>
      ) : null}

      {/* Топ по трафику среди пользователей за период (+ индикатор пер-user лимита) */}
      {usage && usage.users.length > 0 && (
        <div className="stack" style={{ gap: 4 }}>
          <div className="muted-3" style={{ fontSize: 12.5, marginTop: 2 }}>
            {t("srvDetail.usersForPeriod")}
          </div>
          {usage.users.slice(0, 8).map((u) => {
            const over = u.limit != null && u.used >= u.limit;
            const near = u.limit != null && !over && u.used >= u.limit * 0.8;
            const col = over ? "var(--danger)" : near ? "#d97706" : "var(--text-2)";
            return (
              <div key={u.userId} className="rowflex" style={{ justifyContent: "space-between", gap: 8, fontSize: 13 }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{u.name}</span>
                <span style={{ color: col, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", flex: "none" }}>
                  {fmtBytes(t, u.used)}
                  {u.limit != null ? ` / ${fmtBytes(t, u.limit)}` : ""}
                  {over ? ` · ${t("srvDetail.limitReached")}` : ""}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {editing && (
        <Modal
          title={t("srvDetail.trafficQuotaModalTitle")}
          onClose={() => setEditing(false)}
          footer={
            <>
              <Btn variant="ghost" block onClick={() => setEditing(false)}>
                {t("common.cancel")}
              </Btn>
              <Btn variant="primary" block disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>
                {t("common.save")}
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ fontSize: 13, marginBottom: 14 }}>
            {t("srvDetail.trafficQuotaHelp")}
          </p>
          <Field label={t("srvDetail.trafficQuotaFieldLabel")}>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 92px", gap: 8 }}>
              <input
                className="input"
                type="number"
                min={0}
                step={quotaUnit === "B" ? 1 : 0.1}
                value={quotaValue}
                placeholder={t("srvDetail.emptyUnlimited")}
                autoFocus
                onChange={(e) => setQuotaValue(e.target.value)}
              />
              <select
                className="input"
                value={quotaUnit}
                onChange={(e) => {
                  const unit = e.target.value as TrafficUnit;
                  setQuotaValue((v) => convertTrafficInputUnit(v, quotaUnit, unit));
                  setQuotaUnit(unit);
                }}
              >
                {TRAFFIC_UNITS.map((u) => (
                  <option key={u.value} value={u.value}>
                    {u.label}
                  </option>
                ))}
              </select>
            </div>
          </Field>
          <Field label={t("srvDetail.billingDayFieldLabel")}>
            <input
              className="input"
              type="number"
              min={1}
              max={31}
              value={billingDay}
              placeholder={t("srvDetail.emptyFirstDay")}
              onChange={(e) => setBillingDay(e.target.value)}
            />
          </Field>
        </Modal>
      )}
    </div>
  );
}

const pricePeriodLabel = (t: TFunc, period: string): string =>
  period === "minute"
    ? t("srvDetail.periodMinuteShort")
    : period === "day"
      ? t("srvDetail.periodDayShort")
      : t("srvDetail.periodMonthShort");
const CURRENCIES = ["RUB", "USD", "EUR", "KZT", "UAH", "GBP"];
const fmtMoney = (a: number, cur: string): string =>
  `${a.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ${cur}`;

// Карточка «Стоимость»: цена сервера (валюта/период/день обновления) + accrual-расход за 30 дней.
// Цена меняется во времени — история хранится сегментами, расход считается по фактически
// действовавшей цене (см. services/finance). Разные валюты показываем раздельно.
function ServerCostCard({ serverId }: { serverId: string }) {
  const t = useT();
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();
  const priceQ = useQuery({ queryKey: ["serverPrice", serverId], queryFn: () => q.getServerPrice(serverId), retry: 2 });
  const costQ = useQuery({ queryKey: ["serverCost", serverId], queryFn: () => q.serverCost(serverId), retry: 2 });
  const price = priceQ.data?.price ?? null;

  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("RUB");
  const [period, setPeriod] = useState("month");
  const [anchor, setAnchor] = useState("");

  const saveMut = useMutation({
    mutationFn: () =>
      q.setServerPrice(serverId, {
        amount: amount.trim() === "" ? null : Number.parseFloat(amount.replace(",", ".")),
        currency,
        period,
        anchorDay: anchor ? Number.parseInt(anchor, 10) : null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["serverPrice", serverId] });
      qc.invalidateQueries({ queryKey: ["serverCost", serverId] });
      setEditing(false);
      toast(t("srvDetail.priceSaved"));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("srvDetail.priceSaveFailed")),
  });

  const openEdit = () => {
    setAmount(price ? String(price.amount) : "");
    setCurrency(price?.currency ?? "RUB");
    setPeriod(price?.period ?? "month");
    setAnchor(price?.anchorDay ? String(price.anchorDay) : "");
    setEditing(true);
  };

  const label = { fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" as const };
  const cost = costQ.data?.byCurrency ?? [];

  return (
    <div className="card stack">
      <div className="rowflex" style={{ justifyContent: "space-between", gap: 12 }}>
        <div className="muted-3" style={label}>
          {t("srvDetail.cost")}
        </div>
        <Btn sm onClick={openEdit}>
          <Icon name="edit" size={15} />
          {price ? t("common.edit") : t("srvDetail.setPrice")}
        </Btn>
      </div>

      <div className="rowflex" style={{ gap: 24, flexWrap: "wrap" }}>
        <div>
          <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 3 }}>
            {t("srvDetail.price")}
          </div>
          <div style={{ fontSize: 18, fontWeight: 700 }}>
            {price
              ? `${fmtMoney(price.amount, price.currency)} / ${pricePeriodLabel(t, price.period)}`
              : t("srvDetail.priceNotSet")}
          </div>
          {price?.period === "month" && price.anchorDay ? (
            <div className="muted-3" style={{ fontSize: 11.5, marginTop: 2 }}>
              {t("srvDetail.updatesOnDay", { day: price.anchorDay })}
            </div>
          ) : null}
        </div>
        <div>
          <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 3 }}>
            {t("srvDetail.spendFor30Days")}
          </div>
          {cost.length === 0 ? (
            <div style={{ fontSize: 18, fontWeight: 700, color: "var(--text-3)" }}>—</div>
          ) : (
            cost.map((c) => (
              <div key={c.currency} style={{ fontSize: 18, fontWeight: 700 }}>
                {fmtMoney(c.amount, c.currency)}
              </div>
            ))
          )}
        </div>
      </div>

      {editing && (
        <Modal
          title={t("srvDetail.serverCostModalTitle")}
          onClose={() => setEditing(false)}
          footer={
            <>
              <Btn variant="ghost" block onClick={() => setEditing(false)}>
                {t("common.cancel")}
              </Btn>
              <Btn variant="primary" block disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>
                {t("common.save")}
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ fontSize: 13, marginBottom: 14 }}>
            {t("srvDetail.serverCostHelp")}
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
            <Field label={t("srvDetail.pricePerPeriod")}>
              <input
                className="input"
                type="number"
                min={0}
                step="0.01"
                value={amount}
                placeholder={t("srvDetail.emptyFree")}
                autoFocus
                onChange={(e) => setAmount(e.target.value)}
              />
            </Field>
            <Field label={t("srvDetail.currency")}>
              <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                {CURRENCIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label={t("srvDetail.paymentPeriod")}>
            <div style={{ display: "flex", gap: 8 }}>
              {(["minute", "day", "month"] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  className={`chip${period === p ? " selected" : ""}`}
                  style={{ flex: 1, height: 40, justifyContent: "center", cursor: "pointer", fontSize: 13.5 }}
                  onClick={() => setPeriod(p)}
                >
                  {p === "minute"
                    ? t("srvDetail.minuteFull")
                    : p === "day"
                      ? t("srvDetail.dayFull")
                      : t("srvDetail.monthFull")}
                </button>
              ))}
            </div>
          </Field>
          {period === "month" && (
            <Field label={t("srvDetail.updateDayFieldLabel")}>
              <input
                className="input"
                type="number"
                min={1}
                max={31}
                value={anchor}
                placeholder={t("srvDetail.egFifteen")}
                onChange={(e) => setAnchor(e.target.value)}
              />
            </Field>
          )}
        </Modal>
      )}
    </div>
  );
}

// Секция «Цепочка (мультихоп)»: трафик клиентов этого (entry) сервера выходит в интернет через
// другой (exit) сервер. Реализация — Xray outbound chaining: entry становится vless-клиентом exit.
function ChainSection({ server }: { server: Server }) {
  const t = useT();
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();
  const [exitId, setExitId] = useState("");

  const chainsQ = useQuery({
    queryKey: ["chains", server.id],
    queryFn: () => q.listChains(server.id),
    enabled: hasRunningXray(server),
  });
  const serversQ = useQuery({ queryKey: ["servers"], queryFn: () => q.listServers() });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["chains", server.id] });

  const createMut = useMutation({
    mutationFn: () => q.createChain(server.id, exitId),
    onSuccess: () => {
      setExitId("");
      invalidate();
      toast(t("srvDetail.chainCreated"));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("srvDetail.chainCreateFailed")),
  });
  const deleteMut = useMutation({
    mutationFn: (chainId: string) => q.deleteChain(server.id, chainId),
    onSuccess: () => {
      invalidate();
      toast(t("srvDetail.chainDeleted"));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("srvDetail.chainDeleteFailed")),
  });

  // мультихоп работает только для tcp-Reality Xray — прячем секцию, если на entry его нет
  if (!hasRunningXray(server)) return null;

  const chains = chainsQ.data ?? [];
  // кандидаты в exit: чужие серверы владельца, онлайн, с запущенным Xray
  const candidates = (serversQ.data ?? []).filter(
    (s) => s.id !== server.id && s.status === "online" && hasRunningXray(s),
  );

  return (
    <div className="card stack">
      <div
        className="muted-3"
        style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
      >
        {t("srvDetail.multihopTitle")}
      </div>
      <p className="muted" style={{ fontSize: 13 }}>
        {t("srvDetail.multihopExplainBefore")} <strong>Xray</strong> {t("srvDetail.multihopExplainAfter")}
      </p>

      {chains.length > 0 ? (
        <div className="stack" style={{ gap: 8 }}>
          {chains.map((ch) => (
            <div
              key={ch.id}
              className="rowflex"
              style={{
                justifyContent: "space-between",
                gap: 8,
                flexWrap: "nowrap",
                border: "1px solid var(--border)",
                borderRadius: 10,
                padding: "10px 12px",
              }}
            >
              <span className="rowflex" style={{ gap: 8, minWidth: 0 }}>
                <Icon name="refresh" size={15} />
                <span style={{ fontSize: 13.5 }}>
                  {t("srvDetail.chainExitVia")} <strong>{ch.exitServerName || ch.exitServerId}</strong> (Xray)
                </span>
                <span className={`badge ${ch.state === "linked" ? "ok" : "warn"}`}>{ch.state}</span>
              </span>
              <Btn
                variant="ghost"
                sm
                disabled={deleteMut.isPending}
                title={t("srvDetail.deleteChain")}
                onClick={() => deleteMut.mutate(ch.id)}
              >
                <Icon name="trash" size={14} />
              </Btn>
            </div>
          ))}
        </div>
      ) : candidates.length > 0 ? (
        <div className="rowflex" style={{ gap: 8, flexWrap: "nowrap" }}>
          <select className="input" value={exitId} onChange={(e) => setExitId(e.target.value)} style={{ flex: 1 }}>
            <option value="">{t("srvDetail.selectExitServer")}</option>
            {candidates.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} · {s.location || s.ip}
              </option>
            ))}
          </select>
          <Btn variant="primary" disabled={!exitId || createMut.isPending} onClick={() => createMut.mutate()}>
            {createMut.isPending ? <Spinner /> : t("common.create")}
          </Btn>
        </div>
      ) : (
        <p className="muted-3" style={{ fontSize: 12.5 }}>
          {t("srvDetail.noExitServers")}
        </p>
      )}
    </div>
  );
}

export function ServerDetailScreen() {
  const t = useT();
  const serverId = useNav((s) => s.params.serverId) || "";
  const go = useNav((s) => s.go);
  const toast = useStore((s) => s.toast);
  const theme = useStore((s) => s.theme);
  const qc = useQueryClient();

  const [reveal, setReveal] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // мастер «Мигрировать на новый VPS»: новые SSH-реквизиты; secret пустой → оставить текущий
  const [migrateForm, setMigrateForm] = useState<{
    ip: string;
    sshUser: string;
    sshPort: string;
    auth: string;
    secret: string;
  } | null>(null);
  const [advancedVpn, setAdvancedVpn] = useState<VpnType | null>(null);
  // подтверждение сноса всего вендора (все его протоколы + доступы разом)
  const [confirmRemoveVpn, setConfirmRemoveVpn] = useState<VpnType | null>(null);
  // модалка выбора протоколов для установки/докачки: активный вендор + отмеченные id
  const [addProtoVendor, setAddProtoVendor] = useState<VpnType | null>(null);
  const [checkedProtos, setCheckedProtos] = useState<Set<string>>(new Set());
  // подтверждение удаления одного протокола (сносит контейнер + отзывает его конфиги)
  const [confirmRemoveProto, setConfirmRemoveProto] = useState<{
    vendor: VpnType;
    proto: string;
    label: string;
  } | null>(null);
  // активный раздел — в URL (/servers/{id}/{tab}), чтобы на него можно было дать ссылку и делиться
  const tabParam = useNav((s) => s.params.tab);
  const activeTab: ServerDetailTab = SERVER_TABS.includes(tabParam as ServerDetailTab)
    ? (tabParam as ServerDetailTab)
    : "connection";
  const setActiveTab = (tab: ServerDetailTab) => go("server", { serverId, tab });

  const serverQ = useQuery({
    queryKey: ["server", serverId],
    queryFn: () => q.getServer(serverId),
    enabled: !!serverId,
    // прогресс/статус приходят пушем по SSE (см. lib/events); поллинг оставлен СТРАХОВКОЙ
    // на случай тихого обрыва SSE (буферизация прокси / потеря сети) — частоты снижены.
    refetchInterval: (query) => {
      const s = query.state.data as Server | undefined;
      // свежесозданный сервер (ещё не проверен) — ждём авто-пинг/синк, опрашиваем чуть чаще
      if (s?.status === "unknown") return 10000;
      return s?.protocols?.some((p) => p.state === "installing") ? 10000 : 60000;
    },
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["server", serverId] });
    qc.invalidateQueries({ queryKey: ["servers"] });
  };

  const checkMut = useMutation({
    mutationFn: () => q.checkServer(serverId),
    onSuccess: (s) => {
      invalidate();
      toast(
        s.status === "online"
          ? t("srvDetail.serverOnlineLatency", { latency: s.latency ?? "—" })
          : t("srvDetail.serverUnreachable"),
      );
    },
    onError: () => toast(t("srvDetail.checkFailed")),
  });

  const syncMut = useMutation({
    mutationFn: () => q.syncServer(serverId),
    onSuccess: () => {
      invalidate();
      toast(t("srvDetail.syncSuccess"));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("srvDetail.syncFailed")),
  });

  const opMut = useMutation({
    mutationFn: ({ type, op, protos }: { type: VpnType; op: string; protos?: string[] }) =>
      q.vpnOp(serverId, type, op, protos),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      const label = VPN_LABEL[vars.type];
      const msg =
        vars.op === "install"
          ? // установка идёт в фоне (mark_installing + schedule_install),
            // ответ приходит мгновенно — сообщаем о старте, а не о завершении
            t("srvDetail.installStarted", { label })
          : vars.op === "remove"
            ? t("srvDetail.vpnRemoved", { label })
            : vars.op === "start"
              ? t("srvDetail.vpnStarted", { label })
              : t("srvDetail.vpnStopped", { label });
      toast(msg);
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("srvDetail.operationError")),
  });

  const removeProtoMut = useMutation({
    mutationFn: ({ proto }: { proto: string; label: string }) => q.removeProtocol(serverId, proto),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      toast(t("srvDetail.protoRemoved", { label: vars.label }));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("srvDetail.protoRemoveFailed")),
  });

  // свитчер отдельного протокола: временно остановить / снова запустить его контейнер
  const protoOpMut = useMutation({
    mutationFn: ({ proto, op }: { proto: string; label: string; op: string }) => q.protocolOp(serverId, proto, op),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      toast(
        vars.op === "start"
          ? t("srvDetail.vpnStarted", { label: vars.label })
          : t("srvDetail.vpnStopped", { label: vars.label }),
      );
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("srvDetail.operationError")),
  });

  // обновление серверного компонента протокола (xray/hysteria2) до эталонной версии релиза панели
  const updateProtoMut = useMutation({
    mutationFn: ({ proto }: { proto: string; label: string }) => q.updateProtocol(serverId, proto),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      toast(t("srvDetail.updateStarted", { label: vars.label }));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("srvDetail.updateStartFailed")),
  });

  const fixMut = useMutation({
    mutationFn: ({ type }: { type: VpnType }) => q.vpnFix(serverId, type),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      // фикс устраняет причину и запускает переустановку в фоне — сообщаем о старте
      toast(t("srvDetail.fixStarted", { label: VPN_LABEL[vars.type] }));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("srvDetail.fixStartFailed")),
  });

  // миграция на новый VPS: реквизиты меняются сразу, протоколы переустанавливаются в фоне
  // (прогресс виден через state=installing, как обычная установка); конфиги — к перевыдаче
  const migrateMut = useMutation({
    mutationFn: (b: { ip: string; sshPort?: string; sshUser?: string; auth?: string; secret?: string }) =>
      q.migrateServer(serverId, b),
    onSuccess: (r) => {
      setMigrateForm(null);
      invalidate();
      const protoCount = Object.values(r.reinstall).reduce((n, ids) => n + ids.length, 0);
      toast(
        protoCount
          ? t("srvDetail.migrationStarted", { n: protoCount, revoked: r.configsRevoked })
          : t("srvDetail.migrationNoProtocols"),
      );
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("srvDetail.migrationStartFailed")),
  });

  const deleteMut = useMutation({
    mutationFn: () => q.deleteServer(serverId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["servers"] });
      toast(t("srvDetail.serverDeleted"));
      go("servers");
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("srvDetail.serverDeleteFailed")),
  });

  if (serverQ.isLoading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
        <Spinner />
      </div>
    );
  }
  if (serverQ.isError || !serverQ.data) {
    return (
      <div className="stack">
        <ScreenHeader title={t("srvDetail.server")} onBack={() => go("servers")} />
        <div className="card muted">{t("srvDetail.serverNotFound")}</div>
      </div>
    );
  }

  const server: Server = serverQ.data;
  const checking = checkMut.isPending;
  const online = server.status === "online";
  const authLabel = server.auth === "key" ? t("srvDetail.sshKey") : t("srvDetail.password");
  const secretShown = reveal ? server.secret : "•".repeat(Math.max(6, server.secret.length || 6));

  const vpnByType = (vt: VpnType): Vpn =>
    server.vpns.find((v) => v.type === vt) ?? { type: vt, installed: false, running: false, port: "" };
  const protosByVendor = (vt: VpnType): Protocol[] => (server.protocols ?? []).filter((p) => p.vendor === vt);
  const syncing = syncMut.isPending;
  const tabs: { id: ServerDetailTab; label: string; icon: string }[] = [
    { id: "connection", label: t("srvDetail.tabConnection"), icon: "link" },
    { id: "protocols", label: t("srvDetail.tabProtocols"), icon: "servers" },
    { id: "monitoring", label: t("nav.monitoring"), icon: "monitoring" },
    { id: "access", label: t("srvDetail.tabAccess"), icon: "users" },
  ];

  return (
    <div className="stack">
      <ScreenHeader
        title={server.name}
        sub={`${server.provider} · ${server.location}`}
        onBack={() => go("servers")}
        action={
          <div className="rowflex" style={{ flexWrap: "nowrap" }}>
            <Btn sm onClick={() => go("serverForm", { serverId })}>
              <Icon name="edit" size={16} />
              {t("common.edit")}
            </Btn>
            <Btn variant="danger" sm onClick={() => setConfirmDelete(true)}>
              <Icon name="trash" size={16} />
            </Btn>
          </div>
        }
      />

      {/* Статус */}
      <div className="card">
        <div className="rowflex" style={{ justifyContent: "space-between" }}>
          <div className="rowflex">
            <StatusBadge status={server.status} />
            {server.latency && (
              <span className="muted" style={{ fontSize: 13 }}>
                {server.latency}
              </span>
            )}
            <span className="muted-3" style={{ fontSize: 13 }}>
              {t("srvDetail.checkedAt", { time: server.lastCheck || t("srvDetail.neverChecked") })}
            </span>
          </div>
          <div className="rowflex" style={{ flexWrap: "nowrap" }}>
            <Btn sm onClick={() => syncMut.mutate()} disabled={syncing}>
              {syncing ? <Spinner /> : <Icon name="refresh" size={16} />}
              {syncing ? t("srvDetail.syncing") : t("srvDetail.synchronize")}
            </Btn>
            <Btn sm onClick={() => checkMut.mutate()} disabled={checking}>
              {checking ? <Spinner /> : <Icon name="refresh" size={16} />}
              {checking ? t("srvDetail.checking") : t("srvDetail.check")}
            </Btn>
          </div>
        </div>
      </div>

      <div className="detail-tabs" role="tablist" aria-label={t("srvDetail.serverSectionsAriaLabel")}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`server-tab-${tab.id}`}
            aria-selected={activeTab === tab.id}
            aria-controls={`server-tabpanel-${tab.id}`}
            className={`detail-tab${activeTab === tab.id ? " active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >
            <Icon name={tab.icon} size={16} />
            <span>{tab.label}</span>
          </button>
        ))}
      </div>
      <label className="detail-tab-select">
        <span>{t("srvDetail.section")}</span>
        <select className="input" value={activeTab} onChange={(e) => setActiveTab(e.target.value as ServerDetailTab)}>
          {tabs.map((tab) => (
            <option key={tab.id} value={tab.id}>
              {tab.label}
            </option>
          ))}
        </select>
      </label>

      {activeTab === "connection" && (
        <div className="stack" role="tabpanel" id="server-tabpanel-connection" aria-labelledby="server-tab-connection">
          {/* SSH */}
          <div className="card stack">
            <div className="rowflex" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
              <div
                className="muted-3"
                style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
              >
                {t("srvDetail.sshConnection")}
              </div>
              <Btn
                sm
                onClick={() =>
                  setMigrateForm({
                    ip: "",
                    sshUser: server.sshUser,
                    sshPort: server.sshPort,
                    auth: server.auth,
                    secret: "",
                  })
                }
              >
                <Icon name="refresh" size={15} />
                {t("srvDetail.migrateToNewVps")}
              </Btn>
            </div>
            <div className="grid">
              <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px" }}>
                <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 4 }}>
                  {t("srvDetail.ipAddress")}
                </div>
                <div className="rowflex" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                  <span className="mono" style={{ fontSize: 13.5 }}>
                    {server.ip}
                  </span>
                  <Btn variant="ghost" sm onClick={() => copyText(server.ip, toast, t("srvDetail.ipCopied"))}>
                    <Icon name="copy" size={15} />
                  </Btn>
                </div>
              </div>

              <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px" }}>
                <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 4 }}>
                  {t("srvDetail.userPort")}
                </div>
                <span className="mono" style={{ fontSize: 13.5 }}>
                  {server.sshUser} : {server.sshPort}
                </span>
              </div>

              <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px" }}>
                <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 4 }}>
                  {authLabel}
                </div>
                <div className="rowflex" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                  <span className="mono" style={{ fontSize: 13.5, minWidth: 0, wordBreak: "break-all" }}>
                    {secretShown}
                  </span>
                  <Btn variant="ghost" sm onClick={() => setReveal((r) => !r)}>
                    <Icon name="eye" size={15} />
                    {reveal ? t("srvDetail.hide") : t("srvDetail.show")}
                  </Btn>
                </div>
              </div>
            </div>
          </div>
          <ServerTrafficQuotaCard server={server} />
          <ServerCostCard serverId={serverId} />
        </div>
      )}

      {activeTab === "protocols" && (
        <div className="stack" role="tabpanel" id="server-tabpanel-protocols" aria-labelledby="server-tab-protocols">
          {/* VPN ПО */}
          <div className="card stack">
            <div
              className="muted-3"
              style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
            >
              {t("srvDetail.vpnSoftwareOnServer")}
            </div>
            <div className="stack" style={{ gap: 10 }}>
              {VPN_TYPES.map((type) => {
                const v = vpnByType(type);
                const protos = protosByVendor(type);
                const catalog = VENDOR_PROTOCOLS[type]; // все протоколы вендора (для выбора/докачки)
                const notInstalled = catalog.filter((pr) => !protos.find((x) => x.proto === pr.id)?.installed);
                const installing = protos.some((p) => p.state === "installing");
                const errored = protos.find((p) => p.state === "error");
                const rem = errored?.remediation ?? null;
                const busy =
                  (opMut.isPending && opMut.variables?.type === type) ||
                  (fixMut.isPending && fixMut.variables?.type === type);
                const runLabel = installing
                  ? t("srvDetail.installingEllipsis")
                  : !v.installed
                    ? t("srvDetail.notInstalled")
                    : v.running
                      ? t("srvDetail.runningState")
                      : t("srvDetail.stoppedState");
                const runClass = installing ? "neutral" : v.installed && v.running ? "ok" : "neutral";
                return (
                  <div
                    key={type}
                    className="stack"
                    style={{
                      border: `1px solid ${errored ? "var(--danger)" : "var(--border)"}`,
                      borderRadius: 13,
                      padding: 13,
                      gap: 12,
                    }}
                  >
                    {/* Шапка: иконка + имя вендора + агрегатный статус (клик — расширенные настройки) */}
                    <div className="rowflex" style={{ gap: 12, flexWrap: "nowrap", alignItems: "flex-start" }}>
                      <div
                        style={{
                          width: 38,
                          height: 38,
                          borderRadius: 10,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          flex: "none",
                          background: "var(--surface-2)",
                          color: `var(--${type})`,
                        }}
                      >
                        {vpnLogo(type, theme) ? (
                          <img
                            src={vpnLogo(type, theme)}
                            alt={VPN_LABEL[type]}
                            width={26}
                            height={26}
                            style={{ objectFit: "contain", display: "block" }}
                          />
                        ) : (
                          <Icon name={VPN_ICON[type]} size={20} />
                        )}
                      </div>
                      <div
                        style={{ flex: 1, minWidth: 0, cursor: v.installed ? "pointer" : "default" }}
                        onClick={v.installed ? () => setAdvancedVpn(type) : undefined}
                      >
                        <div className="rowflex" style={{ gap: 8 }}>
                          <span style={{ fontWeight: 700, fontSize: 15 }}>{VPN_LABEL[type]}</span>
                          <span className={`badge ${runClass}`}>{runLabel}</span>
                          {v.installed && (
                            <span
                              className="muted-3"
                              style={{ display: "inline-flex" }}
                              title={t("srvDetail.advancedSettings")}
                            >
                              <Icon name="chevron" size={14} />
                            </span>
                          )}
                        </div>
                        <div className="muted-3" style={{ fontSize: 12.5, marginTop: 2 }}>
                          {vpnDesc(type)}
                        </div>
                      </div>
                    </div>

                    {/* Протоколы: ровный список со статус-точкой и пер-протокольными действиями */}
                    {(v.installed || installing) && (
                      <div
                        className="stack"
                        style={{ gap: 2, borderTop: "1px solid var(--border)", paddingTop: 10 }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div
                          className="muted-3"
                          style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".04em", textTransform: "uppercase" }}
                        >
                          {t("srvDetail.protocols")}
                        </div>
                        {catalog.map((pr) => {
                          const p = protos.find((x) => x.proto === pr.id);
                          const st = p?.state ?? "absent";
                          const inst = p?.installed ?? false;
                          const running = p?.running ?? false;
                          const ext = p?.externalClients ?? 0;
                          // у установленного показываем работает/остановлен, иначе — состояние установки
                          const stateText = inst
                            ? running
                              ? t("srvDetail.runningState")
                              : t("srvDetail.stoppedState")
                            : (PROTO_STATE_LABEL[st] ?? st);
                          const dotColor =
                            st === "installing"
                              ? "var(--warn)"
                              : inst && running
                                ? "var(--ok)"
                                : inst
                                  ? "var(--warn)"
                                  : "var(--border-strong)";
                          return (
                            <div
                              key={pr.id}
                              className="rowflex"
                              style={{
                                justifyContent: "space-between",
                                gap: 8,
                                flexWrap: "nowrap",
                                minHeight: 34,
                                opacity: inst || st === "installing" ? 1 : 0.55,
                              }}
                            >
                              <span className="rowflex" style={{ gap: 8, minWidth: 0, flexWrap: "nowrap" }}>
                                <span
                                  style={{
                                    width: 7,
                                    height: 7,
                                    borderRadius: 999,
                                    flex: "none",
                                    background: dotColor,
                                  }}
                                />
                                <span
                                  style={{
                                    fontSize: 13,
                                    fontWeight: 600,
                                    whiteSpace: "nowrap",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                  }}
                                >
                                  {pr.label}
                                </span>
                                <span
                                  className="muted-3"
                                  style={{ fontSize: 11.5, whiteSpace: "nowrap", flex: "none" }}
                                >
                                  {stateText}
                                  {ext > 0 ? ` · ${t("srvDetail.externalCountSuffix", { n: ext })}` : ""}
                                </span>
                                {p?.updateAvailable && (
                                  <span
                                    className="badge warn"
                                    title={t("srvDetail.updateAvailableTooltip", {
                                      current: p.imageVersion ?? "?",
                                      latest: p.latestVersion ?? "?",
                                    })}
                                    style={{ flex: "none" }}
                                  >
                                    {t("srvDetail.updateBadge")}
                                  </span>
                                )}
                              </span>
                              {inst && (
                                <div className="rowflex" style={{ flexWrap: "nowrap", gap: 6, flex: "none" }}>
                                  {p?.updateAvailable && (
                                    <Btn
                                      variant="primary"
                                      sm
                                      disabled={!online || updateProtoMut.isPending}
                                      title={t("srvDetail.updateToVersion", { version: p.latestVersion ?? "" })}
                                      onClick={() => updateProtoMut.mutate({ proto: pr.id, label: pr.label })}
                                    >
                                      {t("srvDetail.updateAction")}
                                    </Btn>
                                  )}
                                  <Btn
                                    sm
                                    disabled={!online || protoOpMut.isPending}
                                    onClick={() =>
                                      protoOpMut.mutate({
                                        proto: pr.id,
                                        label: pr.label,
                                        op: running ? "stop" : "start",
                                      })
                                    }
                                  >
                                    {running ? t("srvDetail.stopAction") : t("srvDetail.startAction")}
                                  </Btn>
                                  <Btn
                                    variant="ghost"
                                    sm
                                    title={t("srvDetail.deleteProtocolTooltip", { label: pr.label })}
                                    disabled={removeProtoMut.isPending}
                                    onClick={() =>
                                      setConfirmRemoveProto({ vendor: type, proto: pr.id, label: pr.label })
                                    }
                                  >
                                    <Icon name="trash" size={13} />
                                  </Btn>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Диагностика ошибки установки/сбоя протокола */}
                    {errored && (
                      <div onClick={(e) => e.stopPropagation()}>
                        {rem ? (
                          <div className="stack" style={{ gap: 3 }}>
                            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--danger)" }}>{rem.title}</div>
                            <div className="muted-3" style={{ fontSize: 11.5, wordBreak: "break-word" }}>
                              {rem.explanation}
                            </div>
                            {rem.manualSteps.length > 0 && (
                              <ol
                                className="muted-3"
                                style={{ fontSize: 11.5, margin: "2px 0 0", paddingLeft: 16, lineHeight: 1.5 }}
                              >
                                {rem.manualSteps.map((step, i) => (
                                  <li key={i} style={{ wordBreak: "break-word" }}>
                                    {step}
                                  </li>
                                ))}
                              </ol>
                            )}
                          </div>
                        ) : (
                          errored.error && (
                            <div className="muted-3" style={{ fontSize: 11.5, wordBreak: "break-word" }}>
                              {t("srvDetail.errorPrefix", { error: errored.error })}
                            </div>
                          )
                        )}
                      </div>
                    )}

                    {/* Действия по вендору: докачать / остановить всё / удалить ПО целиком */}
                    <div
                      className="rowflex"
                      style={{ gap: 8, borderTop: "1px solid var(--border)", paddingTop: 11 }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {installing ? (
                        <span className="rowflex" style={{ gap: 8 }}>
                          <Spinner />
                          <span className="muted-3" style={{ fontSize: 12.5 }}>
                            {t("srvDetail.installingEllipsisLong")}
                          </span>
                        </span>
                      ) : busy ? (
                        <Spinner />
                      ) : (
                        <>
                          {/* fix доступен и в installed-состоянии (частичный сбой: один протокол упал) */}
                          {rem?.canAutoFix && (
                            <Btn variant="primary" sm onClick={() => fixMut.mutate({ type })}>
                              {rem.fixLabel ?? t("srvDetail.fixAction")}
                            </Btn>
                          )}
                          {notInstalled.length > 0 && (
                            <Btn
                              variant={v.installed || rem?.canAutoFix ? "ghost" : "primary"}
                              sm
                              onClick={() => {
                                setCheckedProtos(new Set(notInstalled.map((p) => p.id)));
                                setAddProtoVendor(type);
                              }}
                            >
                              {v.installed ? t("srvDetail.addProtocolsAction") : t("srvDetail.installAction")}
                            </Btn>
                          )}
                          {v.installed && (
                            <Btn
                              sm
                              disabled={!online}
                              onClick={() => opMut.mutate({ type, op: v.running ? "stop" : "start" })}
                            >
                              {v.running ? t("srvDetail.stopAllAction") : t("srvDetail.startAllAction")}
                            </Btn>
                          )}
                          {v.installed && (
                            <Btn
                              variant="ghost"
                              sm
                              title={t("srvDetail.deleteVendorTooltip", { label: VPN_LABEL[type] })}
                              style={{ marginLeft: "auto" }}
                              onClick={() => setConfirmRemoveVpn(type)}
                            >
                              <Icon name="trash" size={15} />
                            </Btn>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          <ChainSection server={server} />
        </div>
      )}

      {activeTab === "monitoring" && (
        <div className="stack" role="tabpanel" id="server-tabpanel-monitoring" aria-labelledby="server-tab-monitoring">
          <ServerMetricsCard serverId={serverId} online={online} />
          <ServerClientsCard serverId={serverId} online={online} />
        </div>
      )}

      {activeTab === "access" && (
        <div className="stack" role="tabpanel" id="server-tabpanel-access" aria-labelledby="server-tab-access">
          <ServerAccessSections serverId={serverId} />
        </div>
      )}

      {advancedVpn && <VpnAdvancedModal serverId={serverId} vtype={advancedVpn} onClose={() => setAdvancedVpn(null)} />}

      {confirmDelete && (
        <Modal
          title={t("srvDetail.deleteServerTitle")}
          onClose={() => setConfirmDelete(false)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setConfirmDelete(false)}>
                {t("common.cancel")}
              </Btn>
              <Btn variant="danger" disabled={deleteMut.isPending} onClick={() => deleteMut.mutate()}>
                {t("common.delete")}
              </Btn>
            </>
          }
        >
          <p className="muted">{t("srvDetail.deleteServerBody")}</p>
        </Modal>
      )}

      {/* Миграция на новый VPS: новые SSH-реквизиты + переустановка протоколов в фоне */}
      {migrateForm && (
        <Modal
          title={t("srvDetail.migrateModalTitle")}
          onClose={() => setMigrateForm(null)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setMigrateForm(null)}>
                {t("common.cancel")}
              </Btn>
              <Btn
                variant="primary"
                disabled={migrateMut.isPending || !migrateForm.ip.trim()}
                onClick={() =>
                  migrateMut.mutate({
                    ip: migrateForm.ip.trim(),
                    sshPort: migrateForm.sshPort.trim() || undefined,
                    sshUser: migrateForm.sshUser.trim() || undefined,
                    auth: migrateForm.auth || undefined,
                    secret: migrateForm.secret || undefined,
                  })
                }
              >
                {migrateMut.isPending ? <Spinner /> : t("srvDetail.migrateAction")}
              </Btn>
            </>
          }
        >
          <div className="stack" style={{ gap: 10 }}>
            <p className="muted" style={{ fontSize: 13 }}>
              {t("srvDetail.migrateHelp")}
            </p>
            <Field label={t("srvDetail.newServerIpLabel")}>
              <input
                className="input mono"
                value={migrateForm.ip}
                onChange={(e) => setMigrateForm({ ...migrateForm, ip: e.target.value })}
                placeholder="203.0.113.10"
              />
            </Field>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
              <Field label={t("srvDetail.userLabel")}>
                <input
                  className="input mono"
                  value={migrateForm.sshUser}
                  onChange={(e) => setMigrateForm({ ...migrateForm, sshUser: e.target.value })}
                  placeholder="root"
                />
              </Field>
              <Field label={t("srvDetail.portLabel")}>
                <input
                  className="input mono"
                  value={migrateForm.sshPort}
                  onChange={(e) => setMigrateForm({ ...migrateForm, sshPort: e.target.value })}
                  placeholder="22"
                />
              </Field>
            </div>
            <Field label={t("srvDetail.authMethodLabel")}>
              <div style={{ display: "flex", gap: 8 }}>
                {(["key", "password"] as const).map((a) => (
                  <button
                    key={a}
                    type="button"
                    className={`chip${migrateForm.auth === a ? " selected" : ""}`}
                    style={{ flex: 1, height: 40, justifyContent: "center", cursor: "pointer", fontSize: 13.5 }}
                    onClick={() => setMigrateForm({ ...migrateForm, auth: a })}
                  >
                    {a === "key" ? t("srvDetail.sshKey") : t("srvDetail.password")}
                  </button>
                ))}
              </div>
            </Field>
            <Field label={migrateForm.auth === "password" ? t("srvDetail.password") : t("srvDetail.privateSshKey")}>
              <input
                className="input mono"
                type={migrateForm.auth === "password" ? "password" : "text"}
                value={migrateForm.secret}
                onChange={(e) => setMigrateForm({ ...migrateForm, secret: e.target.value })}
                placeholder={t("srvDetail.migrateSecretPlaceholder")}
              />
            </Field>
          </div>
        </Modal>
      )}

      {/* Выбор протоколов для установки/докачки (галочки) */}
      {addProtoVendor && (
        <Modal
          title={t("srvDetail.installProtocolsModalTitle", { label: VPN_LABEL[addProtoVendor] })}
          onClose={() => setAddProtoVendor(null)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setAddProtoVendor(null)}>
                {t("common.cancel")}
              </Btn>
              <Btn
                variant="primary"
                disabled={checkedProtos.size === 0 || opMut.isPending}
                onClick={() => {
                  const type = addProtoVendor;
                  const protos = [...checkedProtos];
                  setAddProtoVendor(null);
                  opMut.mutate({ type, op: "install", protos });
                }}
              >
                {checkedProtos.size
                  ? t("srvDetail.installActionCount", { n: checkedProtos.size })
                  : t("srvDetail.installAction")}
              </Btn>
            </>
          }
        >
          <div className="stack" style={{ gap: 8 }}>
            <p className="muted" style={{ fontSize: 13 }}>
              {t("srvDetail.installProtocolsHelp")}
            </p>
            {VENDOR_PROTOCOLS[addProtoVendor]
              .filter((pr) => !protosByVendor(addProtoVendor).find((x) => x.proto === pr.id)?.installed)
              .map((pr) => {
                const on = checkedProtos.has(pr.id);
                return (
                  <label
                    key={pr.id}
                    className="rowflex"
                    style={{
                      gap: 11,
                      cursor: "pointer",
                      padding: "11px 13px",
                      border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`,
                      borderRadius: 10,
                      background: on ? "var(--accent-soft)" : "var(--surface)",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() =>
                        setCheckedProtos((prev) => {
                          const next = new Set(prev);
                          if (on) next.delete(pr.id);
                          else next.add(pr.id);
                          return next;
                        })
                      }
                    />
                    <span style={{ fontWeight: 600, fontSize: 14, flex: 1 }}>{pr.label}</span>
                  </label>
                );
              })}
          </div>
        </Modal>
      )}

      {/* Удаление одного протокола (сносит контейнер + отзывает его конфиги) */}
      {confirmRemoveProto && (
        <Modal
          title={t("srvDetail.deleteProtocolTitle", { label: confirmRemoveProto.label })}
          onClose={() => setConfirmRemoveProto(null)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setConfirmRemoveProto(null)}>
                {t("common.cancel")}
              </Btn>
              <Btn
                variant="danger"
                disabled={removeProtoMut.isPending}
                onClick={() => {
                  const { proto, label } = confirmRemoveProto;
                  setConfirmRemoveProto(null);
                  removeProtoMut.mutate({ proto, label });
                }}
              >
                {t("common.delete")}
              </Btn>
            </>
          }
        >
          <p className="muted">{t("srvDetail.deleteProtocolBody")}</p>
        </Modal>
      )}

      {/* Снос всего вендора: все его протоколы + групповые доступы разом */}
      {confirmRemoveVpn && (
        <Modal
          title={t("srvDetail.deleteVendorTitle", { label: VPN_LABEL[confirmRemoveVpn] })}
          onClose={() => setConfirmRemoveVpn(null)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setConfirmRemoveVpn(null)}>
                {t("common.cancel")}
              </Btn>
              <Btn
                variant="danger"
                disabled={opMut.isPending}
                onClick={() => {
                  const type = confirmRemoveVpn;
                  setConfirmRemoveVpn(null);
                  opMut.mutate({ type, op: "remove" });
                }}
              >
                {t("srvDetail.deleteAllAction")}
              </Btn>
            </>
          }
        >
          <p className="muted">{t("srvDetail.deleteVendorBody")}</p>
        </Modal>
      )}
    </div>
  );
}
