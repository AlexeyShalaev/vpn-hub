// Супер-мониторинг клиентов (владелец): единая таблица per-client трафика+онлайна по ВСЕМ
// серверам и протоколам. Данные — GET /monitoring (TrafficService.global_overview), собранные
// в monitor-тике по SSH (wg dump / xray statsquery / hysteria trafficStats). Сводка сверху +
// фильтр по серверу/протоколу + сортировка + честный диагноз сбора. Поллинг как у остального owner-UI.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { LineChart } from "../components/chart";
import { Btn, Empty, Icon, Modal, MultiSelect, ScreenHeader, Spinner } from "../components/ui";
import type { TFunc } from "../lib/i18n";
import { tg, useT } from "../lib/i18n";
import * as q from "../lib/queries";
import type { CollectionHealth, MonitoringClient } from "../lib/types";
import { useStore } from "../store";

// свежесть данных сбора: max lastCollectedAt по всем серверам (для «обновлено N назад»)
function collectionFreshness(collection?: Record<string, CollectionHealth>): number | null {
  if (!collection) return null;
  let max: number | null = null;
  for (const c of Object.values(collection)) {
    if (c.lastCollectedAt != null && (max == null || c.lastCollectedAt > max)) max = c.lastCollectedAt;
  }
  return max;
}

// честный диагноз пустого мониторинга вместо общей фразы «нет данных» — по статусам сбора
function collectionDiagnosis(t: TFunc, collection?: Record<string, CollectionHealth>): string {
  const servers = collection ? Object.values(collection) : [];
  if (servers.length === 0) return t("mon.diagAddServer");
  const protos = servers.flatMap((c) => c.protocols);
  if (protos.length === 0) return t("mon.diagNoProtocols");
  const statuses = new Set(protos.map((p) => p.status));
  if (statuses.has("ok")) return t("mon.diagNoTrafficYet");
  if (statuses.has("unreachable")) return t("mon.diagUnreachable");
  if (statuses.has("container_down")) return t("mon.diagContainerDown");
  if (statuses.has("stats_disabled")) return t("mon.diagStatsDisabled");
  return t("mon.diagCollectingBackground");
}

const PERIODS = ["1h", "24h", "7d", "30d", "90d", "365d"] as const;
type Period = (typeof PERIODS)[number];
function periodLabel(t: TFunc, p: Period): string {
  switch (p) {
    case "1h":
      return t("mon.period1h");
    case "24h":
      return t("period.24h");
    case "7d":
      return t("period.7d");
    case "30d":
      return t("period.30d");
    case "90d":
      return t("period.90d");
    case "365d":
      return t("mon.periodYear");
  }
}

function protoLabel(t: TFunc, p: string): string {
  switch (p) {
    case "awg":
      return t("proto.awg");
    case "awg_legacy":
      return t("proto.awgLegacy");
    case "xray":
      return t("proto.xray");
    case "xray_xhttp":
      return t("proto.xrayXhttp");
    case "hysteria2":
      return t("proto.hysteria2");
    case "openvpn":
      return t("proto.openvpn");
    case "outline":
      return t("proto.outline");
    default:
      return p;
  }
}

// человекочитаемые байты (как в ServerDetail)
const BYTE_UNIT_KEYS = ["unit.byte", "unit.kilobyte", "unit.megabyte", "unit.gigabyte", "unit.terabyte"] as const;
export const fmtBytes = (n: number | null | undefined): string => {
  if (n == null) return "—";
  let v = n;
  let i = 0;
  while (v >= 1024 && i < BYTE_UNIT_KEYS.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${tg(BYTE_UNIT_KEYS[i])}`;
};
export const fmtSpeed = (bytesPerSec: number): string =>
  bytesPerSec > 0 ? `${fmtBytes(bytesPerSec)}/${tg("unit.perSecond")}` : "—";

const fmtAgo = (t: TFunc, at: number | null): string => {
  if (at == null) return "—";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - at));
  if (s < 60) return t("mon.justNow");
  if (s < 3600) return t("mon.minutesAgo", { n: Math.floor(s / 60) });
  if (s < 86400) return t("mon.hoursAgo", { n: Math.floor(s / 3600) });
  return t("mon.daysAgo", { n: Math.floor(s / 86400) });
};

type SortKey = "traffic" | "speed" | "name";

function OnlineDot({ online, title }: { online: boolean; title: string }) {
  return (
    <span
      title={title}
      style={{
        display: "inline-block",
        width: 9,
        height: 9,
        borderRadius: "50%",
        flex: "none",
        background: online ? "var(--ok, #22c55e)" : "var(--border-strong, #9ca3af)",
        boxShadow: online ? "0 0 0 3px color-mix(in srgb, #22c55e 25%, transparent)" : "none",
      }}
    />
  );
}

function SummaryTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ background: "var(--surface-2)", borderRadius: 12, padding: "13px 15px", minWidth: 0 }}>
      <div className="muted-3" style={{ fontSize: 12, marginBottom: 5 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, lineHeight: 1.05 }}>{value}</div>
      {sub && (
        <div className="muted-3" style={{ fontSize: 12, marginTop: 3 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function clientName(t: TFunc, c: MonitoringClient): string {
  if (c.userName || c.deviceName) return [c.userName, c.deviceName].filter(Boolean).join(" · ");
  // external-клиент (заведён мимо панели) — покажем имя из Amnezia clientsTable, если оно есть
  if (c.external) return c.extName || t("mon.externalClient");
  return c.clientId ?? "—";
}

// График трафика одного клиента за период. Данные — per-server overview (`series` = per-client
// дельты по времени); фильтруем по clientId+proto этого клиента и группируем по времени (at).
// Значения — байт за интервал сбора; для читаемости отрисовываем в МБ (две линии: download/upload).
export function ClientTrafficModal({
  client,
  period,
  periodLabel,
  onClose,
}: {
  client: MonitoringClient;
  period: Period;
  periodLabel: string;
  onClose: () => void;
}) {
  const t = useT();
  const sid = client.serverId ?? "";
  const tq = useQuery({
    queryKey: ["serverTraffic", sid, period],
    queryFn: () => q.serverTraffic(sid, period),
    enabled: !!sid,
    refetchInterval: 30000,
    retry: 2,
  });

  // series → две линии (rx/tx) точками {at, value в МБ}, отфильтрованные по этому клиенту.
  const { rxPoints, txPoints } = useMemo(() => {
    const MB = 1024 * 1024;
    const rx: { at: number; value: number }[] = [];
    const tx: { at: number; value: number }[] = [];
    // сумма по at на случай, если клиент присутствует несколько раз в один момент
    const rxAt = new Map<number, number>();
    const txAt = new Map<number, number>();
    for (const s of tq.data?.series ?? []) {
      if (s.clientId !== client.clientId || s.proto !== client.proto) continue;
      rxAt.set(s.at, (rxAt.get(s.at) ?? 0) + s.rx);
      txAt.set(s.at, (txAt.get(s.at) ?? 0) + s.tx);
    }
    for (const [at, v] of [...rxAt.entries()].sort((a, b) => a[0] - b[0])) rx.push({ at, value: v / MB });
    for (const [at, v] of [...txAt.entries()].sort((a, b) => a[0] - b[0])) tx.push({ at, value: v / MB });
    return { rxPoints: rx, txPoints: tx };
  }, [tq.data, client.clientId, client.proto]);

  const hasData = rxPoints.length > 0 || txPoints.length > 0;
  // подпись интервала точки графика по ярусу series (0 = сырьё/интервал сбора)
  const bucket = tq.data?.seriesBucketSeconds ?? 0;
  const bucketLabel = bucket >= 86400 ? t("mon.perDay") : bucket >= 3600 ? t("mon.perHour") : t("mon.perInterval");

  return (
    <Modal title={t("mon.clientTrafficTitle", { name: clientName(t, client) })} onClose={onClose} wide>
      <div className="stack" style={{ gap: 12 }}>
        <div className="muted-3" style={{ fontSize: 12.5 }}>
          {protoLabel(t, client.proto)}
          {client.serverName ? ` · ${client.serverName}` : ""}
          {" · "}
          {t("mon.forPeriodValuesInMb", { period: periodLabel, bucket: bucketLabel })}
        </div>
        {tq.isLoading ? (
          <div style={{ padding: 24, textAlign: "center" }}>
            <Spinner />
          </div>
        ) : !hasData ? (
          <Empty title={t("mon.noTrafficPointsYet")} sub={t("mon.historyAccumulatesHint")} />
        ) : (
          <LineChart
            lines={[
              { points: txPoints, color: "#3b82f6", label: t("mon.downloadedMb") },
              { points: rxPoints, color: "#22c55e", label: t("mon.uploadedMb") },
            ]}
          />
        )}
        <div className="rowflex" style={{ gap: 16, fontSize: 13, flexWrap: "wrap" }}>
          <span>
            {t("mon.totalDownloaded")} <b>{fmtBytes(client.txTotal)}</b>
          </span>
          <span>
            {t("mon.totalUploaded")} <b>{fmtBytes(client.rxTotal)}</b>
          </span>
        </div>
      </div>
    </Modal>
  );
}

export function MonitoringScreen() {
  const t = useT();
  const [period, setPeriod] = useState<Period>("24h");
  const [selServers, setSelServers] = useState<string[]>([]);
  const [selProtos, setSelProtos] = useState<string[]>([]);
  const [selUsers, setSelUsers] = useState<string[]>([]);
  const [sort, setSort] = useState<SortKey>("traffic");
  const [selected, setSelected] = useState<MonitoringClient | null>(null);

  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const mq = useQuery({
    queryKey: ["monitoring", period],
    queryFn: () => q.monitoring(period),
    refetchInterval: 30000,
    // глобально retry=false и refetchOnWindowFocus=false (main.tsx) → разовый сбой фетча оставлял
    // экран пустым до следующего 30с-тика («мониторинг раз через раз»). Здесь чиним точечно:
    retry: 2,
    refetchOnWindowFocus: true,
  });
  // ручная пауза/старт конфига прямо из мониторинга (тот же suspend/resume, статус paused/active)
  const pauseMut = useMutation({
    mutationFn: (v: { sid: string; cid: string; pause: boolean }) =>
      v.pause ? q.pauseServerClient(v.sid, v.cid) : q.resumeServerClient(v.sid, v.cid),
    onSuccess: (_r, v) => {
      qc.invalidateQueries({ queryKey: ["monitoring"] });
      toast(v.pause ? t("mon.configPaused") : t("mon.configResumed"));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("common.error")),
  });

  const clients = mq.data?.clients ?? [];
  const summary = mq.data?.summary;
  const freshness = collectionFreshness(mq.data?.collection);

  // варианты для фильтров — из полученных данных (мультивыбор)
  const serverOpts = useMemo(() => {
    const seen = new Map<string, string>();
    for (const c of clients) if (c.serverId) seen.set(c.serverId, c.serverName || c.serverId);
    return [...seen.entries()] as [string, string][];
  }, [clients]);
  const protoOpts = useMemo(
    () => [...new Set(clients.map((c) => c.proto))].map((p) => [p, protoLabel(t, p)] as [string, string]),
    [clients, t],
  );
  const userOpts = useMemo(() => {
    const seen = new Set<string>();
    for (const c of clients) if (c.userName) seen.add(c.userName);
    return [...seen].sort((a, b) => a.localeCompare(b, "ru")).map((u) => [u, u] as [string, string]);
  }, [clients]);
  const anyFilter = selServers.length > 0 || selProtos.length > 0 || selUsers.length > 0;

  const rows = useMemo(() => {
    // пустой набор в фильтре = «все»; иначе — членство. Пользователь фильтруется по userName
    // (external-клиенты без userName выпадают, когда фильтр по пользователям активен).
    let out = clients.filter(
      (c) =>
        (selServers.length === 0 || (c.serverId != null && selServers.includes(c.serverId))) &&
        (selProtos.length === 0 || selProtos.includes(c.proto)) &&
        (selUsers.length === 0 || selUsers.includes(c.userName)),
    );
    const cmp: Record<SortKey, (a: MonitoringClient, b: MonitoringClient) => number> = {
      traffic: (a, b) => b.rxTotal + b.txTotal - (a.rxTotal + a.txTotal),
      speed: (a, b) => b.rxSpeed + b.txSpeed - (a.rxSpeed + a.txSpeed),
      name: (a, b) => clientName(t, a).localeCompare(clientName(t, b), "ru"),
    };
    // онлайн — всегда выше при равенстве по остальным критериям
    out = [...out].sort((a, b) => cmp[sort](a, b) || Number(b.online) - Number(a.online));
    return out;
  }, [clients, selServers, selProtos, selUsers, sort]);

  const th: React.CSSProperties = {
    textAlign: "left",
    padding: "8px 10px",
    fontSize: 12,
    fontWeight: 600,
    color: "var(--text-3)",
    whiteSpace: "nowrap",
    borderBottom: "1px solid var(--border)",
  };
  const td: React.CSSProperties = { padding: "9px 10px", fontSize: 13.5, borderBottom: "1px solid var(--border)" };
  const num: React.CSSProperties = {
    ...td,
    textAlign: "right",
    fontVariantNumeric: "tabular-nums",
    whiteSpace: "nowrap",
  };

  return (
    <div className="stack" style={{ gap: 16 }}>
      <ScreenHeader title={t("nav.monitoring")} sub={t("mon.headerSub")} />

      {/* Отдельная строка управления: на десктопе — таблетки-периоды, на мобиле — компактный select
          (иначе описание и период не помещаются в одну строку). Свежесть и «обновить» — справа. */}
      <div className="period-controls">
        <div className="period-pills">
          {PERIODS.map((p) => (
            <Btn key={p} variant={p === period ? "primary" : "ghost"} sm onClick={() => setPeriod(p)}>
              {periodLabel(t, p)}
            </Btn>
          ))}
        </div>
        <select
          className="period-select"
          value={period}
          onChange={(e) => setPeriod(e.target.value as Period)}
          aria-label={t("mon.periodAriaLabel")}
        >
          {PERIODS.map((p) => (
            <option key={p} value={p}>
              {periodLabel(t, p)}
            </option>
          ))}
        </select>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
          {freshness != null && (
            <span className="muted-3" style={{ fontSize: 12, whiteSpace: "nowrap" }} title={t("mon.freshnessHint")}>
              {t("mon.updatedAgo", { ago: fmtAgo(t, freshness) })}
            </span>
          )}
          <Btn
            variant="ghost"
            sm
            onClick={() => mq.refetch()}
            disabled={mq.isFetching}
            title={t("mon.refreshMetrics")}
            aria-label={t("mon.refresh")}
          >
            {mq.isFetching ? <Spinner /> : <Icon name="refresh" size={16} />}
          </Btn>
        </div>
      </div>

      {/* сводка */}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        <SummaryTile
          label={t("mon.onlineNow")}
          value={summary ? String(summary.clientsOnline) : "—"}
          sub={summary ? t("mon.ofClients", { n: summary.clientsTotal }) : undefined}
        />
        <SummaryTile
          label={t("mon.downloadedLabel")}
          value={fmtBytes(summary?.txTotal)}
          sub={t("mon.forPeriod", { period: periodLabel(t, period) })}
        />
        <SummaryTile
          label={t("mon.uploadedLabel")}
          value={fmtBytes(summary?.rxTotal)}
          sub={t("mon.forPeriod", { period: periodLabel(t, period) })}
        />
        <SummaryTile label={t("mon.serversLabel")} value={summary ? String(summary.serversTotal) : "—"} />
      </div>

      {/* фильтры (мультивыбор через выпадашки: пусто = все) + сортировка */}
      <div className="rowflex" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <MultiSelect
          label={t("mon.serversFilterLabel")}
          options={serverOpts}
          selected={selServers}
          onChange={setSelServers}
        />
        <MultiSelect
          label={t("mon.protocolsFilterLabel")}
          options={protoOpts}
          selected={selProtos}
          onChange={setSelProtos}
        />
        <MultiSelect label={t("mon.usersFilterLabel")} options={userOpts} selected={selUsers} onChange={setSelUsers} />
        {anyFilter && (
          <Btn
            variant="ghost"
            sm
            onClick={() => {
              setSelServers([]);
              setSelProtos([]);
              setSelUsers([]);
            }}
          >
            {t("mon.resetFilters")}
          </Btn>
        )}
        <span className="muted-3" style={{ fontSize: 12 }}>
          {t("mon.shown", { n: rows.length })}
        </span>
        <div style={{ flex: 1 }} />
        <span className="muted-3" style={{ fontSize: 12 }}>
          {t("mon.sortLabel")}
        </span>
        {(["traffic", "speed", "name"] as SortKey[]).map((s) => (
          <Btn key={s} variant={s === sort ? "primary" : "ghost"} sm onClick={() => setSort(s)}>
            {s === "traffic" ? t("mon.sortByTraffic") : s === "speed" ? t("mon.sortBySpeed") : t("mon.sortByName")}
          </Btn>
        ))}
      </div>

      {/* таблица клиентов */}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {mq.isLoading ? (
          <div style={{ padding: 24 }}>
            <Spinner />
          </div>
        ) : mq.isError && clients.length === 0 ? (
          // сбой запроса ≠ «нет данных»: данные не потеряны, предлагаем повторить
          <div style={{ padding: 8 }}>
            <Empty
              title={t("mon.loadFailedTitle")}
              sub={t("mon.loadFailedSub")}
              action={
                <Btn variant="primary" sm onClick={() => mq.refetch()} disabled={mq.isFetching}>
                  {mq.isFetching ? <Spinner /> : t("mon.refresh")}
                </Btn>
              }
            />
          </div>
        ) : rows.length === 0 ? (
          <div style={{ padding: 8 }}>
            <Empty
              title={t("mon.noTrafficDataYet")}
              sub={clients.length === 0 ? collectionDiagnosis(t, mq.data?.collection) : t("mon.noClientsUnderFilters")}
            />
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={th}>{t("mon.colClient")}</th>
                  <th style={th}>{t("mon.colProtocol")}</th>
                  <th style={th}>{t("mon.colServer")}</th>
                  <th style={{ ...th, textAlign: "center" }}>{t("mon.colOnline")}</th>
                  <th style={{ ...th, textAlign: "right" }}>{t("mon.colDownloaded")}</th>
                  <th style={{ ...th, textAlign: "right" }}>{t("mon.colUploaded")}</th>
                  <th style={{ ...th, textAlign: "right" }}>{t("mon.colSpeed")}</th>
                  <th style={{ ...th, textAlign: "right" }}>{t("mon.colActivity")}</th>
                  <th style={{ ...th, textAlign: "center" }} />
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr
                    key={`${c.serverId}:${c.proto}:${c.clientId}`}
                    onClick={() => c.serverId && setSelected(c)}
                    style={c.serverId ? { cursor: "pointer" } : undefined}
                    title={c.serverId ? t("mon.showTrafficChart") : undefined}
                  >
                    <td style={td}>
                      <div style={{ fontWeight: 600 }}>{clientName(t, c)}</div>
                      {c.external && (
                        <div className="muted-3" style={{ fontSize: 11.5 }}>
                          {t("mon.outsidePanel")}
                        </div>
                      )}
                    </td>
                    <td style={td}>
                      <span className="badge">{protoLabel(t, c.proto)}</span>
                    </td>
                    <td style={{ ...td, color: "var(--text-2)" }}>{c.serverName || "—"}</td>
                    <td style={{ ...td, textAlign: "center" }}>
                      <OnlineDot online={c.online} title={c.online ? t("status.online") : t("status.offline")} />
                    </td>
                    <td style={num}>{fmtBytes(c.txTotal)}</td>
                    <td style={num}>{fmtBytes(c.rxTotal)}</td>
                    <td style={num}>{c.online ? `${fmtSpeed(c.txSpeed)} / ${fmtSpeed(c.rxSpeed)}` : "—"}</td>
                    <td style={{ ...num, color: "var(--text-3)" }}>
                      {c.online ? t("mon.rightNow") : fmtAgo(t, c.lastSeen)}
                    </td>
                    <td style={{ ...td, textAlign: "center" }} onClick={(e) => e.stopPropagation()}>
                      {!c.external && c.configId && c.serverId && c.status !== "revoked" && (
                        <Btn
                          variant="ghost"
                          sm
                          disabled={pauseMut.isPending}
                          title={c.status === "active" ? t("mon.pauseConfig") : t("mon.resumeConfig")}
                          onClick={() =>
                            pauseMut.mutate({
                              sid: c.serverId as string,
                              cid: c.configId as string,
                              pause: c.status === "active",
                            })
                          }
                        >
                          <Icon name={c.status === "active" ? "stop" : "play"} size={14} />
                        </Btn>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {mq.isError && (
        <div className="muted" style={{ fontSize: 13, display: "flex", gap: 8, alignItems: "center" }}>
          <Icon name="refresh" size={15} />
          {t("mon.loadFailedAutoRetry")}
        </div>
      )}

      {selected && (
        <ClientTrafficModal
          client={selected}
          period={period}
          periodLabel={periodLabel(t, period)}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
