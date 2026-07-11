import { useQuery } from "@tanstack/react-query";
import type { CSSProperties, ReactNode } from "react";
import { useMemo, useState } from "react";
import { Btn, Empty, Icon, ScreenHeader, Spinner, StatusBadge } from "../components/ui";
import * as q from "../lib/queries";
import type { CostByCurrency, FinanceServerRow, FinanceUnitCost } from "../lib/types";
import { useNav } from "../nav";

const PERIODS = [
  { id: "7d", label: "7 дней", days: 7 },
  { id: "30d", label: "30 дней", days: 30 },
  { id: "90d", label: "90 дней", days: 90 },
  { id: "month", label: "Этот месяц", days: null },
] as const;

type PeriodId = (typeof PERIODS)[number]["id"];

function periodRange(period: PeriodId): { start: number; end: number; label: string } {
  const end = Math.floor(Date.now() / 1000);
  if (period === "month") {
    const d = new Date();
    return {
      start: Math.floor(new Date(d.getFullYear(), d.getMonth(), 1).getTime() / 1000),
      end,
      label: "с начала месяца",
    };
  }
  const p = PERIODS.find((x) => x.id === period) ?? PERIODS[1];
  return { start: end - (p.days ?? 30) * 86400, end, label: p.label };
}

function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "без квоты";
  const u = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toLocaleString("ru-RU", { maximumFractionDigits: i === 0 ? 0 : 1 })} ${u[i]}`;
}

function fmtMoney(amount: number, currency: string, maxFractionDigits = amount >= 10 ? 0 : 2): string {
  return `${amount.toLocaleString("ru-RU", { maximumFractionDigits: maxFractionDigits })} ${currency}`;
}

function fmtMoneyList(items: CostByCurrency[]): string {
  if (items.length === 0) return "0";
  return items.map((x) => fmtMoney(x.amount, x.currency)).join(" · ");
}

function fmtPrice(price: FinanceServerRow["price"]): string {
  if (!price) return "не задана";
  const period = price.period === "month" ? "мес" : price.period === "day" ? "день" : "мин";
  return `${fmtMoney(price.amount, price.currency)} / ${period}`;
}

function fmtPct(pct: number | null): string {
  return pct == null ? "—" : `${pct.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
}

function fmtUnit(value: number | null, currency: string): string {
  if (value == null) return "—";
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: value >= 10 ? 2 : 4 })} ${currency}`;
}

function KpiCard({ icon, label, value, sub }: { icon: string; label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="card" style={{ minHeight: 118, display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="rowflex" style={{ gap: 9, color: "var(--text-2)", fontSize: 12.5, fontWeight: 700 }}>
        <Icon name={icon} size={17} />
        {label}
      </div>
      <div style={{ fontSize: 25, fontWeight: 800, lineHeight: 1.1 }}>{value}</div>
      {sub && (
        <div className="muted-3" style={{ fontSize: 12.5, lineHeight: 1.4 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function UtilizationBar({ pct }: { pct: number | null }) {
  const value = Math.max(0, Math.min(100, pct ?? 0));
  const color = value >= 90 ? "var(--danger)" : value >= 75 ? "var(--warn)" : "var(--ok)";
  return (
    <div
      style={{
        height: 8,
        borderRadius: 999,
        background: "var(--surface-3)",
        overflow: "hidden",
        minWidth: 120,
      }}
    >
      <div style={{ height: "100%", width: `${value}%`, background: color }} />
    </div>
  );
}

function UnitCostList({ items }: { items: FinanceUnitCost[] }) {
  if (items.length === 0) return <span className="muted-3">—</span>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {items.map((u) => (
        <div key={u.currency} style={{ fontSize: 12.5, lineHeight: 1.35 }}>
          <b>{u.currency}</b>: {fmtUnit(u.costPerQuotaGb ?? u.costPerUsedGb, u.currency)} / ГБ
          <span className="muted-3"> · {u.costPerQuotaGb != null ? "по квоте" : "по факту"}</span>
        </div>
      ))}
    </div>
  );
}

function SaleGuide({ unitCosts }: { unitCosts: FinanceUnitCost[] }) {
  const guides = unitCosts.flatMap((u) =>
    u.saleGuide
      .filter((g) => g.pricePerGb != null && g.pricePerTb != null)
      .map((g) => ({ ...g, currency: u.currency })),
  );
  if (guides.length === 0) {
    return (
      <div className="card">
        <Empty
          title="Недостаточно данных для цены продажи"
          sub="Нужны цена сервера и квота или накопленный трафик за период."
        />
      </div>
    );
  }
  return (
    <div className="card stack" style={{ gap: 14 }}>
      <div className="rowflex" style={{ gap: 10 }}>
        <Icon name="finance" />
        <div>
          <div className="title">Ориентир продажи трафика</div>
          <div className="muted-3" style={{ fontSize: 12.5, marginTop: 2 }}>
            База считается отдельно по каждой валюте, без конвертации.
          </div>
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
        {guides.map((g) => (
          <div
            key={`${g.currency}-${g.marginPct}`}
            style={{
              border: "1px solid var(--border)",
              borderRadius: "var(--r-sm)",
              padding: 14,
              background: "var(--surface-2)",
              display: "flex",
              flexDirection: "column",
              gap: 7,
            }}
          >
            <div className="muted-3" style={{ fontSize: 12, fontWeight: 700 }}>
              Маржа +{g.marginPct}% · {g.currency}
            </div>
            <div style={{ fontSize: 20, fontWeight: 800 }}>{fmtUnit(g.pricePerGb, g.currency)} / ГБ</div>
            <div className="muted" style={{ fontSize: 12.5 }}>
              {fmtUnit(g.pricePerTb, g.currency)} / ТБ · {g.basis === "quota" ? "по квоте" : "по факту"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DataQuality({ rows }: { rows: FinanceServerRow[] }) {
  const noPrice = rows.filter((s) => !s.price).length;
  const noQuota = rows.filter((s) => !s.trafficQuotaBytes).length;
  const hot = rows.filter((s) => (s.trafficUtilizationPct ?? 0) >= 80).length;
  return (
    <div className="card">
      <div className="title" style={{ marginBottom: 12 }}>
        Контроль данных
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
        <Insight value={String(noPrice)} label="без цены" tone={noPrice ? "warn" : "ok"} />
        <Insight value={String(noQuota)} label="без квоты трафика" tone={noQuota ? "warn" : "ok"} />
        <Insight value={String(hot)} label="квота загружена от 80%" tone={hot ? "danger" : "ok"} />
      </div>
    </div>
  );
}

function Insight({ value, label, tone }: { value: string; label: string; tone: "ok" | "warn" | "danger" }) {
  const colors: Record<typeof tone, string> = {
    ok: "var(--ok-soft)",
    warn: "var(--warn-soft)",
    danger: "var(--danger-soft)",
  };
  return (
    <div
      style={{
        borderRadius: "var(--r-sm)",
        background: colors[tone],
        padding: 13,
        minHeight: 74,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        gap: 3,
      }}
    >
      <div style={{ fontSize: 24, fontWeight: 800, lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 12.5, color: "var(--text-2)" }}>{label}</div>
    </div>
  );
}

const headerCell: CSSProperties = {
  color: "var(--text-3)",
  fontSize: 11,
  fontWeight: 800,
  textTransform: "uppercase",
};

const rowGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns:
    "minmax(210px, 1.35fr) minmax(140px, .85fr) minmax(165px, .9fr) minmax(190px, 1fr) minmax(170px, .95fr)",
  gap: 14,
  alignItems: "center",
};

function ServerFinanceTable({ rows }: { rows: FinanceServerRow[] }) {
  const go = useNav((s) => s.go);
  if (rows.length === 0) {
    return (
      <div className="card">
        <Empty title="Серверов пока нет" sub="Добавьте сервер и задайте цену, чтобы появились финансовые показатели." />
      </div>
    );
  }
  return (
    <div className="card stack" style={{ gap: 12 }}>
      <div className="rowflex" style={{ gap: 10 }}>
        <Icon name="servers" />
        <div className="title">Серверы</div>
      </div>
      <div style={{ overflowX: "auto" }}>
        <div style={{ minWidth: 920, display: "flex", flexDirection: "column", gap: 0 }}>
          <div style={{ ...rowGrid, padding: "0 0 9px", borderBottom: "1px solid var(--border)" }}>
            <div style={headerCell}>Сервер</div>
            <div style={headerCell}>Цена</div>
            <div style={headerCell}>Расход</div>
            <div style={headerCell}>Трафик</div>
            <div style={headerCell}>Unit economics</div>
          </div>
          {rows.map((s) => (
            <div
              key={s.serverId}
              style={{
                ...rowGrid,
                padding: "13px 0",
                borderBottom: "1px solid var(--border)",
              }}
            >
              <div style={{ minWidth: 0 }}>
                <button
                  type="button"
                  onClick={() => go("server", { serverId: s.serverId })}
                  style={{
                    border: 0,
                    background: "transparent",
                    fontWeight: 800,
                    fontSize: 14.5,
                    padding: 0,
                    textAlign: "left",
                    display: "block",
                    maxWidth: "100%",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {s.name}
                </button>
                <div className="muted-3" style={{ fontSize: 12, marginTop: 4 }}>
                  {[s.location, s.providerPlan || s.provider].filter(Boolean).join(" · ")}
                </div>
                <div style={{ marginTop: 7 }}>
                  <StatusBadge status={s.status} />
                </div>
              </div>
              <div style={{ fontSize: 13 }}>{fmtPrice(s.price)}</div>
              <div style={{ fontSize: 13, fontWeight: 700 }}>{fmtMoneyList(s.costByCurrency)}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                <div style={{ fontSize: 13, fontWeight: 700 }}>
                  {fmtBytes(s.trafficUsedBytes)} / {fmtBytes(s.trafficQuotaBytes)}
                </div>
                <UtilizationBar pct={s.trafficUtilizationPct} />
                <div className="muted-3" style={{ fontSize: 12 }}>
                  {fmtPct(s.trafficUtilizationPct)}
                </div>
              </div>
              <UnitCostList items={s.unitCosts} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function FinanceScreen() {
  const [period, setPeriod] = useState<PeriodId>("30d");
  const range = useMemo(() => periodRange(period), [period]);
  const reportQ = useQuery({
    queryKey: ["financeOverview", period],
    queryFn: () => q.financeOverview(range.start, range.end),
    refetchInterval: 60000,
    retry: 2,
  });
  const report = reportQ.data;
  const totals = report?.totals;
  const unit = totals?.unitCosts[0];
  const usedShareLabel =
    totals?.trafficQuotaBytes && totals.trafficUtilizationPct != null
      ? `${fmtPct(totals.trafficUtilizationPct)} квоты`
      : "квота не задана";

  return (
    <div className="stack" style={{ gap: 16 }}>
      <ScreenHeader title="Финансы" sub="Затраты на инфраструктуру, утилизация трафика и ориентиры продажи." />

      {/* Отдельная строка выбора периода: таблетки на десктопе, компактный select на телефоне —
          иначе длинное описание и период не помещаются в одну строку. */}
      <div className="period-controls">
        <div className="period-pills">
          {PERIODS.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`chip${period === p.id ? " selected" : ""}`}
              onClick={() => setPeriod(p.id)}
              style={{ height: 34, padding: "0 12px", fontSize: 12.5 }}
            >
              {p.label}
            </button>
          ))}
        </div>
        <select
          className="period-select"
          value={period}
          onChange={(e) => setPeriod(e.target.value as PeriodId)}
          aria-label="Период"
        >
          {PERIODS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
      </div>

      {reportQ.isLoading ? (
        <div className="card" style={{ display: "flex", justifyContent: "center", padding: 42 }}>
          <Spinner />
        </div>
      ) : reportQ.isError || !report || !totals ? (
        <div className="card">
          <Empty title="Не удалось загрузить финансы" sub="Проверьте backend и повторите позже." />
        </div>
      ) : (
        <>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
            <KpiCard
              icon="finance"
              label={`Расход · ${range.label}`}
              value={fmtMoneyList(totals.costByCurrency)}
              sub={`${totals.pricedServers} из ${totals.servers} серверов с заданной ценой`}
            />
            <KpiCard
              icon="monitoring"
              label="Использование трафика"
              value={fmtBytes(totals.trafficUsedBytes)}
              sub={
                <>
                  {usedShareLabel}
                  {totals.trafficQuotaBytes ? ` · всего ${fmtBytes(totals.trafficQuotaBytes)}` : ""}
                </>
              }
            />
            <KpiCard
              icon="servers"
              label="Себестоимость ГБ"
              value={unit ? fmtUnit(unit.costPerQuotaGb ?? unit.costPerUsedGb, unit.currency) : "—"}
              sub={
                unit
                  ? unit.costPerQuotaGb != null
                    ? "по купленной квоте"
                    : "по фактически использованному"
                  : "нет данных"
              }
            />
            <KpiCard
              icon="access"
              label="Покрытие квот"
              value={`${totals.quotaServers} / ${totals.servers}`}
              sub="серверов с сетевым лимитом тарифа"
            />
          </div>

          <SaleGuide unitCosts={totals.unitCosts} />
          <DataQuality rows={report.servers} />
          <ServerFinanceTable rows={report.servers} />

          <div className="rowflex" style={{ justifyContent: "flex-end" }}>
            <Btn variant="ghost" sm onClick={() => reportQ.refetch()}>
              <Icon name="refresh" size={15} />
              Обновить
            </Btn>
          </div>
        </>
      )}
    </div>
  );
}
