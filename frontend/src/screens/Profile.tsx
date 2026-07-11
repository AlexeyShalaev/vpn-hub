import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Avatar, Btn, Field, Icon, Modal, ScreenHeader, Spinner, Switch } from "../components/ui";
import { ApiError } from "../lib/api";
import { LANG_LABEL, LANGS, useT } from "../lib/i18n";
import * as q from "../lib/queries";
import type { Session } from "../lib/types";
import { useNav } from "../nav";
import { useStore } from "../store";

export function ProfileScreen() {
  const me = useStore((s) => s.me);
  const theme = useStore((s) => s.theme);
  const toggleTheme = useStore((s) => s.toggleTheme);
  const lang = useStore((s) => s.lang);
  const setLang = useStore((s) => s.setLang);
  const t = useT();
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
      qc.setQueryData(["me"], null);
      qc.removeQueries({ predicate: ({ queryKey }) => queryKey[0] !== "me" && queryKey[0] !== "setup" });
      setMe(null);
    },
    onError: () => toast(t("profile.logoutFailed")),
  });

  const sessionsQ = useQuery({ queryKey: ["sessions"], queryFn: q.listSessions });

  const changePw = useMutation({
    mutationFn: () => q.changePassword({ current: pw.current, new: pw.next }),
    onSuccess: () => {
      setPwOpen(false);
      setPw({ current: "", next: "", next2: "" });
      qc.invalidateQueries({ queryKey: ["sessions"] });
      toast(t("profile.pwChanged"));
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : t("profile.pwFailed")),
  });

  const revokeM = useMutation({
    mutationFn: (id: string) => q.revokeSession(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
      toast(t("profile.sessionRevoked"));
    },
  });

  const revokeOthersM = useMutation({
    mutationFn: () => q.revokeOtherSessions(),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
      toast(r.revoked ? t("profile.sessionsRevoked", { n: r.revoked }) : t("profile.noOtherSessions"));
    },
  });

  const sessions = sessionsQ.data ?? [];

  function selectRole(role: "owner" | "member") {
    setViewRole(role);
    go(role === "owner" ? "servers" : "available");
  }

  const ROLE_OPTIONS = [
    { role: "owner", title: t("profile.roleOwner"), sub: t("profile.roleOwnerSub") },
    { role: "member", title: t("profile.roleMember"), sub: t("profile.roleMemberSub") },
  ] as const;

  return (
    <div className="stack" style={{ maxWidth: 600, margin: "0 auto", width: "100%" }}>
      <ScreenHeader title={t("profile.title")} />

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
          {t("profile.logout")}
        </Btn>
      </div>

      {/* Безопасность */}
      <div className="card stack" style={{ gap: 12 }}>
        <div className="rowflex" style={{ justifyContent: "space-between" }}>
          <div
            className="muted-3"
            style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
          >
            {t("profile.security")}
          </div>
          <Btn sm onClick={() => setPwOpen(true)}>
            <Icon name="edit" size={15} />
            {t("profile.changePassword")}
          </Btn>
        </div>

        <div className="rowflex" style={{ justifyContent: "space-between" }}>
          <span className="muted" style={{ fontSize: 13 }}>
            {t("profile.activeSessions")}
            {sessions.length ? ` · ${sessions.length}` : ""}
          </span>
          {sessions.length > 1 && (
            <Btn variant="ghost" sm disabled={revokeOthersM.isPending} onClick={() => revokeOthersM.mutate()}>
              {t("profile.revokeOthers")}
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
            {t("profile.admin")}
          </div>
          <Btn variant="ghost" block onClick={() => go("users")} style={{ justifyContent: "flex-start" }}>
            <Icon name="users" size={18} />
            {t("nav.users")}
            <span className="muted-3" style={{ fontSize: 12.5, fontWeight: 400, marginLeft: 4 }}>
              {t("profile.usersHint")}
            </span>
          </Btn>
          <Btn variant="ghost" block onClick={() => go("system")} style={{ justifyContent: "flex-start" }}>
            <Icon name="system" size={18} />
            {t("nav.system")}
            <span className="muted-3" style={{ fontSize: 12.5, fontWeight: 400, marginLeft: 4 }}>
              {t("profile.systemHint")}
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
          {t("profile.mode")}
        </div>
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>
          {t("profile.modeHint")}
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
            <div style={{ fontWeight: 600, fontSize: 14.5 }}>{t("profile.darkTheme")}</div>
            <div className="muted-3" style={{ fontSize: 12.5 }}>
              {t("profile.themeNow", { value: theme === "dark" ? t("profile.themeDark") : t("profile.themeLight") })}
            </div>
          </div>
          <Switch on={theme === "dark"} onClick={toggleTheme} />
        </div>
        <div className="card-row" style={{ padding: "14px 0" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 14.5 }}>{t("profile.language")}</div>
            <div className="muted-3" style={{ fontSize: 12.5 }}>
              {t("profile.languageHint")}
            </div>
          </div>
          <div className="row" style={{ gap: 6 }}>
            {LANGS.map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => setLang(l)}
                className={lang === l ? "" : "muted"}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  padding: "5px 11px",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                  background: "transparent",
                  color: lang === l ? "var(--text)" : undefined,
                  opacity: lang === l ? 1 : 0.6,
                }}
              >
                {LANG_LABEL[l]}
              </button>
            ))}
          </div>
        </div>
      </div>

      <p className="muted-3" style={{ textAlign: "center", fontSize: 12 }}>
        {t("profile.tagline")}
      </p>

      {pwOpen && (
        <Modal
          title={t("profile.changePassword")}
          onClose={() => setPwOpen(false)}
          footer={
            <>
              <Btn block onClick={() => setPwOpen(false)}>
                {t("common.cancel")}
              </Btn>
              <Btn
                variant="primary"
                block
                disabled={changePw.isPending}
                onClick={() => {
                  if (pw.next !== pw.next2) {
                    toast(t("profile.pwMismatch"));
                    return;
                  }
                  changePw.mutate();
                }}
              >
                {t("common.save")}
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ marginBottom: 12, fontSize: 13 }}>
            {t("profile.pwWarn")}
          </p>
          <Field label={t("profile.pwCurrent")}>
            <input
              className="input"
              type="password"
              value={pw.current}
              onChange={(e) => setPw((p) => ({ ...p, current: e.target.value }))}
            />
          </Field>
          <Field label={t("profile.pwNew")}>
            <input
              className="input"
              type="password"
              value={pw.next}
              onChange={(e) => setPw((p) => ({ ...p, next: e.target.value }))}
            />
          </Field>
          <Field label={t("profile.pwRepeat")}>
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
  const t = useT();
  return (
    <div
      className="card-row"
      style={{ gap: 12, border: "1px solid var(--border)", borderRadius: 12, padding: "10px 12px" }}
    >
      <Icon name="devices" size={18} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="rowflex" style={{ gap: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 14 }}>{s.device}</span>
          {s.current && <span className="badge ok">{t("profile.sessionCurrent")}</span>}
        </div>
        <div className="muted-3" style={{ fontSize: 12 }}>
          {s.ip} ·{" "}
          {s.lastSeen
            ? t("profile.sessionActivity", { at: s.lastSeen })
            : t("profile.sessionLogin", { at: s.createdAt })}
        </div>
      </div>
      {!s.current && (
        <Btn variant="ghost" sm disabled={busy} onClick={onRevoke} title={t("profile.revokeSession")}>
          <Icon name="x" size={16} />
        </Btn>
      )}
    </div>
  );
}
