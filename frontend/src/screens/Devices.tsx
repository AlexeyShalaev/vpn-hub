import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Btn, Empty, Field, Icon, Modal, ScreenHeader, Spinner } from "../components/ui";
import * as q from "../lib/queries";
import type { Device, DeviceConfig } from "../lib/types";
import { PLATFORM_LABEL, VPN_LABEL } from "../lib/types";
import { useStore } from "../store";

type Platform = Device["platform"];

const PLATFORMS: Platform[] = ["ios", "android", "mac", "windows", "linux", "router"];

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
        <Btn variant="ghost" sm onClick={onRemove} aria-label="Удалить">
          <Icon name="trash" size={16} />
        </Btn>
      </div>
      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
        <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 10 }}>Выданные конфиги</div>
        {configs.length === 0 ? (
          <span style={{ fontSize: 13, color: "var(--text-3)" }}>пока нет — добавьте на вкладке «Доступно»</span>
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
                            <span title="Доступ приостановлен из-за лимита трафика — вернётся после сброса периода">
                              {" · приостановлен (лимит трафика)"}
                            </span>
                          ) : revoked ? (
                            " · отозван"
                          ) : (
                            ""
                          )}
                        </span>
                      </span>
                      <Btn
                        variant="ghost"
                        sm
                        aria-label="Отозвать конфиг"
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
      toast("Устройство добавлено");
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось добавить устройство"),
  });

  const removeMut = useMutation({
    mutationFn: (id: string) => q.removeDevice(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      qc.invalidateQueries({ queryKey: ["deviceLimit"] });
      setRemoving(null);
      toast("Устройство удалено");
    },
  });

  const revokeCfgMut = useMutation({
    mutationFn: ({ deviceId, config }: { deviceId: string; config: DeviceConfig; serverName: string }) =>
      q.removeConfig({ serverId: config.serverId, vpn: config.type, deviceId, proto: config.proto }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      setRevokingCfg(null);
      toast("Конфиг отозван");
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось отозвать конфиг"),
  });

  function openAdd() {
    setName("");
    setPlatform("ios");
    setAdding(true);
  }

  function save() {
    if (!name.trim()) {
      toast("Введите имя");
      return;
    }
    addMut.mutate();
  }

  const list = devices ?? [];
  const cap = limit?.limit ?? null;
  const used = list.length;
  const atLimit = cap != null && used >= cap;
  const limitHint = atLimit ? `Достигнут лимит устройств (${used}/${cap}). Обратитесь к владельцу.` : undefined;

  return (
    <div className="screen">
      <ScreenHeader
        title="Мои устройства"
        sub={
          cap != null ? (
            <>
              Куда вы ставите конфиги ·{" "}
              <span style={{ color: atLimit ? "var(--danger)" : "var(--text-2)", fontWeight: 600 }}>
                устройств {used} / {cap}
              </span>
            </>
          ) : (
            "Куда вы ставите конфиги"
          )
        }
        action={
          <Btn variant="primary" onClick={openAdd} disabled={atLimit} title={limitHint}>
            Добавить устройство
          </Btn>
        }
      />

      {isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 48 }}>
          <Spinner />
        </div>
      ) : list.length === 0 ? (
        <Empty
          title="Нет устройств"
          sub="Добавьте устройства, на которые будете ставить VPN-конфиги."
          action={
            <Btn variant="primary" onClick={openAdd}>
              Добавить устройство
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
          title="Новое устройство"
          onClose={() => setAdding(false)}
          footer={
            <>
              <Btn block onClick={() => setAdding(false)}>
                Отмена
              </Btn>
              <Btn variant="primary" block onClick={save} disabled={addMut.isPending}>
                Добавить
              </Btn>
            </>
          }
        >
          <Field label="Название">
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="например, Рабочий ноут"
              autoFocus
            />
          </Field>
          <Field label="Платформа">
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
          title="Удалить устройство?"
          onClose={() => setRemoving(null)}
          footer={
            <>
              <Btn block onClick={() => setRemoving(null)}>
                Отмена
              </Btn>
              <Btn variant="danger" block onClick={() => removeMut.mutate(removing.id)} disabled={removeMut.isPending}>
                Удалить
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ fontSize: 14 }}>
            «{removing.name}» будет удалено. Установленные на нём конфиги перестанут отслеживаться.
          </p>
        </Modal>
      )}

      {revokingCfg && (
        <Modal
          title="Отозвать конфиг?"
          onClose={() => setRevokingCfg(null)}
          footer={
            <>
              <Btn block onClick={() => setRevokingCfg(null)}>
                Отмена
              </Btn>
              <Btn
                variant="danger"
                block
                onClick={() => revokeCfgMut.mutate(revokingCfg)}
                disabled={revokeCfgMut.isPending}
              >
                {revokeCfgMut.isPending ? "Отзыв…" : "Отозвать"}
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ fontSize: 14 }}>
            «{configLabel(revokingCfg.config, revokingCfg.serverName)}» будет отозван: клиент снимется на сервере, и
            подключение по этому конфигу перестанет работать. Позже его можно выдать заново на вкладке «Доступно».
          </p>
        </Modal>
      )}
    </div>
  );
}
