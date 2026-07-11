import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Btn, Field, Icon, Modal, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import { useT } from "../lib/i18n";
import * as q from "../lib/queries";
import type { ServerClientConfig } from "../lib/types";
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

interface GroupPause {
  pause: boolean; // true — приостановить активные, false — возобновить приостановленные
  ids: string[];
}

// групповое действие паузы: есть активные → «приостановить все»; иначе есть на паузе → «возобновить все».
// suspended (лимит трафика) и revoked не трогаем — ими управляет система/владелец отдельно.
function groupPauseAction(configs: ServerClientConfig[]): GroupPause | null {
  const pausable = configs.filter((c) => c.status === "active").map((c) => c.id);
  if (pausable.length) return { pause: true, ids: pausable };
  const resumable = configs.filter((c) => c.status === "paused").map((c) => c.id);
  if (resumable.length) return { pause: false, ids: resumable };
  return null;
}

// конфиги пользователя, сгруппированные по устройству (порядок первого появления устройства)
function groupByDevice(configs: ServerClientConfig[]): [string, ServerClientConfig[]][] {
  const m = new Map<string, ServerClientConfig[]>();
  for (const c of configs) {
    const list = m.get(c.device);
    if (list) list.push(c);
    else m.set(c.device, [c]);
  }
  return [...m];
}

// Кнопка групповой паузы/продолжения (для устройства или всего пользователя). Скрыта, если нечего делать.
function GroupPauseBtn({
  configs,
  scope,
  disabled,
  onRun,
}: {
  configs: ServerClientConfig[];
  scope: "device" | "user";
  disabled: boolean;
  onRun: (a: GroupPause) => void;
}) {
  const t = useT();
  const action = groupPauseAction(configs);
  if (!action) return null;
  // подпись групповой кнопки — явная по области (устройство / пользователь), чтобы было понятно, что затронет
  const label =
    scope === "device"
      ? action.pause
        ? t("srvAccess.pauseAllDevice")
        : t("srvAccess.resumeAllDevice")
      : action.pause
        ? t("srvAccess.pauseAllUser")
        : t("srvAccess.resumeAllUser");
  return (
    <Btn variant="ghost" sm disabled={disabled} title={label} onClick={() => onRun(action)}>
      <Icon name={action.pause ? "stop" : "play"} size={14} />
      {label}
    </Btn>
  );
}

export function ServerAccessSections({ serverId }: { serverId: string }) {
  const t = useT();
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
      toast(t("srvAccess.renamed"));
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : t("common.error")),
  });
  const revokeMut = useMutation({
    mutationFn: (cid: string) => q.revokeServerClient(serverId, cid),
    onSuccess: () => {
      invalidate();
      setRevoke(null);
      toast(t("srvAccess.accessRevoked"));
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : t("common.error")),
  });
  // ручная пауза/старт доступа по конфигу (тот же suspend/resume-механизм, статус → paused/active)
  const pauseMut = useMutation({
    mutationFn: (v: { cid: string; pause: boolean }) =>
      v.pause ? q.pauseServerClient(serverId, v.cid) : q.resumeServerClient(serverId, v.cid),
    onSuccess: (_r, v) => {
      invalidate();
      toast(v.pause ? t("srvAccess.configPaused") : t("srvAccess.configResumed"));
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : t("common.error")),
  });
  // групповая пауза/продолжение (устройство или весь пользователь) — те же suspend/resume, но пачкой.
  // Последовательно: конфиг-файловые протоколы (xray/hysteria2) правят один server.json — параллель бы гонялась.
  const bulkPauseMut = useMutation({
    mutationFn: async (v: GroupPause) => {
      for (const id of v.ids) {
        await (v.pause ? q.pauseServerClient(serverId, id) : q.resumeServerClient(serverId, id));
      }
    },
    onSuccess: (_r, v) => {
      invalidate();
      toast(v.pause ? t("srvAccess.bulkPaused", { n: v.ids.length }) : t("srvAccess.bulkResumed", { n: v.ids.length }));
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : t("common.error")),
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
          {t("srvAccess.usedWhereTitle")}
        </div>
        {pools.length === 0 && groups.length === 0 ? (
          <div className="muted" style={{ fontSize: 13.5 }}>
            {t("srvAccess.usedWhereEmpty")}
          </div>
        ) : (
          <div className="stack" style={{ gap: 12 }}>
            {pools.length > 0 && (
              <div>
                <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 6 }}>
                  {t("srvAccess.poolsTitle")}
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
                  {t("nav.groups")}
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
          {t("srvAccess.usersWithAccessTitle")}
        </div>
        {users.length === 0 ? (
          <div className="muted" style={{ fontSize: 13.5 }}>
            {t("srvAccess.usersEmpty")}
          </div>
        ) : (
          <div className="stack" style={{ gap: 10 }}>
            {users.map((u) => (
              <div
                key={u.userId}
                className="stack"
                style={{ border: "1px solid var(--border)", borderRadius: 13, padding: 13, gap: 10 }}
              >
                <div className="rowflex" style={{ justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: 15 }}>{u.name}</div>
                    <div className="muted-3" style={{ fontSize: 12.5 }}>
                      {u.phone}
                    </div>
                  </div>
                  <div className="stack" style={{ gap: 6, alignItems: "flex-end", maxWidth: "60%" }}>
                    <div className="rowflex" style={{ gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                      {u.groups.map((gn) => (
                        <span key={gn} style={chip}>
                          {gn}
                        </span>
                      ))}
                      {!u.hasAccess && <span style={{ ...chip, color: "var(--warn)" }}>{t("srvAccess.noAccess")}</span>}
                    </div>
                    {/* пауза/продолжение всех конфигов всего пользователя */}
                    <GroupPauseBtn
                      configs={u.configs}
                      scope="user"
                      disabled={bulkPauseMut.isPending}
                      onRun={bulkPauseMut.mutate}
                    />
                  </div>
                </div>

                {u.configs.length === 0 ? (
                  <div className="muted-3" style={{ fontSize: 12.5 }}>
                    {t("srvAccess.noConfigsYet")}
                  </div>
                ) : (
                  <div className="stack" style={{ gap: 12 }}>
                    {groupByDevice(u.configs).map(([device, configs]) => (
                      <div key={device} className="stack" style={{ gap: 6 }}>
                        {/* дивайдер устройства + пауза/продолжение всех протоколов этого устройства */}
                        <div
                          className="rowflex"
                          style={{ justifyContent: "space-between", alignItems: "center", gap: 8 }}
                        >
                          <div
                            className="muted-3"
                            style={{
                              fontSize: 11.5,
                              fontWeight: 700,
                              textTransform: "uppercase",
                              letterSpacing: ".04em",
                              display: "flex",
                              alignItems: "center",
                              gap: 6,
                              minWidth: 0,
                            }}
                          >
                            <Icon name="devices" size={13} />
                            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {device}
                            </span>
                            <span style={{ opacity: 0.7 }}>· {configs.length}</span>
                          </div>
                          <GroupPauseBtn
                            configs={configs}
                            scope="device"
                            disabled={bulkPauseMut.isPending}
                            onRun={bulkPauseMut.mutate}
                          />
                        </div>
                        {configs.map((c) => (
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
                                {c.proto}
                                {c.status === "paused"
                                  ? ` · ${t("srvAccess.statusPaused")}`
                                  : c.status === "suspended"
                                    ? ` · ${t("srvAccess.statusTrafficLimit")}`
                                    : c.status === "revoked"
                                      ? ` · ${t("srvAccess.statusRevoked")}`
                                      : ""}
                              </div>
                            </div>
                            <div className="rowflex" style={{ flexWrap: "nowrap" }}>
                              {c.status !== "revoked" && (
                                <Btn
                                  variant="ghost"
                                  sm
                                  disabled={pauseMut.isPending}
                                  title={
                                    c.status === "active"
                                      ? t("srvAccess.pauseConfigTitle")
                                      : t("srvAccess.resumeConfigTitle")
                                  }
                                  onClick={() => pauseMut.mutate({ cid: c.id, pause: c.status === "active" })}
                                >
                                  <Icon name={c.status === "active" ? "stop" : "play"} size={15} />
                                </Btn>
                              )}
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
          title={t("srvAccess.renameConfigTitle")}
          onClose={() => setRename(null)}
          footer={
            <>
              <Btn onClick={() => setRename(null)}>{t("common.cancel")}</Btn>
              <Btn variant="primary" block disabled={renameMut.isPending} onClick={() => renameMut.mutate(rename)}>
                {t("common.save")}
              </Btn>
            </>
          }
        >
          <Field label={t("srvAccess.configNameLabel")}>
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
          title={t("srvAccess.revokeConfigTitle")}
          onClose={() => setRevoke(null)}
          footer={
            <>
              <Btn onClick={() => setRevoke(null)}>{t("common.cancel")}</Btn>
              <Btn variant="danger" block disabled={revokeMut.isPending} onClick={() => revokeMut.mutate(revoke.cid)}>
                {t("srvAccess.revokeConfirm")}
              </Btn>
            </>
          }
        >
          <p className="muted">{t("srvAccess.revokeConfigBody", { label: revoke.label })}</p>
        </Modal>
      )}
    </>
  );
}
