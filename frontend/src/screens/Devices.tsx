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
}: {
  d: Device;
  serverNames: Record<string, string>;
  onRemove: () => void;
}) {
  const configs = d.configs ?? [];
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
          <Icon name="devices" />
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
        <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 8 }}>Выданные конфиги</div>
        {configs.length === 0 ? (
          <span style={{ fontSize: 13, color: "var(--text-3)" }}>пока нет — добавьте на вкладке «Доступно»</span>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
            {configs.map((c) => (
              <span key={`${c.serverId}-${c.type}-${c.proto ?? ""}`} className="chip">
                <span className={`dot ${c.type}`} />
                {configLabel(c, serverNames[c.serverId] ?? "—")}
              </span>
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

  const addMut = useMutation({
    mutationFn: () => q.addDevice({ name: name.trim(), platform }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      setAdding(false);
      toast("Устройство добавлено");
    },
  });

  const removeMut = useMutation({
    mutationFn: (id: string) => q.removeDevice(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      setRemoving(null);
      toast("Устройство удалено");
    },
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

  return (
    <div className="screen">
      <ScreenHeader
        title="Мои устройства"
        sub="Куда вы ставите конфиги"
        action={
          <Btn variant="primary" onClick={openAdd}>
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
            <DeviceCard key={d.id} d={d} serverNames={serverNames} onRemove={() => setRemoving(d)} />
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
                  style={{ cursor: "pointer", padding: "8px 14px" }}
                  onClick={() => setPlatform(p)}
                >
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
    </div>
  );
}
