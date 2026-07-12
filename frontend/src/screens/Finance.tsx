import { useQuery } from "@tanstack/react-query";
import type { CSSProperties, ReactNode } from "react";
import { useMemo, useState } from "react";
import { LineChart } from "../components/chart";
import { Btn, Empty, Icon, ScreenHeader, Spinner, StatusBadge } from "../components/ui";
import { type TFunc, useT } from "../lib/i18n";
import { currencySymbol, fmtMoney, sumCostIn } from "../lib/providerPlans";
import * as q from "../lib/queries";
import type { CostByCurrency, FinanceServerRow, FinanceUsageUser } from "../lib/types";
import { useNav } from "../nav";
import { useStore } from "../store";

const GIB = 1024 ** 3;
const MONTH_SECONDS = (365.25 / 12) * 86400; // средний месяц — как accrual на бэке
const MARGIN_PRESETS = [20, 50, 100] as const;
const BASE_CURRENCIES = ["RUB", "USD", "EUR"]; // всегда в списке валют, даже если сервер в них не тарифицирован

const PERIODS = [
  { id: "7d", key: "period.7d", days: 7 },
  { id: "30d", key: "period.30d", days: 30 },
  { id: "90d", key: "period.90d", days: 90 },
  { id: "month", key: "finance.periodMonth", days: null },
] as const;

type PeriodId = (typeof PERIODS)[number]["id"];

function periodRange(t: TFunc, period: PeriodId): { start: number; end: number; label: string } {
  const end = Math.floor(Date.now() / 1000);
  if (period === "month") {
    const d = new Date();
    return {
      start: Math.floor(new Date(d.getFullYear(), d.getMonth(), 1).getTime() / 1000),
      end,
      label: t("finance.sinceMonthStart"),
    };
  }
  const p = PERIODS.find((x) => x.id === period) ?? PERIODS[1];
  return { start: end - (p.days ?? 30) * 86400, end, label: t(p.key) };
}

function fmtBytes(t: TFunc, n: number | null | undefined): string {
  if (n == null) return t("finance.noQuota");
  const u = [t("finance.unitByte"), t("finance.unitKb"), t("finance.unitMb"), t("finance.unitGb"), t("finance.unitTb")];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toLocaleString("ru-RU", { maximumFractionDigits: i === 0 ? 0 : 1 })} ${u[i]}`;
}

function fmtPct(pct: number | null): string {
  return pct == null ? "—" : `${pct.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
}

// цена сервера в СВОЕЙ валюте за период (как настроено) — показываем факт, не конвертируем
function fmtServerPrice(t: TFunc, price: FinanceServerRow["price"]): string {
  if (!price) return t("finance.priceNotSet");
  const period =
    price.period === "month"
      ? t("finance.periodMonthShort")
      : price.period === "day"
        ? t("finance.periodDayShort")
        : t("finance.periodMinShort");
  return `${fmtMoney(price.amount, price.currency)} / ${period}`;
}

// компактная подпись оси Y для денег (1234 → «1,2k ₽»)
function fmtMoneyCompact(v: number, cur: string): string {
  const sym = currencySymbol(cur);
  if (v >= 1000) return `${(v / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}k ${sym}`;
  return `${Math.round(v)} ${sym}`;
}

const fmtDayLabel = (at: number) =>
  new Date(at * 1000).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });

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
    <div style={{ height: 8, borderRadius: 999, background: "var(--surface-3)", overflow: "hidden", minWidth: 120 }}>
      <div style={{ height: "100%", width: `${value}%`, background: color }} />
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

function DataQuality({ rows }: { rows: FinanceServerRow[] }) {
  const t = useT();
  const noPrice = rows.filter((s) => !s.price).length;
  const noQuota = rows.filter((s) => !s.trafficQuotaBytes).length;
  const hot = rows.filter((s) => (s.trafficUtilizationPct ?? 0) >= 80).length;
  return (
    <div className="card">
      <div className="title" style={{ marginBottom: 12 }}>
        {t("finance.dataQualityTitle")}
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
        <Insight value={String(noPrice)} label={t("finance.noPriceCount")} tone={noPrice ? "warn" : "ok"} />
        <Insight value={String(noQuota)} label={t("finance.noQuotaCount")} tone={noQuota ? "warn" : "ok"} />
        <Insight value={String(hot)} label={t("finance.hotQuotaCount")} tone={hot ? "danger" : "ok"} />
      </div>
    </div>
  );
}

// --- калькулятор цены продажи (what-if, обе модели: за ГБ и за устройство/мес) ---

function CalcMetric({ label, value, tone }: { label: string; value: string; tone?: "ok" | "muted" }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 13 }}>
      <span className="muted-3">{label}</span>
      <b style={{ color: tone === "ok" ? "var(--ok)" : tone === "muted" ? "var(--text-3)" : "inherit" }}>{value}</b>
    </div>
  );
}

function CalcCard({
  title,
  icon,
  price,
  breakeven,
  revenue,
  revenueSub,
  profit,
  cur,
  unit,
}: {
  title: string;
  icon: string;
  price: number;
  breakeven: number;
  revenue: number;
  revenueSub: string;
  profit: number;
  cur: string;
  unit: string;
}) {
  const t = useT();
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: "var(--r-sm)",
        padding: 14,
        background: "var(--surface-2)",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div className="rowflex" style={{ gap: 8, fontWeight: 700, fontSize: 13 }}>
        <Icon name={icon} size={16} />
        {title}
      </div>
      <div style={{ fontSize: 22, fontWeight: 800 }}>
        {fmtMoney(price, cur)}{" "}
        <span className="muted-3" style={{ fontSize: 13, fontWeight: 600 }}>
          {unit}
        </span>
      </div>
      <CalcMetric label={t("finance.calcBreakeven")} value={`${fmtMoney(breakeven, cur)} ${unit}`} tone="muted" />
      <CalcMetric label={`${t("finance.calcRevenue")} · ${revenueSub}`} value={fmtMoney(revenue, cur)} />
      <CalcMetric label={t("finance.calcProfit")} value={fmtMoney(profit, cur)} tone={profit >= 0 ? "ok" : undefined} />
    </div>
  );
}

function SaleCalculator({
  cur,
  margin,
  setMargin,
  costPerGb,
  usedGb,
  expense,
  runRate,
  deviceCount,
}: {
  cur: string;
  margin: number;
  setMargin: (m: number) => void;
  costPerGb: number | null;
  usedGb: number;
  expense: number;
  runRate: number;
  deviceCount: number;
}) {
  const t = useT();
  const k = 1 + margin / 100;
  const costPerDevice = deviceCount > 0 ? runRate / deviceCount : null;
  const hasAny = costPerGb != null || costPerDevice != null;

  return (
    <div className="card stack" style={{ gap: 14 }}>
      <div className="rowflex" style={{ gap: 10 }}>
        <Icon name="finance" />
        <div>
          <div className="title">{t("finance.calcTitle")}</div>
          <div className="muted-3" style={{ fontSize: 12.5, marginTop: 2 }}>
            {t("finance.calcHint")}
          </div>
        </div>
      </div>

      <div className="rowflex" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span className="muted-3" style={{ fontSize: 12.5, fontWeight: 700 }}>
          {t("finance.calcMargin")}
        </span>
        {MARGIN_PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            className={`chip${margin === p ? " selected" : ""}`}
            onClick={() => setMargin(p)}
            style={{ height: 32, padding: "0 12px", fontSize: 12.5 }}
          >
            +{p}%
          </button>
        ))}
        <input
          type="number"
          className="input"
          value={margin}
          min={0}
          max={100000}
          onChange={(e) => setMargin(Math.max(0, Number(e.target.value) || 0))}
          aria-label={t("finance.calcMargin")}
          style={{ width: 92 }}
        />
        <span className="muted-3" style={{ fontSize: 12.5 }}>
          %
        </span>
      </div>

      {!hasAny ? (
        <Empty title={t("finance.calcNoDataTitle")} sub={t("finance.calcNoDataSub")} />
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
          {costPerGb != null && (
            <CalcCard
              title={t("finance.calcPerGbTitle")}
              icon="monitoring"
              cur={cur}
              unit={`/ ${t("finance.unitGb")}`}
              price={costPerGb * k}
              breakeven={costPerGb}
              revenue={costPerGb * k * usedGb}
              revenueSub={t("finance.calcOnUsed", { gb: usedGb.toLocaleString("ru-RU", { maximumFractionDigits: 1 }) })}
              profit={costPerGb * k * usedGb - expense}
            />
          )}
          {costPerDevice != null && (
            <CalcCard
              title={t("finance.calcPerDeviceTitle")}
              icon="access"
              cur={cur}
              unit={t("finance.calcPerDeviceUnit")}
              price={costPerDevice * k}
              breakeven={costPerDevice}
              revenue={costPerDevice * k * deviceCount}
              revenueSub={t("finance.calcOnDevices", { n: deviceCount })}
              profit={costPerDevice * k * deviceCount - runRate}
            />
          )}
        </div>
      )}
    </div>
  );
}

// --- «кто и как использует серверы» ---

const usageGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns:
    "minmax(150px, 1.3fr) minmax(120px, .9fr) minmax(120px, 1fr) minmax(80px, .5fr) minmax(120px, .9fr) minmax(120px, .9fr)",
  gap: 12,
  alignItems: "center",
};

const headerCell: CSSProperties = { color: "var(--text-3)", fontSize: 11, fontWeight: 800, textTransform: "uppercase" };

function UsageRow({
  name,
  usedBytes,
  sharePct,
  deviceCount,
  cost,
  suggested,
  cur,
  muted,
}: {
  name: string;
  usedBytes: number;
  sharePct: number | null;
  deviceCount: number | null;
  cost: number;
  suggested: number;
  cur: string;
  muted?: boolean;
}) {
  const t = useT();
  return (
    <div style={{ ...usageGrid, padding: "12px 0", borderBottom: "1px solid var(--border)" }}>
      <div style={{ fontWeight: 700, fontSize: 13.5, color: muted ? "var(--text-3)" : "inherit", minWidth: 0 }}>
        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</div>
      </div>
      <div style={{ fontSize: 13, fontWeight: 700 }}>{fmtBytes(t, usedBytes)}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <UtilizationBar pct={sharePct} />
        <span className="muted-3" style={{ fontSize: 12 }}>
          {fmtPct(sharePct)}
        </span>
      </div>
      <div style={{ fontSize: 13 }}>{deviceCount == null ? "—" : deviceCount}</div>
      <div style={{ fontSize: 13, fontWeight: 700 }}>{fmtMoney(cost, cur)}</div>
      <div style={{ fontSize: 13, color: "var(--ok)", fontWeight: 700 }}>{fmtMoney(suggested, cur)}</div>
    </div>
  );
}

// --- экран ---

export function FinanceScreen() {
  const t = useT();
  const go = useNav((s) => s.go);
  const cur = useStore((s) => s.financeCurrency);
  const setCur = useStore((s) => s.setFinanceCurrency);
  const [period, setPeriod] = useState<PeriodId>("30d");
  const [margin, setMargin] = useState(50);
  const range = useMemo(() => periodRange(t, period), [t, period]);

  const fxQ = useQuery({ queryKey: ["fxRates"], queryFn: q.fxRates, staleTime: 60 * 60 * 1000 });
  const reportQ = useQuery({
    queryKey: ["financeOverview", period],
    queryFn: () => q.financeOverview(range.start, range.end),
    refetchInterval: 60000,
    retry: 2,
  });
  const usageQ = useQuery({
    queryKey: ["financeUsage", period],
    queryFn: () => q.financeUsage(range.start, range.end),
    refetchInterval: 60000,
    retry: 2,
  });

  const rates = fxQ.data?.rates ?? { RUB: 1 };
  const conv = useMemo(() => (items: CostByCurrency[]) => sumCostIn(items, cur, rates), [cur, rates]);
  const report = reportQ.data;
  const usage = usageQ.data;
  const totals = report?.totals;

  // список валют: базовые + выбранная + те, в которых реально тарифицированы серверы (и есть курс)
  const currencyOpts = useMemo(() => {
    const used = new Set<string>([...BASE_CURRENCIES, cur]);
    for (const s of report?.servers ?? []) for (const c of s.costByCurrency) used.add(c.currency);
    return [...used].filter((c) => c === cur || c === "RUB" || (rates[c] ?? 0) > 0).sort();
  }, [report, rates, cur]);

  const expense = totals ? conv(totals.costByCurrency) : { amount: 0, partial: false };
  const prevAmount = totals ? conv(totals.prevCostByCurrency).amount : 0;
  const deltaPct = prevAmount > 0 ? ((expense.amount - prevAmount) / prevAmount) * 100 : null;
  const windowSec = Math.max(1, range.end - range.start);
  const runRate = expense.amount * (MONTH_SECONDS / windowSec);
  // трафик за КВАДРАТ ОКНА [start,end] (usage_report из traffic_daily) — тот же горизонт, что расход;
  // KPI-карточка «использование трафика» ниже показывает биллинг-периодный трафик (он про квоту).
  const windowUsedGb = (usage?.totalUsedBytes ?? 0) / GIB;
  const costPerGb = windowUsedGb > 0 && expense.amount > 0 ? expense.amount / windowUsedGb : null;
  const k = 1 + margin / 100;

  const usedShareLabel =
    totals?.trafficQuotaBytes && totals.trafficUtilizationPct != null
      ? t("finance.quotaShare", { pct: fmtPct(totals.trafficUtilizationPct) })
      : t("finance.quotaNotSet");

  const costLine = {
    color: "var(--accent)",
    label: t("finance.chartCostLegend"),
    points: (report?.costSeries ?? []).map((p) => ({ at: p.at, value: conv(p.byCurrency).amount })),
  };
  const trafficLine = {
    color: "var(--ok)",
    label: t("finance.chartTrafficLegend"),
    points: (report?.trafficSeries ?? []).map((p) => ({ at: p.at, value: p.bytes / GIB })),
  };

  return (
    <div className="stack" style={{ gap: 16 }}>
      <ScreenHeader title={t("nav.finance")} sub={t("finance.headerSub")} />

      {/* Единая валюта + период. Валюта конвертируется по курсу ЦБ (лежит в fx/rates). */}
      <div className="period-controls" style={{ gap: 10, flexWrap: "wrap" }}>
        <select
          className="input"
          value={cur}
          onChange={(e) => setCur(e.target.value)}
          aria-label={t("finance.currencyAriaLabel")}
          style={{ width: "auto", flex: "none" }}
        >
          {currencyOpts.map((c) => (
            <option key={c} value={c}>
              {currencySymbol(c)} {c}
            </option>
          ))}
        </select>
        <div className="period-pills">
          {PERIODS.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`chip${period === p.id ? " selected" : ""}`}
              onClick={() => setPeriod(p.id)}
              style={{ height: 34, padding: "0 12px", fontSize: 12.5 }}
            >
              {t(p.key)}
            </button>
          ))}
        </div>
        <select
          className="period-select"
          value={period}
          onChange={(e) => setPeriod(e.target.value as PeriodId)}
          aria-label={t("finance.periodAriaLabel")}
        >
          {PERIODS.map((p) => (
            <option key={p.id} value={p.id}>
              {t(p.key)}
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
          <Empty title={t("finance.loadFailedTitle")} sub={t("finance.loadFailedSub")} />
        </div>
      ) : (
        <>
          {expense.partial && (
            <div className="muted-3" style={{ fontSize: 12 }}>
              {t("finance.fxPartial")}
            </div>
          )}

          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
            <KpiCard
              icon="finance"
              label={t("finance.kpiExpense", { period: range.label })}
              value={fmtMoney(expense.amount, cur)}
              sub={
                <>
                  {deltaPct != null && (
                    <span style={{ color: deltaPct > 0 ? "var(--danger)" : "var(--ok)", fontWeight: 700 }}>
                      {deltaPct > 0 ? "▲" : "▼"}{" "}
                      {Math.abs(deltaPct).toLocaleString("ru-RU", { maximumFractionDigits: 0 })}% {t("finance.vsPrev")}{" "}
                      ·{" "}
                    </span>
                  )}
                  {t("finance.kpiExpenseSub", { priced: totals.pricedServers, total: totals.servers })}
                </>
              }
            />
            <KpiCard
              icon="finance"
              label={t("finance.kpiRunRate")}
              value={fmtMoney(runRate, cur)}
              sub={t("finance.kpiRunRateSub")}
            />
            <KpiCard
              icon="monitoring"
              label={t("finance.kpiTrafficUsage")}
              value={fmtBytes(t, totals.trafficUsedBytes)}
              sub={
                <>
                  {usedShareLabel}
                  {totals.trafficQuotaBytes
                    ? ` · ${t("finance.kpiTrafficTotal", { total: fmtBytes(t, totals.trafficQuotaBytes) })}`
                    : ""}
                </>
              }
            />
            <KpiCard
              icon="servers"
              label={t("finance.kpiCostPerGb")}
              value={costPerGb != null ? fmtMoney(costPerGb, cur) : "—"}
              sub={costPerGb != null ? t("finance.byFactUsed") : t("finance.noData")}
            />
          </div>

          {/* графики трендов */}
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
            <div className="card stack" style={{ gap: 10 }}>
              <div className="title">{t("finance.chartCostTitle")}</div>
              <LineChart lines={[costLine]} fmtX={fmtDayLabel} fmtY={(v) => fmtMoneyCompact(v, cur)} />
            </div>
            <div className="card stack" style={{ gap: 10 }}>
              <div className="title">{t("finance.chartTrafficTitle")}</div>
              <LineChart
                lines={[trafficLine]}
                fmtX={fmtDayLabel}
                fmtY={(v) =>
                  `${v.toLocaleString("ru-RU", { maximumFractionDigits: v >= 10 ? 0 : 1 })} ${t("finance.unitGb")}`
                }
              />
            </div>
          </div>

          {/* калькулятор цены продажи */}
          <SaleCalculator
            cur={cur}
            margin={margin}
            setMargin={setMargin}
            costPerGb={costPerGb}
            usedGb={windowUsedGb}
            expense={expense.amount}
            runRate={runRate}
            deviceCount={usage?.deviceCount ?? 0}
          />

          {/* кто и как использует серверы */}
          <div className="card stack" style={{ gap: 12 }}>
            <div className="rowflex" style={{ gap: 10 }}>
              <Icon name="monitoring" />
              <div>
                <div className="title">{t("finance.usageTitle")}</div>
                <div className="muted-3" style={{ fontSize: 12.5, marginTop: 2 }}>
                  {t("finance.usageHint")}
                </div>
              </div>
            </div>
            {usageQ.isLoading ? (
              <div style={{ display: "flex", justifyContent: "center", padding: 24 }}>
                <Spinner />
              </div>
            ) : !usage || (usage.users.length === 0 && usage.external.usedBytes === 0) ? (
              <Empty title={t("finance.usageEmptyTitle")} sub={t("finance.usageEmptySub")} />
            ) : (
              <div style={{ overflowX: "auto" }}>
                <div style={{ minWidth: 760 }}>
                  <div style={{ ...usageGrid, padding: "0 0 9px", borderBottom: "1px solid var(--border)" }}>
                    <div style={headerCell}>{t("finance.usageColUser")}</div>
                    <div style={headerCell}>{t("finance.colTraffic")}</div>
                    <div style={headerCell}>{t("finance.usageColShare")}</div>
                    <div style={headerCell}>{t("finance.usageColDevices")}</div>
                    <div style={headerCell}>{t("finance.usageColCost")}</div>
                    <div style={headerCell}>{t("finance.usageColSuggested")}</div>
                  </div>
                  {usage.users.map((u: FinanceUsageUser) => {
                    const cost = conv(u.costByCurrency).amount;
                    return (
                      <UsageRow
                        key={u.userId}
                        name={u.name || t("finance.usageNoName")}
                        usedBytes={u.usedBytes}
                        sharePct={u.sharePct}
                        deviceCount={u.deviceCount}
                        cost={cost}
                        suggested={cost * k}
                        cur={cur}
                      />
                    );
                  })}
                  {usage.external.usedBytes > 0 &&
                    (() => {
                      const cost = conv(usage.external.costByCurrency).amount;
                      return (
                        <UsageRow
                          name={t("finance.usageExternal")}
                          usedBytes={usage.external.usedBytes}
                          sharePct={usage.external.sharePct}
                          deviceCount={null}
                          cost={cost}
                          suggested={cost * k}
                          cur={cur}
                          muted
                        />
                      );
                    })()}
                </div>
              </div>
            )}
          </div>

          <DataQuality rows={report.servers} />

          {/* серверы: цена (в своей валюте) + расход/себестоимость в выбранной валюте */}
          {report.servers.length > 0 && (
            <div className="card stack" style={{ gap: 12 }}>
              <div className="rowflex" style={{ gap: 10 }}>
                <Icon name="servers" />
                <div className="title">{t("finance.serversTitle")}</div>
              </div>
              <div style={{ overflowX: "auto" }}>
                <div style={{ minWidth: 820 }}>
                  <div style={{ ...serverGrid, padding: "0 0 9px", borderBottom: "1px solid var(--border)" }}>
                    <div style={headerCell}>{t("finance.colServer")}</div>
                    <div style={headerCell}>{t("finance.colPrice")}</div>
                    <div style={headerCell}>{t("finance.colExpense")}</div>
                    <div style={headerCell}>{t("finance.colTraffic")}</div>
                    <div style={headerCell}>{t("finance.colCostPerGb")}</div>
                  </div>
                  {report.servers.map((s) => {
                    const exp = conv(s.costByCurrency).amount;
                    const gb = s.trafficUsedBytes / GIB;
                    const perGb = gb > 0 && exp > 0 ? exp / gb : null;
                    return (
                      <div
                        key={s.serverId}
                        style={{ ...serverGrid, padding: "13px 0", borderBottom: "1px solid var(--border)" }}
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
                        <div style={{ fontSize: 13 }}>{fmtServerPrice(t, s.price)}</div>
                        <div style={{ fontSize: 13, fontWeight: 700 }}>{fmtMoney(exp, cur)}</div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                          <div style={{ fontSize: 13, fontWeight: 700 }}>
                            {fmtBytes(t, s.trafficUsedBytes)} / {fmtBytes(t, s.trafficQuotaBytes)}
                          </div>
                          <UtilizationBar pct={s.trafficUtilizationPct} />
                          <div className="muted-3" style={{ fontSize: 12 }}>
                            {fmtPct(s.trafficUtilizationPct)}
                          </div>
                        </div>
                        <div style={{ fontSize: 13 }}>
                          {perGb != null ? `${fmtMoney(perGb, cur)} / ${t("finance.unitGb")}` : "—"}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          <div className="rowflex" style={{ justifyContent: "flex-end" }}>
            <Btn variant="ghost" sm onClick={() => reportQ.refetch()}>
              <Icon name="refresh" size={15} />
              {t("finance.refresh")}
            </Btn>
          </div>
        </>
      )}
    </div>
  );
}

const serverGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns:
    "minmax(200px, 1.4fr) minmax(120px, .8fr) minmax(120px, .8fr) minmax(180px, 1fr) minmax(120px, .8fr)",
  gap: 14,
  alignItems: "center",
};
