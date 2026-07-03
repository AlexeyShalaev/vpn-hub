import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Avatar, Btn, Field, Icon, Modal, ScreenHeader, Spinner, Switch } from "../components/ui";
import { ApiError } from "../lib/api";
import * as q from "../lib/queries";
import type { Session } from "../lib/types";
import { useNav } from "../nav";
import { useStore } from "../store";

export function ProfileScreen() {
  const me = useStore((s) => s.me);
  const theme = useStore((s) => s.theme);
  const toggleTheme = useStore((s) => s.toggleTheme);
  const viewRole = useStore((s) => s.viewRole);
  const setViewRole = useStore((s) => s.setViewRole);
  const setMe = useStore((s) => s.setMe);
  const toast = useStore((s) => s.toast);
  const go = useNav((s) => s.go);
  const qc = useQueryClient();

  const [pwOpen, setPwOpen] = useState(false);
  const [pw, setPw] = useState({ current: "", next: "", next2: "" });

  const logoutM = useMutation({
    mutationFn: () => q.logout(),
    onSuccess: () => {
      setMe(null);
      qc.invalidateQueries();
    },
    onError: () => toast("Не удалось выйти"),
  });

  const sessionsQ = useQuery({ queryKey: ["sessions"], queryFn: q.listSessions });

  const changePw = useMutation({
    mutationFn: () => q.changePassword({ current: pw.current, new: pw.next }),
    onSuccess: () => {
      setPwOpen(false);
      setPw({ current: "", next: "", next2: "" });
      qc.invalidateQueries({ queryKey: ["sessions"] });
      toast("Пароль изменён, остальные сессии завершены");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Не удалось сменить пароль"),
  });

  const revokeM = useMutation({
    mutationFn: (id: string) => q.revokeSession(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
      toast("Сессия завершена");
    },
  });

  const revokeOthersM = useMutation({
    mutationFn: () => q.revokeOtherSessions(),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
      toast(r.revoked ? `Завершено сессий: ${r.revoked}` : "Других сессий нет");
    },
  });

  const sessions = sessionsQ.data ?? [];

  function selectRole(role: "owner" | "member") {
    setViewRole(role);
    go(role === "owner" ? "servers" : "available");
  }

  const ROLE_OPTIONS = [
    { role: "owner", title: "Владелец", sub: "Серверы, группы, доступы" },
    { role: "member", title: "Участник", sub: "Доступное мне, устройства" },
  ] as const;

  return (
    <div className="stack" style={{ maxWidth: 600, margin: "0 auto", width: "100%" }}>
      <ScreenHeader title="Профиль" />

      {/* Аккаунт */}
      <div className="card card-row">
        <Avatar name={me?.name ?? ""} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 18 }}>{me?.name}</div>
          <div className="mono muted-3" style={{ fontSize: 13 }}>
            {me?.phone}
          </div>
        </div>
        <Btn variant="danger" sm disabled={logoutM.isPending} onClick={() => logoutM.mutate()}>
          <Icon name="logout" size={16} />
          Выйти
        </Btn>
      </div>

      {/* Безопасность */}
      <div className="card stack" style={{ gap: 12 }}>
        <div className="rowflex" style={{ justifyContent: "space-between" }}>
          <div
            className="muted-3"
            style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
          >
            Безопасность
          </div>
          <Btn sm onClick={() => setPwOpen(true)}>
            <Icon name="edit" size={15} />
            Сменить пароль
          </Btn>
        </div>

        <div className="rowflex" style={{ justifyContent: "space-between" }}>
          <span className="muted" style={{ fontSize: 13 }}>
            Активные сессии{sessions.length ? ` · ${sessions.length}` : ""}
          </span>
          {sessions.length > 1 && (
            <Btn variant="ghost" sm disabled={revokeOthersM.isPending} onClick={() => revokeOthersM.mutate()}>
              Завершить остальные
            </Btn>
          )}
        </div>

        {sessionsQ.isLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: 12 }}>
            <Spinner />
          </div>
        ) : (
          <div className="stack" style={{ gap: 8 }}>
            {sessions.map((s) => (
              <SessionRow key={s.id} s={s} onRevoke={() => revokeM.mutate(s.id)} busy={revokeM.isPending} />
            ))}
          </div>
        )}
      </div>

      {/* Администрирование (для админа) */}
      {me?.isAdmin && (
        <div className="card stack" style={{ gap: 10 }}>
          <div
            className="muted-3"
            style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
          >
            Администрирование
          </div>
          <Btn variant="ghost" block onClick={() => go("users")} style={{ justifyContent: "flex-start" }}>
            <Icon name="users" size={18} />
            Пользователи
            <span className="muted-3" style={{ fontSize: 12.5, fontWeight: 400, marginLeft: 4 }}>
              Управление пользователями
            </span>
          </Btn>
          <Btn variant="ghost" block onClick={() => go("system")} style={{ justifyContent: "flex-start" }}>
            <Icon name="system" size={18} />
            Система
            <span className="muted-3" style={{ fontSize: 12.5, fontWeight: 400, marginLeft: 4 }}>
              Версия, обновления, БД
            </span>
          </Btn>
        </div>
      )}

      {/* Режим работы */}
      <div className="card stack" style={{ gap: 12 }}>
        <div
          className="muted-3"
          style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
        >
          Режим работы
        </div>
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>
          Переключитесь, чтобы увидеть приложение глазами участника группы.
        </p>
        <div style={{ display: "flex", gap: 9 }}>
          {ROLE_OPTIONS.map((opt) => {
            const active = viewRole === opt.role;
            return (
              <button
                key={opt.role}
                onClick={() => selectRole(opt.role)}
                style={{
                  flex: 1,
                  display: "flex",
                  flexDirection: "column",
                  gap: 5,
                  padding: 14,
                  borderRadius: 13,
                  cursor: "pointer",
                  textAlign: "left",
                  border: `1.5px solid ${active ? "var(--accent)" : "var(--border)"}`,
                  background: active ? "var(--accent-soft)" : "var(--surface)",
                }}
              >
                <span style={{ fontWeight: 700, fontSize: 14.5, color: "var(--text)" }}>{opt.title}</span>
                <span style={{ fontSize: 12, color: "var(--text-3)" }}>{opt.sub}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Настройки */}
      <div className="card stack" style={{ gap: 0 }}>
        <div className="card-row" style={{ padding: "14px 0", borderBottom: "1px solid var(--border)" }}>
          <Icon name={theme === "dark" ? "moon" : "sun"} size={18} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 14.5 }}>Тёмная тема</div>
            <div className="muted-3" style={{ fontSize: 12.5 }}>
              Сейчас: {theme === "dark" ? "Тёмная" : "Светлая"}
            </div>
          </div>
          <Switch on={theme === "dark"} onClick={toggleTheme} />
        </div>
        <div className="card-row" style={{ padding: "14px 0" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 14.5 }}>Язык</div>
            <div className="muted-3" style={{ fontSize: 12.5 }}>
              Интерфейс приложения
            </div>
          </div>
          <span className="muted" style={{ fontSize: 13.5, fontWeight: 600 }}>
            Русский
          </span>
        </div>
      </div>

      <p className="muted-3" style={{ textAlign: "center", fontSize: 12 }}>
        VPN Hub · self-hosted панель VPN
      </p>

      {pwOpen && (
        <Modal
          title="Сменить пароль"
          onClose={() => setPwOpen(false)}
          footer={
            <>
              <Btn block onClick={() => setPwOpen(false)}>
                Отмена
              </Btn>
              <Btn
                variant="primary"
                block
                disabled={changePw.isPending}
                onClick={() => {
                  if (pw.next !== pw.next2) {
                    toast("Пароли не совпадают");
                    return;
                  }
                  changePw.mutate();
                }}
              >
                Сохранить
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ marginBottom: 12, fontSize: 13 }}>
            После смены пароля все остальные сессии будут завершены.
          </p>
          <Field label="Текущий пароль">
            <input
              className="input"
              type="password"
              value={pw.current}
              onChange={(e) => setPw((p) => ({ ...p, current: e.target.value }))}
            />
          </Field>
          <Field label="Новый пароль (мин. 8 символов)">
            <input
              className="input"
              type="password"
              value={pw.next}
              onChange={(e) => setPw((p) => ({ ...p, next: e.target.value }))}
            />
          </Field>
          <Field label="Повторите новый пароль">
            <input
              className="input"
              type="password"
              value={pw.next2}
              onChange={(e) => setPw((p) => ({ ...p, next2: e.target.value }))}
            />
          </Field>
        </Modal>
      )}
    </div>
  );
}

function SessionRow({ s, onRevoke, busy }: { s: Session; onRevoke: () => void; busy: boolean }) {
  return (
    <div
      className="card-row"
      style={{ gap: 12, border: "1px solid var(--border)", borderRadius: 12, padding: "10px 12px" }}
    >
      <Icon name="devices" size={18} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="rowflex" style={{ gap: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 14 }}>{s.device}</span>
          {s.current && <span className="badge ok">текущая</span>}
        </div>
        <div className="muted-3" style={{ fontSize: 12 }}>
          {s.ip} · {s.lastSeen ? `активность ${s.lastSeen}` : `вход ${s.createdAt}`}
        </div>
      </div>
      {!s.current && (
        <Btn variant="ghost" sm disabled={busy} onClick={onRevoke} title="Завершить сессию">
          <Icon name="x" size={16} />
        </Btn>
      )}
    </div>
  );
}
