import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Btn, Icon, Modal, ScreenHeader, Spinner, StatusBadge } from "../components/ui";
import * as q from "../lib/queries";
import type { Protocol, Server, Vpn, VpnType } from "../lib/types";
import { PROTO_LABEL, PROTO_STATE_LABEL, VPN_DESC, VPN_LABEL } from "../lib/types";
import { useNav } from "../nav";
import { copyText, useStore } from "../store";
import { ServerAccessSections } from "./ServerAccess";
import { VpnAdvancedModal } from "./VpnAdvanced";

const VPN_TYPES: VpnType[] = ["amnezia", "openvpn", "outline"];

export function ServerDetailScreen() {
  const serverId = useNav((s) => s.params.serverId) || "";
  const go = useNav((s) => s.go);
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();

  const [reveal, setReveal] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmRemoveVpn, setConfirmRemoveVpn] = useState<VpnType | null>(null);
  const [advancedVpn, setAdvancedVpn] = useState<VpnType | null>(null);

  const serverQ = useQuery({
    queryKey: ["server", serverId],
    queryFn: () => q.getServer(serverId),
    enabled: !!serverId,
    // во время установки опрашиваем чаще, чтобы прогресс обновлялся почти вживую
    refetchInterval: (query) => {
      const s = query.state.data as Server | undefined;
      // свежесозданный сервер (ещё не проверен) — ждём авто-пинг/синк, опрашиваем чаще
      if (s?.status === "unknown") return 2500;
      return s?.protocols?.some((p) => p.state === "installing") ? 4000 : 15000;
    },
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["server", serverId] });
    qc.invalidateQueries({ queryKey: ["servers"] });
  };

  const checkMut = useMutation({
    mutationFn: () => q.checkServer(serverId),
    onSuccess: (s) => {
      invalidate();
      toast(s.status === "online" ? `Сервер онлайн · ${s.latency ?? "—"}` : "Сервер недоступен");
    },
    onError: () => toast("Не удалось проверить сервер"),
  });

  const syncMut = useMutation({
    mutationFn: () => q.syncServer(serverId),
    onSuccess: () => {
      invalidate();
      toast("Состояние сервера синхронизировано");
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось синхронизировать"),
  });

  const opMut = useMutation({
    mutationFn: ({ type, op }: { type: VpnType; op: string }) => q.vpnOp(serverId, type, op),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      const label = VPN_LABEL[vars.type];
      const msg =
        vars.op === "install"
          ? // установка любого вендора идёт в фоне (mark_installing + schedule_install),
            // ответ приходит мгновенно — сообщаем о старте, а не о завершении
            `${label}: установка запущена — займёт пару минут`
          : vars.op === "remove"
            ? `${label} удалён`
            : vars.op === "start"
              ? `${label} запущен`
              : `${label} остановлен`;
      toast(msg);
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Ошибка операции"),
  });

  const fixMut = useMutation({
    mutationFn: ({ type }: { type: VpnType }) => q.vpnFix(serverId, type),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      // фикс устраняет причину и запускает переустановку в фоне — сообщаем о старте
      toast(`${VPN_LABEL[vars.type]}: исправление запущено — займёт пару минут`);
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось запустить исправление"),
  });

  const deleteMut = useMutation({
    mutationFn: () => q.deleteServer(serverId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["servers"] });
      toast("Сервер удалён");
      go("servers");
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось удалить сервер"),
  });

  if (serverQ.isLoading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
        <Spinner />
      </div>
    );
  }
  if (serverQ.isError || !serverQ.data) {
    return (
      <div className="stack">
        <ScreenHeader title="Сервер" onBack={() => go("servers")} />
        <div className="card muted">Сервер не найден.</div>
      </div>
    );
  }

  const server: Server = serverQ.data;
  const checking = checkMut.isPending;
  const online = server.status === "online";
  const authLabel = server.auth === "key" ? "SSH-ключ" : "Пароль";
  const secretShown = reveal ? server.secret : "•".repeat(Math.max(6, server.secret.length || 6));

  const vpnByType = (t: VpnType): Vpn =>
    server.vpns.find((v) => v.type === t) ?? { type: t, installed: false, running: false, port: "" };
  const protosByVendor = (t: VpnType): Protocol[] => (server.protocols ?? []).filter((p) => p.vendor === t);
  const syncing = syncMut.isPending;

  return (
    <div className="stack">
      <ScreenHeader
        title={server.name}
        sub={`${server.provider} · ${server.location}`}
        onBack={() => go("servers")}
        action={
          <div className="rowflex" style={{ flexWrap: "nowrap" }}>
            <Btn sm onClick={() => go("serverForm", { serverId })}>
              <Icon name="edit" size={16} />
              Изменить
            </Btn>
            <Btn variant="danger" sm onClick={() => setConfirmDelete(true)}>
              <Icon name="trash" size={16} />
            </Btn>
          </div>
        }
      />

      {/* Статус */}
      <div className="card">
        <div className="rowflex" style={{ justifyContent: "space-between" }}>
          <div className="rowflex">
            <StatusBadge status={server.status} />
            {server.latency && (
              <span className="muted" style={{ fontSize: 13 }}>
                {server.latency}
              </span>
            )}
            <span className="muted-3" style={{ fontSize: 13 }}>
              проверен: {server.lastCheck || "ещё не проверялся"}
            </span>
          </div>
          <div className="rowflex" style={{ flexWrap: "nowrap" }}>
            <Btn sm onClick={() => syncMut.mutate()} disabled={syncing}>
              {syncing ? <Spinner /> : <Icon name="refresh" size={16} />}
              {syncing ? "Синк…" : "Синхронизировать"}
            </Btn>
            <Btn sm onClick={() => checkMut.mutate()} disabled={checking}>
              {checking ? <Spinner /> : <Icon name="refresh" size={16} />}
              {checking ? "Проверка…" : "Проверить"}
            </Btn>
          </div>
        </div>
      </div>

      {/* SSH */}
      <div className="card stack">
        <div
          className="muted-3"
          style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
        >
          Подключение SSH
        </div>
        <div className="grid">
          <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px" }}>
            <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 4 }}>
              IP-адрес
            </div>
            <div className="rowflex" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
              <span className="mono" style={{ fontSize: 13.5 }}>
                {server.ip}
              </span>
              <Btn variant="ghost" sm onClick={() => copyText(server.ip, toast, "IP скопирован")}>
                <Icon name="copy" size={15} />
              </Btn>
            </div>
          </div>

          <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px" }}>
            <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 4 }}>
              Пользователь · порт
            </div>
            <span className="mono" style={{ fontSize: 13.5 }}>
              {server.sshUser} : {server.sshPort}
            </span>
          </div>

          <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px" }}>
            <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 4 }}>
              {authLabel}
            </div>
            <div className="rowflex" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
              <span className="mono" style={{ fontSize: 13.5, minWidth: 0, wordBreak: "break-all" }}>
                {secretShown}
              </span>
              <Btn variant="ghost" sm onClick={() => setReveal((r) => !r)}>
                <Icon name="eye" size={15} />
                {reveal ? "Скрыть" : "Показать"}
              </Btn>
            </div>
          </div>
        </div>
      </div>

      {/* VPN ПО */}
      <div className="card stack">
        <div
          className="muted-3"
          style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
        >
          VPN ПО на сервере
        </div>
        <div className="stack" style={{ gap: 10 }}>
          {VPN_TYPES.map((type) => {
            const v = vpnByType(type);
            const protos = protosByVendor(type);
            const installing = protos.some((p) => p.state === "installing");
            const errored = protos.find((p) => p.state === "error");
            const rem = errored?.remediation ?? null;
            const busy =
              (opMut.isPending && opMut.variables?.type === type) ||
              (fixMut.isPending && fixMut.variables?.type === type);
            const runLabel = installing
              ? "устанавливается…"
              : !v.installed
                ? "не установлен"
                : v.running
                  ? "работает"
                  : "остановлен";
            const runClass = installing ? "neutral" : v.installed && v.running ? "ok" : "neutral";
            return (
              <div
                key={type}
                className="card-row"
                style={{ border: "1px solid var(--border)", borderRadius: 13, padding: 13 }}
              >
                <div
                  style={{
                    width: 38,
                    height: 38,
                    borderRadius: 10,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flex: "none",
                    background: "var(--surface-2)",
                  }}
                >
                  <span className={`dot ${type}`} style={{ width: 10, height: 10 }} />
                </div>
                <div
                  style={{ flex: 1, minWidth: 0, cursor: v.installed ? "pointer" : "default" }}
                  onClick={v.installed ? () => setAdvancedVpn(type) : undefined}
                >
                  <div className="rowflex">
                    <span style={{ fontWeight: 700, fontSize: 15 }}>{VPN_LABEL[type]}</span>
                    <span className={`badge ${runClass}`}>{runLabel}</span>
                    {v.installed && (
                      <span className="muted-3" style={{ display: "inline-flex" }} title="Подробнее">
                        <Icon name="chevron" size={14} />
                      </span>
                    )}
                  </div>
                  <div className="muted-3" style={{ fontSize: 12.5, marginTop: 2 }}>
                    {VPN_DESC[type]}
                  </div>
                  {protos.length > 0 && (
                    <div className="rowflex" style={{ gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                      {protos.map((p) => (
                        <span key={p.proto} className={`badge ${p.state === "installed" ? "ok" : "neutral"}`}>
                          {PROTO_LABEL[p.proto] ?? p.proto} · {PROTO_STATE_LABEL[p.state]}
                          {p.externalClients > 0 ? ` · +${p.externalClients} внешн.` : ""}
                        </span>
                      ))}
                    </div>
                  )}
                  {errored && (
                    <div style={{ marginTop: 6 }} onClick={(e) => e.stopPropagation()}>
                      {rem ? (
                        <div className="stack" style={{ gap: 3 }}>
                          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--danger)" }}>{rem.title}</div>
                          <div className="muted-3" style={{ fontSize: 11.5, wordBreak: "break-word" }}>
                            {rem.explanation}
                          </div>
                          {rem.manualSteps.length > 0 && (
                            <ol
                              className="muted-3"
                              style={{ fontSize: 11.5, margin: "2px 0 0", paddingLeft: 16, lineHeight: 1.5 }}
                            >
                              {rem.manualSteps.map((step, i) => (
                                <li key={i} style={{ wordBreak: "break-word" }}>
                                  {step}
                                </li>
                              ))}
                            </ol>
                          )}
                        </div>
                      ) : (
                        errored.error && (
                          <div className="muted-3" style={{ fontSize: 11.5, wordBreak: "break-word" }}>
                            Ошибка: {errored.error}
                          </div>
                        )
                      )}
                    </div>
                  )}
                </div>

                {busy ? (
                  <Spinner />
                ) : installing ? (
                  <div className="rowflex" style={{ flexWrap: "nowrap", gap: 6 }}>
                    <Spinner />
                    <span className="muted-3" style={{ fontSize: 12.5 }}>
                      Устанавливается…
                    </span>
                  </div>
                ) : !v.installed ? (
                  <div className="rowflex" style={{ flexWrap: "nowrap", gap: 6 }}>
                    {rem?.canAutoFix && (
                      <Btn variant="primary" sm onClick={() => fixMut.mutate({ type })}>
                        {rem.fixLabel ?? "Исправить"}
                      </Btn>
                    )}
                    <Btn
                      variant={rem?.canAutoFix ? "ghost" : "primary"}
                      sm
                      onClick={() => opMut.mutate({ type, op: "install" })}
                    >
                      Установить
                    </Btn>
                  </div>
                ) : (
                  <div className="rowflex" style={{ flexWrap: "nowrap", gap: 6 }}>
                    {/* частичный сбой вендора: один протокол установлен, другой упал с auto-ошибкой —
                        кнопка фикса должна быть доступна и в installed-состоянии */}
                    {rem?.canAutoFix && (
                      <Btn variant="primary" sm onClick={() => fixMut.mutate({ type })}>
                        {rem.fixLabel ?? "Исправить"}
                      </Btn>
                    )}
                    <Btn sm disabled={!online} onClick={() => opMut.mutate({ type, op: v.running ? "stop" : "start" })}>
                      {v.running ? "Стоп" : "Запустить"}
                    </Btn>
                    <Btn variant="ghost" sm onClick={() => setConfirmRemoveVpn(type)}>
                      <Icon name="trash" size={15} />
                    </Btn>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <ServerAccessSections serverId={serverId} />

      {advancedVpn && <VpnAdvancedModal serverId={serverId} vtype={advancedVpn} onClose={() => setAdvancedVpn(null)} />}

      {confirmDelete && (
        <Modal
          title="Удалить сервер?"
          onClose={() => setConfirmDelete(false)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setConfirmDelete(false)}>
                Отмена
              </Btn>
              <Btn variant="danger" disabled={deleteMut.isPending} onClick={() => deleteMut.mutate()}>
                Удалить
              </Btn>
            </>
          }
        >
          <p className="muted">Сервер пропадёт из пулов и групповых доступов. Действие необратимо.</p>
        </Modal>
      )}

      {confirmRemoveVpn && (
        <Modal
          title={`Удалить ${VPN_LABEL[confirmRemoveVpn]}?`}
          onClose={() => setConfirmRemoveVpn(null)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setConfirmRemoveVpn(null)}>
                Отмена
              </Btn>
              <Btn
                variant="danger"
                disabled={opMut.isPending}
                onClick={() => {
                  const type = confirmRemoveVpn;
                  setConfirmRemoveVpn(null);
                  opMut.mutate({ type, op: "remove" });
                }}
              >
                Удалить
              </Btn>
            </>
          }
        >
          <p className="muted">ПО будет помечено как не установленное, доступы к нему снимутся.</p>
        </Modal>
      )}
    </div>
  );
}
