import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { PhoneField } from "../components/PhoneField";
import { Avatar, Btn, Field, Icon, Modal, ScreenHeader, Spinner } from "../components/ui";
import {
  type AddMemberBody,
  type AddMemberMode,
  buildAddMemberBody,
  defaultAddMemberMode,
  type MemberRole,
} from "../lib/groupMembers";
import { useT } from "../lib/i18n";
import { toDataUrl } from "../lib/qr";
import * as q from "../lib/queries";
import {
  bytesToTrafficInput,
  convertTrafficInputUnit,
  TRAFFIC_UNITS,
  type TrafficUnit,
  trafficValueToBytes,
} from "../lib/trafficUnits";
import type { Group, Member, Pool } from "../lib/types";
import { useNav } from "../nav";
import { copyText, useStore } from "../store";
import { fmtBytes } from "./Monitoring";

const intOrNull = (s: string): number | null => {
  const n = Number.parseInt(s, 10);
  return s.trim() === "" || !Number.isFinite(n) ? null : n;
};

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
  const t = useT();
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
  const [groupBytesVal, setGroupBytesVal] = useState("");
  const [groupBytesUnit, setGroupBytesUnit] = useState<TrafficUnit>("GB");
  const [editingMember, setEditingMember] = useState<Member | null>(null);
  const [memberLimitVal, setMemberLimitVal] = useState("");
  const [memberBytesVal, setMemberBytesVal] = useState("");
  const [memberBytesUnit, setMemberBytesUnit] = useState<TrafficUnit>("GB");

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["group", groupId] });
    qc.invalidateQueries({ queryKey: ["groups"] });
  };

  const deleteMut = useMutation({
    mutationFn: () => q.deleteGroup(groupId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["groups"] });
      toast(t("groupDetail.groupDeleted"));
      go("groups");
    },
  });
  const renameMut = useMutation({
    mutationFn: (name: string) => q.updateGroup(groupId, { name }),
    onSuccess: () => {
      invalidate();
      setRenaming(false);
      toast(t("groupDetail.saved"));
    },
  });
  const regenMut = useMutation({
    mutationFn: () => q.regenToken(groupId),
    onSuccess: (g) => {
      qc.setQueryData(["group", groupId], g);
      qc.invalidateQueries({ queryKey: ["groups"] });
      toast(t("groupDetail.linkRefreshed"));
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
  // сохраняет ОБА лимита группы разом (устройства + трафик)
  const groupLimitMut = useMutation({
    mutationFn: async () => {
      await q.setGroupLimit(groupId, intOrNull(groupLimitVal));
      await q.setGroupBytes(groupId, trafficValueToBytes(groupBytesVal, groupBytesUnit));
    },
    onSuccess: () => {
      invalidate();
      setEditingGroupLimit(false);
      toast(t("groupDetail.saved"));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("groupDetail.saveFailed")),
  });
  const memberLimitMut = useMutation({
    mutationFn: async (mid: string) => {
      await q.setMemberLimit(groupId, mid, intOrNull(memberLimitVal));
      await q.setMemberBytes(groupId, mid, trafficValueToBytes(memberBytesVal, memberBytesUnit));
    },
    onSuccess: () => {
      invalidate();
      setEditingMember(null);
      toast(t("groupDetail.saved"));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("groupDetail.saveFailed")),
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
        <ScreenHeader title={t("groupDetail.title")} onBack={() => go("groups")} />
        <div className="card" style={{ textAlign: "center" }}>
          <Spinner />
        </div>
      </div>
    );
  }

  if (!group) {
    return (
      <div className="stack">
        <ScreenHeader title={t("groupDetail.title")} onBack={() => go("groups")} />
        <div className="card muted">{t("groupDetail.notFound")}</div>
      </div>
    );
  }

  const mono = (group.name || "?").slice(0, 2).toUpperCase();

  return (
    <div className="stack">
      <ScreenHeader
        title={group.name}
        sub={`${t("groupDetail.membersCount", { n: group.members.length })} · ${t("groupDetail.serversAvailableCount", { n: serverCount })}`}
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
              title={t("common.rename")}
            >
              <Icon name="edit" size={16} />
            </Btn>
            <Btn variant="danger" sm onClick={() => setConfirmDelete(true)} title={t("common.delete")}>
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
            {t("groupDetail.membersCount", { n: group.members.length })} ·{" "}
            {t("groupDetail.serversAvailableCount", { n: serverCount })}
          </div>
        </div>
      </div>

      {/* Пригласить участника */}
      <Btn variant="primary" block onClick={() => setInviting(true)}>
        <Icon name="link" size={18} />
        {t("groupDetail.inviteMember")}
      </Btn>

      {/* Доступы группы */}
      <div className="card" style={{ cursor: "pointer" }} onClick={() => go("access", { groupId: group.id })}>
        <div className="rowflex" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <div
            className="muted"
            style={{ fontWeight: 700, fontSize: 12, textTransform: "uppercase", letterSpacing: ".05em" }}
          >
            {t("groupDetail.groupAccess")}
          </div>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--accent)" }}>{t("groupDetail.configure")}</span>
        </div>
        <div className="rowflex" style={{ flexWrap: "wrap", gap: 8 }}>
          {poolTags.map((p) => (
            <span key={p.id} className="chip">
              <Icon name="servers" size={13} />
              {t("groupDetail.poolChip", { name: p.name })}
            </span>
          ))}
          <span style={{ fontSize: 13, color: "var(--text-2)" }}>
            {t("groupDetail.serversAvailableToGroup", { n: serverCount })}
          </span>
        </div>
      </div>

      {/* Лимиты группы (устройства + трафик) */}
      <div className="card">
        <div className="rowflex" style={{ justifyContent: "space-between", gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <div
              className="muted"
              style={{ fontWeight: 700, fontSize: 12, textTransform: "uppercase", letterSpacing: ".05em" }}
            >
              {t("groupDetail.groupLimits")}
            </div>
            <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6 }}>
              {t("groupDetail.devicesLabel")}:{" "}
              {group.maxDevices != null
                ? t("groupDetail.devicesPerMember", { n: group.maxDevices })
                : t("groupDetail.byDefault")}{" "}
              · {t("groupDetail.trafficLabel")}:{" "}
              {group.maxBytes != null
                ? t("groupDetail.trafficPerPeriodPerServer", { value: fmtBytes(group.maxBytes) })
                : t("groupDetail.noLimit")}
              <span className="muted"> · {t("groupDetail.personalLimitsHint")}</span>
            </div>
          </div>
          <Btn
            variant="default"
            sm
            style={{ flex: "none" }}
            onClick={() => {
              const limit = bytesToTrafficInput(group.maxBytes);
              setGroupLimitVal(group.maxDevices?.toString() ?? "");
              setGroupBytesVal(limit.value);
              setGroupBytesUnit(limit.unit);
              setEditingGroupLimit(true);
            }}
          >
            <Icon name="edit" size={15} />
            {t("groupDetail.change")}
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
            {t("groupDetail.membersHeading", { n: group.members.length })}
          </div>
          <Btn variant="default" sm onClick={() => setAdding(true)}>
            <Icon name="plus" size={15} />
            {t("common.add")}
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
                const limit = bytesToTrafficInput(m.maxBytes);
                setMemberLimitVal(m.maxDevices?.toString() ?? "");
                setMemberBytesVal(limit.value);
                setMemberBytesUnit(limit.unit);
                setEditingMember(m);
              }}
            />
          ))}
        </div>
      </div>

      {/* Удаление группы */}
      {confirmDelete && (
        <Modal
          title={t("groupDetail.deleteGroupTitle")}
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
          <p className="muted">{t("groupDetail.deleteGroupWarning")}</p>
        </Modal>
      )}

      {/* Переименование */}
      {renaming && (
        <Modal
          title={t("groupDetail.renameGroupTitle")}
          onClose={() => setRenaming(false)}
          footer={
            <>
              <Btn variant="default" block onClick={() => setRenaming(false)}>
                {t("common.cancel")}
              </Btn>
              <Btn
                variant="primary"
                block
                onClick={() => {
                  if (!renameName.trim()) {
                    toast(t("groupDetail.enterName"));
                    return;
                  }
                  renameMut.mutate(renameName.trim());
                }}
                disabled={renameMut.isPending}
              >
                {t("common.save")}
              </Btn>
            </>
          }
        >
          <Field label={t("groupDetail.groupNameLabel")}>
            <input
              className="input"
              value={renameName}
              placeholder={t("groupDetail.groupNamePlaceholder")}
              autoFocus
              onChange={(e) => setRenameName(e.target.value)}
            />
          </Field>
        </Modal>
      )}

      {/* Пригласить — ссылка + QR */}
      {inviting && (
        <Modal
          title={t("groupDetail.inviteToGroupTitle", { name: group.name })}
          onClose={() => setInviting(false)}
          footer={
            <>
              <Btn variant="default" block onClick={() => regenMut.mutate()} disabled={regenMut.isPending}>
                <Icon name="refresh" size={16} />
                {t("groupDetail.newLink")}
              </Btn>
              <Btn variant="primary" block onClick={() => setInviting(false)}>
                {t("common.done")}
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ marginBottom: 16, textAlign: "center" }}>
            {t("groupDetail.inviteHint")}
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
            <Btn variant="primary" sm onClick={() => copyText(inviteUrl, toast, t("groupDetail.linkCopied"))}>
              <Icon name="copy" size={15} />
              {t("common.copy")}
            </Btn>
          </div>
        </Modal>
      )}

      {/* Добавить участника: выбор из зарегистрированных или приглашение по телефону */}
      {adding && (
        <AddMemberModal
          groupId={groupId}
          onClose={() => setAdding(false)}
          onAdded={() => {
            invalidate();
            setAdding(false);
            toast(t("groupDetail.memberAdded"));
          }}
        />
      )}

      {/* Лимиты группы: устройства + трафик */}
      {editingGroupLimit && (
        <Modal
          title={t("groupDetail.groupLimitsTitle")}
          onClose={() => setEditingGroupLimit(false)}
          footer={
            <>
              <Btn variant="default" block onClick={() => setEditingGroupLimit(false)}>
                {t("common.cancel")}
              </Btn>
              <Btn variant="primary" block onClick={() => groupLimitMut.mutate()} disabled={groupLimitMut.isPending}>
                {t("common.save")}
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ marginBottom: 16, fontSize: 14 }}>
            {t("groupDetail.groupLimitsHint")}
          </p>
          <Field label={t("groupDetail.devicesPerMemberLabel")}>
            <input
              className="input"
              type="number"
              min={1}
              value={groupLimitVal}
              placeholder={t("groupDetail.devicesPerMemberPlaceholder")}
              autoFocus
              onChange={(e) => setGroupLimitVal(e.target.value)}
            />
          </Field>
          <Field label={t("groupDetail.trafficPerPeriodLabel")}>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 92px", gap: 8 }}>
              <input
                className="input"
                type="number"
                min={0}
                step={groupBytesUnit === "B" ? 1 : 0.1}
                value={groupBytesVal}
                placeholder={t("groupDetail.trafficNoLimitPlaceholder")}
                onChange={(e) => setGroupBytesVal(e.target.value)}
              />
              <select
                className="input"
                value={groupBytesUnit}
                onChange={(e) => {
                  const unit = e.target.value as TrafficUnit;
                  setGroupBytesVal((v) => convertTrafficInputUnit(v, groupBytesUnit, unit));
                  setGroupBytesUnit(unit);
                }}
              >
                {TRAFFIC_UNITS.map((u) => (
                  <option key={u.value} value={u.value}>
                    {u.label}
                  </option>
                ))}
              </select>
            </div>
          </Field>
        </Modal>
      )}

      {/* Персональные лимиты участника: устройства + трафик */}
      {editingMember && (
        <Modal
          title={t("groupDetail.memberLimitsTitle", { name: editingMember.name })}
          onClose={() => setEditingMember(null)}
          footer={
            <>
              <Btn variant="default" block onClick={() => setEditingMember(null)}>
                {t("common.cancel")}
              </Btn>
              <Btn
                variant="primary"
                block
                onClick={() => editingMember && memberLimitMut.mutate(editingMember.id)}
                disabled={memberLimitMut.isPending}
              >
                {t("common.save")}
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ marginBottom: 16, fontSize: 14 }}>
            {t("groupDetail.memberLimitsHint", { name: editingMember.name })}
          </p>
          <Field label={t("groupDetail.devicesLabelShort")}>
            <input
              className="input"
              type="number"
              min={1}
              value={memberLimitVal}
              placeholder={t("groupDetail.emptyLikeGroup")}
              autoFocus
              onChange={(e) => setMemberLimitVal(e.target.value)}
            />
          </Field>
          <Field label={t("groupDetail.trafficPerPeriodLabel")}>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 92px", gap: 8 }}>
              <input
                className="input"
                type="number"
                min={0}
                step={memberBytesUnit === "B" ? 1 : 0.1}
                value={memberBytesVal}
                placeholder={t("groupDetail.emptyLikeGroup")}
                onChange={(e) => setMemberBytesVal(e.target.value)}
              />
              <select
                className="input"
                value={memberBytesUnit}
                onChange={(e) => {
                  const unit = e.target.value as TrafficUnit;
                  setMemberBytesVal((v) => convertTrafficInputUnit(v, memberBytesUnit, unit));
                  setMemberBytesUnit(unit);
                }}
              >
                {TRAFFIC_UNITS.map((u) => (
                  <option key={u.value} value={u.value}>
                    {u.label}
                  </option>
                ))}
              </select>
            </div>
          </Field>
        </Modal>
      )}
    </div>
  );
}

function AddMemberModal({ groupId, onClose, onAdded }: { groupId: string; onClose: () => void; onAdded: () => void }) {
  const t = useT();
  const toast = useStore((s) => s.toast);
  // mode === null — ещё не знаем, есть ли кого выбрать; решаем по первому ответу кандидатов
  const [mode, setMode] = useState<AddMemberMode | null>(null);
  const [role, setRole] = useState<MemberRole>("member");
  const [userId, setUserId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(search.trim()), 250);
    return () => window.clearTimeout(id);
  }, [search]);

  const candQ = useQuery({
    queryKey: ["groupCandidates", groupId, debounced],
    queryFn: () => q.memberCandidates(groupId, debounced),
    placeholderData: (prev) => prev,
  });

  useEffect(() => {
    if (mode !== null) return;
    if (candQ.isError) setMode("phone");
    else if (candQ.data && !candQ.isPlaceholderData) setMode(defaultAddMemberMode(candQ.data.length));
  }, [mode, candQ.data, candQ.isError, candQ.isPlaceholderData]);

  const addMut = useMutation({
    mutationFn: (b: AddMemberBody) => q.addMember(groupId, b),
    onSuccess: onAdded,
    onError: (e) => toast(e instanceof Error ? e.message : t("groupDetail.addMemberFailed")),
  });

  const candidates = candQ.data ?? [];
  const submit = () => {
    if (!mode) return;
    // выбранный, но отфильтрованный поиском пользователь не должен добавиться «вслепую»
    const picked = candidates.some((c) => c.id === userId) ? userId : null;
    const res = buildAddMemberBody({ mode, role, userId: picked, name, phone });
    if ("error" in res) {
      toast(t(res.error));
      return;
    }
    addMut.mutate(res.body);
  };

  const modeChip = (m: AddMemberMode, label: string) => (
    <button type="button" className={`chip ${mode === m ? "selected" : ""}`} onClick={() => setMode(m)}>
      {label}
    </button>
  );

  return (
    <Modal
      title={t("groupDetail.addMemberTitle")}
      onClose={onClose}
      footer={
        <>
          <Btn variant="default" block onClick={onClose}>
            {t("common.cancel")}
          </Btn>
          <Btn variant="primary" block onClick={submit} disabled={!mode || addMut.isPending}>
            {t("common.add")}
          </Btn>
        </>
      }
    >
      {mode === null ? (
        <Spinner />
      ) : (
        <>
          <div className="rowflex" style={{ gap: 8, marginBottom: 16 }}>
            {modeChip("pick", t("groupDetail.addModePick"))}
            {modeChip("phone", t("groupDetail.addModePhone"))}
          </div>

          {mode === "pick" ? (
            <>
              <p className="muted" style={{ marginBottom: 12 }}>
                {t("groupDetail.pickUserHint")}
              </p>
              <input
                className="input"
                type="search"
                value={search}
                placeholder={t("groupDetail.searchUsers")}
                autoFocus
                onChange={(e) => setSearch(e.target.value)}
              />
              <div className="stack" style={{ gap: 6, marginTop: 10, maxHeight: 280, overflowY: "auto" }}>
                {candidates.length === 0 ? (
                  <div className="muted-3" style={{ fontSize: 13, padding: "8px 2px" }}>
                    {debounced ? t("groupDetail.noCandidatesFound") : t("groupDetail.noCandidates")}
                  </div>
                ) : (
                  candidates.map((c) => {
                    const checked = c.id === userId;
                    return (
                      <button
                        key={c.id}
                        type="button"
                        className="card-row"
                        onClick={() => setUserId(checked ? null : c.id)}
                        style={{
                          gap: 12,
                          padding: 10,
                          borderRadius: 12,
                          cursor: "pointer",
                          textAlign: "left",
                          border: `1.5px solid ${checked ? "var(--accent)" : "var(--border)"}`,
                          background: checked ? "var(--accent-soft)" : "var(--surface)",
                        }}
                      >
                        <Avatar name={c.name} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div
                            style={{
                              fontWeight: 600,
                              fontSize: 14,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {c.name}
                          </div>
                          <div style={{ fontSize: 12, color: "var(--text-3)" }}>{c.phone}</div>
                        </div>
                        {checked && (
                          <span style={{ color: "var(--accent)", display: "inline-flex" }}>
                            <Icon name="check" size={20} />
                          </span>
                        )}
                      </button>
                    );
                  })
                )}
              </div>
            </>
          ) : (
            <>
              <p className="muted" style={{ marginBottom: 16 }}>
                {t("groupDetail.addMemberHint")}
              </p>
              <Field label={t("groupDetail.nameLabel")}>
                <input
                  className="input"
                  value={name}
                  placeholder={t("groupDetail.namePlaceholder")}
                  autoFocus
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              <Field label={t("groupDetail.phoneOptionalLabel")}>
                <PhoneField value={phone} onChange={setPhone} />
              </Field>
            </>
          )}

          <div style={{ marginTop: 16 }}>
            <Field label={t("groupDetail.roleLabel")}>
              <div className="rowflex" style={{ gap: 8 }}>
                <button
                  type="button"
                  className={`chip ${role === "member" ? "selected" : ""}`}
                  onClick={() => setRole("member")}
                >
                  {t("groupDetail.roleMember")}
                </button>
                <button
                  type="button"
                  className={`chip ${role === "admin" ? "selected" : ""}`}
                  onClick={() => setRole("admin")}
                >
                  {t("groupDetail.roleGroupAdmin")}
                </button>
              </div>
            </Field>
          </div>
        </>
      )}
    </Modal>
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
  const t = useT();
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
          {member.status === "invited" && <span className="badge warn">{t("groupDetail.invited")}</span>}
        </div>
      </div>
      <Btn variant="default" sm onClick={onEditLimit} title={t("groupDetail.personalLimitsTitle")}>
        {member.maxDevices != null || member.maxBytes != null
          ? [
              member.maxDevices != null ? t("groupDetail.devicesShort", { n: member.maxDevices }) : null,
              member.maxBytes != null ? fmtBytes(member.maxBytes) : null,
            ]
              .filter(Boolean)
              .join(" · ")
          : t("groupDetail.limits")}
      </Btn>
      <Btn variant="default" sm onClick={onToggleRole} title={t("groupDetail.changeRole")}>
        {member.role === "admin" ? t("groupDetail.roleAdminShort") : t("groupDetail.roleMemberShort")}
      </Btn>
      <Btn variant="ghost" sm onClick={onRemove} title={t("common.delete")}>
        <Icon name="x" size={16} />
      </Btn>
    </div>
  );
}
