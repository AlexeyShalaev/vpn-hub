import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { PhoneField } from "../components/PhoneField";
import { Avatar, Btn, Field, Icon, Modal, ScreenHeader, Spinner } from "../components/ui";
import { toDataUrl } from "../lib/qr";
import * as q from "../lib/queries";
import type { Group, Member, Pool } from "../lib/types";
import { useNav } from "../nav";
import { copyText, useStore } from "../store";

function plural(n: number, a: string, b: string, c: string): string {
  const n10 = n % 10;
  const n100 = n % 100;
  if (n10 === 1 && n100 !== 11) return a;
  if (n10 >= 2 && n10 <= 4 && (n100 < 10 || n100 >= 20)) return b;
  return c;
}

// Эффективный доступ группы = серверы её пулов ∪ точечно выданные серверы.
function effectiveServerCount(group: Group, pools: Pool[]): number {
  const set = new Set<string>();
  for (const pid of group.access.pools || []) {
    const pool = pools.find((p) => p.id === pid);
    if (pool) {
      for (const id of pool.serverIds) set.add(id);
    }
  }
  for (const id of Object.keys(group.access.servers || {})) set.add(id);
  return set.size;
}

export function GroupDetailScreen() {
  const groupId = useNav((s) => s.params.groupId) || "";
  const go = useNav((s) => s.go);
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();

  const groupQ = useQuery({
    queryKey: ["group", groupId],
    queryFn: () => q.getGroup(groupId),
    enabled: !!groupId,
  });
  const poolsQ = useQuery({ queryKey: ["pools"], queryFn: q.listPools });

  const [confirmDelete, setConfirmDelete] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameName, setRenameName] = useState("");
  const [inviting, setInviting] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editingGroupLimit, setEditingGroupLimit] = useState(false);
  const [groupLimitVal, setGroupLimitVal] = useState("");
  const [editingMember, setEditingMember] = useState<Member | null>(null);
  const [memberLimitVal, setMemberLimitVal] = useState("");
  const [form, setForm] = useState<{ name: string; role: "admin" | "member"; phone: string }>({
    name: "",
    role: "member",
    phone: "",
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["group", groupId] });
    qc.invalidateQueries({ queryKey: ["groups"] });
  };

  const deleteMut = useMutation({
    mutationFn: () => q.deleteGroup(groupId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["groups"] });
      toast("Группа удалена");
      go("groups");
    },
  });
  const renameMut = useMutation({
    mutationFn: (name: string) => q.updateGroup(groupId, { name }),
    onSuccess: () => {
      invalidate();
      setRenaming(false);
      toast("Сохранено");
    },
  });
  const regenMut = useMutation({
    mutationFn: () => q.regenToken(groupId),
    onSuccess: (g) => {
      qc.setQueryData(["group", groupId], g);
      qc.invalidateQueries({ queryKey: ["groups"] });
      toast("Ссылка обновлена");
    },
  });
  const addMut = useMutation({
    mutationFn: (b: { name: string; role: string; phone?: string }) => q.addMember(groupId, b),
    onSuccess: () => {
      invalidate();
      setAdding(false);
      toast("Участник добавлен");
    },
  });
  const roleMut = useMutation({
    mutationFn: (memberId: string) => q.toggleMemberRole(groupId, memberId),
    onSuccess: () => invalidate(),
  });
  const removeMut = useMutation({
    mutationFn: (memberId: string) => q.removeMember(groupId, memberId),
    onSuccess: () => invalidate(),
  });
  const groupLimitMut = useMutation({
    mutationFn: (n: number | null) => q.setGroupLimit(groupId, n),
    onSuccess: () => {
      invalidate();
      setEditingGroupLimit(false);
      toast("Сохранено");
    },
  });
  const memberLimitMut = useMutation({
    mutationFn: ({ mid, n }: { mid: string; n: number | null }) => q.setMemberLimit(groupId, mid, n),
    onSuccess: () => {
      invalidate();
      setEditingMember(null);
      toast("Сохранено");
    },
  });

  const group = groupQ.data;
  const inviteUrl = group ? `${location.origin}/join/${group.token}` : "";

  // QR для инвайт-ссылки.
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!inviting || !inviteUrl) {
      setQrUrl(null);
      return;
    }
    let alive = true;
    setQrUrl(null);
    toDataUrl(inviteUrl)
      .then((u) => {
        if (alive) setQrUrl(u);
      })
      .catch(() => {
        if (alive) setQrUrl(null);
      });
    return () => {
      alive = false;
    };
  }, [inviting, inviteUrl]);

  const pools = poolsQ.data ?? [];
  const serverCount = useMemo(() => (group ? effectiveServerCount(group, pools) : 0), [group, pools]);
  const poolTags = useMemo(
    () => (group ? (group.access.pools || []).map((pid) => pools.find((p) => p.id === pid)).filter(Boolean) : []),
    [group, pools],
  ) as Pool[];

  if (groupQ.isLoading) {
    return (
      <div className="stack">
        <ScreenHeader title="Группа" onBack={() => go("groups")} />
        <div className="card" style={{ textAlign: "center" }}>
          <Spinner />
        </div>
      </div>
    );
  }

  if (!group) {
    return (
      <div className="stack">
        <ScreenHeader title="Группа" onBack={() => go("groups")} />
        <div className="card muted">Группа не найдена.</div>
      </div>
    );
  }

  const mono = (group.name || "?").slice(0, 2).toUpperCase();

  return (
    <div className="stack">
      <ScreenHeader
        title={group.name}
        sub={`${group.members.length} ${plural(group.members.length, "участник", "участника", "участников")} · ${serverCount} ${plural(serverCount, "сервер", "сервера", "серверов")} доступно`}
        onBack={() => go("groups")}
        action={
          <div className="rowflex" style={{ gap: 8 }}>
            <Btn
              variant="default"
              sm
              onClick={() => {
                setRenameName(group.name);
                setRenaming(true);
              }}
              title="Переименовать"
            >
              <Icon name="edit" size={16} />
            </Btn>
            <Btn variant="danger" sm onClick={() => setConfirmDelete(true)} title="Удалить">
              <Icon name="trash" size={16} />
            </Btn>
          </div>
        }
      />

      {/* Шапка с аватаром группы */}
      <div className="card rowflex" style={{ gap: 14, alignItems: "center" }}>
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: 14,
            background: "var(--accent-soft)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: 17,
            flex: "none",
          }}
        >
          {mono}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="title" style={{ fontSize: 18 }}>
            {group.name}
          </div>
          <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>
            {group.members.length} {plural(group.members.length, "участник", "участника", "участников")} · {serverCount}{" "}
            {plural(serverCount, "сервер", "сервера", "серверов")} доступно
          </div>
        </div>
      </div>

      {/* Пригласить участника */}
      <Btn variant="primary" block onClick={() => setInviting(true)}>
        <Icon name="link" size={18} />
        Пригласить участника
      </Btn>

      {/* Доступы группы */}
      <div className="card" style={{ cursor: "pointer" }} onClick={() => go("access", { groupId: group.id })}>
        <div className="rowflex" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <div
            className="muted"
            style={{ fontWeight: 700, fontSize: 12, textTransform: "uppercase", letterSpacing: ".05em" }}
          >
            Доступы группы
          </div>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--accent)" }}>Настроить →</span>
        </div>
        <div className="rowflex" style={{ flexWrap: "wrap", gap: 8 }}>
          {poolTags.map((p) => (
            <span key={p.id} className="chip">
              <Icon name="servers" size={13} />
              Пул «{p.name}»
            </span>
          ))}
          <span style={{ fontSize: 13, color: "var(--text-2)" }}>
            {serverCount} {plural(serverCount, "сервер", "сервера", "серверов")} доступно группе
          </span>
        </div>
      </div>

      {/* Лимит устройств группы */}
      <div className="card">
        <div className="rowflex" style={{ justifyContent: "space-between", gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <div
              className="muted"
              style={{ fontWeight: 700, fontSize: 12, textTransform: "uppercase", letterSpacing: ".05em" }}
            >
              Лимит устройств
            </div>
            <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6 }}>
              {group.maxDevices != null ? `${group.maxDevices} на участника` : "по умолчанию (глобальный лимит)"}
              <span className="muted"> · персональный лимит участника — в его строке ниже</span>
            </div>
          </div>
          <Btn
            variant="default"
            sm
            style={{ flex: "none" }}
            onClick={() => {
              setGroupLimitVal(group.maxDevices?.toString() ?? "");
              setEditingGroupLimit(true);
            }}
          >
            <Icon name="edit" size={15} />
            Изменить
          </Btn>
        </div>
      </div>

      {/* Участники */}
      <div className="card">
        <div className="rowflex" style={{ justifyContent: "space-between", marginBottom: 14 }}>
          <div
            className="muted"
            style={{ fontWeight: 700, fontSize: 12, textTransform: "uppercase", letterSpacing: ".05em" }}
          >
            Участники · {group.members.length}
          </div>
          <Btn
            variant="default"
            sm
            onClick={() => {
              setForm({ name: "", role: "member", phone: "" });
              setAdding(true);
            }}
          >
            <Icon name="plus" size={15} />
            Добавить
          </Btn>
        </div>
        <div className="stack" style={{ gap: 8 }}>
          {group.members.map((m) => (
            <MemberRow
              key={m.id}
              member={m}
              onToggleRole={() => roleMut.mutate(m.id)}
              onRemove={() => removeMut.mutate(m.id)}
              onEditLimit={() => {
                setMemberLimitVal(m.maxDevices?.toString() ?? "");
                setEditingMember(m);
              }}
            />
          ))}
        </div>
      </div>

      {/* Удаление группы */}
      {confirmDelete && (
        <Modal
          title="Удалить группу?"
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
          <p className="muted">Участники потеряют доступ. Действие необратимо.</p>
        </Modal>
      )}

      {/* Переименование */}
      {renaming && (
        <Modal
          title="Переименовать группу"
          onClose={() => setRenaming(false)}
          footer={
            <>
              <Btn variant="default" block onClick={() => setRenaming(false)}>
                Отмена
              </Btn>
              <Btn
                variant="primary"
                block
                onClick={() => {
                  if (!renameName.trim()) {
                    toast("Введите название");
                    return;
                  }
                  renameMut.mutate(renameName.trim());
                }}
                disabled={renameMut.isPending}
              >
                Сохранить
              </Btn>
            </>
          }
        >
          <Field label="Название группы">
            <input
              className="input"
              value={renameName}
              placeholder="например, Семья"
              autoFocus
              onChange={(e) => setRenameName(e.target.value)}
            />
          </Field>
        </Modal>
      )}

      {/* Пригласить — ссылка + QR */}
      {inviting && (
        <Modal
          title={`Пригласить в «${group.name}»`}
          onClose={() => setInviting(false)}
          footer={
            <>
              <Btn variant="default" block onClick={() => regenMut.mutate()} disabled={regenMut.isPending}>
                <Icon name="refresh" size={16} />
                Новая ссылка
              </Btn>
              <Btn variant="primary" block onClick={() => setInviting(false)}>
                Готово
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ marginBottom: 16, textAlign: "center" }}>
            Покажите QR-код или отправьте ссылку — участник присоединится сам.
          </p>
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 16 }}>
            {qrUrl ? (
              <img className="qr" src={qrUrl} alt="QR" />
            ) : (
              <div className="qr" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Spinner />
              </div>
            )}
          </div>
          <div className="copyable" style={{ marginBottom: 12, display: "flex", alignItems: "flex-start" }}>
            <span
              className="mono"
              style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere", wordBreak: "break-word", fontSize: 13 }}
            >
              {inviteUrl}
            </span>
            <Btn variant="primary" sm onClick={() => copyText(inviteUrl, toast, "Ссылка скопирована")}>
              <Icon name="copy" size={15} />
              Копировать
            </Btn>
          </div>
        </Modal>
      )}

      {/* Добавить участника вручную */}
      {adding && (
        <Modal
          title="Добавить участника"
          onClose={() => setAdding(false)}
          footer={
            <>
              <Btn variant="default" block onClick={() => setAdding(false)}>
                Отмена
              </Btn>
              <Btn
                variant="primary"
                block
                onClick={() => {
                  if (!form.name.trim()) {
                    toast("Введите имя");
                    return;
                  }
                  addMut.mutate({
                    name: form.name.trim(),
                    role: form.role,
                    phone: form.phone.trim() || undefined,
                  });
                }}
                disabled={addMut.isPending}
              >
                Добавить
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ marginBottom: 16 }}>
            Обычно участники присоединяются по ссылке, но можно добавить вручную.
          </p>
          <Field label="Имя">
            <input
              className="input"
              value={form.name}
              placeholder="например, Бабушка"
              autoFocus
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </Field>
          <Field label="Роль">
            <div className="rowflex" style={{ gap: 8 }}>
              <button
                type="button"
                className={`chip ${form.role === "member" ? "selected" : ""}`}
                onClick={() => setForm((f) => ({ ...f, role: "member" }))}
              >
                Участник
              </button>
              <button
                type="button"
                className={`chip ${form.role === "admin" ? "selected" : ""}`}
                onClick={() => setForm((f) => ({ ...f, role: "admin" }))}
              >
                Админ группы
              </button>
            </div>
          </Field>
          <Field label="Телефон (необязательно)">
            <PhoneField value={form.phone} onChange={(v) => setForm((f) => ({ ...f, phone: v }))} />
          </Field>
        </Modal>
      )}

      {/* Лимит устройств группы */}
      {editingGroupLimit && (
        <Modal
          title="Лимит устройств группы"
          onClose={() => setEditingGroupLimit(false)}
          footer={
            <>
              <Btn variant="default" block onClick={() => setEditingGroupLimit(false)}>
                Отмена
              </Btn>
              <Btn
                variant="primary"
                block
                onClick={() => {
                  const n = Number.parseInt(groupLimitVal, 10);
                  groupLimitMut.mutate(groupLimitVal.trim() === "" || !Number.isFinite(n) ? null : n);
                }}
                disabled={groupLimitMut.isPending}
              >
                Сохранить
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ marginBottom: 16, fontSize: 14 }}>
            Сколько устройств может завести каждый участник группы. Пусто — наследовать глобальный лимит. Персональный
            лимит участника (в его строке) перекрывает этот.
          </p>
          <Field label="Устройств на участника">
            <input
              className="input"
              type="number"
              min={1}
              value={groupLimitVal}
              placeholder="напр. 5 (пусто — глобальный)"
              autoFocus
              onChange={(e) => setGroupLimitVal(e.target.value)}
            />
          </Field>
        </Modal>
      )}

      {/* Персональный лимит устройств участника */}
      {editingMember && (
        <Modal
          title={`Лимит устройств · ${editingMember.name}`}
          onClose={() => setEditingMember(null)}
          footer={
            <>
              <Btn variant="default" block onClick={() => setEditingMember(null)}>
                Отмена
              </Btn>
              <Btn
                variant="primary"
                block
                onClick={() => {
                  const n = Number.parseInt(memberLimitVal, 10);
                  memberLimitMut.mutate({
                    mid: editingMember.id,
                    n: memberLimitVal.trim() === "" || !Number.isFinite(n) ? null : n,
                  });
                }}
                disabled={memberLimitMut.isPending}
              >
                Сохранить
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ marginBottom: 16, fontSize: 14 }}>
            Персональный лимит устройств для «{editingMember.name}». Пусто — наследовать лимит группы или глобальный.
          </p>
          <Field label="Устройств">
            <input
              className="input"
              type="number"
              min={1}
              value={memberLimitVal}
              placeholder="пусто — как у группы"
              autoFocus
              onChange={(e) => setMemberLimitVal(e.target.value)}
            />
          </Field>
        </Modal>
      )}
    </div>
  );
}

function MemberRow({
  member,
  onToggleRole,
  onRemove,
  onEditLimit,
}: {
  member: Member;
  onToggleRole: () => void;
  onRemove: () => void;
  onEditLimit: () => void;
}) {
  return (
    <div className="card-row" style={{ gap: 12 }}>
      <Avatar name={member.name} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="rowflex" style={{ gap: 8 }}>
          <span
            style={{
              fontWeight: 600,
              fontSize: 14.5,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {member.name}
          </span>
          {member.status === "invited" && <span className="badge warn">приглашён</span>}
        </div>
      </div>
      <Btn
        variant="default"
        sm
        onClick={onEditLimit}
        title={member.maxDevices != null ? "Персональный лимит устройств" : "Задать лимит устройств"}
      >
        {member.maxDevices != null ? `${member.maxDevices} уст.` : "лимит"}
      </Btn>
      <Btn variant="default" sm onClick={onToggleRole} title="Сменить роль">
        {member.role === "admin" ? "админ" : "участник"}
      </Btn>
      <Btn variant="ghost" sm onClick={onRemove} title="Удалить">
        <Icon name="x" size={16} />
      </Btn>
    </div>
  );
}
