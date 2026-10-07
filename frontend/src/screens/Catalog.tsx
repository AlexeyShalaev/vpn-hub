import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { type CSSProperties, useMemo, useState } from "react";
import { Btn, Empty, Field, Icon, Modal, MultiSelect, ScreenHeader, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import { useT } from "../lib/i18n";
import { countryLabel, flagEmoji } from "../lib/locations";
import {
  DEFAULT_PLAN_FILTER,
  type FinderPlan,
  type PlanFilter,
  type PlanSort,
  planLocation,
  type RankedPlan,
  rankPlans,
} from "../lib/planFinder";
import { PLAN_SOURCES } from "../lib/planSources";
import {
  type CatalogFilter,
  type CatalogSort,
  cardTags,
  EMPTY_CATALOG_FILTER,
  facetCounts,
  filterProviders,
  PAYMENT_METHODS,
  providerBlurb,
} from "../lib/providerCatalog";
import {
  currencySymbol,
  dynamicPlanProviderId,
  fmtMoney,
  fmtPrice,
  hasLivePlans,
  isDynamicPlanProviderId,
  planProviderDisplayName,
  planSpecs,
} from "../lib/providerPlans";
import * as q from "../lib/queries";
import type { PaymentMethod, Provider } from "../lib/types";
import { useNav } from "../nav";
import { useStore } from "../store";

// общие стили кнопок карточки (DRY): основная «купить» на всю ширину + вторичные в ряд.
// Все одинаковой высоты (box-sizing: border-box, чтобы 1px-бордер вторичных не сбивал высоту).
const ACTION_HEIGHT = 44;
const primaryAction: CSSProperties = {
  width: "100%",
  height: ACTION_HEIGHT,
  boxSizing: "border-box",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 7,
  borderRadius: 12,
  background: "var(--ink)",
  color: "var(--on-ink)",
  font: "600 14px/1 var(--font)",
  textDecoration: "none",
};
const secondaryAction: CSSProperties = {
  flex: 1,
  height: ACTION_HEIGHT,
  boxSizing: "border-box",
  padding: "0 14px",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  border: "1px solid var(--border-strong)",
  borderRadius: 12,
  background: "var(--surface)",
  color: "var(--text)",
  font: "600 13px/1 var(--font)",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

// Модалка «Тарифы провайдера»: распарсенные планы (GET /providers/{pid}/plans). Кнопка «Купить» ведёт
// на исходную страницу тарифа, «Выбрать» — открывает форму сервера с этим провайдером (автозаполнение).
function PlansModal({
  planPid,
  title,
  buyUrl,
  onPick,
  onClose,
}: {
  planPid: string;
  title: string;
  buyUrl: string;
  onPick: () => void;
  onClose: () => void;
}) {
  const t = useT();
  const pq = useQuery({
    queryKey: ["providerPlans", planPid],
    queryFn: () => q.providerPlans(planPid),
    retry: 1,
  });
  const plans = pq.data ?? [];
  return (
    <Modal title={t("catalog.plansModalTitle", { title })} onClose={onClose} wide>
      <div className="stack" style={{ gap: 10 }}>
        {pq.isLoading ? (
          <div style={{ padding: 24, textAlign: "center" }}>
            <Spinner />
          </div>
        ) : pq.isError ? (
          <Empty title={t("catalog.plansLoadFailedTitle")} sub={t("catalog.plansLoadFailedSub")} />
        ) : plans.length === 0 ? (
          <Empty title={t("catalog.plansEmptyTitle")} sub={t("catalog.plansEmptySub")} />
        ) : (
          <div className="stack" style={{ gap: 8 }}>
            {plans.map((p) => (
              <div
                key={`${p.id}:${p.region}:${p.name}`}
                className="rowflex"
                style={{
                  gap: 12,
                  alignItems: "center",
                  padding: "10px 12px",
                  borderRadius: 10,
                  background: "var(--surface-2)",
                  opacity: p.available === false ? 0.55 : 1,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13.5 }}>
                    {p.name}
                    {p.available === false && (
                      <span className="muted-3" style={{ fontSize: 12 }}>
                        {" "}
                        · {t("catalog.outOfStock")}
                      </span>
                    )}
                  </div>
                  <div className="muted-3" style={{ fontSize: 12 }}>
                    {planSpecs(p)}
                  </div>
                </div>
                <div style={{ fontWeight: 700, fontSize: 13.5, whiteSpace: "nowrap" }}>{fmtPrice(p)}</div>
              </div>
            ))}
          </div>
        )}
        <div className="rowflex" style={{ gap: 8, justifyContent: "flex-end", marginTop: 4 }}>
          <a href={buyUrl} target="_blank" rel="noopener">
            <Btn variant="ghost" sm>
              {t("catalog.toProviderSite")} <Icon name="external" size={14} />
            </Btn>
          </a>
          <Btn variant="primary" sm onClick={onPick}>
            {t("catalog.selectProvider")}
          </Btn>
        </div>
      </div>
    </Modal>
  );
}

// честная подпись про актуальность курса, которым сводим цены к одной валюте
const FX_SOURCE_NOTE_KEY: Record<string, "catalog.fxNoteCbr" | "catalog.fxNoteCbrStale" | "catalog.fxNoteFallback"> = {
  cbr: "catalog.fxNoteCbr",
  "cbr-stale": "catalog.fxNoteCbrStale",
  fallback: "catalog.fxNoteFallback",
};

// сколько строк тарифов рисовать сразу: у облаков с десятками локаций тарифов тысячи
const FINDER_PAGE_SIZE = 100;

// Подбор тарифа по всем провайдерам с живыми тарифами: тянет их тарифы параллельно (по мере загрузки),
// фильтрует и сортирует через rankPlans (lib/planFinder). Валюты сводятся к одной по курсу ЦБ РФ.
function PlanFinderModal({
  onPick,
  onClose,
}: {
  onPick: (providerName: string, plan: FinderPlan) => void;
  onClose: () => void;
}) {
  const t = useT();
  const providerIds = PLAN_SOURCES.map((s) => s.id);
  const results = useQueries({
    queries: providerIds.map((pid) => ({
      queryKey: ["providerPlans", pid],
      queryFn: () => q.providerPlans(pid),
      retry: 1,
    })),
  });
  // пересобираем только когда реально обновились данные (а не на каждый рендер из-за нового массива results)
  const dataVersion = results.map((r) => r.dataUpdatedAt).join(",");
  const all: FinderPlan[] = useMemo(
    () =>
      results.flatMap((r, i) =>
        (r.data ?? []).map((p) => ({
          ...p,
          providerId: providerIds[i],
          providerLabel: planProviderDisplayName(providerIds[i]),
        })),
      ),
    [dataVersion],
  );
  const doneCount = results.filter((r) => !r.isLoading).length;
  const failed = results.flatMap((r, i) => (r.isError ? [planProviderDisplayName(providerIds[i])] : []));

  // курсы к RUB (кэш ЦБ РФ на бэкенде): держим свежими полдня — повторные фетчи ни к чему
  const fx = useQuery({ queryKey: ["fxRates"], queryFn: q.fxRates, staleTime: 6 * 60 * 60 * 1000, retry: 1 });
  const rates = fx.data?.rates ?? {};

  const [filter, setFilter] = useState<PlanFilter>(DEFAULT_PLAN_FILTER);
  const [limit, setLimit] = useState(FINDER_PAGE_SIZE);
  const patch = (p: Partial<PlanFilter>) => {
    setFilter((f) => ({ ...f, ...p }));
    setLimit(FINDER_PAGE_SIZE);
  };

  // локации сводим к стране: ОАЭ/UAE/Дубай → одна опция «ОАЭ / UAE» (см. planLocation)
  const locationOpts = useMemo<[string, string][]>(() => {
    const byKey = new Map<string, string>();
    for (const p of all) {
      const { key, label } = planLocation(p);
      if (!byKey.has(key)) byKey.set(key, key.startsWith("x:") ? label : `${flagEmoji(key)} ${label}`);
    }
    return [...byKey].sort((a, b) => a[1].replace(/^\S+ /, "").localeCompare(b[1].replace(/^\S+ /, ""), "ru"));
  }, [all]);
  const providerOpts = useMemo<[string, string][]>(
    () =>
      providerIds.filter((id) => all.some((p) => p.providerId === id)).map((id) => [id, planProviderDisplayName(id)]),
    [all],
  );
  const diskTypeOpts = useMemo<[string, string][]>(
    () => [...new Set(all.map((p) => p.diskType).filter(Boolean))].sort().map((d) => [d, d]),
    [all],
  );
  // валюты для бюджета: встречающиеся у тарифов + RUB (база), чтобы всегда было к чему сводить
  const currencyOpts = useMemo(
    () => [...new Set(["RUB", ...all.map((p) => p.currency).filter(Boolean)])].sort(),
    [all],
  );

  // rates берём по версии fx-запроса, чтобы не пересобирать на каждый рендер из-за нового {}-дефолта
  const rows = useMemo<RankedPlan[]>(() => rankPlans(all, filter, rates), [all, filter, fx.dataUpdatedAt]);

  // спиннер — только пока данных совсем нет; дальше показываем результаты по мере подгрузки провайдеров
  const loading = all.length === 0 && results.some((r) => r.isLoading);
  const fxNoteKey = FX_SOURCE_NOTE_KEY[fx.data?.source ?? ""];
  const fxNote = fxNoteKey ? t(fxNoteKey) : "";
  const rangeInput: CSSProperties = { width: "100%", minWidth: 0 };
  const groupLabel: CSSProperties = { fontSize: 12, marginBottom: 5 };
  const filterGrid: CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
    gap: 10,
  };
  const numInput = (key: keyof PlanFilter, placeholder: string) => (
    <input
      className="input"
      type="number"
      min={0}
      placeholder={placeholder}
      value={filter[key] as string}
      onChange={(e) => patch({ [key]: e.target.value })}
      style={rangeInput}
    />
  );
  return (
    <Modal title={t("catalog.finderTitle")} onClose={onClose} xl>
      <div className="stack" style={{ gap: 12 }}>
        <input
          className="input"
          type="search"
          placeholder={t("catalog.finderSearch")}
          value={filter.query}
          onChange={(e) => patch({ query: e.target.value })}
        />
        {/* мультивыборы локаций/провайдеров/типа диска (с поиском) + переключатели */}
        <div className="rowflex" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <MultiSelect
            label={t("catalog.locations")}
            options={locationOpts}
            selected={filter.regions}
            onChange={(regions) => patch({ regions })}
          />
          <MultiSelect
            label={t("catalog.providers")}
            options={providerOpts}
            selected={filter.providers}
            onChange={(providers) => patch({ providers })}
          />
          <MultiSelect
            label={t("catalog.diskType")}
            options={diskTypeOpts}
            selected={filter.diskTypes}
            onChange={(diskTypes) => patch({ diskTypes })}
          />
          <label className="rowflex" style={{ gap: 6, fontSize: 13, cursor: "pointer", alignItems: "center" }}>
            <input
              type="checkbox"
              checked={filter.unlimitedOnly}
              onChange={(e) => patch({ unlimitedOnly: e.target.checked })}
            />
            {t("catalog.unlimitedOnly")}
          </label>
          <label className="rowflex" style={{ gap: 6, fontSize: 13, cursor: "pointer", alignItems: "center" }}>
            <input
              type="checkbox"
              checked={filter.onlyAvailable}
              onChange={(e) => patch({ onlyAvailable: e.target.checked })}
            />
            {t("catalog.onlyAvailable")}
          </label>
          <select
            className="input"
            value={filter.sort}
            onChange={(e) => patch({ sort: e.target.value as PlanSort })}
            style={{ ...compactSelect, marginLeft: "auto" }}
          >
            <option value="price">{t("catalog.sortPrice")}</option>
            <option value="pricePerGb">{t("catalog.sortPricePerGb")}</option>
            <option value="ram">{t("catalog.sortRam")}</option>
            <option value="cpu">{t("catalog.sortCpu")}</option>
          </select>
        </div>

        {/* числовые диапазоны: RAM, CPU, диск, порт и бюджет за месяц в выбранной валюте */}
        <div style={filterGrid}>
          <div>
            <div className="muted-3" style={groupLabel}>
              {t("catalog.ramGb")}
            </div>
            <div style={pairRow}>
              {numInput("ramMin", t("catalog.rangeFrom"))}
              {numInput("ramMax", t("catalog.rangeTo"))}
            </div>
          </div>
          <div>
            <div className="muted-3" style={groupLabel}>
              {t("catalog.cpuMin")}
            </div>
            {numInput("cpuMin", t("catalog.rangeFrom"))}
          </div>
          <div>
            <div className="muted-3" style={groupLabel}>
              {t("catalog.diskMin")}
            </div>
            {numInput("diskMin", t("catalog.rangeFrom"))}
          </div>
          <div>
            <div className="muted-3" style={groupLabel}>
              {t("catalog.portMin")}
            </div>
            {numInput("portMin", t("catalog.rangeFrom"))}
          </div>
          <div style={{ gridColumn: "span 2" }}>
            <div className="muted-3" style={groupLabel}>
              {t("catalog.monthlyBudget")}
            </div>
            <div style={pairRow}>
              {numInput("priceMin", t("catalog.rangeFrom"))}
              {numInput("priceMax", t("catalog.rangeTo"))}
              <select
                className="input"
                value={filter.currency}
                onChange={(e) => patch({ currency: e.target.value })}
                style={{ width: "auto", flex: "none", padding: "11px 8px" }}
              >
                {currencyOpts.map((c) => (
                  <option key={c} value={c}>
                    {currencySymbol(c)} {c}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div
          className="rowflex"
          style={{ justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}
        >
          <span className="muted-3" style={{ fontSize: 12 }}>
            {t("catalog.loadedProviders", { done: doneCount, total: providerIds.length })}
            {failed.length > 0 && ` · ${t("catalog.failedProviders", { names: failed.join(", ") })}`}
            {fxNote && ` · ${fxNote}`}
          </span>
          <span className="muted-3" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
            {t("catalog.foundCount", { n: rows.length })}
          </span>
        </div>

        {loading ? (
          <div style={{ padding: 24, textAlign: "center" }}>
            <Spinner />
          </div>
        ) : rows.length === 0 ? (
          <Empty title={t("catalog.finderEmptyTitle")} sub={t("catalog.finderEmptySub")} />
        ) : (
          <div className="stack" style={{ gap: 8, maxHeight: "56vh", overflowY: "auto" }}>
            {rows.slice(0, limit).map((p) => (
              <div
                key={`${p.providerId}:${p.id}:${p.region}:${p.name}`}
                className="rowflex"
                style={{
                  gap: 12,
                  alignItems: "center",
                  flexWrap: "wrap",
                  padding: "10px 12px",
                  borderRadius: 10,
                  background: "var(--surface-2)",
                }}
              >
                <div style={{ flex: "1 1 200px", minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13.5 }}>
                    <span className="badge" style={{ marginRight: 6 }}>
                      {p.providerLabel}
                    </span>
                    {p.name}
                  </div>
                  <div className="muted-3" style={{ fontSize: 12 }}>
                    {planSpecs(p)}
                  </div>
                </div>
                <div className="rowflex" style={{ gap: 10, alignItems: "center", marginLeft: "auto" }}>
                  <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <div style={{ fontWeight: 700, fontSize: 13.5 }}>{fmtPrice(p)}</div>
                    {p.monthly != null && (p.currency !== filter.currency || p.period !== "month") && (
                      <div className="muted-3" style={{ fontSize: 11.5 }}>
                        {t("catalog.approxMonthly", { amount: fmtMoney(p.monthly, filter.currency) })}
                      </div>
                    )}
                  </div>
                  {p.sourceUrl && (
                    <a href={p.sourceUrl} target="_blank" rel="noopener">
                      <Btn variant="ghost" sm>
                        {t("catalog.buy")} <Icon name="external" size={13} />
                      </Btn>
                    </a>
                  )}
                  <Btn variant="primary" sm onClick={() => onPick(p.providerLabel, p)}>
                    {t("catalog.select")}
                  </Btn>
                </div>
              </div>
            ))}
            {rows.length > limit && (
              <div style={{ display: "flex", justifyContent: "center", padding: 4 }}>
                <Btn variant="ghost" sm onClick={() => setLimit((n) => n + FINDER_PAGE_SIZE)}>
                  {t("catalog.showMore", { n: rows.length - limit })}
                </Btn>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}

interface FormState {
  id?: string;
  name: string;
  url: string;
  blurb: string;
  blurbEn: string;
  tags: string;
  hq: string;
  countries: string;
  payments: PaymentMethod[];
}

const EMPTY: FormState = {
  name: "",
  url: "",
  blurb: "",
  blurbEn: "",
  tags: "",
  hq: "",
  countries: "",
  payments: [],
};

// сколько карточек рисовать сразу (дальше — «Показать ещё») и сколько флагов локаций на карточке
const PAGE_SIZE = 48;
const MAX_FLAGS = 10;

// опции мультивыбора стран: «🇩🇪 Германия / Germany · 12» (12 — сколько провайдеров там есть)
function countryOptions(lists: string[][]): [string, string][] {
  return facetCounts(lists).map(([code, n]) => [code, `${flagEmoji(code)} ${countryLabel(code)} · ${n}`]);
}

// селект в ряду фильтров — по высоте как кнопки-мультивыборы, а не как поле формы
const compactSelect: CSSProperties = { width: "auto", padding: "6px 10px", fontSize: 13 };
// пара полей «от/до» в одну строку (общий .rowflex переносит их в столбик на узких ячейках)
const pairRow: CSSProperties = { display: "flex", gap: 6, alignItems: "center" };

const chipStyle: CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  padding: "4px 9px",
  borderRadius: 999,
  background: "var(--surface-2)",
  color: "var(--text-2)",
};
const outlineChipStyle: CSSProperties = {
  ...chipStyle,
  background: "transparent",
  border: "1px solid var(--border-strong)",
};

// строка «a, b, c» из формы → список без пустых
const splitList = (text: string) =>
  text
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

export function CatalogScreen() {
  const t = useT();
  const go = useNav((s) => s.go);
  const isAdmin = useStore((s) => s.me?.isAdmin ?? false);
  const lang = useStore((s) => s.lang);
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();

  const { data: providers, isLoading } = useQuery({
    queryKey: ["providers"],
    queryFn: q.listProviders,
  });

  const [form, setForm] = useState<FormState | null>(null);
  const [filter, setFilter] = useState<CatalogFilter>(EMPTY_CATALOG_FILTER);
  const [limit, setLimit] = useState(PAGE_SIZE);
  // любое изменение фильтра — снова с первой «страницы», чтобы не держать сотни карточек в DOM
  const patchFilter = (patch: Partial<CatalogFilter>) => {
    setFilter((f) => ({ ...f, ...patch }));
    setLimit(PAGE_SIZE);
  };
  const all = providers ?? [];
  const shown = useMemo(() => filterProviders(all, filter, hasLivePlans), [all, filter]);
  const countryOpts = useMemo(() => countryOptions(all.map((p) => p.countries)), [all]);
  const hqOpts = useMemo(() => countryOptions(all.map((p) => (p.hq ? [p.hq] : []))), [all]);
  const paymentOpts: [string, string][] = PAYMENT_METHODS.filter((m) => all.some((p) => p.payments.includes(m))).map(
    (m) => [m, t(`pay.${m}`)],
  );
  const filtered =
    filter.query.trim() !== "" ||
    filter.countries.length > 0 ||
    filter.payments.length > 0 ||
    filter.hq.length > 0 ||
    filter.liveOnly;
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [plansFor, setPlansFor] = useState<{ pid: string; provider: Provider } | null>(null);
  const [showFinder, setShowFinder] = useState(false);
  const set = (k: Exclude<keyof FormState, "payments">, v: string) => setForm((f) => (f ? { ...f, [k]: v } : f));
  const togglePayment = (m: PaymentMethod) =>
    setForm((f) =>
      f ? { ...f, payments: f.payments.includes(m) ? f.payments.filter((x) => x !== m) : [...f.payments, m] } : f,
    );

  const invalidate = () => qc.invalidateQueries({ queryKey: ["providers"] });

  const save = useMutation({
    mutationFn: async (f: FormState) => {
      const body = {
        name: f.name,
        url: f.url,
        blurb: f.blurb,
        blurbEn: f.blurbEn,
        tags: splitList(f.tags),
        hq: f.hq.trim().toUpperCase(),
        countries: splitList(f.countries).map((c) => c.toUpperCase()),
        payments: f.payments,
      };
      return f.id ? q.adminUpdateProvider(f.id, body) : q.adminCreateProvider(body);
    },
    onSuccess: () => {
      invalidate();
      setForm(null);
      toast(t("catalog.saved"));
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : t("common.error")),
  });

  const del = useMutation({
    mutationFn: (id: string) => q.adminDeleteProvider(id),
    onSuccess: () => {
      invalidate();
      setConfirmId(null);
      toast(t("catalog.providerDeleted"));
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : t("common.error")),
  });

  const openCreate = () => setForm({ ...EMPTY });
  const openEdit = (p: Provider) =>
    setForm({
      id: p.id,
      name: p.name,
      url: p.url,
      blurb: p.blurb,
      blurbEn: p.blurbEn,
      tags: p.tags.join(", "),
      hq: p.hq,
      countries: p.countries.join(", "),
      payments: p.payments,
    });

  return (
    <div className="stack">
      <ScreenHeader
        title={t("catalog.title")}
        sub={t("catalog.sub")}
        onBack={() => go("servers")}
        action={
          <div className="rowflex" style={{ gap: 8 }}>
            <Btn variant="ghost" onClick={() => setShowFinder(true)}>
              <Icon name="search" size={16} />
              {t("catalog.findTariff")}
            </Btn>
            {isAdmin && (
              <Btn variant="primary" onClick={openCreate}>
                <Icon name="plus" size={16} />
                {t("common.add")}
              </Btn>
            )}
          </div>
        }
      />

      {isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner />
        </div>
      ) : all.length === 0 ? (
        <Empty
          title={t("catalog.emptyTitle")}
          sub={t("catalog.emptySub")}
          action={
            isAdmin ? (
              <Btn variant="primary" onClick={openCreate}>
                {t("catalog.addProvider")}
              </Btn>
            ) : undefined
          }
        />
      ) : (
        <>
          <div className="stack" style={{ gap: 10 }}>
            <div style={{ position: "relative" }}>
              <span
                style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", display: "flex" }}
                className="muted-3"
              >
                <Icon name="search" size={16} />
              </span>
              <input
                className="input"
                type="search"
                placeholder={t("catalog.searchPlaceholder")}
                value={filter.query}
                onChange={(e) => patchFilter({ query: e.target.value })}
                style={{ paddingLeft: 36, width: "100%", boxSizing: "border-box" }}
              />
            </div>
            <div className="rowflex" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <MultiSelect
                label={t("catalog.locations")}
                options={countryOpts}
                selected={filter.countries}
                onChange={(countries) => patchFilter({ countries })}
              />
              <MultiSelect
                label={t("catalog.payments")}
                options={paymentOpts}
                selected={filter.payments}
                onChange={(payments) => patchFilter({ payments: payments as PaymentMethod[] })}
              />
              <MultiSelect
                label={t("catalog.hq")}
                options={hqOpts}
                selected={filter.hq}
                onChange={(hq) => patchFilter({ hq })}
              />
              <label className="rowflex" style={{ gap: 6, fontSize: 13, cursor: "pointer", alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={filter.liveOnly}
                  onChange={(e) => patchFilter({ liveOnly: e.target.checked })}
                />
                {t("catalog.liveOnly")}
              </label>
              <select
                className="input"
                value={filter.sort}
                onChange={(e) => patchFilter({ sort: e.target.value as CatalogSort })}
                style={{ ...compactSelect, marginLeft: "auto" }}
              >
                <option value="catalog">{t("catalog.sortCatalog")}</option>
                <option value="name">{t("catalog.sortName")}</option>
                <option value="locations">{t("catalog.sortLocations")}</option>
              </select>
            </div>
            <div className="rowflex" style={{ gap: 10, alignItems: "center" }}>
              <span className="muted-3" style={{ fontSize: 12 }}>
                {t("catalog.shownOf", { n: shown.length, total: all.length })}
              </span>
              {filtered && (
                <Btn variant="ghost" sm onClick={() => patchFilter({ ...EMPTY_CATALOG_FILTER, sort: filter.sort })}>
                  {t("catalog.resetFilters")}
                </Btn>
              )}
            </div>
          </div>

          {shown.length === 0 ? (
            <Empty title={t("catalog.nothingFoundTitle")} sub={t("catalog.nothingFoundSub")} />
          ) : (
            <div className="grid">
              {shown.slice(0, limit).map((p) => (
                <div key={p.id} className="card" style={{ display: "flex", flexDirection: "column", gap: 13 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div
                      style={{
                        width: 44,
                        height: 44,
                        borderRadius: 12,
                        background: "var(--surface-2)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 800,
                        fontSize: 17,
                        color: "var(--text-2)",
                        flex: "none",
                      }}
                    >
                      {(p.name || "?").trim().slice(0, 2).toUpperCase()}
                    </div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontWeight: 700, fontSize: 16, letterSpacing: "-.01em" }}>{p.name}</div>
                    </div>
                    {isAdmin && (
                      <div style={{ display: "flex", gap: 4 }}>
                        <Btn variant="ghost" sm onClick={() => openEdit(p)}>
                          <Icon name="edit" size={16} />
                        </Btn>
                        <Btn variant="ghost" sm onClick={() => setConfirmId(p.id)}>
                          <Icon name="trash" size={16} />
                        </Btn>
                      </div>
                    )}
                  </div>

                  <p className="muted" style={{ fontSize: 13.5, lineHeight: 1.45, minHeight: 38, margin: 0 }}>
                    {providerBlurb(p, lang)}
                  </p>

                  {p.countries.length > 0 && (
                    <div
                      title={p.countries.map(countryLabel).join(", ")}
                      style={{
                        fontSize: 16,
                        lineHeight: 1.3,
                        display: "flex",
                        flexWrap: "wrap",
                        gap: 4,
                        alignItems: "center",
                      }}
                    >
                      {p.countries.slice(0, MAX_FLAGS).map((c) => (
                        <span key={c}>{flagEmoji(c)}</span>
                      ))}
                      {p.countries.length > MAX_FLAGS && (
                        <span className="muted-3" style={{ fontSize: 12, fontWeight: 600 }}>
                          +{p.countries.length - MAX_FLAGS}
                        </span>
                      )}
                    </div>
                  )}

                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, minHeight: 24 }}>
                    {hasLivePlans(p) && (
                      <span
                        style={{
                          ...chipStyle,
                          background: "var(--ok-soft)",
                          color: "var(--ok)",
                        }}
                      >
                        {t("catalog.liveBadge")}
                      </span>
                    )}
                    {p.payments.map((m) => (
                      <span key={m} style={outlineChipStyle}>
                        {t(`pay.${m}`)}
                      </span>
                    ))}
                    {cardTags(p, lang).map((tag) => (
                      <span key={tag} style={chipStyle}>
                        {tag}
                      </span>
                    ))}
                  </div>

                  {/* действия: основная — «Перейти и купить» на всю ширину; ниже — второй ряд */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: "auto" }}>
                    <a href={p.url} target="_blank" rel="noopener" style={primaryAction}>
                      {t("catalog.goAndBuy")}
                      <Icon name="external" size={15} />
                    </a>
                    <div style={{ display: "flex", gap: 8 }}>
                      {isDynamicPlanProviderId(dynamicPlanProviderId(p, p.name)) && (
                        <button
                          type="button"
                          onClick={() => setPlansFor({ pid: dynamicPlanProviderId(p, p.name), provider: p })}
                          title={t("catalog.currentTariffsTitle")}
                          style={secondaryAction}
                        >
                          {t("catalog.tariffs")}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => go("serverForm", { provider: p.name })}
                        style={secondaryAction}
                      >
                        {t("catalog.alreadyHave")}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {shown.length > limit && (
            <div style={{ display: "flex", justifyContent: "center" }}>
              <Btn variant="ghost" onClick={() => setLimit((n) => n + PAGE_SIZE)}>
                {t("catalog.showMore", { n: shown.length - limit })}
              </Btn>
            </div>
          )}
        </>
      )}

      {showFinder && (
        <PlanFinderModal
          onPick={(providerName, plan) => {
            setShowFinder(false);
            // передаём и провайдера, и конкретный тариф — форма создания сервера сразу подставит его
            // (локацию, цену, квоту): см. presetPlan в ServerForm
            go("serverForm", {
              provider: providerName,
              planProviderId: plan.providerId,
              planTariff: plan.name,
              planLocation: plan.region,
            });
          }}
          onClose={() => setShowFinder(false)}
        />
      )}

      {plansFor && (
        <PlansModal
          planPid={plansFor.pid}
          title={plansFor.provider.name}
          buyUrl={plansFor.provider.url}
          onPick={() => {
            const name = plansFor.provider.name;
            setPlansFor(null);
            go("serverForm", { provider: name });
          }}
          onClose={() => setPlansFor(null)}
        />
      )}

      {form && (
        <Modal
          title={form.id ? t("catalog.editProviderTitle") : t("catalog.newProviderTitle")}
          onClose={() => setForm(null)}
          footer={
            <>
              <Btn onClick={() => setForm(null)}>{t("common.cancel")}</Btn>
              <Btn variant="primary" disabled={save.isPending} onClick={() => save.mutate(form)}>
                {t("common.save")}
              </Btn>
            </>
          }
        >
          <Field label={t("catalog.nameLabel")}>
            <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field label={t("catalog.buyUrlLabel")}>
            <input
              className="input"
              placeholder="https://…"
              value={form.url}
              onChange={(e) => set("url", e.target.value)}
            />
          </Field>
          <Field label={t("catalog.descriptionLabel")}>
            <textarea
              className="input"
              rows={3}
              style={{ resize: "vertical", lineHeight: 1.5, minHeight: 78 }}
              value={form.blurb}
              onChange={(e) => set("blurb", e.target.value)}
            />
          </Field>
          <Field label={t("catalog.blurbEnLabel")}>
            <textarea
              className="input"
              rows={3}
              style={{ resize: "vertical", lineHeight: 1.5, minHeight: 78 }}
              value={form.blurbEn}
              onChange={(e) => set("blurbEn", e.target.value)}
            />
          </Field>
          <Field label={t("catalog.countriesLabel")}>
            <input
              className="input"
              placeholder={t("catalog.countriesPlaceholder")}
              value={form.countries}
              onChange={(e) => set("countries", e.target.value)}
            />
          </Field>
          <Field label={t("catalog.hqLabel")}>
            <input
              className="input"
              maxLength={2}
              placeholder="RU"
              value={form.hq}
              onChange={(e) => set("hq", e.target.value)}
              style={{ width: 90 }}
            />
          </Field>
          <Field label={t("catalog.paymentsLabel")}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {PAYMENT_METHODS.map((m) => (
                <button
                  key={m}
                  type="button"
                  className={`chip${form.payments.includes(m) ? " selected" : ""}`}
                  style={{ cursor: "pointer" }}
                  onClick={() => togglePayment(m)}
                >
                  {t(`pay.${m}`)}
                </button>
              ))}
            </div>
          </Field>
          <Field label={t("catalog.tagsLabel")}>
            <input
              className="input"
              placeholder={t("catalog.tagsPlaceholder")}
              value={form.tags}
              onChange={(e) => set("tags", e.target.value)}
            />
          </Field>
        </Modal>
      )}

      {confirmId && (
        <Modal
          title={t("catalog.deleteProviderTitle")}
          onClose={() => setConfirmId(null)}
          footer={
            <>
              <Btn onClick={() => setConfirmId(null)}>{t("common.cancel")}</Btn>
              <Btn variant="danger" disabled={del.isPending} onClick={() => del.mutate(confirmId)}>
                {t("common.delete")}
              </Btn>
            </>
          }
        >
          <p className="muted">{t("catalog.deleteProviderWarning")}</p>
        </Modal>
      )}
    </div>
  );
}
