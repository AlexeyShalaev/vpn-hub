import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { type CSSProperties, useMemo, useState } from "react";
import { Btn, Empty, Field, Icon, Modal, MultiSelect, ScreenHeader, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import { useT } from "../lib/i18n";
import { canonicalLocation } from "../lib/locations";
import {
  currencySymbol,
  DYNAMIC_PLAN_PROVIDER_LABELS,
  dynamicPlanProviderId,
  fmtMoney,
  fmtPrice,
  isDynamicPlanProviderId,
  monthlyPriceIn,
  planProviderDisplayName,
  planSpecs,
} from "../lib/providerPlans";
import * as q from "../lib/queries";
import type { Provider, ProviderPlan } from "../lib/types";
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

// план + к какому провайдеру относится (для агрегированного подбора по всем провайдерам)
type FinderPlan = ProviderPlan & { providerId: string; providerLabel: string };
// плюс месячная цена, приведённая к выбранной валюте (null = пересчёт невозможен — нет курса)
type RankedPlan = FinderPlan & { monthly: number | null };

// число из инпута диапазона; пустое/некорректное → значение по умолчанию (граница «без ограничения»)
function numOr(text: string, fallback: number): number {
  const n = Number(text);
  return text.trim() !== "" && Number.isFinite(n) ? n : fallback;
}

// честная подпись про актуальность курса, которым сводим цены к одной валюте
const FX_SOURCE_NOTE_KEY: Record<string, "catalog.fxNoteCbr" | "catalog.fxNoteCbrStale" | "catalog.fxNoteFallback"> = {
  cbr: "catalog.fxNoteCbr",
  "cbr-stale": "catalog.fxNoteCbrStale",
  fallback: "catalog.fxNoteFallback",
};

// Подбор тарифа по всем провайдерам: агрегирует их тарифы и фильтрует по локациям, провайдерам, RAM и
// бюджету. Валюты у провайдеров разные (RUB/USD/EUR) — все цены сводятся к одной валюте за месяц по
// курсу ЦБ РФ (кэшируется на бэкенде), поэтому бюджет и сортировка работают через провайдеров разом.
function PlanFinderModal({
  onPick,
  onClose,
}: {
  onPick: (providerName: string, plan: FinderPlan) => void;
  onClose: () => void;
}) {
  const t = useT();
  const providerIds = Object.keys(DYNAMIC_PLAN_PROVIDER_LABELS);
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

  // курсы к RUB (кэш ЦБ РФ на бэкенде): держим свежими полдня — повторные фетчи ни к чему
  const fx = useQuery({ queryKey: ["fxRates"], queryFn: q.fxRates, staleTime: 6 * 60 * 60 * 1000, retry: 1 });
  const rates = fx.data?.rates ?? {};

  const [regions, setRegions] = useState<string[]>([]);
  const [providerSel, setProviderSel] = useState<string[]>([]);
  const [ramMin, setRamMin] = useState("");
  const [ramMax, setRamMax] = useState("");
  const [priceMin, setPriceMin] = useState("");
  const [priceMax, setPriceMax] = useState("");
  const [priceCur, setPriceCur] = useState("RUB");
  const [onlyAvailable, setOnlyAvailable] = useState(true);

  // локации сводим к стране: ОАЭ/UAE/Дубай → одна опция «ОАЭ / UAE» (см. canonicalLocation)
  const locationOpts = useMemo<[string, string][]>(() => {
    const byKey = new Map<string, string>();
    for (const p of all) {
      const { key, label } = canonicalLocation(p.region);
      if (!byKey.has(key)) byKey.set(key, label);
    }
    return [...byKey].sort((a, b) => a[1].localeCompare(b[1], "ru"));
  }, [all]);
  const providerOpts = useMemo<[string, string][]>(
    () =>
      providerIds.filter((id) => all.some((p) => p.providerId === id)).map((id) => [id, planProviderDisplayName(id)]),
    [all],
  );
  // валюты для бюджета: встречающиеся у тарифов + RUB (база), чтобы всегда было к чему сводить
  const currencyOpts = useMemo(
    () => [...new Set(["RUB", ...all.map((p) => p.currency).filter(Boolean)])].sort(),
    [all],
  );

  const rows = useMemo<RankedPlan[]>(() => {
    const ramLo = numOr(ramMin, 0);
    const ramHi = numOr(ramMax, Number.POSITIVE_INFINITY);
    const priceLo = numOr(priceMin, 0);
    const priceHi = numOr(priceMax, Number.POSITIVE_INFINITY);
    const hasPriceBound = priceMin.trim() !== "" || priceMax.trim() !== "";
    return all
      .filter((p) => (onlyAvailable ? p.available !== false : true))
      .filter((p) => (regions.length === 0 ? true : regions.includes(canonicalLocation(p.region).key)))
      .filter((p) => (providerSel.length === 0 ? true : providerSel.includes(p.providerId)))
      .filter((p) => p.ramGb >= ramLo && p.ramGb <= ramHi)
      .map((p) => ({ ...p, monthly: monthlyPriceIn(p, priceCur, rates) }))
      .filter((p) => (hasPriceBound ? p.monthly != null && p.monthly >= priceLo && p.monthly <= priceHi : true))
      .sort((a, b) => {
        // дешёвые сверху; тарифы без пересчёта (нет курса валюты) — в конец списка
        if (a.monthly == null || b.monthly == null) return (a.monthly == null ? 1 : 0) - (b.monthly == null ? 1 : 0);
        return a.monthly - b.monthly;
      });
    // rates берём по версии fx-запроса, чтобы не пересобирать на каждый рендер из-за нового {}-дефолта
  }, [all, regions, providerSel, ramMin, ramMax, priceMin, priceMax, priceCur, onlyAvailable, fx.dataUpdatedAt]);

  // спиннер — только пока данных совсем нет; дальше показываем результаты по мере подгрузки провайдеров
  const loading = all.length === 0 && results.some((r) => r.isLoading);
  const fxNoteKey = FX_SOURCE_NOTE_KEY[fx.data?.source ?? ""];
  const fxNote = fxNoteKey ? t(fxNoteKey) : "";
  const rangeInput: CSSProperties = { width: "100%", minWidth: 0 };
  const groupLabel: CSSProperties = { fontSize: 12, marginBottom: 5 };
  const filterGrid: CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
    gap: 10,
  };
  return (
    <Modal title={t("catalog.finderTitle")} onClose={onClose} wide>
      <div className="stack" style={{ gap: 12 }}>
        {/* мультивыборы локаций/провайдеров (с поиском) + переключатель наличия */}
        <div className="rowflex" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <MultiSelect label={t("catalog.locations")} options={locationOpts} selected={regions} onChange={setRegions} />
          <MultiSelect
            label={t("catalog.providers")}
            options={providerOpts}
            selected={providerSel}
            onChange={setProviderSel}
          />
          <label
            className="rowflex"
            style={{ gap: 6, fontSize: 13, cursor: "pointer", alignItems: "center", marginLeft: "auto" }}
          >
            <input type="checkbox" checked={onlyAvailable} onChange={(e) => setOnlyAvailable(e.target.checked)} />
            {t("catalog.onlyAvailable")}
          </label>
        </div>

        {/* числовые диапазоны: RAM и бюджет за месяц в выбранной валюте */}
        <div style={filterGrid}>
          <div>
            <div className="muted-3" style={groupLabel}>
              {t("catalog.ramGb")}
            </div>
            <div className="rowflex" style={{ gap: 6 }}>
              <input
                className="input"
                type="number"
                min={0}
                placeholder={t("catalog.rangeFrom")}
                value={ramMin}
                onChange={(e) => setRamMin(e.target.value)}
                style={rangeInput}
              />
              <input
                className="input"
                type="number"
                min={0}
                placeholder={t("catalog.rangeTo")}
                value={ramMax}
                onChange={(e) => setRamMax(e.target.value)}
                style={rangeInput}
              />
            </div>
          </div>
          <div style={{ gridColumn: "span 2" }}>
            <div className="muted-3" style={groupLabel}>
              {t("catalog.monthlyBudget")}
            </div>
            <div className="rowflex" style={{ gap: 6 }}>
              <input
                className="input"
                type="number"
                min={0}
                placeholder={t("catalog.rangeFrom")}
                value={priceMin}
                onChange={(e) => setPriceMin(e.target.value)}
                style={rangeInput}
              />
              <input
                className="input"
                type="number"
                min={0}
                placeholder={t("catalog.rangeTo")}
                value={priceMax}
                onChange={(e) => setPriceMax(e.target.value)}
                style={rangeInput}
              />
              <select
                className="input"
                value={priceCur}
                onChange={(e) => setPriceCur(e.target.value)}
                style={{ width: "auto", flex: "none" }}
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

        <div className="rowflex" style={{ justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <span className="muted-3" style={{ fontSize: 12 }}>
            {fxNote}
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
            {rows.map((p) => (
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
                    {p.monthly != null && p.currency !== priceCur && (
                      <div className="muted-3" style={{ fontSize: 11.5 }}>
                        {t("catalog.approxMonthly", { amount: fmtMoney(p.monthly, priceCur) })}
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
  tags: string;
}

const EMPTY: FormState = { name: "", url: "", blurb: "", tags: "" };

export function CatalogScreen() {
  const t = useT();
  const go = useNav((s) => s.go);
  const isAdmin = useStore((s) => s.me?.isAdmin ?? false);
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();

  const { data: providers, isLoading } = useQuery({
    queryKey: ["providers"],
    queryFn: q.listProviders,
  });

  const [form, setForm] = useState<FormState | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [plansFor, setPlansFor] = useState<{ pid: string; provider: Provider } | null>(null);
  const [showFinder, setShowFinder] = useState(false);
  const set = (k: keyof FormState, v: string) => setForm((f) => (f ? { ...f, [k]: v } : f));

  const invalidate = () => qc.invalidateQueries({ queryKey: ["providers"] });

  const save = useMutation({
    mutationFn: async (f: FormState) => {
      const body = {
        name: f.name,
        url: f.url,
        blurb: f.blurb,
        tags: f.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
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
    setForm({ id: p.id, name: p.name, url: p.url, blurb: p.blurb, tags: p.tags.join(", ") });

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
      ) : !providers || providers.length === 0 ? (
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
        <div className="grid">
          {providers.map((p) => (
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
                {p.blurb}
              </p>

              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, minHeight: 24 }}>
                {p.tags.map((tag) => (
                  <span
                    key={tag}
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: "4px 9px",
                      borderRadius: 999,
                      background: "var(--surface-2)",
                      color: "var(--text-2)",
                    }}
                  >
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
                  <button type="button" onClick={() => go("serverForm", { provider: p.name })} style={secondaryAction}>
                    {t("catalog.alreadyHave")}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
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
