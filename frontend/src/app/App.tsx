import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PhoneField } from "../components/PhoneField";
import { Btn, Field, FilePicker, Icon, KeyInput } from "../components/ui";
import { ApiError } from "../lib/api";
import * as q from "../lib/queries";
import { downloadRecoveryKey } from "../lib/recoveryKey";
import type { Me } from "../lib/types";
import { useNav } from "../nav";
import { AccessScreen } from "../screens/Access";
import { AvailableScreen } from "../screens/Available";
import { CatalogScreen } from "../screens/Catalog";
import { DevicesScreen } from "../screens/Devices";
import { GroupDetailScreen } from "../screens/GroupDetail";
import { GroupsScreen } from "../screens/Groups";
import { ProfileScreen } from "../screens/Profile";
import { ServerDetailScreen } from "../screens/ServerDetail";
import { ServerFormScreen } from "../screens/ServerForm";
import { ServersScreen } from "../screens/Servers";
import { SystemScreen } from "../screens/System";
import { UsersScreen } from "../screens/Users";
import { useStore } from "../store";

function Toast() {
  const msg = useStore((s) => s.toastMsg);
  if (!msg) return null;
  return <div className="toast">{msg}</div>;
}

function AuthScreen({ redirect = true, joinName }: { redirect?: boolean; joinName?: string }) {
  const qc = useQueryClient();
  const setMe = useStore((s) => s.setMe);
  const go = useNav((s) => s.go);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [form, setForm] = useState({ name: "", phone: "", password: "", password2: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));

  async function onLogin() {
    setError("");
    setBusy(true);
    try {
      const me = await q.login({ phone: form.phone, password: form.password });
      setMe(me);
      qc.invalidateQueries();
      if (redirect) go(me.role === "owner" ? "servers" : "available");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Ошибка входа");
    } finally {
      setBusy(false);
    }
  }

  async function onRegister() {
    setError("");
    if (!form.name.trim()) return setError("Введите имя");
    if (form.password !== form.password2) return setError("Пароли не совпадают");
    setBusy(true);
    try {
      await q.register(form);
      setInfo(
        "Аккаунт создан. Если вас пригласили в группу — можно сразу войти; иначе дождитесь подтверждения администратора.",
      );
      setMode("login");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Ошибка регистрации");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <div className="brand-logo">V</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 18 }}>VPN Hub</div>
            <div className="muted" style={{ fontSize: 13 }}>
              {mode === "login" ? "Вход" : "Регистрация"}
            </div>
          </div>
        </div>
        {joinName && (
          <div className="muted" style={{ marginBottom: 12, fontSize: 13, lineHeight: 1.45 }}>
            Войдите или зарегистрируйтесь, чтобы присоединиться к группе «{joinName}».
          </div>
        )}
        {info && (
          <div className="badge ok" style={{ marginBottom: 12, display: "flex" }}>
            {info}
          </div>
        )}
        {error && <div className="err">{error}</div>}

        {mode === "register" && (
          <Field label="Имя">
            <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
        )}
        <Field label="Телефон">
          <PhoneField value={form.phone} onChange={(v) => set("phone", v)} />
        </Field>
        <Field label={mode === "register" ? "Пароль (мин. 8 символов)" : "Пароль"}>
          <input
            className="input"
            type="password"
            value={form.password}
            onChange={(e) => set("password", e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && mode === "login" && onLogin()}
          />
        </Field>
        {mode === "register" && (
          <Field label="Повторите пароль">
            <input
              className="input"
              type="password"
              value={form.password2}
              onChange={(e) => set("password2", e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onRegister()}
            />
          </Field>
        )}
        <Btn variant="primary" block disabled={busy} onClick={() => (mode === "login" ? onLogin() : onRegister())}>
          {busy ? "…" : mode === "login" ? "Войти" : "Зарегистрироваться"}
        </Btn>

        <div style={{ textAlign: "center", marginTop: 14 }}>
          <Btn
            variant="ghost"
            sm
            onClick={() => {
              setError("");
              setInfo("");
              setMode(mode === "login" ? "register" : "login");
            }}
          >
            {mode === "login" ? "Создать аккаунт" : "У меня уже есть аккаунт"}
          </Btn>
        </div>
      </div>
    </div>
  );
}

function JoinScreen({ token, me }: { token: string; me: Me }) {
  const go = useNav((s) => s.go);
  const qc = useQueryClient();
  const setMe = useStore((s) => s.setMe);
  const [state, setState] = useState<"idle" | "joining" | "done" | "error">("idle");
  const [error, setError] = useState("");

  const peekQ = useQuery({ queryKey: ["invite", token], queryFn: () => q.peekInvite(token), retry: false });

  async function join() {
    setState("joining");
    setError("");
    try {
      await q.joinGroup(token);
      // членство даёт доступ участника → обновим роль в шапке и кэш
      const fresh = await q.getMe();
      if (fresh) setMe(fresh);
      qc.invalidateQueries();
      setState("done");
      setTimeout(() => go("available"), 900);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось присоединиться");
      setState("error");
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 18 }}>
          <div className="brand-logo">V</div>
          <div style={{ fontWeight: 800, fontSize: 18 }}>Приглашение в группу</div>
        </div>

        {peekQ.isLoading ? (
          <div style={{ textAlign: "center", padding: 20 }}>
            <Icon name="refresh" />
          </div>
        ) : peekQ.isError || !peekQ.data ? (
          <>
            <div className="err">Приглашение недействительно или было отозвано.</div>
            <Btn block onClick={() => go(me.role === "owner" ? "servers" : "available")}>
              На главную
            </Btn>
          </>
        ) : state === "done" ? (
          <div className="badge ok" style={{ display: "flex" }}>
            Готово! Вы присоединились к «{peekQ.data.name}».
          </div>
        ) : (
          <>
            <div className="muted" style={{ fontSize: 14, lineHeight: 1.5, marginBottom: 16 }}>
              <b>{peekQ.data.ownerName || "Владелец"}</b> приглашает вас в группу <b>«{peekQ.data.name}»</b>. После
              присоединения вам станут доступны VPN-серверы этой группы.
            </div>
            {error && <div className="err">{error}</div>}
            <Btn variant="primary" block disabled={state === "joining"} onClick={join}>
              {state === "joining" ? "Присоединяемся…" : `Присоединиться как ${me.name}`}
            </Btn>
            <div style={{ textAlign: "center", marginTop: 12 }}>
              <Btn variant="ghost" sm onClick={() => go(me.role === "owner" ? "servers" : "available")}>
                Не сейчас
              </Btn>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function SetupScreen({ keyFromEnv }: { keyFromEnv: boolean }) {
  const qc = useQueryClient();
  const setMe = useStore((s) => s.setMe);
  const go = useNav((s) => s.go);
  const [mode, setMode] = useState<"new" | "restore">("new");
  const [form, setForm] = useState({ name: "", phone: "", password: "", password2: "", masterKey: "" });
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [restoreKey, setRestoreKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [keySaved, setKeySaved] = useState(false);
  const [error, setError] = useState("");
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));
  async function submit() {
    setError("");
    if (form.password !== form.password2) {
      setError("Пароли не совпадают");
      return;
    }
    if (!keyFromEnv) {
      if (!form.masterKey) {
        setError("Задайте мастер-ключ восстановления");
        return;
      }
      if (form.masterKey.length < 8) {
        setError("Мастер-ключ — минимум 8 символов");
        return;
      }
      if (!keySaved) {
        setError("Подтвердите, что сохранили ключ восстановления");
        return;
      }
    }
    setBusy(true);
    try {
      const me = await q.setupAdmin(form);
      setMe(me);
      qc.invalidateQueries();
      go("system");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }
  async function restore() {
    setError("");
    if (!restoreFile || !restoreKey) {
      setError("Выберите файл бэкапа и введите ключ");
      return;
    }
    setBusy(true);
    try {
      await q.setupRestore(restoreFile, restoreKey);
      setDone(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }
  if (done) {
    return (
      <div className="auth-wrap">
        <div className="auth-card">
          <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 4 }}>Система восстановлена</div>
          <div className="muted" style={{ fontSize: 13, marginBottom: 18 }}>
            Войдите под учётной записью из восстановленного бэкапа.
          </div>
          <Btn variant="primary" block onClick={() => qc.invalidateQueries({ queryKey: ["setup"] })}>
            Перейти ко входу
          </Btn>
        </div>
      </div>
    );
  }
  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div style={{ fontWeight: 800, fontSize: 18, marginBottom: 4 }}>Первичная настройка</div>
        <div className="muted" style={{ fontSize: 13, marginBottom: 16 }}>
          {mode === "new" ? "Создайте учётную запись администратора" : "Разверните систему из бэкапа"}
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          <Btn
            block
            sm
            variant={mode === "new" ? "primary" : "default"}
            onClick={() => {
              setMode("new");
              setError("");
            }}
          >
            Новая установка
          </Btn>
          <Btn
            block
            sm
            variant={mode === "restore" ? "primary" : "default"}
            onClick={() => {
              setMode("restore");
              setError("");
            }}
          >
            Из бэкапа
          </Btn>
        </div>

        {error && <div className="err">{error}</div>}

        {mode === "new" ? (
          <>
            <Field label="Имя">
              <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} />
            </Field>
            <Field label="Телефон">
              <PhoneField value={form.phone} onChange={(v) => set("phone", v)} />
            </Field>
            <Field label="Пароль (мин. 8 символов)">
              <input
                className="input"
                type="password"
                value={form.password}
                onChange={(e) => set("password", e.target.value)}
              />
            </Field>
            <Field label="Повторите пароль">
              <input
                className="input"
                type="password"
                value={form.password2}
                onChange={(e) => set("password2", e.target.value)}
              />
            </Field>
            {keyFromEnv ? (
              <div className="muted" style={{ fontSize: 12.5, marginBottom: 14, lineHeight: 1.45 }}>
                Мастер-ключ задан через переменную окружения
                <code style={{ margin: "0 3px" }}>VPNHUB_MASTER_KEY</code> — вводить не нужно.
              </div>
            ) : (
              <>
                <Field label="Мастер-ключ восстановления (мин. 8 символов)">
                  <KeyInput
                    value={form.masterKey}
                    placeholder="Минимум 8 символов"
                    onChange={(v) => {
                      set("masterKey", v);
                      setKeySaved(false);
                    }}
                  />
                </Field>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 12,
                    padding: 14,
                    marginBottom: 14,
                    borderRadius: "var(--r-sm)",
                    border: "1px solid var(--warn-soft)",
                    background: "var(--warn-soft)",
                  }}
                >
                  <div style={{ fontSize: 12.5, color: "var(--text-2)", lineHeight: 1.5 }}>
                    Это <b>мастер-ключ восстановления</b> — им шифруются SSH-доступы к серверам и бэкапы. Без него
                    нельзя ни восстановить копию, ни расшифровать секреты серверов (например, при переносе на другой
                    сервер). Сохраните его в надёжном месте: мы не храним его в открытом виде.
                  </div>
                  <Btn sm onClick={() => downloadRecoveryKey(form.masterKey)} disabled={form.masterKey.length < 8}>
                    <Icon name="download" size={15} />
                    Скачать ключ (.txt)
                  </Btn>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                    <input type="checkbox" checked={keySaved} onChange={(e) => setKeySaved(e.target.checked)} />
                    <span style={{ fontSize: 13, color: "var(--text-2)" }}>
                      Я сохранил ключ восстановления в надёжном месте
                    </span>
                  </label>
                </div>
              </>
            )}
            <Btn
              variant="primary"
              block
              onClick={submit}
              disabled={busy || (!keyFromEnv && (form.masterKey.length < 8 || !keySaved))}
            >
              {busy ? "Создаём…" : "Создать администратора"}
            </Btn>
          </>
        ) : (
          <>
            <Field label="Файл бэкапа (.vhb)">
              <FilePicker accept=".vhb" file={restoreFile} onPick={setRestoreFile} />
            </Field>
            <Field label="Ключ шифрования">
              <input
                className="input"
                type="password"
                value={restoreKey}
                onChange={(e) => setRestoreKey(e.target.value)}
              />
            </Field>
            <Btn variant="primary" block onClick={restore} disabled={busy}>
              {busy ? "Восстанавливаем…" : "Восстановить систему"}
            </Btn>
          </>
        )}
      </div>
    </div>
  );
}

const NAV_META: Record<string, { label: string; icon: string }> = {
  servers: { label: "Серверы", icon: "servers" },
  groups: { label: "Группы", icon: "groups" },
  access: { label: "Доступы", icon: "access" },
  available: { label: "Доступно", icon: "available" },
  devices: { label: "Устройства", icon: "devices" },
  users: { label: "Пользователи", icon: "users" },
  system: { label: "Система", icon: "system" },
  profile: { label: "Профиль", icon: "profile" },
};

function Shell({ me }: { me: Me }) {
  const { screen, go } = useNav();
  const viewRole = useStore((s) => s.viewRole);

  const ownerItems = ["servers", "groups", "access"];
  const memberItems = ["available", "devices"];
  const main = viewRole === "owner" ? ownerItems : memberItems;
  const adminItems = me.isAdmin ? ["users", "system"] : [];

  const activeTop =
    screen === "server" || screen === "serverForm" || screen === "catalog"
      ? "servers"
      : screen === "group"
        ? "groups"
        : screen;

  const renderScreen = () => {
    switch (screen) {
      case "servers":
        return <ServersScreen />;
      case "server":
        return <ServerDetailScreen />;
      case "serverForm":
        return <ServerFormScreen />;
      case "catalog":
        return <CatalogScreen />;
      case "groups":
        return <GroupsScreen />;
      case "group":
        return <GroupDetailScreen />;
      case "access":
        return <AccessScreen />;
      case "available":
        return <AvailableScreen />;
      case "devices":
        return <DevicesScreen />;
      case "users":
        return <UsersScreen />;
      case "system":
        return <SystemScreen />;
      case "profile":
        return <ProfileScreen />;
      default:
        return <AvailableScreen />;
    }
  };

  const NavItem = ({ id }: { id: string }) => (
    <button className={`nav-btn ${activeTop === id ? "active" : ""}`} onClick={() => go(id as never)}>
      <Icon name={NAV_META[id].icon} />
      {NAV_META[id].label}
    </button>
  );

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-logo">V</div>
          <div style={{ fontWeight: 800 }}>VPN Hub</div>
        </div>
        <div className="stack" style={{ gap: 4 }}>
          {main.map((id) => (
            <NavItem key={id} id={id} />
          ))}
        </div>
        {adminItems.length > 0 && (
          <>
            <div className="nav-divider" />
            <div className="nav-label">Администрирование</div>
            <div className="stack" style={{ gap: 4 }}>
              {adminItems.map((id) => (
                <NavItem key={id} id={id} />
              ))}
            </div>
          </>
        )}
        <div className="spacer" />
        <button className={`nav-btn ${screen === "profile" ? "active" : ""}`} onClick={() => go("profile")}>
          <Icon name="profile" />
          {me.name}
        </button>
      </aside>

      <main className="main">
        <div className="content">
          <div className="col">{renderScreen()}</div>
        </div>
      </main>

      <nav className="bottom-nav">
        {[...main, "profile"].map((id) => (
          <button
            key={id}
            className={activeTop === id || (id === "profile" && screen === "profile") ? "active" : ""}
            onClick={() => go(id as never)}
          >
            <Icon name={NAV_META[id].icon} size={21} />
            {NAV_META[id].label}
          </button>
        ))}
      </nav>
    </div>
  );
}

export function App() {
  const me = useStore((s) => s.me);
  const setMe = useStore((s) => s.setMe);
  const nav = useNav();

  const meQuery = useQuery({ queryKey: ["me"], queryFn: q.getMe });
  const setupQuery = useQuery({
    queryKey: ["setup"],
    queryFn: q.setupStatus,
    enabled: meQuery.isSuccess && !meQuery.data,
  });
  const invitePeek = useQuery({
    queryKey: ["invite", nav.params.token],
    queryFn: () => q.peekInvite(nav.params.token || ""),
    enabled: nav.screen === "join" && !!nav.params.token,
    retry: false,
  });

  // sync store on first load
  if (meQuery.isSuccess && me === null && meQuery.data) {
    setMe(meQuery.data);
  }

  if (meQuery.isLoading) {
    return (
      <div className="auth-wrap">
        <Icon name="refresh" />
      </div>
    );
  }

  const current = me ?? meQuery.data ?? null;

  // Присоединение по инвайт-ссылке /join/<token> — работает и до, и после входа.
  if (nav.screen === "join") {
    if (!current) {
      return (
        <>
          <AuthScreen redirect={false} joinName={invitePeek.data?.name} />
          <Toast />
        </>
      );
    }
    return (
      <>
        <JoinScreen token={nav.params.token || ""} me={current} />
        <Toast />
      </>
    );
  }

  if (!current) {
    if (setupQuery.data?.needed) return <SetupScreen keyFromEnv={!!setupQuery.data?.keyFromEnv} />;
    return (
      <>
        <AuthScreen />
        <Toast />
      </>
    );
  }

  return (
    <>
      <Shell me={current} />
      <Toast />
    </>
  );
}
