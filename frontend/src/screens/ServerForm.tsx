import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Btn, Field, Icon, ScreenHeader, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import type { ParsedServerInfo } from "../lib/credentialParse";
import { parseServerInfo } from "../lib/credentialParse";
import * as q from "../lib/queries";
import {
  bytesToTrafficInput,
  convertTrafficInputUnit,
  TRAFFIC_UNITS,
  type TrafficUnit,
  trafficValueToBytes,
} from "../lib/trafficUnits";
import type { Provider, ProviderPlan, Server } from "../lib/types";
import { useNav } from "../nav";
import { useStore } from "../store";

interface FormState {
  name: string;
  provider: string;
  providerCustom: boolean;
  ip: string;
  location: string;
  providerPlan: string;
  sshUser: string;
  sshPort: string;
  auth: "key" | "password";
  secret: string;
}

interface BillingState {
  priceAmount: string;
  priceCurrency: string;
  pricePeriod: string;
  priceAnchorDay: string;
  trafficQuotaValue: string;
  trafficQuotaUnit: TrafficUnit;
  trafficBillingDay: string;
}

const EMPTY: FormState = {
  name: "",
  provider: "",
  providerCustom: false,
  ip: "",
  location: "",
  providerPlan: "",
  sshUser: "root",
  sshPort: "22",
  auth: "key",
  secret: "",
};

const EMPTY_BILLING: BillingState = {
  priceAmount: "",
  priceCurrency: "RUB",
  pricePeriod: "month",
  priceAnchorDay: "",
  trafficQuotaValue: "",
  trafficQuotaUnit: "GB",
  trafficBillingDay: "",
};

const CURRENCIES = ["RUB", "USD", "EUR", "KZT", "UAH", "GBP"];
const PRICE_PERIODS = ["minute", "day", "month"];

// Популярные локации VPN-серверов. Пользователь может выбрать из списка
// или ввести любое своё значение — поле-датлист принимает и то, и другое.
const LOCATION_OPTIONS = [
  "Нидерланды",
  "Германия",
  "Финляндия",
  "Франция",
  "Швеция",
  "Швейцария",
  "Великобритания",
  "США",
  "Польша",
  "Латвия",
  "Литва",
  "Эстония",
  "Турция",
  "Сербия",
  "Чехия",
  "Австрия",
  "Испания",
  "Италия",
  "Казахстан",
  "Россия",
  "Армения",
  "Грузия",
  "ОАЭ",
  "Сингапур",
  "Япония",
  "Гонконг",
  "Канада",
];

// Название сервера по умолчанию: «Локация [Провайдер]». Провайдер опционален
// (для «Другой» без имени — только локация). Без локации имя не предлагаем.
function suggestName(location: string, provider: string): string {
  const loc = location.trim();
  const prov = provider.trim();
  if (!loc) return "";
  return prov ? `${loc} [${prov}]` : loc;
}

const PRICE_PERIOD_LABEL: Record<string, string> = { minute: "мин", day: "день", month: "мес" };
const DYNAMIC_PLAN_PROVIDER_LABELS: Record<string, string> = {
  ahost: "AHost",
  firstbyte: "FirstByte",
  ishosting: "ISHOSTING",
  serverspace: "Serverspace",
  ufo: "UFO Hosting",
};

function normalizeProviderKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[\s._-]+/g, "");
}

function isDynamicPlanProviderId(providerId: string | undefined): providerId is string {
  return !!providerId && Object.hasOwn(DYNAMIC_PLAN_PROVIDER_LABELS, providerId);
}

function dynamicPlanProviderIdByName(name: string): string {
  const key = normalizeProviderKey(name);
  if (key === "ahost" || key === "ahosteu") return "ahost";
  if (key === "firstbyte") return "firstbyte";
  if (key === "ishosting" || key === "ishostingcom") return "ishosting";
  if (key === "serverspace" || key === "serverspaceru" || key === "serverspaceio") return "serverspace";
  if (key === "ufo" || key === "ufohosting") return "ufo";
  return "";
}

function dynamicPlanProviderId(p: Provider | null, providerName: string): string {
  const byId = (p?.id ?? "").toLowerCase();
  if (isDynamicPlanProviderId(byId)) return byId;
  const byKnownName = dynamicPlanProviderIdByName(p?.name ?? "");
  if (byKnownName) return byKnownName;
  return dynamicPlanProviderIdByName(providerName);
}

function planProviderDisplayName(providerId: string): string {
  return DYNAMIC_PLAN_PROVIDER_LABELS[providerId] ?? providerId;
}

function fmtTraffic(tb: number | null): string {
  return tb == null ? "безлимит" : `${tb} ТБ`;
}

function fmtPrice(p: ProviderPlan): string {
  return `${p.price.toLocaleString("ru-RU")} ${p.currency}/${PRICE_PERIOD_LABEL[p.period] ?? p.period}`;
}

function fmtPort(p: ProviderPlan): string {
  return p.portMbps > 0 ? `${p.portMbps} Мбит` : "порт не указан";
}

function planSpecs(p: ProviderPlan): string {
  return `${p.cpu}vCPU/${p.ramGb}ГБ RAM · ${p.diskGb}ГБ ${p.diskType} · ${fmtPort(p)} · ${fmtTraffic(p.trafficTb)}`;
}

function planOptionKey(p: ProviderPlan): string {
  return `${p.id}::${p.region}::${p.name}`;
}

function providerPlanLabel(p: ProviderPlan): string {
  return p.name.split(" · ")[0]?.trim() || p.name;
}

function providerPlanMatchKey(name: string): string {
  return name.trim().toLowerCase().replace(/\s+/g, " ");
}

function providerPlanBaseMatchKey(name: string): string {
  return providerPlanMatchKey(name.replace(/\[[a-z]{2}\]\s*$/i, "").replace(/\s+·.+$/, ""));
}

function providerPlanLooseMatchKey(name: string): string {
  const base = providerPlanBaseMatchKey(name);
  const ishostingPlan = /^(lite|start|medium|premium|elite|exclusive)\b/.exec(base);
  return ishostingPlan?.[1] ?? base;
}

function sameRegion(a: string, b: string): boolean {
  return a.trim().localeCompare(b.trim(), "ru", { sensitivity: "accent" }) === 0;
}

function findProviderPlanByTariff(plans: ProviderPlan[], tariff: string, region = ""): ProviderPlan | null {
  const target = providerPlanMatchKey(tariff);
  const targetBase = providerPlanBaseMatchKey(tariff);
  const targetLoose = providerPlanLooseMatchKey(tariff);
  if (!target) return null;
  const exactMatches = plans.filter((p) => {
    const label = providerPlanLabel(p);
    return (
      providerPlanMatchKey(label) === target ||
      providerPlanMatchKey(p.name) === target ||
      (targetBase && providerPlanBaseMatchKey(label) === targetBase)
    );
  });
  const matches =
    exactMatches.length > 0 || !region.trim()
      ? exactMatches
      : plans.filter((p) => providerPlanLooseMatchKey(providerPlanLabel(p)) === targetLoose);
  const regionMatch = region.trim() ? matches.find((p) => sameRegion(p.region, region)) : null;
  return regionMatch ?? matches[0] ?? null;
}

function providerNameById(providers: Provider[], providerId: string): string {
  const p = providers.find((pp) => pp.id === providerId);
  if (p) return p.name;
  if (isDynamicPlanProviderId(providerId)) return planProviderDisplayName(providerId);
  return providerId;
}

function withProviderPlan(
  metadata: Record<string, unknown> | undefined,
  providerPlan: string,
): Record<string, unknown> {
  const next = { ...(metadata ?? {}) };
  const plan = providerPlan.trim();
  if (plan) next.providerPlan = plan;
  else delete next.providerPlan;
  return next;
}

function nullableNumber(s: string): number | null {
  if (!s.trim()) return null;
  const n = Number.parseFloat(s.replace(",", "."));
  return Number.isFinite(n) && n >= 0 ? n : null;
}

function nullableDay(s: string): number | null {
  if (!s.trim()) return null;
  const n = Number.parseInt(s, 10);
  return Number.isInteger(n) && n >= 1 && n <= 31 ? n : null;
}

export function ServerFormScreen() {
  const params = useNav((s) => s.params);
  const go = useNav((s) => s.go);
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();

  const serverId = params.serverId;
  const presetProvider = params.provider;

  const providersQ = useQuery({ queryKey: ["providers"], queryFn: q.listProviders });
  const serverQ = useQuery({
    queryKey: ["server", serverId],
    queryFn: () => q.getServer(serverId!),
    enabled: !!serverId,
  });
  const priceQ = useQuery({
    queryKey: ["serverPrice", serverId],
    queryFn: () => q.getServerPrice(serverId!),
    enabled: !!serverId,
  });

  const providers: Provider[] = providersQ.data ?? [];
  const known = useMemo(() => (name: string) => providers.some((p) => p.name === name), [providers]);

  const [form, setForm] = useState<FormState>(() => {
    if (presetProvider) return { ...EMPTY, provider: presetProvider };
    return EMPTY;
  });
  const [loaded, setLoaded] = useState(!serverId);
  const [priceLoaded, setPriceLoaded] = useState(!serverId);
  const [billing, setBilling] = useState<BillingState>(EMPTY_BILLING);
  // Пользователь правил название вручную → перестаём автоподставлять его.
  const [nameTouched, setNameTouched] = useState(false);

  // Заполнить форму данными существующего сервера.
  useEffect(() => {
    if (!serverId || loaded) return;
    const s: Server | undefined = serverQ.data;
    if (!s) return;
    setForm({
      name: s.name,
      provider: s.provider,
      providerCustom: !!s.provider && !known(s.provider),
      ip: s.ip,
      location: s.location,
      providerPlan: typeof s.providerMetadata?.providerPlan === "string" ? s.providerMetadata.providerPlan : "",
      sshUser: s.sshUser,
      sshPort: s.sshPort,
      auth: s.auth,
      secret: s.secret,
    });
    const quotaInput = bytesToTrafficInput(s.bandwidthQuota);
    setBilling((b) => ({
      ...b,
      trafficQuotaValue: quotaInput.value,
      trafficQuotaUnit: quotaInput.unit,
      trafficBillingDay: s.billingDay ? String(s.billingDay) : "",
    }));
    setLoaded(true);
  }, [serverId, loaded, serverQ.data, known]);

  useEffect(() => {
    if (!serverId || priceLoaded || !priceQ.isSuccess) return;
    const price = priceQ.data.price;
    setBilling((b) => ({
      ...b,
      priceAmount: price ? String(price.amount) : "",
      priceCurrency: price?.currency ?? b.priceCurrency,
      pricePeriod: price?.period ?? b.pricePeriod,
      priceAnchorDay: price?.anchorDay ? String(price.anchorDay) : "",
    }));
    setPriceLoaded(true);
  }, [serverId, priceLoaded, priceQ.isSuccess, priceQ.data]);

  // Автоподстановка названия из локации и провайдера, пока пользователь
  // не тронул поле вручную (только при создании — существующий сервер не трогаем).
  useEffect(() => {
    if (serverId || nameTouched) return;
    const auto = suggestName(form.location, form.provider);
    setForm((f) => (f.name === auto ? f : { ...f, name: auto }));
  }, [serverId, nameTouched, form.provider, form.location]);

  function set<K extends keyof FormState>(key: K, val: FormState[K]) {
    setForm((p) => ({ ...p, [key]: val }));
  }

  // Ручная правка названия отключает автоподстановку; очистка поля — включает обратно.
  function onNameChange(val: string) {
    set("name", val);
    setNameTouched(val.trim() !== "");
  }

  const selProvider = useMemo(() => {
    if (form.providerCustom) return null;
    return providers.find((p) => p.name === form.provider) ?? null;
  }, [providers, form.provider, form.providerCustom]);
  const planProviderId = dynamicPlanProviderId(selProvider, form.provider);
  const planProviderLabel = planProviderDisplayName(planProviderId);

  const [planRegion, setPlanRegion] = useState("");
  const [planId, setPlanId] = useState("");

  // Динамические тарифы провайдера. Страна/тариф — необязательная подсказка
  // для автозаполнения локации, цены и квоты трафика; SSH/IP остаются ручными.
  const plansQ = useQuery({
    queryKey: ["providerPlans", planProviderId],
    queryFn: () => q.providerPlans(planProviderId),
    enabled: !!planProviderId,
  });
  const plans = plansQ.data ?? [];
  const planRegions = useMemo(
    () => [...new Set(plans.map((p) => p.region).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru")),
    [plans],
  );
  const filteredPlans = useMemo(
    () => (planRegion ? plans.filter((p) => p.region === planRegion) : []),
    [plans, planRegion],
  );
  const selPlan = useMemo(() => plans.find((p) => planOptionKey(p) === planId) ?? null, [plans, planId]);

  useEffect(() => {
    setPlanRegion("");
    setPlanId("");
  }, [planProviderId]);

  useEffect(() => {
    if (planRegion || !form.location.trim() || planRegions.length === 0) return;
    const match = planRegions.find((r) => r.localeCompare(form.location.trim(), "ru", { sensitivity: "accent" }) === 0);
    if (match) setPlanRegion(match);
  }, [planRegion, planRegions, form.location]);

  function onPlanRegionChange(region: string) {
    setPlanRegion(region);
    setPlanId("");
    if (region) set("location", region);
  }

  function applyProviderPlan(plan: ProviderPlan) {
    setPlanRegion(plan.region);
    setPlanId(planOptionKey(plan));
    setForm((f) => ({ ...f, location: plan.region, providerPlan: providerPlanLabel(plan) }));
    setBilling((b) => ({
      ...b,
      priceAmount: String(plan.price),
      priceCurrency: plan.currency,
      pricePeriod: plan.period,
      priceAnchorDay: "",
      trafficQuotaValue: plan.trafficTb ? String(plan.trafficTb) : "",
      trafficQuotaUnit: "TB",
    }));
  }

  function onPlanChange(id: string) {
    const plan = plans.find((p) => planOptionKey(p) === id);
    if (!plan) return;
    applyProviderPlan(plan);
    setPendingProviderPlan(null);
  }

  async function applyBillingToServer(targetServerId: string) {
    await q.setServerPrice(targetServerId, {
      amount: nullableNumber(billing.priceAmount),
      currency: billing.priceCurrency,
      period: billing.pricePeriod,
      anchorDay: billing.pricePeriod === "month" ? nullableDay(billing.priceAnchorDay) : null,
    });
    await q.setBandwidthQuota(
      targetServerId,
      trafficValueToBytes(billing.trafficQuotaValue, billing.trafficQuotaUnit),
      nullableDay(billing.trafficBillingDay),
    );
  }

  // Умное автозаполнение: пользователь вставляет письмо провайдера,
  // распознанные реквизиты сразу подставляются в поля.
  const [pasteText, setPasteText] = useState("");
  const [parsed, setParsed] = useState<ParsedServerInfo | null>(null);
  const [pendingProviderPlan, setPendingProviderPlan] = useState<{
    providerId: string;
    tariff: string;
    location?: string;
  } | null>(null);

  useEffect(() => {
    if (!pendingProviderPlan || pendingProviderPlan.providerId !== planProviderId || plans.length === 0) return;
    const plan = findProviderPlanByTariff(plans, pendingProviderPlan.tariff, pendingProviderPlan.location);
    if (!plan) return;
    applyProviderPlan(plan);
    setPendingProviderPlan(null);
  }, [pendingProviderPlan, planProviderId, plans]);

  function onPasteChange(text: string) {
    setPasteText(text);
    if (!text.trim()) {
      setParsed(null);
      setPendingProviderPlan(null);
      return;
    }
    const selectedProvider = providers.find((p) => p.name === form.provider);
    const selectedId =
      selectedProvider?.id ??
      (!form.providerCustom ? dynamicPlanProviderIdByName(form.provider) || undefined : undefined);
    const info = parseServerInfo(text, selectedId);
    setParsed(info);
    const planProvider = info.providerId ?? selectedId;
    setPendingProviderPlan(
      planProvider && isDynamicPlanProviderId(planProvider) && info.tariff
        ? { providerId: planProvider, tariff: info.tariff, location: info.location }
        : null,
    );
    setForm((f) => {
      const n = { ...f };
      if (info.providerId) {
        const p = providers.find((pp) => pp.id === info.providerId);
        if (p || isDynamicPlanProviderId(info.providerId)) {
          n.provider = p?.name ?? planProviderDisplayName(info.providerId);
          n.providerCustom = false;
        }
      }
      if (info.ip) n.ip = info.ip;
      else if (info.hostname) n.ip = info.hostname;
      if (info.sshUser) n.sshUser = info.sshUser;
      if (info.sshPort) n.sshPort = info.sshPort;
      if (info.tariff) n.providerPlan = info.tariff;
      if (info.password) {
        n.secret = info.password;
        n.auth = "password";
      }
      if (info.location) n.location = info.location;
      return n;
    });
  }

  const parsedChips = useMemo(() => {
    if (!parsed) return [];
    const chips: string[] = [];
    if (parsed.providerId) {
      chips.push(`Провайдер: ${providerNameById(providers, parsed.providerId)}`);
    }
    if (parsed.ip) chips.push(`IP: ${parsed.ip}`);
    else if (parsed.hostname) chips.push(`Хост: ${parsed.hostname}`);
    if (parsed.sshUser) chips.push(`Пользователь: ${parsed.sshUser}`);
    if (parsed.password) chips.push("Пароль: ••••••");
    if (parsed.sshPort) chips.push(`Порт: ${parsed.sshPort}`);
    if (parsed.location) chips.push(`Локация: ${parsed.location}`);
    if (parsed.tariff) chips.push(`Тариф: ${parsed.tariff}`);
    return chips;
  }, [parsed, providers]);
  const pendingTariff = pendingProviderPlan?.providerId === planProviderId ? pendingProviderPlan.tariff : "";
  const pendingMatch = pendingTariff
    ? findProviderPlanByTariff(plans, pendingTariff, pendingProviderPlan?.location)
    : null;
  const pendingNotFound = !!pendingTariff && plansQ.isSuccess && plans.length > 0 && !pendingMatch;
  const pendingPlanProviderLabel = planProviderDisplayName(pendingProviderPlan?.providerId ?? planProviderId);
  const pendingPlanMessage = (() => {
    if (!pendingTariff) return "";
    if (plansQ.isError) {
      return `Нашли тариф ${pendingTariff}, но каталог ${pendingPlanProviderLabel} сейчас не загрузился. Тариф оставлен в поле.`;
    }
    if (pendingNotFound) {
      return `Каталог ${pendingPlanProviderLabel} загружен, но тариф ${pendingTariff} не найден. Тариф оставлен в поле.`;
    }
    if (plansQ.isLoading || plansQ.isFetching) {
      return `Нашли тариф ${pendingTariff}. Загружаем каталог ${pendingPlanProviderLabel}, затем подставим цену и квоту.`;
    }
    return `Нашли тариф ${pendingTariff}. Ждём каталог ${pendingPlanProviderLabel} для автозаполнения цены и квоты.`;
  })();

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => (serverId ? q.updateServer(serverId, body) : q.createServer(body)),
    onSuccess: async (res) => {
      qc.invalidateQueries({ queryKey: ["servers"] });
      qc.invalidateQueries({ queryKey: ["server", res.id] });
      try {
        await applyBillingToServer(res.id);
        qc.invalidateQueries({ queryKey: ["server", res.id] });
        qc.invalidateQueries({ queryKey: ["serverPrice", res.id] });
        qc.invalidateQueries({ queryKey: ["serverCost", res.id] });
        qc.invalidateQueries({ queryKey: ["serverUsage", res.id] });
      } catch {
        toast("Сервер сохранён, но цену/квоту не удалось применить");
        go("server", { serverId: res.id });
        return;
      }
      toast("Сервер сохранён");
      go("server", { serverId: res.id });
    },
    onError: (e) => {
      toast(e instanceof ApiError ? e.message : "Не удалось сохранить");
    },
  });

  function onSave() {
    if (!form.name.trim() || !form.ip.trim() || !form.location.trim()) {
      toast("Заполните название, IP и локацию");
      return;
    }
    if (billing.priceAmount.trim() && nullableNumber(billing.priceAmount) == null) {
      toast("Проверьте стоимость сервера");
      return;
    }
    if (
      billing.trafficQuotaValue.trim() &&
      trafficValueToBytes(billing.trafficQuotaValue, billing.trafficQuotaUnit) == null
    ) {
      toast("Проверьте квоту трафика");
      return;
    }
    if (
      (billing.pricePeriod === "month" &&
        billing.priceAnchorDay.trim() &&
        nullableDay(billing.priceAnchorDay) == null) ||
      (billing.trafficBillingDay.trim() && nullableDay(billing.trafficBillingDay) == null)
    ) {
      toast("День периода должен быть от 1 до 31");
      return;
    }
    save.mutate({
      name: form.name,
      provider: form.provider || "Другой",
      ip: form.ip,
      location: form.location.trim(),
      providerMetadata: withProviderPlan(serverQ.data?.providerMetadata, form.providerPlan),
      sshUser: form.sshUser || "root",
      sshPort: form.sshPort || "22",
      auth: form.auth,
      secret: form.secret,
    });
  }

  const loginLabel = form.auth === "key" ? "SSH пользователь" : "Логин";
  const secretLabel = form.auth === "key" ? "SSH-ключ" : "Пароль";
  const secretPlaceholder = form.auth === "key" ? "путь к ключу или вставьте ключ" : "пароль для пользователя";

  if (serverId && (serverQ.isLoading || priceQ.isLoading || !loaded)) {
    return (
      <div style={{ maxWidth: 620, margin: "0 auto", width: "100%" }}>
        <ScreenHeader title="Редактировать сервер" onBack={() => go("server", { serverId })} />
        <div className="card" style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner />
        </div>
      </div>
    );
  }

  const onBack = () => (serverId ? go("server", { serverId }) : go("servers"));

  return (
    <div style={{ maxWidth: 620, margin: "0 auto", width: "100%" }}>
      <ScreenHeader title={serverId ? "Редактировать сервер" : "Новый сервер"} onBack={onBack} />

      <div className="card stack" style={{ gap: 18 }}>
        {/* Провайдер */}
        <Field label="Провайдер">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {providers.map((p) => {
              const on = !form.providerCustom && form.provider === p.name;
              return (
                <button
                  key={p.id}
                  type="button"
                  className={`chip${on ? " selected" : ""}`}
                  style={{ cursor: "pointer", height: 38, padding: "0 14px", fontSize: 13 }}
                  onClick={() => setForm((f) => ({ ...f, provider: p.name, providerCustom: false }))}
                >
                  {p.name}
                </button>
              );
            })}
            <button
              type="button"
              className={`chip${form.providerCustom ? " selected" : ""}`}
              style={{ cursor: "pointer", height: 38, padding: "0 14px", fontSize: 13 }}
              onClick={() =>
                setForm((f) => ({
                  ...f,
                  providerCustom: true,
                  provider: f.providerCustom ? f.provider : "",
                }))
              }
            >
              Другой
            </button>
          </div>

          {form.providerCustom && (
            <input
              className="input"
              style={{ marginTop: 10 }}
              value={form.provider}
              onChange={(e) => set("provider", e.target.value)}
              placeholder="Название провайдера"
            />
          )}

          {selProvider && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 12,
                marginTop: 12,
                padding: 15,
                border: "1px solid var(--border)",
                borderRadius: 14,
                background: "var(--surface-2)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: 11,
                    background: "var(--surface)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 800,
                    fontSize: 15,
                    color: "var(--text-2)",
                    flex: "none",
                    border: "1px solid var(--border)",
                  }}
                >
                  {selProvider.name.slice(0, 2).toUpperCase()}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 15.5 }}>{selProvider.name}</div>
                </div>
              </div>
              <p style={{ fontSize: 13, color: "var(--text-2)", lineHeight: 1.45, margin: 0 }}>{selProvider.blurb}</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {selProvider.tags.map((t) => (
                  <span
                    key={t}
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: "4px 9px",
                      borderRadius: 999,
                      background: "var(--surface)",
                      color: "var(--text-2)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    {t}
                  </span>
                ))}
              </div>

              {planProviderId && (
                <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-2)" }}>
                    Тариф {planProviderLabel} для автозаполнения
                  </span>
                  {plansQ.isLoading ? (
                    <div className="rowflex" style={{ gap: 8, color: "var(--text-3)", fontSize: 12.5 }}>
                      <Spinner />
                      Загружаем страны и тарифы…
                    </div>
                  ) : plansQ.isError ? (
                    <span style={{ fontSize: 12.5, color: "var(--danger)" }}>
                      Не удалось загрузить тарифы {planProviderLabel}.
                    </span>
                  ) : plans.length === 0 ? (
                    <span style={{ fontSize: 12.5, color: "var(--text-3)" }}>
                      Тарифы {planProviderLabel} не найдены.
                    </span>
                  ) : (
                    <>
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                          gap: 10,
                        }}
                      >
                        <Field label="Страна">
                          <select
                            className="input"
                            value={planRegion}
                            onChange={(e) => onPlanRegionChange(e.target.value)}
                          >
                            <option value="">— выбрать —</option>
                            {planRegions.map((r) => (
                              <option key={r} value={r}>
                                {r} · {plans.filter((p) => p.region === r).length}
                              </option>
                            ))}
                          </select>
                        </Field>
                        <Field label="Тариф">
                          <select
                            className="input"
                            value={planId}
                            disabled={!planRegion || filteredPlans.length === 0}
                            onChange={(e) => onPlanChange(e.target.value)}
                          >
                            <option value="">— выбрать тариф —</option>
                            {filteredPlans.map((p) => (
                              <option key={planOptionKey(p)} value={planOptionKey(p)}>
                                {p.name} — {fmtPrice(p)} · {planSpecs(p)}
                                {p.available === false ? " · недоступен к заказу" : ""}
                              </option>
                            ))}
                          </select>
                        </Field>
                      </div>
                      {selPlan && (
                        <div
                          style={{
                            border: "1px solid var(--border)",
                            borderRadius: 11,
                            background: "var(--surface)",
                            padding: "10px 12px",
                          }}
                        >
                          <div style={{ fontSize: 13, fontWeight: 700 }}>{selPlan.name}</div>
                          <div className="muted-3" style={{ fontSize: 12, marginTop: 3 }}>
                            {fmtPrice(selPlan)} · {planSpecs(selPlan)}
                            {selPlan.available === false ? " · недоступен к заказу" : ""}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              <a
                href={selProvider.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 7,
                  height: 40,
                  borderRadius: 11,
                  background: "var(--ink)",
                  color: "var(--on-ink)",
                  fontWeight: 600,
                  fontSize: 13,
                  textDecoration: "none",
                }}
              >
                Перейти на сайт и купить
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M7 17L17 7M9 7h8v8" />
                </svg>
              </a>
            </div>
          )}
        </Field>

        {/* Умное автозаполнение из письма провайдера */}
        {!serverId && (
          <Field label="Автозаполнение из письма">
            <textarea
              className="input"
              rows={4}
              value={pasteText}
              onChange={(e) => onPasteChange(e.target.value)}
              placeholder="Вставьте письмо от провайдера с данными сервера — IP, логин и пароль заполнятся сами"
              style={{ resize: "vertical", minHeight: 96, fontSize: 13.5 }}
            />
            {parsed &&
              (parsedChips.length > 0 ? (
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    alignItems: "center",
                    gap: 6,
                    marginTop: 8,
                  }}
                >
                  <span style={{ color: "var(--text-2)", display: "inline-flex" }}>
                    <Icon name="sparkles" size={15} />
                  </span>
                  {parsedChips.map((c) => (
                    <span key={c} className="chip" style={{ fontSize: 11.5 }}>
                      {c}
                    </span>
                  ))}
                </div>
              ) : (
                <p style={{ fontSize: 12.5, color: "var(--text-3)", margin: "8px 0 0" }}>
                  Не удалось распознать реквизиты — заполните поля вручную.
                </p>
              ))}
            {pendingPlanMessage && (
              <div
                className="rowflex"
                style={{
                  gap: 8,
                  marginTop: 8,
                  alignItems: "flex-start",
                  color: pendingNotFound || plansQ.isError ? "var(--text-3)" : "var(--text-2)",
                  fontSize: 12.5,
                  lineHeight: 1.45,
                }}
              >
                {(plansQ.isLoading || plansQ.isFetching) && <Spinner />}
                <span>{pendingPlanMessage}</span>
              </div>
            )}
          </Field>
        )}

        {/* Локация — выбирается до названия, т.к. подставляется в него */}
        <Field label="Локация">
          <input
            className="input"
            list="server-location-options"
            value={form.location}
            onChange={(e) => set("location", e.target.value)}
            placeholder="Выберите или введите"
          />
          <datalist id="server-location-options">
            {LOCATION_OPTIONS.map((loc) => (
              <option key={loc} value={loc} />
            ))}
          </datalist>
        </Field>

        {/* Название — по умолчанию «Локация [Провайдер]», можно изменить */}
        <Field label="Название">
          <input
            className="input"
            value={form.name}
            onChange={(e) => onNameChange(e.target.value)}
            placeholder="например, Нидерланды [FirstByte]"
          />
          {!serverId && !nameTouched && (
            <p style={{ fontSize: 12.5, color: "var(--text-3)", margin: "6px 0 0" }}>
              Составляется из локации и провайдера — можно изменить.
            </p>
          )}
        </Field>

        <Field label="Тариф провайдера">
          <input
            className="input"
            value={form.providerPlan}
            onChange={(e) => {
              setPendingProviderPlan(null);
              set("providerPlan", e.target.value);
            }}
            placeholder="например, MSK-highmem-KVM-SSD-2"
          />
        </Field>

        {/* IP */}
        <Field label="IP-адрес">
          <input
            className="input mono"
            value={form.ip}
            onChange={(e) => set("ip", e.target.value)}
            placeholder="203.0.113.10"
          />
        </Field>

        <div className="stack" style={{ gap: 12 }}>
          <div
            className="muted-3"
            style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
          >
            Стоимость и трафик
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
            <Field label="Стоимость">
              <input
                className="input"
                type="number"
                min={0}
                step="0.01"
                value={billing.priceAmount}
                placeholder="пусто — бесплатно"
                onChange={(e) => setBilling((b) => ({ ...b, priceAmount: e.target.value }))}
              />
            </Field>
            <Field label="Валюта">
              <select
                className="input"
                value={billing.priceCurrency}
                onChange={(e) => setBilling((b) => ({ ...b, priceCurrency: e.target.value }))}
              >
                {CURRENCIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="День оплаты">
              <input
                className="input"
                type="number"
                min={1}
                max={31}
                value={billing.priceAnchorDay}
                disabled={billing.pricePeriod !== "month"}
                placeholder={billing.pricePeriod === "month" ? "необязательно" : "только для месяца"}
                onChange={(e) => setBilling((b) => ({ ...b, priceAnchorDay: e.target.value }))}
              />
            </Field>
          </div>
          <Field label="Период оплаты">
            <div style={{ display: "flex", gap: 8 }}>
              {PRICE_PERIODS.map((p) => (
                <button
                  key={p}
                  type="button"
                  className={`chip${billing.pricePeriod === p ? " selected" : ""}`}
                  style={{ flex: 1, height: 40, justifyContent: "center", cursor: "pointer", fontSize: 13.5 }}
                  onClick={() =>
                    setBilling((b) => ({ ...b, pricePeriod: p, priceAnchorDay: p === "month" ? b.priceAnchorDay : "" }))
                  }
                >
                  {p === "minute" ? "Минута" : p === "day" ? "Сутки" : "Месяц"}
                </button>
              ))}
            </div>
          </Field>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
            <Field label="Квота сетевого трафика">
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 92px", gap: 8 }}>
                <input
                  className="input"
                  type="number"
                  min={0}
                  step={billing.trafficQuotaUnit === "B" ? 1 : 0.1}
                  value={billing.trafficQuotaValue}
                  placeholder="пусто — безлимит"
                  onChange={(e) => setBilling((b) => ({ ...b, trafficQuotaValue: e.target.value }))}
                />
                <select
                  className="input"
                  value={billing.trafficQuotaUnit}
                  onChange={(e) =>
                    setBilling((b) => {
                      const unit = e.target.value as TrafficUnit;
                      return {
                        ...b,
                        trafficQuotaValue: convertTrafficInputUnit(b.trafficQuotaValue, b.trafficQuotaUnit, unit),
                        trafficQuotaUnit: unit,
                      };
                    })
                  }
                >
                  {TRAFFIC_UNITS.map((u) => (
                    <option key={u.value} value={u.value}>
                      {u.label}
                    </option>
                  ))}
                </select>
              </div>
            </Field>
            <Field label="День сброса трафика">
              <input
                className="input"
                type="number"
                min={1}
                max={31}
                value={billing.trafficBillingDay}
                placeholder="пусто — 1-е число"
                onChange={(e) => setBilling((b) => ({ ...b, trafficBillingDay: e.target.value }))}
              />
            </Field>
          </div>
        </div>

        <div style={{ height: 1, background: "var(--border)" }} />

        {/* Способ авторизации */}
        <Field label="Способ авторизации">
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className={`chip${form.auth === "key" ? " selected" : ""}`}
              style={{ flex: 1, height: 42, justifyContent: "center", cursor: "pointer", fontSize: 13.5 }}
              onClick={() => set("auth", "key")}
            >
              SSH-ключ
            </button>
            <button
              type="button"
              className={`chip${form.auth === "password" ? " selected" : ""}`}
              style={{ flex: 1, height: 42, justifyContent: "center", cursor: "pointer", fontSize: 13.5 }}
              onClick={() => set("auth", "password")}
            >
              Пароль
            </button>
          </div>
        </Field>

        {/* Логин + порт */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
          <Field label={loginLabel}>
            <input
              className="input mono"
              value={form.sshUser}
              onChange={(e) => set("sshUser", e.target.value)}
              placeholder="root"
            />
          </Field>
          <Field label="Порт">
            <input
              className="input mono"
              value={form.sshPort}
              onChange={(e) => set("sshPort", e.target.value)}
              placeholder="22"
            />
          </Field>
        </div>

        {/* Ключ / пароль */}
        <Field label={secretLabel}>
          <input
            className="input mono"
            type={form.auth === "password" ? "password" : "text"}
            value={form.secret}
            onChange={(e) => set("secret", e.target.value)}
            placeholder={secretPlaceholder}
          />
        </Field>

        {/* Действия */}
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", paddingTop: 4 }}>
          <Btn onClick={onBack}>Отмена</Btn>
          <Btn
            variant="primary"
            onClick={onSave}
            disabled={save.isPending || !form.name.trim() || !form.ip.trim() || !form.location.trim()}
          >
            {save.isPending ? <Spinner /> : "Сохранить"}
          </Btn>
        </div>
      </div>
    </div>
  );
}
