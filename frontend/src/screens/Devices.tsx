import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Btn, Empty, Field, Icon, Modal, ScreenHeader, Spinner } from "../components/ui";
import { useT } from "../lib/i18n";
import * as q from "../lib/queries";
import type { Device, DeviceConfig } from "../lib/types";
import { PLATFORM_LABEL, VPN_LABEL } from "../lib/types";
import { useStore } from "../store";
import { fmtBytes } from "./Monitoring";

type Platform = Device["platform"];

const PLATFORMS: Platform[] = ["ios", "android", "mac", "windows", "linux", "router"];

// «Мой трафик за период по серверам»: израсходовано / лимит + пометка приостановки.
function TrafficUsageCard({ rows }: { rows: import("../lib/types").MyUsage[] }) {
  const t = useT();
  if (rows.length === 0) return null;
  return (
    <div
      style={{
        padding: "var(--pad)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r)",
        background: "var(--surface)",
        boxShadow: "var(--shadow)",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        marginBottom: 16,
      }}
    >
      <div
        style={{
          fontSize: 12,
          fontWeight: 700,
          letterSpacing: ".05em",
          textTransform: "uppercase",
          color: "var(--text-3)",
        }}
      >
        {t("devices.trafficUsageTitle")}
      </div>
      {rows.map((r) => {
        const pct = r.limit && r.limit > 0 ? Math.min(100, Math.round((r.used / r.limit) * 100)) : null;
        const col =
          r.suspended || (pct != null && pct >= 100)
            ? "var(--danger)"
            : pct != null && pct >= 80
              ? "#d97706"
              : "var(--text-2)";
        return (
          <div key={r.serverId} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <div className="rowflex" style={{ justifyContent: "space-between", gap: 8, fontSize: 13.5 }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.serverName}
                {r.suspended && (
                  <span className="badge warn" style={{ marginLeft: 8 }} title={t("devices.suspendedHint")}>
                    {t("devices.suspended")}
                  </span>
                )}
              </span>
              <span style={{ color: col, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", flex: "none" }}>
                {fmtBytes(r.used)}
                {r.limit != null ? ` / ${fmtBytes(r.limit)}` : ` · ${t("devices.noLimit")}`}
              </span>
            </div>
            {pct != null && (
              <div style={{ height: 6, borderRadius: 999, background: "var(--surface-2)", overflow: "hidden" }}>
                <div style={{ width: `${pct}%`, height: "100%", background: col }} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function configLabel(c: DeviceConfig, serverName: string) {
  return `${serverName} · ${c.proto || VPN_LABEL[c.type]}`;
}

function DeviceCard({
  d,
  serverNames,
  onRemove,
  onRevokeConfig,
}: {
  d: Device;
  serverNames: Record<string, string>;
  onRemove: () => void;
  onRevokeConfig: (c: DeviceConfig) => void;
}) {
  const t = useT();
  const configs = d.configs ?? [];
  // группируем выданные конфиги по серверу (порядок серверов — по первому появлению),
  // чтобы внутри устройства показать «сервер → его протоколы», а не плоский список.
  const groups: { serverId: string; serverName: string; items: DeviceConfig[] }[] = [];
  const byServer = new Map<string, DeviceConfig[]>();
  for (const c of configs) {
    let bucket = byServer.get(c.serverId);
    if (!bucket) {
      bucket = [];
      byServer.set(c.serverId, bucket);
      groups.push({ serverId: c.serverId, serverName: serverNames[c.serverId] ?? "—", items: bucket });
    }
    bucket.push(c);
  }
  return (
    <div
      style={{
        padding: "var(--pad)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r)",
        background: "var(--surface)",
        boxShadow: "var(--shadow)",
        display: "flex",
        flexDirection: "column",
        gap: 13,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div
          style={{
            width: 42,
            height: 42,
            borderRadius: 12,
            background: "var(--surface-2)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--text-2)",
            flex: "none",
          }}
        >
          <Icon name={d.platform} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontWeight: 700,
              fontSize: 15.5,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {d.name}
          </div>
          <div style={{ fontSize: 12, color: "var(--text-3)" }}>{PLATFORM_LABEL[d.platform]}</div>
        </div>
        <Btn variant="ghost" sm onClick={onRemove} aria-label={t("common.delete")}>
          <Icon name="trash" size={16} />
        </Btn>
      </div>
      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
        <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 10 }}>{t("devices.issuedConfigs")}</div>
        {configs.length === 0 ? (
          <span style={{ fontSize: 13, color: "var(--text-3)" }}>{t("devices.noConfigsYet")}</span>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
            {groups.map((g) => (
              <div key={g.serverId} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {/* дивайдер: имя сервера + линия — группировка протоколов по серверу */}
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 700,
                      color: "var(--text-2)",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      maxWidth: "82%",
                    }}
                  >
                    {g.serverName}
                  </span>
                  <span style={{ flex: 1, height: 1, background: "var(--border)" }} />
                </div>
                {g.items.map((c) => {
                  const suspended = c.status === "suspended";
                  const revoked = c.status && c.status !== "active" && !suspended;
                  const dimmed = revoked || suspended;
                  return (
                    <div
                      key={`${c.type}-${c.proto ?? ""}`}
                      className="rowflex"
                      style={{
                        justifyContent: "space-between",
                        gap: 8,
                        flexWrap: "nowrap",
                        paddingLeft: 2,
                        opacity: dimmed ? 0.55 : 1,
                      }}
                    >
                      <span className="rowflex" style={{ gap: 8, minWidth: 0, flexWrap: "nowrap" }}>
                        <span className={`dot ${c.type}`} style={{ flex: "none" }} />
                        <span
                          style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        >
                          {c.proto || VPN_LABEL[c.type]}
                          {suspended ? (
                            <span title={t("devices.suspendedTrafficHint")}>
                              {` · ${t("devices.suspendedTraffic")}`}
                            </span>
                          ) : revoked ? (
                            ` · ${t("devices.revoked")}`
                          ) : (
                            ""
                          )}
                        </span>
                      </span>
                      <Btn
                        variant="ghost"
                        sm
                        aria-label={t("devices.revokeConfig")}
                        style={{ flex: "none" }}
                        onClick={() => onRevokeConfig(c)}
                      >
                        <Icon name="trash" size={14} />
                      </Btn>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function DevicesScreen() {
  const t = useT();
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);

  const { data: devices, isLoading } = useQuery({
    queryKey: ["devices"],
    queryFn: q.listDevices,
  });
  const { data: limit } = useQuery({
    queryKey: ["deviceLimit"],
    queryFn: q.deviceLimit,
  });
  const { data: usage } = useQuery({
    queryKey: ["myUsage"],
    queryFn: q.myUsage,
    refetchInterval: 60000,
  });
  const { data: servers } = useQuery({
    queryKey: ["servers"],
    queryFn: q.listServers,
  });

  const serverNames = useMemo(() => {
    const map: Record<string, string> = {};
    for (const s of servers ?? []) map[s.id] = s.name;
    return map;
  }, [servers]);

  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState<Platform>("ios");
  const [removing, setRemoving] = useState<Device | null>(null);
  // отзыв одного своего конфига (снимет клиента на сервере + удалит запись)
  const [revokingCfg, setRevokingCfg] = useState<{ deviceId: string; config: DeviceConfig; serverName: string } | null>(
    null,
  );

  const addMut = useMutation({
    mutationFn: () => q.addDevice({ name: name.trim(), platform }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      qc.invalidateQueries({ queryKey: ["deviceLimit"] });
      setAdding(false);
      toast(t("devices.deviceAdded"));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("devices.addDeviceFailed")),
  });

  const removeMut = useMutation({
    mutationFn: (id: string) => q.removeDevice(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      qc.invalidateQueries({ queryKey: ["deviceLimit"] });
      setRemoving(null);
      toast(t("devices.deviceRemoved"));
    },
  });

  const revokeCfgMut = useMutation({
    mutationFn: ({ deviceId, config }: { deviceId: string; config: DeviceConfig; serverName: string }) =>
      q.removeConfig({ serverId: config.serverId, vpn: config.type, deviceId, proto: config.proto }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      setRevokingCfg(null);
      toast(t("devices.configRevoked"));
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("devices.revokeConfigFailed")),
  });

  function openAdd() {
    setName("");
    setPlatform("ios");
    setAdding(true);
  }

  function save() {
    if (!name.trim()) {
      toast(t("devices.enterName"));
      return;
    }
    addMut.mutate();
  }

  const list = devices ?? [];
  const cap = limit?.limit ?? null;
  const used = list.length;
  const atLimit = cap != null && used >= cap;
  const limitHint = atLimit ? t("devices.deviceLimitReached", { used, cap }) : undefined;

  return (
    <div className="screen">
      <ScreenHeader
        title={t("devices.title")}
        sub={
          cap != null ? (
            <>
              {t("devices.subtitle")} ·{" "}
              <span style={{ color: atLimit ? "var(--danger)" : "var(--text-2)", fontWeight: 600 }}>
                {t("devices.deviceCount", { used, cap })}
              </span>
            </>
          ) : (
            t("devices.subtitle")
          )
        }
        action={
          <Btn variant="primary" onClick={openAdd} disabled={atLimit} title={limitHint}>
            {t("devices.addDevice")}
          </Btn>
        }
      />

      <TrafficUsageCard rows={usage ?? []} />

      {isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 48 }}>
          <Spinner />
        </div>
      ) : list.length === 0 ? (
        <Empty
          title={t("devices.emptyTitle")}
          sub={t("devices.emptySub")}
          action={
            <Btn variant="primary" onClick={openAdd}>
              {t("devices.addDevice")}
            </Btn>
          }
        />
      ) : (
        <div className="grid">
          {list.map((d) => (
            <DeviceCard
              key={d.id}
              d={d}
              serverNames={serverNames}
              onRemove={() => setRemoving(d)}
              onRevokeConfig={(c) =>
                setRevokingCfg({ deviceId: d.id, config: c, serverName: serverNames[c.serverId] ?? "—" })
              }
            />
          ))}
        </div>
      )}

      {adding && (
        <Modal
          title={t("devices.newDevice")}
          onClose={() => setAdding(false)}
          footer={
            <>
              <Btn block onClick={() => setAdding(false)}>
                {t("common.cancel")}
              </Btn>
              <Btn variant="primary" block onClick={save} disabled={addMut.isPending}>
                {t("common.add")}
              </Btn>
            </>
          }
        >
          <Field label={t("devices.nameLabel")}>
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("devices.namePlaceholder")}
              autoFocus
            />
          </Field>
          <Field label={t("devices.platformLabel")}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {PLATFORMS.map((p) => (
                <button
                  key={p}
                  type="button"
                  className={`chip ${platform === p ? "selected" : ""}`}
                  style={{ cursor: "pointer", padding: "8px 14px", gap: 7 }}
                  onClick={() => setPlatform(p)}
                >
                  <Icon name={p} size={15} />
                  {PLATFORM_LABEL[p]}
                </button>
              ))}
            </div>
          </Field>
        </Modal>
      )}

      {removing && (
        <Modal
          title={t("devices.removeDeviceTitle")}
          onClose={() => setRemoving(null)}
          footer={
            <>
              <Btn block onClick={() => setRemoving(null)}>
                {t("common.cancel")}
              </Btn>
              <Btn variant="danger" block onClick={() => removeMut.mutate(removing.id)} disabled={removeMut.isPending}>
                {t("common.delete")}
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ fontSize: 14 }}>
            {t("devices.removeDeviceBody", { name: removing.name })}
          </p>
        </Modal>
      )}

      {revokingCfg && (
        <Modal
          title={t("devices.revokeConfigTitle")}
          onClose={() => setRevokingCfg(null)}
          footer={
            <>
              <Btn block onClick={() => setRevokingCfg(null)}>
                {t("common.cancel")}
              </Btn>
              <Btn
                variant="danger"
                block
                onClick={() => revokeCfgMut.mutate(revokingCfg)}
                disabled={revokeCfgMut.isPending}
              >
                {revokeCfgMut.isPending ? t("devices.revoking") : t("devices.revoke")}
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ fontSize: 14 }}>
            {t("devices.revokeConfigBody", { label: configLabel(revokingCfg.config, revokingCfg.serverName) })}
          </p>
        </Modal>
      )}
    </div>
  );
}
