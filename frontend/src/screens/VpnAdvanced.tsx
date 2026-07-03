import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Btn, Icon, Modal, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import * as q from "../lib/queries";
import type { VpnType } from "../lib/types";
import { VPN_LABEL } from "../lib/types";
import { copyText, useStore } from "../store";

const sectionTitle = {
  fontSize: 12,
  fontWeight: 700,
  letterSpacing: ".05em",
  textTransform: "uppercase" as const,
};
const chip = {
  fontSize: 11,
  fontWeight: 600,
  padding: "3px 8px",
  borderRadius: 999,
  background: "var(--surface-2)",
  color: "var(--text-2)",
};

export function VpnAdvancedModal({
  serverId,
  vtype,
  onClose,
}: {
  serverId: string;
  vtype: VpnType;
  onClose: () => void;
}) {
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["vpn-advanced", serverId, vtype],
    queryFn: () => q.vpnAdvanced(serverId, vtype),
    enabled: !!serverId,
  });
  const [revoke, setRevoke] = useState<{ cid: string; label: string } | null>(null);
  const [showExternal, setShowExternal] = useState(false);

  const externalQ = useQuery({
    queryKey: ["vpn-external", serverId, vtype],
    queryFn: () => q.vpnExternal(serverId, vtype),
    enabled: showExternal,
  });
  const externalFor = (proto: string) => externalQ.data?.external.find((e) => e.proto === proto)?.clients ?? [];

  const revokeMut = useMutation({
    mutationFn: (cid: string) => q.revokeServerClient(serverId, cid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vpn-advanced", serverId, vtype] });
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      qc.invalidateQueries({ queryKey: ["server-access", serverId] });
      setRevoke(null);
      toast("Конфиг отозван");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Ошибка"),
  });

  return (
    <>
      <Modal
        title={`${VPN_LABEL[vtype]} · подробно`}
        wide
        onClose={onClose}
        footer={
          <Btn block onClick={onClose}>
            Закрыть
          </Btn>
        }
      >
        {isLoading || !data ? (
          <div style={{ display: "flex", justifyContent: "center", padding: 30 }}>
            <Spinner />
          </div>
        ) : (
          <div className="stack" style={{ gap: 16 }}>
            {/* Контейнеры / протоколы */}
            <div>
              <div className="rowflex" style={{ justifyContent: "space-between", alignItems: "center" }}>
                <div className="muted-3" style={sectionTitle}>
                  Контейнеры / протоколы
                </div>
                {data.protocols.some((p) => p.externalClients > 0) && (
                  <Btn variant="ghost" sm onClick={() => setShowExternal((v) => !v)}>
                    {showExternal ? "Скрыть внешних" : "Показать внешних"}
                  </Btn>
                )}
              </div>
              <div className="stack" style={{ gap: 8, marginTop: 8 }}>
                {data.protocols.length === 0 && (
                  <div className="muted-3" style={{ fontSize: 12.5 }}>
                    Нет установленных протоколов.
                  </div>
                )}
                {data.protocols.map((p) => (
                  <div
                    key={p.proto}
                    className="stack"
                    style={{ border: "1px solid var(--border)", borderRadius: 12, padding: 12, gap: 8 }}
                  >
                    <div className="rowflex" style={{ justifyContent: "space-between" }}>
                      <div className="rowflex">
                        <span style={{ fontWeight: 700, fontSize: 14 }}>{p.label}</span>
                        <span
                          className={`badge ${p.state === "installed" ? "ok" : p.state === "error" ? "danger" : "neutral"}`}
                        >
                          {p.state}
                        </span>
                      </div>
                      {p.externalClients > 0 && <span style={chip}>+{p.externalClients} внешн.</span>}
                    </div>
                    <div className="mono muted-3" style={{ fontSize: 12 }}>
                      {p.container || "—"} · порт {p.port || "—"}
                    </div>
                    {p.error && (
                      <div style={{ fontSize: 12, color: "var(--danger)", wordBreak: "break-word" }}>
                        Ошибка: {p.error}
                      </div>
                    )}
                    {Object.entries(p.keys).map(([k, v]) => (
                      <div
                        key={k}
                        className="rowflex"
                        style={{
                          justifyContent: "space-between",
                          background: "var(--surface-2)",
                          borderRadius: 8,
                          padding: "6px 9px",
                          flexWrap: "nowrap",
                        }}
                      >
                        <div style={{ minWidth: 0 }}>
                          <div className="muted-3" style={{ fontSize: 11 }}>
                            {k}
                          </div>
                          <div className="mono" style={{ fontSize: 11.5, wordBreak: "break-all" }}>
                            {v}
                          </div>
                        </div>
                        <Btn variant="ghost" sm onClick={() => copyText(v, toast, "Скопировано")}>
                          <Icon name="copy" size={14} />
                        </Btn>
                      </div>
                    ))}
                    {p.params && Object.keys(p.params).length > 0 && (
                      <details>
                        <summary style={{ cursor: "pointer", fontSize: 12.5, color: "var(--text-2)" }}>
                          Параметры обфускации
                        </summary>
                        <div
                          className="codebox"
                          style={{ marginTop: 6, maxHeight: 160, overflow: "auto", fontSize: 12 }}
                        >
                          {Object.entries(p.params)
                            .map(([k, v]) => `${k} = ${v}`)
                            .join("\n")}
                        </div>
                      </details>
                    )}
                    {showExternal && p.externalClients > 0 && (
                      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                        <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 6 }}>
                          Внешние клиенты · {p.externalClients} (заведены вне панели)
                        </div>
                        {externalQ.isLoading ? (
                          <Spinner />
                        ) : (
                          <div className="stack" style={{ gap: 5 }}>
                            {externalFor(p.proto).map((c) => (
                              <div
                                key={c.id}
                                className="rowflex"
                                style={{ justifyContent: "space-between", flexWrap: "nowrap", gap: 8 }}
                              >
                                <span style={{ fontSize: 13, fontWeight: 600, minWidth: 0, wordBreak: "break-word" }}>
                                  {c.name || "(без имени)"}
                                </span>
                                <span
                                  className="mono muted-3"
                                  style={{ fontSize: 11, wordBreak: "break-all", maxWidth: "58%" }}
                                >
                                  {c.id}
                                </span>
                              </div>
                            ))}
                            {externalFor(p.proto).length === 0 && (
                              <span className="muted-3" style={{ fontSize: 12 }}>
                                —
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Пиры / клиенты */}
            <div>
              <div className="muted-3" style={sectionTitle}>
                Пиры / клиенты ({data.clients.length})
              </div>
              <div className="stack" style={{ gap: 6, marginTop: 8 }}>
                {data.clients.length === 0 && (
                  <div className="muted-3" style={{ fontSize: 12.5 }}>
                    Выданных конфигов ещё нет.
                  </div>
                )}
                {data.clients.map((c) => (
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
                      <div className="muted-3" style={{ fontSize: 11.5 }}>
                        {c.user} · {c.device} · {c.proto}
                        {c.clientIp ? ` · ${c.clientIp}` : ""}
                        {c.status !== "active" ? " · отозван" : ""}
                      </div>
                      <div className="muted-3 mono" style={{ fontSize: 11, wordBreak: "break-all", opacity: 0.8 }}>
                        {c.clientId}
                      </div>
                    </div>
                    <div className="rowflex" style={{ flexWrap: "nowrap" }}>
                      <Btn variant="ghost" sm onClick={() => copyText(c.clientId, toast, "ID скопирован")}>
                        <Icon name="copy" size={15} />
                      </Btn>
                      <Btn variant="ghost" sm onClick={() => setRevoke({ cid: c.id, label: c.clientName || c.device })}>
                        <Icon name="trash" size={15} />
                      </Btn>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </Modal>

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
            Конфиг «{revoke.label}» будет удалён на сервере — пользователь потеряет доступ через него.
          </p>
        </Modal>
      )}
    </>
  );
}
