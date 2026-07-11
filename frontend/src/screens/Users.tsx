import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { PhoneField } from "../components/PhoneField";
import { Btn, Empty, Field, Icon, Modal, ScreenHeader, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import { useT } from "../lib/i18n";
import * as q from "../lib/queries";
import type { AdminUser } from "../lib/types";
import { useStore } from "../store";

type UserStatus = AdminUser["status"];

const STATUS_CLS: Record<UserStatus, "ok" | "warn" | "danger"> = {
  active: "ok",
  pending: "warn",
  blocked: "danger",
};

const STATUS_KEYS: Record<UserStatus, "status.active" | "status.pending" | "status.blocked"> = {
  active: "status.active",
  pending: "status.pending",
  blocked: "status.blocked",
};

const STATUS_OPTIONS: UserStatus[] = ["active", "pending", "blocked"];

function mono(name: string) {
  return (name || "?").slice(0, 2).toUpperCase();
}

function genPassword() {
  return Math.random().toString(36).slice(2, 8) + Math.floor(Math.random() * 90 + 10);
}

function StatusBadge({ status }: { status: UserStatus }) {
  const t = useT();
  const cls = STATUS_CLS[status] ?? STATUS_CLS.pending;
  const key = STATUS_KEYS[status] ?? STATUS_KEYS.pending;
  return <span className={`badge ${cls}`}>{t(key)}</span>;
}

function UserRow({ u, onOpen }: { u: AdminUser; onOpen: () => void }) {
  const t = useT();
  return (
    <button
      onClick={onOpen}
      style={{
        textAlign: "left",
        display: "flex",
        alignItems: "center",
        gap: 13,
        padding: "14px var(--pad)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r)",
        background: "var(--surface)",
        boxShadow: "var(--shadow)",
        cursor: "pointer",
        userSelect: "none",
      }}
    >
      <div
        style={{
          width: 42,
          height: 42,
          borderRadius: 12,
          background: u.isAdmin ? "var(--ink)" : "var(--surface-2)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontWeight: 700,
          fontSize: 14,
          color: u.isAdmin ? "var(--on-ink)" : "var(--text-2)",
          flex: "none",
        }}
      >
        {mono(u.name)}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span
            style={{
              fontWeight: 700,
              fontSize: 15.5,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {u.name}
          </span>
          {u.isAdmin && (
            <span className="badge" style={{ background: "var(--ink)", color: "var(--on-ink)" }}>
              {t("status.admin")}
            </span>
          )}
          <StatusBadge status={u.status} />
        </div>
        <div className="mono" style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 2 }}>
          {u.phone}
        </div>
      </div>
      <div style={{ fontSize: 12, color: "var(--text-3)", whiteSpace: "nowrap", flex: "none" }}>
        {t("users.since", { date: u.createdAt })}
      </div>
    </button>
  );
}

function EditUserModal({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const t = useT();
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);

  const [name, setName] = useState(user.name);
  const [phone, setPhone] = useState(user.phone);
  const [status, setStatus] = useState<UserStatus>(user.status);
  const [pwMode, setPwMode] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const isAdmin = user.isAdmin;

  const saveMut = useMutation({
    mutationFn: () =>
      q.adminUpdateUser(user.id, {
        name: name.trim(),
        phone: phone.trim(),
        status,
        ...(pwMode && newPassword ? { newPassword } : {}),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["adminUsers"] });
      toast(pwMode && newPassword ? t("users.savedPasswordUpdated") : t("users.changesSaved"));
      onClose();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : t("users.saveFailed")),
  });

  const deleteMut = useMutation({
    mutationFn: () => q.adminDeleteUser(user.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["adminUsers"] });
      toast(t("users.userDeleted"));
      onClose();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : t("users.deleteFailed")),
  });

  const save = () => {
    if (!name.trim() || !phone.trim()) {
      toast(t("users.nameAndPhoneRequired"));
      return;
    }
    saveMut.mutate();
  };

  if (confirmDelete) {
    return (
      <Modal
        title={t("users.deleteUserTitle")}
        onClose={() => setConfirmDelete(false)}
        footer={
          <>
            <Btn variant="default" block onClick={() => setConfirmDelete(false)}>
              {t("common.cancel")}
            </Btn>
            <Btn variant="danger" block onClick={() => deleteMut.mutate()} disabled={deleteMut.isPending}>
              {t("common.delete")}
            </Btn>
          </>
        }
      >
        <p className="muted">{t("users.deleteIrreversible")}</p>
      </Modal>
    );
  }

  return (
    <Modal
      title={t("users.userData")}
      onClose={onClose}
      footer={
        <>
          <Btn variant="default" block onClick={onClose}>
            {t("common.cancel")}
          </Btn>
          <Btn variant="primary" block onClick={save} disabled={saveMut.isPending}>
            {t("common.save")}
          </Btn>
        </>
      }
    >
      <Field label={t("users.name")}>
        <input className="input" value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </Field>

      <Field label={t("users.phoneLogin")}>
        <PhoneField value={phone} onChange={setPhone} />
      </Field>

      <Field label={t("users.status")}>
        {isAdmin ? (
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            {t("users.adminStatusNotEditable")}
          </p>
        ) : (
          <div style={{ display: "flex", gap: 7 }}>
            {STATUS_OPTIONS.map((o) => (
              <button
                key={o}
                type="button"
                className={`chip ${status === o ? "selected" : ""}`}
                onClick={() => setStatus(o)}
                style={{ flex: 1, justifyContent: "center", height: 44, cursor: "pointer" }}
              >
                {t(STATUS_KEYS[o])}
              </button>
            ))}
          </div>
        )}
      </Field>

      <div style={{ height: 1, background: "var(--border)", margin: "4px 0 16px" }} />

      <Field label={t("users.password")}>
        {!pwMode ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div
                className="mono"
                style={{
                  flex: 1,
                  minWidth: 0,
                  height: 46,
                  display: "flex",
                  alignItems: "center",
                  padding: "0 14px",
                  border: "1px solid var(--border)",
                  borderRadius: 12,
                  background: "var(--surface-2)",
                  color: "var(--text-3)",
                  fontSize: 18,
                  letterSpacing: 3,
                }}
              >
                ••••••••
              </div>
              <Btn onClick={() => setPwMode(true)}>{t("users.setNew")}</Btn>
            </div>
            <p style={{ fontSize: 12, color: "var(--text-3)", marginTop: 8 }}>{t("users.passwordEncryptedHint")}</p>
          </>
        ) : (
          <>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                className="input mono"
                value={newPassword}
                placeholder={t("users.newPasswordPlaceholder")}
                style={{ flex: 1, minWidth: 0 }}
                onChange={(e) => setNewPassword(e.target.value)}
              />
              <Btn
                onClick={() => {
                  setNewPassword(genPassword());
                  toast(t("users.passwordGenerated"));
                }}
              >
                {t("users.generate")}
              </Btn>
            </div>
            <p style={{ fontSize: 12, color: "var(--text-3)", marginTop: 8 }}>{t("users.oldPasswordReplaceHint")}</p>
          </>
        )}
      </Field>

      {!isAdmin && (
        <Btn variant="danger" block onClick={() => setConfirmDelete(true)}>
          <Icon name="trash" size={16} />
          {t("users.deleteUser")}
        </Btn>
      )}
    </Modal>
  );
}

export function UsersScreen() {
  const t = useT();
  const [query, setQuery] = useState("");
  const [editId, setEditId] = useState<string | null>(null);

  const { data: users, isLoading } = useQuery({
    queryKey: ["adminUsers"],
    queryFn: q.adminUsers,
  });

  const all = useMemo(() => [...(users ?? [])].sort((a, b) => Number(b.isAdmin) - Number(a.isAdmin)), [users]);
  const showSearch = all.length >= 3;

  const filtered = useMemo(() => {
    const sq = query.trim().toLowerCase();
    if (sq.length < 3) return all;
    return all.filter((u) => `${u.name} ${u.phone}`.toLowerCase().includes(sq));
  }, [all, query]);

  const editing = editId ? (all.find((u) => u.id === editId) ?? null) : null;

  // Если пользователь исчез из списка (удалён) — закрываем модалку.
  useEffect(() => {
    if (editId && !editing) setEditId(null);
  }, [editId, editing]);

  const hasQuery = query.trim().length >= 3;

  return (
    <div className="screen">
      <ScreenHeader title={t("users.title")} sub={t("users.allAccounts")} />

      {isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 48 }}>
          <Spinner />
        </div>
      ) : all.length === 0 ? (
        <Empty title={t("users.noUsersYet")} sub={t("users.accountsAppearAfterRegistration")} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {showSearch && (
            <div style={{ position: "relative" }}>
              <span
                style={{
                  position: "absolute",
                  left: 13,
                  top: "50%",
                  transform: "translateY(-50%)",
                  color: "var(--text-3)",
                  pointerEvents: "none",
                  display: "inline-flex",
                }}
              >
                <Icon name="search" size={18} />
              </span>
              <input
                className="input"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("users.searchPlaceholder")}
                style={{ paddingLeft: 42 }}
              />
            </div>
          )}

          {hasQuery && filtered.length === 0 ? (
            <Empty title={t("users.noOneFound")} sub={t("users.tryDifferentQuery")} />
          ) : (
            filtered.map((u) => <UserRow key={u.id} u={u} onOpen={() => setEditId(u.id)} />)
          )}
        </div>
      )}

      {editing && <EditUserModal user={editing} onClose={() => setEditId(null)} />}
    </div>
  );
}
