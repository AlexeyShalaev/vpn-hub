import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Btn, Empty, Icon, Modal, ScreenHeader, Spinner, StatusBadge, VpnChip } from "../components/ui";
import { amneziaQrChunks, toDataUrl } from "../lib/qr";
import * as q from "../lib/queries";
import type { AvailableServer, VpnType } from "../lib/types";
import { PLATFORM_LABEL, VPN_DESC, VPN_LABEL } from "../lib/types";
import { useNav } from "../nav";
import { copyText, useStore } from "../store";

interface GetTarget {
  serverId: string;
  vpn: VpnType;
  serverName: string;
}

// Расширение файла с точкой (.conf / .ovpn / .vpn / .txt) для подписи кнопки скачивания.
function fileExt(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot > 0 ? filename.slice(dot) : "";
}

export function AvailableScreen() {
  const go = useNav((s) => s.go);

  const { data: servers, isLoading } = useQuery({
    queryKey: ["available"],
    queryFn: q.listAvailable,
    refetchInterval: 30000,
  });

  const [target, setTarget] = useState<GetTarget | null>(null);

  return (
    <div className="stack">
      <ScreenHeader title="Доступно мне" sub="Серверы из ваших групп" />

      {isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner />
        </div>
      ) : !servers || servers.length === 0 ? (
        <Empty
          title="Пока ничего не открыто"
          sub="Когда владелец добавит вас в группу и выдаст доступ, серверы появятся здесь."
        />
      ) : (
        <div className="stack">
          {servers.map((s) => (
            <ServerCard key={s.id} server={s} onGet={(vpn) => setTarget({ serverId: s.id, vpn, serverName: s.name })} />
          ))}
        </div>
      )}

      {target && (
        <GetConfigModal
          target={target}
          onClose={() => setTarget(null)}
          onNoDevices={() => {
            setTarget(null);
            go("devices");
          }}
        />
      )}
    </div>
  );
}

function ServerCard({ server, onGet }: { server: AvailableServer; onGet: (vpn: VpnType) => void }) {
  const mono = (server.name || "?").slice(0, 2).toUpperCase();
  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="card-row">
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 12,
            background: "var(--surface-2)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: 15,
            color: "var(--text-2)",
            flex: "none",
          }}
        >
          {mono}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 700, fontSize: 16.5, letterSpacing: "-.01em" }}>{server.name}</span>
            <StatusBadge status={server.status} />
          </div>
          <div style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 2 }}>
            {server.location} · из «{server.fromGroup}»
          </div>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
        {server.vpns.map((type) => (
          <div
            key={type}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "11px 13px",
              border: "1px solid var(--border)",
              borderRadius: 12,
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ marginBottom: 4 }}>
                <VpnChip type={type} />
              </div>
              <div style={{ fontSize: 12, color: "var(--text-3)" }}>{VPN_DESC[type]}</div>
            </div>
            <Btn variant="primary" sm onClick={() => onGet(type)}>
              Получить
            </Btn>
          </div>
        ))}
      </div>
    </div>
  );
}

function GetConfigModal({
  target,
  onClose,
  onNoDevices,
}: {
  target: GetTarget;
  onClose: () => void;
  onNoDevices: () => void;
}) {
  const toast = useStore((s) => s.toast);

  const { data: devices, isLoading: devicesLoading } = useQuery({
    queryKey: ["devices"],
    queryFn: q.listDevices,
  });

  const [step, setStep] = useState<"pick" | "config">("pick");
  const [deviceId, setDeviceId] = useState<string | undefined>(undefined);
  const [proto, setProto] = useState<string | undefined>(undefined);
  const [fmt, setFmt] = useState<string | undefined>(undefined);

  // НЕ автовыбираем устройство/протокол: на шаге выбора запрашиваем только СПИСОК (peek) —
  // без провижининга. Реальная выдача (создание клиента на сервере) — только на шаге config,
  // т.е. после явного «Показать конфиг».
  const peek = step !== "config";
  const { data: cfg, isFetching: cfgFetching } = useQuery({
    queryKey: ["config", target.serverId, target.vpn, deviceId, proto, peek],
    queryFn: () => q.genConfig({ serverId: target.serverId, vpn: target.vpn, deviceId, proto, peek }),
    enabled: !!deviceId,
  });

  const install = useMutation({
    mutationFn: () =>
      q.installConfig({
        serverId: target.serverId,
        vpn: target.vpn,
        deviceId: deviceId as string,
        proto,
      }),
    onSuccess: () => toast("Конфиг сохранён для устройства"),
  });

  const title = VPN_LABEL[target.vpn];
  const noDevices = !devicesLoading && (!devices || devices.length === 0);

  function downloadFile(text: string, filename: string) {
    try {
      // octet-stream форсирует сохранение файла (а не открытие инлайн) и сохраняет
      // расширение как есть — .conf / .ovpn / .vpn / .txt по формату протокола.
      const blob = new Blob([text], { type: "application/octet-stream" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 800);
      toast(`Файл ${filename} скачан`);
    } catch {
      toast("Не удалось скачать файл");
    }
  }

  const canShare = typeof navigator !== "undefined" && typeof navigator.share === "function";

  async function shareConfig(text: string, filename: string) {
    try {
      const file = new File([text], filename, { type: "text/plain" });
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], title: filename });
      } else {
        await navigator.share({ title: filename, text });
      }
    } catch {
      /* пользователь отменил или формат не поддержан — noop */
    }
  }

  // шаг 2 (загрузка): вход в config меняет запрос на peek=false → провижининг на сервере; ждём конфиг
  if (step === "config" && (cfgFetching || !cfg || (cfg.formats?.length ?? 0) === 0)) {
    return (
      <Modal
        title={title}
        onClose={onClose}
        footer={
          <Btn onClick={() => setStep("pick")}>
            <Icon name="back" size={16} />
            Назад
          </Btn>
        }
      >
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, padding: 28 }}>
          <Spinner />
          <span style={{ fontSize: 13.5, color: "var(--text-2)" }}>Готовим конфиг…</span>
        </div>
      </Modal>
    );
  }

  // ----- шаг 2: готовый конфиг -----
  if (step === "config" && cfg) {
    const formats = cfg.formats ?? [];
    const selected = formats.find((f) => f.id === fmt) ?? formats[0];
    const shownText = selected?.text ?? cfg.text;
    const shownQr = selected?.qr ?? cfg.uri;
    return (
      <Modal
        title={title}
        onClose={onClose}
        footer={
          <>
            <Btn onClick={() => setStep("pick")}>
              <Icon name="back" size={16} />
              Назад
            </Btn>
            {target.vpn === "amnezia" ? (
              <Btn variant="primary" block onClick={onClose}>
                Готово
              </Btn>
            ) : (
              <Btn variant="primary" block disabled={install.isPending} onClick={() => install.mutate()}>
                {install.isPending ? "Сохранение…" : "Сохранить для устройства"}
              </Btn>
            )}
          </>
        }
      >
        <div style={{ fontSize: 12.5, color: "var(--text-3)", marginBottom: 12 }}>сервер {target.serverName}</div>

        {formats.length > 1 && (
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            {formats.map((f) => {
              const active = f.id === (selected?.id ?? "");
              return (
                <button
                  key={f.id}
                  onClick={() => setFmt(f.id)}
                  style={{
                    flex: 1,
                    padding: "9px 11px",
                    borderRadius: 11,
                    cursor: "pointer",
                    textAlign: "left",
                    border: active ? "1.5px solid var(--ink)" : "1px solid var(--border-strong)",
                    background: active ? "var(--surface-2)" : "var(--surface)",
                    color: "var(--text)",
                  }}
                >
                  <div style={{ fontWeight: 700, fontSize: 13.5 }}>{f.label}</div>
                  {f.sub && <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>{f.sub}</div>}
                </button>
              );
            })}
          </div>
        )}

        {selected?.id === "amnezia" ? <AmneziaQrSeries config={selected.text} /> : <ConfigQr uri={shownQr} />}

        <div className="codebox" style={{ maxHeight: 96, overflow: "auto", marginBottom: 12 }}>
          {shownText}
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: selected && canShare ? 8 : 14 }}>
          <Btn block onClick={() => copyText(shownText, toast, "Скопировано")}>
            <Icon name="copy" size={16} />
            Копировать
          </Btn>
          {selected && (
            <Btn block onClick={() => downloadFile(selected.text, selected.filename)}>
              <Icon name="download" size={16} />
              {fileExt(selected.filename) ? `Скачать ${fileExt(selected.filename)}` : "Скачать"}
            </Btn>
          )}
        </div>
        {selected && canShare && (
          <div style={{ display: "flex", marginBottom: 14 }}>
            <Btn block onClick={() => shareConfig(selected.text, selected.filename)}>
              <Icon name="share" size={16} />
              Поделиться
            </Btn>
          </div>
        )}

        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 8,
            fontSize: 12.5,
            color: "var(--text-3)",
          }}
        >
          <Icon name="eye" size={15} />
          <span>{cfg.hint}</span>
        </div>
      </Modal>
    );
  }

  // ----- шаг 1: выбор устройства и протокола -----
  return (
    <Modal title={title} onClose={onClose}>
      <div style={{ fontSize: 12.5, color: "var(--text-3)", marginBottom: 16 }}>сервер {target.serverName}</div>

      {devicesLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 24 }}>
          <Spinner />
        </div>
      ) : noDevices ? (
        <Empty
          title="Нет устройств"
          sub="Сначала добавьте устройство, на которое поставите конфиг."
          action={
            <Btn variant="primary" onClick={onNoDevices}>
              К устройствам
            </Btn>
          }
        />
      ) : (
        <>
          <label
            style={{
              display: "block",
              fontSize: 13,
              fontWeight: 600,
              color: "var(--text-2)",
              marginBottom: 9,
            }}
          >
            На какое устройство
          </label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 18 }}>
            {(devices ?? []).map((d) => (
              <button
                key={d.id}
                type="button"
                className={`chip ${d.id === deviceId ? "selected" : ""}`}
                onClick={() => {
                  setDeviceId(d.id);
                  setProto(undefined);
                }}
                style={{ cursor: "pointer", padding: "8px 14px", gap: 7 }}
              >
                <Icon name={d.platform} size={15} />
                {d.name} · {PLATFORM_LABEL[d.platform]}
              </button>
            ))}
          </div>

          {cfg && cfg.protos.length > 1 && (
            <>
              <label
                style={{
                  display: "block",
                  fontSize: 13,
                  fontWeight: 600,
                  color: "var(--text-2)",
                  marginBottom: 9,
                }}
              >
                Протокол
              </label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 18 }}>
                {cfg.protos.map((p) => (
                  <button
                    key={p}
                    type="button"
                    className={`chip ${p === proto ? "selected" : ""}`}
                    onClick={() => setProto(p)}
                    style={{ cursor: "pointer", padding: "8px 14px" }}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </>
          )}

          {cfg && cfg.clients.length > 0 && (
            <>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 9,
                  marginBottom: 10,
                }}
              >
                <span
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: 7,
                    background: "var(--ink)",
                    color: "var(--on-ink)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    font: "700 12px/1 var(--font)",
                    flex: "none",
                  }}
                >
                  1
                </span>
                <span style={{ fontSize: 13.5, fontWeight: 600 }}>Установите приложение</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 18 }}>
                {cfg.clients.map((c) => (
                  <a
                    key={c.name}
                    href={c.url}
                    target="_blank"
                    rel="noopener"
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                      padding: "11px 13px",
                      border: "1px solid var(--border-strong)",
                      borderRadius: 12,
                      background: "var(--surface)",
                      textDecoration: "none",
                      color: "var(--text)",
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
                        fontSize: 14,
                        color: "var(--text-2)",
                        flex: "none",
                      }}
                    >
                      {c.name.slice(0, 1)}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 14 }}>{c.name}</div>
                      <div style={{ fontSize: 12, color: "var(--text-3)" }}>
                        {c.note ? `${c.store} · ${c.note}` : c.store}
                      </div>
                    </div>
                    <Icon name="link" size={16} />
                  </a>
                ))}
              </div>
            </>
          )}

          <Btn
            variant="primary"
            block
            disabled={!deviceId || cfgFetching || !cfg || ((cfg.protos?.length ?? 0) > 1 && !proto)}
            onClick={() => setStep("config")}
          >
            {cfgFetching ? (
              <Spinner />
            ) : !deviceId ? (
              "Выберите устройство"
            ) : (cfg?.protos?.length ?? 0) > 1 && !proto ? (
              "Выберите протокол"
            ) : (
              "Показать конфиг"
            )}
          </Btn>
        </>
      )}
    </Modal>
  );
}

// Серия QR для AmneziaVPN (формат vpn://): большие конфиги дробятся на несколько QR
// (протокол amnezia-client), кадры анимируются — приложение собирает их обратно.
function AmneziaQrSeries({ config }: { config: string }) {
  const chunks = useMemo(() => amneziaQrChunks(config), [config]);
  const multi = chunks.length > 1;
  const [zoom, setZoom] = useState(false);
  const [frame, setFrame] = useState(0);

  const { data: qrs, isError } = useQuery({
    queryKey: ["amz-qr", config],
    queryFn: () => Promise.all(chunks.map((c) => toDataUrl(c, 380, "L"))),
    enabled: !!config,
    retry: false,
  });
  const { data: qrsBig } = useQuery({
    queryKey: ["amz-qr-big", config],
    queryFn: () => Promise.all(chunks.map((c) => toDataUrl(c, 1000, "L"))),
    enabled: zoom && !!config,
    retry: false,
  });

  useEffect(() => {
    if (!multi) return;
    const t = setInterval(() => setFrame((f) => (f + 1) % chunks.length), 1000);
    return () => clearInterval(t);
  }, [multi, chunks.length]);

  const idx = frame % chunks.length;
  const src = qrs?.[idx];
  const bigSrc = qrsBig?.[idx] || src;

  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: 14 }}>
        {src ? (
          <>
            <button
              type="button"
              onClick={() => setZoom(true)}
              title="Нажмите, чтобы увеличить"
              style={{ border: "none", background: "none", padding: 0, cursor: "zoom-in", display: "inline-flex" }}
            >
              <img className="qr" src={src} alt="QR" style={{ imageRendering: "pixelated" }} />
            </button>
            <div className="muted-3" style={{ fontSize: 11.5, marginTop: 6, textAlign: "center", maxWidth: 280 }}>
              {multi
                ? `QR ${idx + 1} из ${chunks.length} · коды меняются сами — наведите камеру AmneziaVPN и держите`
                : "нажмите на QR, чтобы увеличить"}
            </div>
          </>
        ) : (
          <div
            className="qr"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              textAlign: "center",
              padding: 14,
              fontSize: 12,
              color: "var(--text-3)",
            }}
          >
            {isError ? "Не удалось построить QR — используйте файл или копирование" : <Spinner />}
          </div>
        )}
      </div>

      {zoom &&
        src &&
        createPortal(
          <div
            onClick={() => setZoom(false)}
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 3000,
              background: "rgba(0,0,0,.85)",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              padding: 20,
              cursor: "zoom-out",
            }}
          >
            <img
              src={bigSrc}
              alt="QR"
              style={{
                width: "min(92vw, 92vh)",
                height: "min(92vw, 92vh)",
                maxWidth: 680,
                maxHeight: 680,
                imageRendering: "pixelated",
                background: "#fff",
                borderRadius: 14,
                padding: 16,
              }}
            />
            <div
              style={{
                color: "rgba(255,255,255,.85)",
                marginTop: 16,
                fontSize: 13,
                textAlign: "center",
                maxWidth: 420,
              }}
            >
              {multi
                ? `QR ${idx + 1} из ${chunks.length} · держите камеру AmneziaVPN — кадры меняются автоматически`
                : "Нажмите в любом месте, чтобы закрыть"}
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

function ConfigQr({ uri }: { uri: string }) {
  const [zoom, setZoom] = useState(false);
  const { data: qrUrl, isError } = useQuery({
    queryKey: ["qr", uri],
    queryFn: () => toDataUrl(uri),
    enabled: !!uri,
    retry: false,
  });
  // высокое разрешение только когда открыли фуллскрин (плотный WG-код сканируется легче)
  const { data: qrBig } = useQuery({
    queryKey: ["qr-big", uri],
    queryFn: () => toDataUrl(uri, 1000),
    enabled: zoom && !!uri,
    retry: false,
  });

  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: 14 }}>
        {qrUrl ? (
          <>
            <button
              type="button"
              onClick={() => setZoom(true)}
              title="Нажмите, чтобы увеличить"
              style={{ border: "none", background: "none", padding: 0, cursor: "zoom-in", display: "inline-flex" }}
            >
              <img className="qr" src={qrUrl} alt="QR" style={{ imageRendering: "pixelated" }} />
            </button>
            <div className="muted-3" style={{ fontSize: 11.5, marginTop: 6 }}>
              нажмите на QR, чтобы увеличить
            </div>
          </>
        ) : (
          <div
            className="qr"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              textAlign: "center",
              padding: 14,
              fontSize: 12,
              color: "var(--text-3)",
            }}
          >
            {isError ? "Конфиг слишком большой для QR — используйте файл или копирование" : <Spinner />}
          </div>
        )}
      </div>

      {zoom &&
        qrUrl &&
        createPortal(
          <div
            onClick={() => setZoom(false)}
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 3000,
              background: "rgba(0,0,0,.85)",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              padding: 20,
              cursor: "zoom-out",
            }}
          >
            <img
              src={qrBig || qrUrl}
              alt="QR"
              style={{
                width: "min(92vw, 92vh)",
                height: "min(92vw, 92vh)",
                maxWidth: 680,
                maxHeight: 680,
                imageRendering: "pixelated",
                background: "#fff",
                borderRadius: 14,
                padding: 16,
              }}
            />
            <div style={{ color: "rgba(255,255,255,.85)", marginTop: 16, fontSize: 13 }}>
              Нажмите в любом месте, чтобы закрыть
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
