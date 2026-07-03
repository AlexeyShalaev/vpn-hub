import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Btn, Field, Icon, Modal, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import * as q from "../lib/queries";
import { useNav } from "../nav";
import { useStore } from "../store";

const sectionTitle = {
  fontSize: 12,
  fontWeight: 700,
  letterSpacing: ".05em",
  textTransform: "uppercase" as const,
};
const chip = {
  fontSize: 11.5,
  fontWeight: 600,
  padding: "4px 9px",
  borderRadius: 999,
  background: "var(--surface-2)",
  color: "var(--text-2)",
};

export function ServerAccessSections({ serverId }: { serverId: string }) {
  const toast = useStore((s) => s.toast);
  const go = useNav((s) => s.go);
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["server-access", serverId],
    queryFn: () => q.serverAccess(serverId),
    enabled: !!serverId,
  });

  const [rename, setRename] = useState<{ cid: string; name: string } | null>(null);
  const [revoke, setRevoke] = useState<{ cid: string; label: string } | null>(null);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["server-access", serverId] });
    qc.invalidateQueries({ queryKey: ["server", serverId] });
  };

  const renameMut = useMutation({
    mutationFn: (v: { cid: string; name: string }) => q.renameServerClient(serverId, v.cid, v.name),
    onSuccess: () => {
      invalidate();
      setRename(null);
      toast("Переименовано");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Ошибка"),
  });
  const revokeMut = useMutation({
    mutationFn: (cid: string) => q.revokeServerClient(serverId, cid),
    onSuccess: () => {
      invalidate();
      setRevoke(null);
      toast("Доступ отозван");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Ошибка"),
  });

  if (isLoading || !data) {
    return (
      <div className="card" style={{ display: "flex", justifyContent: "center", padding: 24 }}>
        <Spinner />
      </div>
    );
  }

  const { pools, groups, users } = data;

  return (
    <>
      {/* Где используется */}
      <div className="card stack">
        <div className="muted-3" style={sectionTitle}>
          Где используется
        </div>
        {pools.length === 0 && groups.length === 0 ? (
          <div className="muted" style={{ fontSize: 13.5 }}>
            Сервер пока не входит в пулы и не выдан ни одной группе.
          </div>
        ) : (
          <div className="stack" style={{ gap: 12 }}>
            {pools.length > 0 && (
              <div>
                <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 6 }}>
                  Пулы
                </div>
                <div className="rowflex" style={{ gap: 6, flexWrap: "wrap" }}>
                  {pools.map((p) => (
                    <span key={p.id} style={chip}>
                      {p.name}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {groups.length > 0 && (
              <div>
                <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 6 }}>
                  Группы
                </div>
                <div className="stack" style={{ gap: 6 }}>
                  {groups.map((g) => (
                    <button
                      key={g.id}
                      onClick={() => go("group", { groupId: g.id })}
                      className="rowflex"
                      style={{
                        justifyContent: "space-between",
                        width: "100%",
                        textAlign: "left",
                        border: "1px solid var(--border)",
                        borderRadius: 10,
                        background: "var(--surface)",
                        padding: "9px 11px",
                        cursor: "pointer",
                        color: "var(--text)",
                      }}
                    >
                      <span style={{ fontWeight: 600, fontSize: 14 }}>{g.name}</span>
                      <span className="rowflex" style={{ gap: 6, flexWrap: "nowrap" }}>
                        <span className="muted-3" style={{ fontSize: 12 }}>
                          {g.via}
                        </span>
                        <span className="muted-3" style={{ display: "inline-flex" }}>
                          <Icon name="chevron" size={15} />
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Пользователи с доступом */}
      <div className="card stack">
        <div className="muted-3" style={sectionTitle}>
          Пользователи с доступом
        </div>
        {users.length === 0 ? (
          <div className="muted" style={{ fontSize: 13.5 }}>
            Пока никто не пользуется этим сервером.
          </div>
        ) : (
          <div className="stack" style={{ gap: 10 }}>
            {users.map((u) => (
              <div
                key={u.userId}
                className="stack"
                style={{ border: "1px solid var(--border)", borderRadius: 13, padding: 13, gap: 10 }}
              >
                <div className="rowflex" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: 15 }}>{u.name}</div>
                    <div className="muted-3" style={{ fontSize: 12.5 }}>
                      {u.phone}
                    </div>
                  </div>
                  <div
                    className="rowflex"
                    style={{ gap: 6, flexWrap: "wrap", justifyContent: "flex-end", maxWidth: "55%" }}
                  >
                    {u.groups.map((gn) => (
                      <span key={gn} style={chip}>
                        {gn}
                      </span>
                    ))}
                    {!u.hasAccess && <span style={{ ...chip, color: "var(--warn)" }}>нет доступа</span>}
                  </div>
                </div>

                {u.configs.length === 0 ? (
                  <div className="muted-3" style={{ fontSize: 12.5 }}>
                    конфигов ещё нет
                  </div>
                ) : (
                  <div className="stack" style={{ gap: 6 }}>
                    {u.configs.map((c) => (
                      <div
                        key={c.id}
                        className="rowflex"
                        style={{
                          justifyContent: "space-between",
                          background: "var(--surface-2)",
                          borderRadius: 10,
                          padding: "8px 11px",
                          flexWrap: "nowrap",
                        }}
                      >
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 13.5, fontWeight: 600, wordBreak: "break-word" }}>
                            {c.clientName || c.device}
                          </div>
                          <div className="muted-3" style={{ fontSize: 12 }}>
                            {c.device} · {c.proto}
                            {c.status !== "active" ? " · отозван" : ""}
                          </div>
                        </div>
                        <div className="rowflex" style={{ flexWrap: "nowrap" }}>
                          <Btn
                            variant="ghost"
                            sm
                            onClick={() => setRename({ cid: c.id, name: c.clientName || c.device })}
                          >
                            <Icon name="edit" size={15} />
                          </Btn>
                          <Btn
                            variant="ghost"
                            sm
                            onClick={() => setRevoke({ cid: c.id, label: c.clientName || c.device })}
                          >
                            <Icon name="trash" size={15} />
                          </Btn>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {rename && (
        <Modal
          title="Переименовать конфиг"
          onClose={() => setRename(null)}
          footer={
            <>
              <Btn onClick={() => setRename(null)}>Отмена</Btn>
              <Btn variant="primary" block disabled={renameMut.isPending} onClick={() => renameMut.mutate(rename)}>
                Сохранить
              </Btn>
            </>
          }
        >
          <Field label="Имя конфига">
            <input
              className="input"
              value={rename.name}
              autoFocus
              onChange={(e) => setRename((r) => (r ? { ...r, name: e.target.value } : r))}
              onKeyDown={(e) => e.key === "Enter" && renameMut.mutate(rename)}
            />
          </Field>
        </Modal>
      )}

      {revoke && (
        <Modal
          title="Отозвать конфиг?"
          onClose={() => setRevoke(null)}
          footer={
            <>
              <Btn onClick={() => setRevoke(null)}>Отмена</Btn>
              <Btn variant="danger" block disabled={revokeMut.isPending} onClick={() => revokeMut.mutate(revoke.cid)}>
                Отозвать
              </Btn>
            </>
          }
        >
          <p className="muted">
            Конфиг «{revoke.label}» перестанет работать: пир будет удалён на сервере, у пользователя доступ к этому
            серверу через него пропадёт.
          </p>
        </Modal>
      )}
    </>
  );
}
