import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { PhoneField } from "../components/PhoneField";
import { Btn, Empty, Field, Icon, Modal, ScreenHeader, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import * as q from "../lib/queries";
import type { AdminUser } from "../lib/types";
import { useStore } from "../store";

type UserStatus = AdminUser["status"];

const STATUS_META: Record<UserStatus, { label: string; cls: "ok" | "warn" | "danger" }> = {
  active: { label: "Активен", cls: "ok" },
  pending: { label: "В ожидании", cls: "warn" },
  blocked: { label: "Заблокирован", cls: "danger" },
};

const STATUS_OPTIONS: { value: UserStatus; label: string }[] = [
  { value: "active", label: "Активен" },
  { value: "pending", label: "В ожидании" },
  { value: "blocked", label: "Заблокирован" },
];

function mono(name: string) {
  return (name || "?").slice(0, 2).toUpperCase();
}

function genPassword() {
  return Math.random().toString(36).slice(2, 8) + Math.floor(Math.random() * 90 + 10);
}

function StatusBadge({ status }: { status: UserStatus }) {
  const meta = STATUS_META[status] ?? STATUS_META.pending;
  return <span className={`badge ${meta.cls}`}>{meta.label}</span>;
}

function UserRow({ u, onOpen }: { u: AdminUser; onOpen: () => void }) {
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
              Админ
            </span>
          )}
          <StatusBadge status={u.status} />
        </div>
        <div className="mono" style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 2 }}>
          {u.phone}
        </div>
      </div>
      <div style={{ fontSize: 12, color: "var(--text-3)", whiteSpace: "nowrap", flex: "none" }}>с {u.createdAt}</div>
    </button>
  );
}

function EditUserModal({ user, onClose }: { user: AdminUser; onClose: () => void }) {
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
      toast(pwMode && newPassword ? "Сохранено, пароль обновлён" : "Изменения сохранены");
      onClose();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Не удалось сохранить"),
  });

  const deleteMut = useMutation({
    mutationFn: () => q.adminDeleteUser(user.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["adminUsers"] });
      toast("Пользователь удалён");
      onClose();
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Не удалось удалить"),
  });

  const save = () => {
    if (!name.trim() || !phone.trim()) {
      toast("Имя и телефон обязательны");
      return;
    }
    saveMut.mutate();
  };

  if (confirmDelete) {
    return (
      <Modal
        title="Удалить пользователя?"
        onClose={() => setConfirmDelete(false)}
        footer={
          <>
            <Btn variant="default" block onClick={() => setConfirmDelete(false)}>
              Отмена
            </Btn>
            <Btn variant="danger" block onClick={() => deleteMut.mutate()} disabled={deleteMut.isPending}>
              Удалить
            </Btn>
          </>
        }
      >
        <p className="muted">Аккаунт будет удалён безвозвратно.</p>
      </Modal>
    );
  }

  return (
    <Modal
      title="Данные пользователя"
      onClose={onClose}
      footer={
        <>
          <Btn variant="default" block onClick={onClose}>
            Отмена
          </Btn>
          <Btn variant="primary" block onClick={save} disabled={saveMut.isPending}>
            Сохранить
          </Btn>
        </>
      }
    >
      <Field label="Имя">
        <input className="input" value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </Field>

      <Field label="Телефон (логин)">
        <PhoneField value={phone} onChange={setPhone} />
      </Field>

      <Field label="Статус">
        {isAdmin ? (
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            Администратор — всегда активен, статус не редактируется.
          </p>
        ) : (
          <div style={{ display: "flex", gap: 7 }}>
            {STATUS_OPTIONS.map((o) => (
              <button
                key={o.value}
                type="button"
                className={`chip ${status === o.value ? "selected" : ""}`}
                onClick={() => setStatus(o.value)}
                style={{ flex: 1, justifyContent: "center", height: 44, cursor: "pointer" }}
              >
                {o.label}
              </button>
            ))}
          </div>
        )}
      </Field>

      <div style={{ height: 1, background: "var(--border)", margin: "4px 0 16px" }} />

      <Field label="Пароль">
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
              <Btn onClick={() => setPwMode(true)}>Задать новый</Btn>
            </div>
            <p style={{ fontSize: 12, color: "var(--text-3)", marginTop: 8 }}>
              Пароль хранится в зашифрованном виде и не отображается.
            </p>
          </>
        ) : (
          <>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                className="input mono"
                value={newPassword}
                placeholder="новый пароль"
                style={{ flex: 1, minWidth: 0 }}
                onChange={(e) => setNewPassword(e.target.value)}
              />
              <Btn
                onClick={() => {
                  setNewPassword(genPassword());
                  toast("Пароль сгенерирован");
                }}
              >
                Сгенерировать
              </Btn>
            </div>
            <p style={{ fontSize: 12, color: "var(--text-3)", marginTop: 8 }}>
              Старый пароль будет заменён на этот при сохранении.
            </p>
          </>
        )}
      </Field>

      {!isAdmin && (
        <Btn variant="danger" block onClick={() => setConfirmDelete(true)}>
          <Icon name="trash" size={16} />
          Удалить пользователя
        </Btn>
      )}
    </Modal>
  );
}

export function UsersScreen() {
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
      <ScreenHeader title="Пользователи" sub="Все аккаунты" />

      {isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 48 }}>
          <Spinner />
        </div>
      ) : all.length === 0 ? (
        <Empty title="Пока нет пользователей" sub="Аккаунты появятся после регистрации." />
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
                placeholder="Поиск по имени или телефону…"
                style={{ paddingLeft: 42 }}
              />
            </div>
          )}

          {hasQuery && filtered.length === 0 ? (
            <Empty title="Никого не найдено" sub="Попробуйте изменить запрос." />
          ) : (
            filtered.map((u) => <UserRow key={u.id} u={u} onOpen={() => setEditId(u.id)} />)
          )}
        </div>
      )}

      {editing && <EditUserModal user={editing} onClose={() => setEditId(null)} />}
    </div>
  );
}
