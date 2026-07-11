import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Btn, Icon, Modal, ScreenHeader, Spinner, Switch } from "../components/ui";
import { useT } from "../lib/i18n";
import * as q from "../lib/queries";
import type { Server, VpnType } from "../lib/types";
import { VPN_LABEL } from "../lib/types";
import { useNav } from "../nav";
import { useStore } from "../store";

const VPN_DOT: Record<VpnType, string> = {
  amnezia: "var(--amnezia)",
  openvpn: "var(--openvpn)",
  outline: "var(--outline)",
  hysteria2: "var(--hysteria2)",
};

const mono = (name: string) => (name || "?").slice(0, 2).toUpperCase();

interface PoolFormState {
  id: string | null;
  name: string;
  serverIds: string[];
}

export function AccessScreen() {
  const t = useT();
  const toast = useStore((s) => s.toast);
  const params = useNav((s) => s.params);
  const go = useNav((s) => s.go);
  const qc = useQueryClient();

  const { data: groups, isLoading: groupsLoading } = useQuery({
    queryKey: ["groups"],
    queryFn: q.listGroups,
  });
  const { data: pools, isLoading: poolsLoading } = useQuery({
    queryKey: ["pools"],
    queryFn: q.listPools,
  });
  const { data: servers, isLoading: serversLoading } = useQuery({
    queryKey: ["servers"],
    queryFn: q.listServers,
  });

  // Выбранная группа: из params.groupId, иначе первая.
  const [selectedGid, setSelectedGid] = useState<string | undefined>(params.groupId);
  const accGid = selectedGid || groups?.[0]?.id;
  const accGroup = groups?.find((g) => g.id === accGid);

  // Модалка пула
  const [poolForm, setPoolForm] = useState<PoolFormState | null>(null);
  const [delPool, setDelPool] = useState<{ id: string; name: string } | null>(null);

  const invalidateGroups = () => qc.invalidateQueries({ queryKey: ["groups"] });

  const togglePool = useMutation({
    mutationFn: (poolId: string) => q.toggleGroupPool(accGid!, poolId),
    onSuccess: invalidateGroups,
  });
  const toggleServer = useMutation({
    mutationFn: (serverId: string) => q.toggleGroupServer(accGid!, serverId),
    onSuccess: invalidateGroups,
  });
  const toggleServerVpn = useMutation({
    mutationFn: (v: { serverId: string; type: VpnType }) => q.toggleGroupServerVpn(accGid!, v.serverId, v.type),
    onSuccess: invalidateGroups,
  });

  const savePool = useMutation({
    mutationFn: (f: PoolFormState) =>
      f.id
        ? q.updatePool(f.id, { name: f.name, serverIds: f.serverIds })
        : q.createPool({ name: f.name, serverIds: f.serverIds }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pools"] });
      invalidateGroups();
      setPoolForm(null);
      toast(t("access.poolSaved"));
    },
  });
  const deletePool = useMutation({
    mutationFn: (id: string) => q.deletePool(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pools"] });
      invalidateGroups();
      setDelPool(null);
      toast(t("access.poolDeleted"));
    },
  });

  // Карта: serverId -> имена пулов, через которые он уже выдан группе.
  const viaPool = useMemo(() => {
    const map: Record<string, string[]> = {};
    if (!accGroup || !pools) return map;
    for (const pid of accGroup.access.pools || []) {
      const pl = pools.find((p) => p.id === pid);
      if (!pl) continue;
      for (const sid of pl.serverIds) {
        map[sid] = map[sid] || [];
        map[sid].push(pl.name);
      }
    }
    return map;
  }, [accGroup, pools]);

  // Эффективный доступ = серверы из пулов ∪ точечные серверы.
  const effCount = useMemo(() => {
    if (!accGroup || !pools) return 0;
    const set = new Set<string>();
    for (const pid of accGroup.access.pools || []) {
      const pl = pools.find((p) => p.id === pid);
      if (pl) {
        for (const id of pl.serverIds) set.add(id);
      }
    }
    for (const id of Object.keys(accGroup.access.servers || {})) set.add(id);
    return set.size;
  }, [accGroup, pools]);

  const accessSummary = accGroup
    ? effCount
      ? `${t("access.summaryHasAccess", { name: accGroup.name })} ${t("access.serversCount", { n: effCount })}`
      : t("access.summaryNoAccess", { name: accGroup.name })
    : "";

  const loading = groupsLoading || poolsLoading || serversLoading;

  return (
    <div className="stack">
      <ScreenHeader
        title={t("access.title")}
        sub={t("access.sub")}
        action={
          <Btn variant="primary" sm onClick={() => openPoolForm(null)}>
            <Icon name="plus" size={16} />
            {t("access.newPool")}
          </Btn>
        }
        onBack={() => go("groups")}
      />

      {loading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner />
        </div>
      ) : !groups || groups.length === 0 ? (
        <div className="empty">
          <h3>{t("access.noGroups")}</h3>
          <p className="muted">{t("access.noGroupsHint")}</p>
          <div style={{ marginTop: 16 }}>
            <Btn variant="primary" onClick={() => go("groups")}>
              {t("access.toGroups")}
            </Btn>
          </div>
        </div>
      ) : (
        <>
          {/* Выбор группы */}
          <div>
            <div style={{ fontSize: 12.5, color: "var(--text-3)", marginBottom: 9 }}>{t("access.configuringFor")}</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {groups.map((g) => {
                const active = g.id === accGid;
                return (
                  <button
                    key={g.id}
                    type="button"
                    onClick={() => setSelectedGid(g.id)}
                    style={{
                      height: 40,
                      padding: "0 16px",
                      borderRadius: 11,
                      cursor: "pointer",
                      font: "600 14px/1 var(--font)",
                      border: `1px solid ${active ? "var(--ink)" : "var(--border-strong)"}`,
                      background: active ? "var(--ink)" : "var(--surface)",
                      color: active ? "var(--on-ink)" : "var(--text)",
                    }}
                  >
                    {g.name}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Сводка */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 11,
              padding: "14px 16px",
              borderRadius: "var(--r)",
              background: "var(--accent-soft)",
            }}
          >
            <Icon name="access" size={20} />
            <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>{accessSummary}</span>
          </div>

          {/* Пулы серверов */}
          <div className="card">
            <div
              style={{
                font: "700 12px/1 var(--font)",
                letterSpacing: ".05em",
                textTransform: "uppercase",
                color: "var(--text-3)",
              }}
            >
              {t("access.serverPools")}
            </div>
            <div style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 6, maxWidth: 360 }}>
              {t("access.serverPoolsHint")}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 9, marginTop: 14 }}>
              {(pools || []).length === 0 ? (
                <div style={{ fontSize: 13, color: "var(--text-3)" }}>{t("access.noPools")}</div>
              ) : (
                (pools || []).map((pl) => {
                  const on = !!accGroup?.access.pools?.includes(pl.id);
                  return (
                    <div
                      key={pl.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 13,
                        padding: 13,
                        border: "1px solid var(--border)",
                        borderRadius: 13,
                      }}
                    >
                      <div
                        style={{
                          width: 38,
                          height: 38,
                          borderRadius: 10,
                          background: "var(--accent-soft)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          color: "var(--text)",
                          flex: "none",
                        }}
                      >
                        <Icon name="servers" size={19} />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 700, fontSize: 15 }}>{pl.name}</div>
                        <div style={{ fontSize: 12.5, color: "var(--text-3)" }}>
                          {t("access.serversInPoolCount", { n: pl.serverIds.length })}
                        </div>
                      </div>
                      <Btn sm onClick={() => openPoolForm(pl.id)}>
                        {t("access.composition")}
                      </Btn>
                      <Switch on={on} onClick={() => accGid && togglePool.mutate(pl.id)} />
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Отдельные серверы */}
          <div className="card">
            <div
              style={{
                font: "700 12px/1 var(--font)",
                letterSpacing: ".05em",
                textTransform: "uppercase",
                color: "var(--text-3)",
                marginBottom: 6,
              }}
            >
              {t("access.individualServers")}
            </div>
            <div style={{ fontSize: 12.5, color: "var(--text-3)", marginBottom: 14 }}>
              {t("access.individualServersHint")}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
              {(servers || []).length === 0 ? (
                <div style={{ fontSize: 13, color: "var(--text-3)" }}>{t("access.noServersYet")}</div>
              ) : (
                (servers || []).map((s) => {
                  const installed = s.vpns.filter((v) => v.installed);
                  const explicit = accGroup?.access.servers[s.id];
                  const byPoolNames = viaPool[s.id];
                  const byPool = !!byPoolNames && byPoolNames.length > 0;
                  const grantedAny = byPool || !!explicit;
                  return (
                    <div
                      key={s.id}
                      style={{
                        padding: 14,
                        border: "1px solid var(--border)",
                        borderRadius: 13,
                        background: byPool ? "var(--accent-soft)" : "var(--surface)",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <div
                          style={{
                            width: 38,
                            height: 38,
                            borderRadius: 10,
                            background: "var(--surface-2)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            fontWeight: 700,
                            fontSize: 13,
                            color: "var(--text-2)",
                            flex: "none",
                          }}
                        >
                          {mono(s.name)}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div
                            style={{
                              fontWeight: 700,
                              fontSize: 15,
                              whiteSpace: "nowrap",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            }}
                          >
                            {s.name}
                          </div>
                          <div
                            style={{
                              fontSize: 12,
                              color: "var(--text-3)",
                              whiteSpace: "nowrap",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            }}
                          >
                            {s.provider} · {s.location}
                          </div>
                          {/* метки — под названием, чтобы на узком экране не наезжать на имя/свитчер */}
                          {(byPool || installed.length === 0) && (
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                              {byPool && (
                                <span
                                  style={{
                                    fontSize: 11,
                                    fontWeight: 600,
                                    padding: "4px 9px",
                                    borderRadius: 999,
                                    background: "var(--accent-soft)",
                                    color: "var(--text-2)",
                                    maxWidth: "100%",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap",
                                  }}
                                >
                                  {t("access.viaPoolBadge", { name: byPoolNames![0] })}
                                </span>
                              )}
                              {installed.length === 0 && !byPool && (
                                <span style={{ fontSize: 12, color: "var(--text-3)" }}>{t("access.noVpn")}</span>
                              )}
                            </div>
                          )}
                        </div>
                        <Switch
                          on={grantedAny}
                          onClick={() =>
                            byPool
                              ? toast(t("access.accessViaPoolToast", { name: byPoolNames![0] }))
                              : accGid && toggleServer.mutate(s.id)
                          }
                        />
                      </div>
                      {grantedAny && installed.length > 0 && (
                        <div
                          style={{
                            display: "flex",
                            flexWrap: "wrap",
                            gap: 8,
                            marginTop: 13,
                            paddingTop: 13,
                            borderTop: "1px solid var(--border)",
                          }}
                        >
                          {installed.map((v) => {
                            const allowed = byPool ? true : explicit ? explicit.includes(v.type) : false;
                            return (
                              <button
                                key={v.type}
                                type="button"
                                onClick={() =>
                                  byPool
                                    ? toast(t("access.managedByPoolToast", { name: byPoolNames![0] }))
                                    : accGid && toggleServerVpn.mutate({ serverId: s.id, type: v.type })
                                }
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: 7,
                                  height: 34,
                                  padding: "0 13px",
                                  borderRadius: 9,
                                  cursor: byPool ? "default" : "pointer",
                                  font: "600 12.5px/1 var(--font)",
                                  border: `1px solid ${allowed ? VPN_DOT[v.type] : "var(--border)"}`,
                                  background: allowed ? VPN_DOT[v.type] : "var(--surface-2)",
                                  color: allowed ? "#fff" : "var(--text-3)",
                                }}
                              >
                                {allowed && <Icon name="check" size={14} />}
                                {VPN_LABEL[v.type]}
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </>
      )}

      {/* Модалка пула */}
      {poolForm && (
        <Modal
          title={poolForm.id ? t("access.poolComposition") : t("access.newPool")}
          onClose={() => setPoolForm(null)}
          footer={
            <>
              {poolForm.id && (
                <Btn
                  variant="danger"
                  onClick={() => {
                    const pl = pools?.find((p) => p.id === poolForm.id);
                    setDelPool({ id: poolForm.id!, name: pl?.name || poolForm.name });
                  }}
                  style={{ marginRight: "auto" }}
                >
                  <Icon name="trash" size={16} />
                  {t("common.delete")}
                </Btn>
              )}
              <Btn onClick={() => setPoolForm(null)}>{t("common.cancel")}</Btn>
              <Btn
                variant="primary"
                disabled={!poolForm.name.trim() || savePool.isPending}
                onClick={() => {
                  if (!poolForm.name.trim()) {
                    toast(t("access.enterName"));
                    return;
                  }
                  savePool.mutate({
                    id: poolForm.id,
                    name: poolForm.name.trim(),
                    serverIds: poolForm.serverIds,
                  });
                }}
              >
                {t("common.save")}
              </Btn>
            </>
          }
        >
          <div className="field">
            <label>{t("access.poolName")}</label>
            <input
              className="input"
              value={poolForm.name}
              placeholder={t("access.poolNamePlaceholder")}
              onChange={(e) => setPoolForm((f) => (f ? { ...f, name: e.target.value } : f))}
            />
          </div>
          <div className="field">
            <label>{t("access.serversInPool")}</label>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {(servers || []).length === 0 ? (
                <div style={{ fontSize: 13, color: "var(--text-3)" }}>{t("access.noServersYet")}</div>
              ) : (
                (servers || []).map((s: Server) => {
                  const checked = poolForm.serverIds.includes(s.id);
                  return (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => togglePoolServer(s.id)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 12,
                        padding: 11,
                        borderRadius: 12,
                        cursor: "pointer",
                        textAlign: "left",
                        border: `1.5px solid ${checked ? "var(--accent)" : "var(--border)"}`,
                        background: checked ? "var(--accent-soft)" : "var(--surface)",
                      }}
                    >
                      <div
                        style={{
                          width: 34,
                          height: 34,
                          borderRadius: 9,
                          background: "var(--surface-2)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontWeight: 700,
                          fontSize: 12,
                          color: "var(--text-2)",
                          flex: "none",
                        }}
                      >
                        {mono(s.name)}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: 14 }}>{s.name}</div>
                        <div style={{ fontSize: 11.5, color: "var(--text-3)" }}>{s.location}</div>
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
          </div>
        </Modal>
      )}

      {/* Подтверждение удаления пула */}
      {delPool && (
        <Modal
          title={t("access.deletePoolTitle")}
          onClose={() => setDelPool(null)}
          footer={
            <>
              <Btn onClick={() => setDelPool(null)}>{t("common.cancel")}</Btn>
              <Btn variant="danger" disabled={deletePool.isPending} onClick={() => deletePool.mutate(delPool.id)}>
                {t("common.delete")}
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ fontSize: 14, lineHeight: 1.45 }}>
            {t("access.deletePoolWarning", { name: delPool.name })}
          </p>
        </Modal>
      )}
    </div>
  );

  function openPoolForm(id: string | null) {
    const pl = id ? pools?.find((p) => p.id === id) : null;
    setPoolForm({
      id: id || null,
      name: pl?.name || "",
      serverIds: pl ? [...pl.serverIds] : [],
    });
  }

  function togglePoolServer(serverId: string) {
    setPoolForm((f) => {
      if (!f) return f;
      const ids = f.serverIds;
      return {
        ...f,
        serverIds: ids.includes(serverId) ? ids.filter((x) => x !== serverId) : [...ids, serverId],
      };
    });
  }
}
