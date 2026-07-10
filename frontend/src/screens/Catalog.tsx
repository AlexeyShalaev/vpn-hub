import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { type CSSProperties, useMemo, useState } from "react";
import { Btn, Empty, Field, Icon, Modal, MultiSelect, ScreenHeader, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
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
  const pq = useQuery({
    queryKey: ["providerPlans", planPid],
    queryFn: () => q.providerPlans(planPid),
    retry: 1,
  });
  const plans = pq.data ?? [];
  return (
    <Modal title={`Тарифы · ${title}`} onClose={onClose} wide>
      <div className="stack" style={{ gap: 10 }}>
        {pq.isLoading ? (
          <div style={{ padding: 24, textAlign: "center" }}>
            <Spinner />
          </div>
        ) : pq.isError ? (
          <Empty title="Не удалось загрузить тарифы" sub="Провайдер мог изменить страницу. Попробуйте на сайте." />
        ) : plans.length === 0 ? (
          <Empty title="Тарифы не найдены" sub="Актуальный список — на сайте провайдера." />
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
                        · нет в наличии
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
              На сайт провайдера <Icon name="external" size={14} />
            </Btn>
          </a>
          <Btn variant="primary" sm onClick={onPick}>
            Выбрать провайдера
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
const FX_SOURCE_NOTE: Record<string, string> = {
  cbr: "Цены сведены к выбранной валюте по курсу ЦБ РФ.",
  "cbr-stale": "Цены сведены по последнему сохранённому курсу ЦБ РФ.",
  fallback: "Курс ЦБ РФ недоступен — пересчёт приблизительный.",
};

// Подбор тарифа по всем провайдерам: агрегирует их тарифы и фильтрует по локациям, провайдерам, RAM и
// бюджету. Валюты у провайдеров разные (RUB/USD/EUR) — все цены сводятся к одной валюте за месяц по
// курсу ЦБ РФ (кэшируется на бэкенде), поэтому бюджет и сортировка работают через провайдеров разом.
function PlanFinderModal({ onPick, onClose }: { onPick: (providerName: string) => void; onClose: () => void }) {
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

  const regionOpts = useMemo<[string, string][]>(
    () =>
      [...new Set(all.map((p) => p.region).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b, "ru"))
        .map((r) => [r, r]),
    [all],
  );
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
      .filter((p) => (regions.length === 0 ? true : regions.includes(p.region)))
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
  const fxNote = FX_SOURCE_NOTE[fx.data?.source ?? ""] ?? "";
  const rangeInput: CSSProperties = { width: "100%", minWidth: 0 };
  const groupLabel: CSSProperties = { fontSize: 12, marginBottom: 5 };
  const filterGrid: CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
    gap: 10,
  };
  return (
    <Modal title="Подбор тарифа по всем провайдерам" onClose={onClose} wide>
      <div className="stack" style={{ gap: 12 }}>
        {/* мультивыборы локаций/провайдеров (с поиском) + переключатель наличия */}
        <div className="rowflex" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <MultiSelect label="Локации" options={regionOpts} selected={regions} onChange={setRegions} />
          <MultiSelect label="Провайдеры" options={providerOpts} selected={providerSel} onChange={setProviderSel} />
          <label
            className="rowflex"
            style={{ gap: 6, fontSize: 13, cursor: "pointer", alignItems: "center", marginLeft: "auto" }}
          >
            <input type="checkbox" checked={onlyAvailable} onChange={(e) => setOnlyAvailable(e.target.checked)} />
            только в наличии
          </label>
        </div>

        {/* числовые диапазоны: RAM и бюджет за месяц в выбранной валюте */}
        <div style={filterGrid}>
          <div>
            <div className="muted-3" style={groupLabel}>
              RAM, ГБ
            </div>
            <div className="rowflex" style={{ gap: 6 }}>
              <input
                className="input"
                type="number"
                min={0}
                placeholder="от"
                value={ramMin}
                onChange={(e) => setRamMin(e.target.value)}
                style={rangeInput}
              />
              <input
                className="input"
                type="number"
                min={0}
                placeholder="до"
                value={ramMax}
                onChange={(e) => setRamMax(e.target.value)}
                style={rangeInput}
              />
            </div>
          </div>
          <div style={{ gridColumn: "span 2" }}>
            <div className="muted-3" style={groupLabel}>
              Бюджет за месяц
            </div>
            <div className="rowflex" style={{ gap: 6 }}>
              <input
                className="input"
                type="number"
                min={0}
                placeholder="от"
                value={priceMin}
                onChange={(e) => setPriceMin(e.target.value)}
                style={rangeInput}
              />
              <input
                className="input"
                type="number"
                min={0}
                placeholder="до"
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
            Найдено: {rows.length}
          </span>
        </div>

        {loading ? (
          <div style={{ padding: 24, textAlign: "center" }}>
            <Spinner />
          </div>
        ) : rows.length === 0 ? (
          <Empty title="Под фильтры ничего не нашлось" sub="Смягчите условия — например, бюджет, RAM или локации." />
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
                        ≈ {fmtMoney(p.monthly, priceCur)}/мес
                      </div>
                    )}
                  </div>
                  {p.sourceUrl && (
                    <a href={p.sourceUrl} target="_blank" rel="noopener">
                      <Btn variant="ghost" sm>
                        Купить <Icon name="external" size={13} />
                      </Btn>
                    </a>
                  )}
                  <Btn variant="primary" sm onClick={() => onPick(p.providerLabel)}>
                    Выбрать
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
      toast("Сохранено");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Ошибка"),
  });

  const del = useMutation({
    mutationFn: (id: string) => q.adminDeleteProvider(id),
    onSuccess: () => {
      invalidate();
      setConfirmId(null);
      toast("Провайдер удалён");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Ошибка"),
  });

  const openCreate = () => setForm({ ...EMPTY });
  const openEdit = (p: Provider) =>
    setForm({ id: p.id, name: p.name, url: p.url, blurb: p.blurb, tags: p.tags.join(", ") });

  return (
    <div className="stack">
      <ScreenHeader
        title="Каталог провайдеров"
        sub="Где арендовать VPS под VPN"
        onBack={() => go("servers")}
        action={
          <div className="rowflex" style={{ gap: 8 }}>
            <Btn variant="ghost" onClick={() => setShowFinder(true)}>
              <Icon name="search" size={16} />
              Подобрать тариф
            </Btn>
            {isAdmin && (
              <Btn variant="primary" onClick={openCreate}>
                <Icon name="plus" size={16} />
                Добавить
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
          title="Каталог пуст"
          sub="Провайдеры пока не добавлены"
          action={
            isAdmin ? (
              <Btn variant="primary" onClick={openCreate}>
                Добавить провайдера
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
                {p.tags.map((t) => (
                  <span
                    key={t}
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: "4px 9px",
                      borderRadius: 999,
                      background: "var(--surface-2)",
                      color: "var(--text-2)",
                    }}
                  >
                    {t}
                  </span>
                ))}
              </div>

              {/* действия: основная — «Перейти и купить» на всю ширину; ниже — второй ряд */}
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: "auto" }}>
                <a href={p.url} target="_blank" rel="noopener" style={primaryAction}>
                  Перейти и купить
                  <Icon name="external" size={15} />
                </a>
                <div style={{ display: "flex", gap: 8 }}>
                  {isDynamicPlanProviderId(dynamicPlanProviderId(p, p.name)) && (
                    <button
                      type="button"
                      onClick={() => setPlansFor({ pid: dynamicPlanProviderId(p, p.name), provider: p })}
                      title="Актуальные тарифы провайдера"
                      style={secondaryAction}
                    >
                      Тарифы
                    </button>
                  )}
                  <button type="button" onClick={() => go("serverForm", { provider: p.name })} style={secondaryAction}>
                    У меня уже есть
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {showFinder && (
        <PlanFinderModal
          onPick={(providerName) => {
            setShowFinder(false);
            go("serverForm", { provider: providerName });
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
          title={form.id ? "Редактировать провайдера" : "Новый провайдер"}
          onClose={() => setForm(null)}
          footer={
            <>
              <Btn onClick={() => setForm(null)}>Отмена</Btn>
              <Btn variant="primary" disabled={save.isPending} onClick={() => save.mutate(form)}>
                Сохранить
              </Btn>
            </>
          }
        >
          <Field label="Название">
            <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field label="Ссылка для покупки">
            <input
              className="input"
              placeholder="https://…"
              value={form.url}
              onChange={(e) => set("url", e.target.value)}
            />
          </Field>
          <Field label="Описание">
            <textarea
              className="input"
              rows={3}
              style={{ resize: "vertical", lineHeight: 1.5, minHeight: 78 }}
              value={form.blurb}
              onChange={(e) => set("blurb", e.target.value)}
            />
          </Field>
          <Field label="Теги (через запятую)">
            <input
              className="input"
              placeholder="Дёшево, Европа"
              value={form.tags}
              onChange={(e) => set("tags", e.target.value)}
            />
          </Field>
        </Modal>
      )}

      {confirmId && (
        <Modal
          title="Удалить провайдера?"
          onClose={() => setConfirmId(null)}
          footer={
            <>
              <Btn onClick={() => setConfirmId(null)}>Отмена</Btn>
              <Btn variant="danger" disabled={del.isPending} onClick={() => del.mutate(confirmId)}>
                Удалить
              </Btn>
            </>
          }
        >
          <p className="muted">Провайдер исчезнет из каталога. На уже созданные серверы это не влияет.</p>
        </Modal>
      )}
    </div>
  );
}
