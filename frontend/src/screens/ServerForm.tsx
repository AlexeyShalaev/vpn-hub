import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Btn, Field, Icon, ScreenHeader, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import type { ParsedServerInfo } from "../lib/credentialParse";
import { hasUsefulInfo, parseServerInfo } from "../lib/credentialParse";
import * as q from "../lib/queries";
import type { Provider, Server } from "../lib/types";
import { useNav } from "../nav";
import { useStore } from "../store";

interface FormState {
  name: string;
  provider: string;
  providerCustom: boolean;
  ip: string;
  location: string;
  sshUser: string;
  sshPort: string;
  auth: "key" | "password";
  secret: string;
}

const EMPTY: FormState = {
  name: "",
  provider: "",
  providerCustom: false,
  ip: "",
  location: "",
  sshUser: "root",
  sshPort: "22",
  auth: "key",
  secret: "",
};

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

  const providers: Provider[] = providersQ.data ?? [];
  const known = useMemo(() => (name: string) => providers.some((p) => p.name === name), [providers]);

  const [form, setForm] = useState<FormState>(() => {
    if (presetProvider) return { ...EMPTY, provider: presetProvider };
    return EMPTY;
  });
  const [loaded, setLoaded] = useState(!serverId);

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
      sshUser: s.sshUser,
      sshPort: s.sshPort,
      auth: s.auth,
      secret: s.secret,
    });
    setLoaded(true);
  }, [serverId, loaded, serverQ.data, known]);

  function set<K extends keyof FormState>(key: K, val: FormState[K]) {
    setForm((p) => ({ ...p, [key]: val }));
  }

  // Умное автозаполнение: пользователь вставляет письмо провайдера,
  // распознанные реквизиты сразу подставляются в поля.
  const [pasteText, setPasteText] = useState("");
  const [parsed, setParsed] = useState<ParsedServerInfo | null>(null);

  function onPasteChange(text: string) {
    setPasteText(text);
    if (!text.trim()) {
      setParsed(null);
      return;
    }
    const selectedId = providers.find((p) => p.name === form.provider)?.id;
    const info = parseServerInfo(text, selectedId);
    setParsed(info);
    if (!hasUsefulInfo(info)) return;
    setForm((f) => {
      const n = { ...f };
      if (info.providerId) {
        const p = providers.find((pp) => pp.id === info.providerId);
        if (p) {
          n.provider = p.name;
          n.providerCustom = false;
        }
      }
      if (info.ip) n.ip = info.ip;
      else if (info.hostname) n.ip = info.hostname;
      if (info.sshUser) n.sshUser = info.sshUser;
      if (info.sshPort) n.sshPort = info.sshPort;
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
      const p = providers.find((pp) => pp.id === parsed.providerId);
      if (p) chips.push(`Провайдер: ${p.name}`);
    }
    if (parsed.ip) chips.push(`IP: ${parsed.ip}`);
    else if (parsed.hostname) chips.push(`Хост: ${parsed.hostname}`);
    if (parsed.sshUser) chips.push(`Пользователь: ${parsed.sshUser}`);
    if (parsed.password) chips.push("Пароль: ••••••");
    if (parsed.sshPort) chips.push(`Порт: ${parsed.sshPort}`);
    if (parsed.location) chips.push(`Локация: ${parsed.location}`);
    return chips;
  }, [parsed, providers]);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => (serverId ? q.updateServer(serverId, body) : q.createServer(body)),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["servers"] });
      qc.invalidateQueries({ queryKey: ["server", res.id] });
      toast("Сервер сохранён");
      go("server", { serverId: res.id });
    },
    onError: (e) => {
      toast(e instanceof ApiError ? e.message : "Не удалось сохранить");
    },
  });

  function onSave() {
    if (!form.name.trim() || !form.ip.trim()) {
      toast("Заполните название и IP");
      return;
    }
    save.mutate({
      name: form.name,
      provider: form.provider || "Другой",
      ip: form.ip,
      location: form.location,
      sshUser: form.sshUser || "root",
      sshPort: form.sshPort || "22",
      auth: form.auth,
      secret: form.secret,
    });
  }

  const selProvider = useMemo(() => {
    if (form.providerCustom) return null;
    return providers.find((p) => p.name === form.provider) ?? null;
  }, [providers, form.provider, form.providerCustom]);

  const loginLabel = form.auth === "key" ? "SSH пользователь" : "Логин";
  const secretLabel = form.auth === "key" ? "SSH-ключ" : "Пароль";
  const secretPlaceholder = form.auth === "key" ? "путь к ключу или вставьте ключ" : "пароль для пользователя";

  if (serverId && (serverQ.isLoading || !loaded)) {
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
          </Field>
        )}

        {/* Название */}
        <Field label="Название">
          <input
            className="input"
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="например, Амстердам-1"
          />
        </Field>

        {/* IP + локация */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="IP-адрес">
            <input
              className="input mono"
              value={form.ip}
              onChange={(e) => set("ip", e.target.value)}
              placeholder="203.0.113.10"
            />
          </Field>
          <Field label="Локация">
            <input
              className="input"
              value={form.location}
              onChange={(e) => set("location", e.target.value)}
              placeholder="Нидерланды"
            />
          </Field>
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
          <Btn variant="primary" onClick={onSave} disabled={save.isPending || !form.name.trim() || !form.ip.trim()}>
            {save.isPending ? <Spinner /> : "Сохранить"}
          </Btn>
        </div>
      </div>
    </div>
  );
}
