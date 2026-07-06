// Супер-мониторинг клиентов (владелец): единая таблица per-client трафика+онлайна по ВСЕМ
// серверам и протоколам. Данные — GET /monitoring (TrafficService.global_overview), собранные
// в sync-тике по SSH (wg dump / xray statsquery / hysteria trafficStats). Сводка сверху +
// фильтр по серверу/протоколу + сортировка. Поллинг как у остального owner-UI.
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Btn, Empty, Icon, ScreenHeader, Spinner } from "../components/ui";
import { useT } from "../lib/i18n";
import * as q from "../lib/queries";
import type { MonitoringClient } from "../lib/types";

const PERIODS = ["1h", "24h", "7d"] as const;
type Period = (typeof PERIODS)[number];
const PERIOD_LABEL: Record<Period, string> = { "1h": "1 час", "24h": "24 часа", "7d": "7 дней" };

const PROTO_LABEL: Record<string, string> = {
  awg: "AmneziaWG",
  awg_legacy: "AWG Legacy",
  xray: "Xray",
  xray_xhttp: "Xray XHTTP",
  hysteria2: "Hysteria2",
  openvpn: "OpenVPN",
  outline: "Outline",
};

// человекочитаемые байты (как в ServerDetail)
export const fmtBytes = (n: number | null | undefined): string => {
  if (n == null) return "—";
  const u = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
};
export const fmtSpeed = (bytesPerSec: number): string => (bytesPerSec > 0 ? `${fmtBytes(bytesPerSec)}/с` : "—");

const fmtAgo = (at: number | null): string => {
  if (at == null) return "—";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - at));
  if (s < 60) return "только что";
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  return `${Math.floor(s / 86400)} дн назад`;
};

type SortKey = "traffic" | "speed" | "name";

function OnlineDot({ online }: { online: boolean }) {
  return (
    <span
      title={online ? "онлайн" : "офлайн"}
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

function clientName(c: MonitoringClient): string {
  if (c.userName || c.deviceName) return [c.userName, c.deviceName].filter(Boolean).join(" · ");
  return c.external ? "Внешний клиент" : (c.clientId ?? "—");
}

export function MonitoringScreen() {
  const t = useT();
  const [period, setPeriod] = useState<Period>("24h");
  const [server, setServer] = useState<string>("");
  const [proto, setProto] = useState<string>("");
  const [sort, setSort] = useState<SortKey>("traffic");

  const mq = useQuery({
    queryKey: ["monitoring", period],
    queryFn: () => q.monitoring(period),
    refetchInterval: 30000,
  });

  const clients = mq.data?.clients ?? [];
  const summary = mq.data?.summary;

  // варианты для фильтров — из полученных данных
  const servers = useMemo(() => {
    const seen = new Map<string, string>();
    for (const c of clients) if (c.serverId) seen.set(c.serverId, c.serverName || c.serverId);
    return [...seen.entries()];
  }, [clients]);
  const protos = useMemo(() => [...new Set(clients.map((c) => c.proto))], [clients]);

  const rows = useMemo(() => {
    let out = clients.filter((c) => (!server || c.serverId === server) && (!proto || c.proto === proto));
    const cmp: Record<SortKey, (a: MonitoringClient, b: MonitoringClient) => number> = {
      traffic: (a, b) => b.rxTotal + b.txTotal - (a.rxTotal + a.txTotal),
      speed: (a, b) => b.rxSpeed + b.txSpeed - (a.rxSpeed + a.txSpeed),
      name: (a, b) => clientName(a).localeCompare(clientName(b), "ru"),
    };
    // онлайн — всегда выше при равенстве по остальным критериям
    out = [...out].sort((a, b) => cmp[sort](a, b) || Number(b.online) - Number(a.online));
    return out;
  }, [clients, server, proto, sort]);

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

  const selStyle: React.CSSProperties = {
    padding: "6px 10px",
    borderRadius: "var(--r-sm)",
    border: "1px solid var(--border-strong)",
    background: "var(--surface)",
    fontSize: 13,
    color: "var(--text)",
  };

  return (
    <div className="stack" style={{ gap: 16 }}>
      <ScreenHeader
        title={t("nav.monitoring")}
        sub="Кто онлайн, по какому протоколу и сколько трафика — по всем вашим серверам"
        action={
          <div style={{ display: "flex", gap: 6 }}>
            {PERIODS.map((p) => (
              <Btn key={p} variant={p === period ? "primary" : "ghost"} sm onClick={() => setPeriod(p)}>
                {PERIOD_LABEL[p]}
              </Btn>
            ))}
          </div>
        }
      />

      {/* сводка */}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        <SummaryTile
          label="Онлайн сейчас"
          value={summary ? String(summary.clientsOnline) : "—"}
          sub={summary ? `из ${summary.clientsTotal} клиентов` : undefined}
        />
        <SummaryTile label="Скачано (download)" value={fmtBytes(summary?.txTotal)} sub={`за ${PERIOD_LABEL[period]}`} />
        <SummaryTile label="Отдано (upload)" value={fmtBytes(summary?.rxTotal)} sub={`за ${PERIOD_LABEL[period]}`} />
        <SummaryTile label="Серверов" value={summary ? String(summary.serversTotal) : "—"} />
      </div>

      {/* фильтры + сортировка */}
      <div className="rowflex" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <select style={selStyle} value={server} onChange={(e) => setServer(e.target.value)}>
          <option value="">Все серверы</option>
          {servers.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
        <select style={selStyle} value={proto} onChange={(e) => setProto(e.target.value)}>
          <option value="">Все протоколы</option>
          {protos.map((p) => (
            <option key={p} value={p}>
              {PROTO_LABEL[p] ?? p}
            </option>
          ))}
        </select>
        <div style={{ flex: 1 }} />
        <span className="muted-3" style={{ fontSize: 12 }}>
          Сортировка:
        </span>
        {(["traffic", "speed", "name"] as SortKey[]).map((s) => (
          <Btn key={s} variant={s === sort ? "primary" : "ghost"} sm onClick={() => setSort(s)}>
            {s === "traffic" ? "по трафику" : s === "speed" ? "по скорости" : "по имени"}
          </Btn>
        ))}
      </div>

      {/* таблица клиентов */}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {mq.isLoading ? (
          <div style={{ padding: 24 }}>
            <Spinner />
          </div>
        ) : rows.length === 0 ? (
          <div style={{ padding: 8 }}>
            <Empty
              title="Пока нет данных о трафике"
              sub={
                clients.length === 0
                  ? "Статистика собирается в фоне по SSH. Для Xray/Hysteria2 включите точную статистику в карточке сервера."
                  : "Под текущие фильтры нет клиентов."
              }
            />
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={th}>Клиент</th>
                  <th style={th}>Протокол</th>
                  <th style={th}>Сервер</th>
                  <th style={{ ...th, textAlign: "center" }}>Онлайн</th>
                  <th style={{ ...th, textAlign: "right" }}>Скачал</th>
                  <th style={{ ...th, textAlign: "right" }}>Отдал</th>
                  <th style={{ ...th, textAlign: "right" }}>Скорость ↓/↑</th>
                  <th style={{ ...th, textAlign: "right" }}>Активность</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={`${c.serverId}:${c.proto}:${c.clientId}`}>
                    <td style={td}>
                      <div style={{ fontWeight: 600 }}>{clientName(c)}</div>
                      {c.external && (
                        <div className="muted-3" style={{ fontSize: 11.5 }}>
                          вне панели
                        </div>
                      )}
                    </td>
                    <td style={td}>
                      <span className="badge">{PROTO_LABEL[c.proto] ?? c.proto}</span>
                    </td>
                    <td style={{ ...td, color: "var(--text-2)" }}>{c.serverName || "—"}</td>
                    <td style={{ ...td, textAlign: "center" }}>
                      <OnlineDot online={c.online} />
                    </td>
                    <td style={num}>{fmtBytes(c.txTotal)}</td>
                    <td style={num}>{fmtBytes(c.rxTotal)}</td>
                    <td style={num}>{c.online ? `${fmtSpeed(c.txSpeed)} / ${fmtSpeed(c.rxSpeed)}` : "—"}</td>
                    <td style={{ ...num, color: "var(--text-3)" }}>{c.online ? "сейчас" : fmtAgo(c.lastSeen)}</td>
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
          Не удалось загрузить мониторинг. Обновление произойдёт автоматически.
        </div>
      )}
    </div>
  );
}
