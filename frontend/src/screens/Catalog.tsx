import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { type CSSProperties, useMemo, useState } from "react";
import { Btn, Empty, Field, Icon, Modal, ScreenHeader, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import {
  DYNAMIC_PLAN_PROVIDER_LABELS,
  dynamicPlanProviderId,
  fmtPrice,
  isDynamicPlanProviderId,
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

// Подбор тарифа по всем провайдерам: агрегирует их тарифы и фильтрует по локации, бюджету и RAM.
// Валюты у провайдеров разные (RUB/USD/EUR) — бюджет применяется в рамках выбранной валюты.
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

  const [region, setRegion] = useState("");
  const [currency, setCurrency] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [minRam, setMinRam] = useState("");
  const [onlyAvailable, setOnlyAvailable] = useState(true);

  const regions = useMemo(() => [...new Set(all.map((p) => p.region).filter(Boolean))].sort(), [all]);
  const currencies = useMemo(() => [...new Set(all.map((p) => p.currency).filter(Boolean))].sort(), [all]);

  const rows = useMemo(() => {
    const budget = Number(maxPrice) || 0;
    const ram = Number(minRam) || 0;
    return all
      .filter((p) => (onlyAvailable ? p.available !== false : true))
      .filter((p) => (region ? p.region === region : true))
      .filter((p) => (currency ? p.currency === currency : true))
      .filter((p) => (budget > 0 && currency ? p.price <= budget : true))
      .filter((p) => (ram > 0 ? p.ramGb >= ram : true))
      .sort((a, b) => a.currency.localeCompare(b.currency) || a.price - b.price);
  }, [all, region, currency, maxPrice, minRam, onlyAvailable]);

  // спиннер — только пока данных совсем нет; дальше показываем результаты по мере подгрузки провайдеров
  const loading = all.length === 0 && results.some((r) => r.isLoading);
  const filterGrid: CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
    gap: 8,
  };
  return (
    <Modal title="Подбор тарифа по всем провайдерам" onClose={onClose} wide>
      <div className="stack" style={{ gap: 12 }}>
        {/* фильтры — адаптивная сетка (используем родной .input, без форс-высоты, иначе текст обрезается) */}
        <div style={filterGrid}>
          <select className="input" value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">Все локации</option>
            {regions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            <option value="">Любая валюта</option>
            {currencies.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <input
            className="input"
            type="number"
            min={0}
            placeholder={currency ? `Бюджет, ${currency}` : "Бюджет"}
            value={maxPrice}
            disabled={!currency}
            title={currency ? "" : "Сначала выберите валюту"}
            onChange={(e) => setMaxPrice(e.target.value)}
          />
          <select className="input" value={minRam} onChange={(e) => setMinRam(e.target.value)}>
            <option value="">RAM любой</option>
            {[1, 2, 4, 8, 16].map((g) => (
              <option key={g} value={g}>
                от {g} ГБ
              </option>
            ))}
          </select>
        </div>
        <div className="rowflex" style={{ justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <label className="rowflex" style={{ gap: 6, fontSize: 13, cursor: "pointer", alignItems: "center" }}>
            <input type="checkbox" checked={onlyAvailable} onChange={(e) => setOnlyAvailable(e.target.checked)} />
            только в наличии
          </label>
          <span className="muted-3" style={{ fontSize: 12 }}>
            Найдено: {rows.length}
          </span>
        </div>

        {loading ? (
          <div style={{ padding: 24, textAlign: "center" }}>
            <Spinner />
          </div>
        ) : rows.length === 0 ? (
          <Empty title="Под фильтры ничего не нашлось" sub="Смягчите условия — например, бюджет или локацию." />
        ) : (
          <div className="stack" style={{ gap: 8, maxHeight: "60vh", overflowY: "auto" }}>
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
                  <div style={{ fontWeight: 700, fontSize: 13.5, whiteSpace: "nowrap" }}>{fmtPrice(p)}</div>
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
