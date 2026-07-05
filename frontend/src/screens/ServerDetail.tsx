import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Btn, Icon, Modal, ScreenHeader, Spinner, StatusBadge } from "../components/ui";
import * as q from "../lib/queries";
import type { Protocol, Server, Vpn, VpnType } from "../lib/types";
import { PROTO_STATE_LABEL, VENDOR_PROTOCOLS, VPN_DESC, VPN_ICON, VPN_LABEL } from "../lib/types";
import { vpnLogo } from "../lib/vpnLogos";
import { useNav } from "../nav";
import { copyText, useStore } from "../store";
import { ServerAccessSections } from "./ServerAccess";
import { VpnAdvancedModal } from "./VpnAdvanced";

const VPN_TYPES: VpnType[] = ["amnezia", "openvpn", "outline", "hysteria2"];

export function ServerDetailScreen() {
  const serverId = useNav((s) => s.params.serverId) || "";
  const go = useNav((s) => s.go);
  const toast = useStore((s) => s.toast);
  const theme = useStore((s) => s.theme);
  const qc = useQueryClient();

  const [reveal, setReveal] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [advancedVpn, setAdvancedVpn] = useState<VpnType | null>(null);
  // подтверждение сноса всего вендора (все его протоколы + доступы разом)
  const [confirmRemoveVpn, setConfirmRemoveVpn] = useState<VpnType | null>(null);
  // модалка выбора протоколов для установки/докачки: активный вендор + отмеченные id
  const [addProtoVendor, setAddProtoVendor] = useState<VpnType | null>(null);
  const [checkedProtos, setCheckedProtos] = useState<Set<string>>(new Set());
  // подтверждение удаления одного протокола (сносит контейнер + отзывает его конфиги)
  const [confirmRemoveProto, setConfirmRemoveProto] = useState<{
    vendor: VpnType;
    proto: string;
    label: string;
  } | null>(null);

  const serverQ = useQuery({
    queryKey: ["server", serverId],
    queryFn: () => q.getServer(serverId),
    enabled: !!serverId,
    // прогресс/статус приходят пушем по SSE (см. lib/events); поллинг оставлен СТРАХОВКОЙ
    // на случай тихого обрыва SSE (буферизация прокси / потеря сети) — частоты снижены.
    refetchInterval: (query) => {
      const s = query.state.data as Server | undefined;
      // свежесозданный сервер (ещё не проверен) — ждём авто-пинг/синк, опрашиваем чуть чаще
      if (s?.status === "unknown") return 10000;
      return s?.protocols?.some((p) => p.state === "installing") ? 10000 : 60000;
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
    mutationFn: ({ type, op, protos }: { type: VpnType; op: string; protos?: string[] }) =>
      q.vpnOp(serverId, type, op, protos),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      const label = VPN_LABEL[vars.type];
      const msg =
        vars.op === "install"
          ? // установка идёт в фоне (mark_installing + schedule_install),
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

  const removeProtoMut = useMutation({
    mutationFn: ({ proto }: { proto: string; label: string }) => q.removeProtocol(serverId, proto),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      toast(`${vars.label} удалён — связанные конфиги отозваны`);
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось удалить протокол"),
  });

  // свитчер отдельного протокола: временно остановить / снова запустить его контейнер
  const protoOpMut = useMutation({
    mutationFn: ({ proto, op }: { proto: string; label: string; op: string }) => q.protocolOp(serverId, proto, op),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      toast(`${vars.label} ${vars.op === "start" ? "запущен" : "остановлен"}`);
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
            const catalog = VENDOR_PROTOCOLS[type]; // все протоколы вендора (для выбора/докачки)
            const notInstalled = catalog.filter((pr) => !protos.find((x) => x.proto === pr.id)?.installed);
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
                className="stack"
                style={{
                  border: `1px solid ${errored ? "var(--danger)" : "var(--border)"}`,
                  borderRadius: 13,
                  padding: 13,
                  gap: 12,
                }}
              >
                {/* Шапка: иконка + имя вендора + агрегатный статус (клик — расширенные настройки) */}
                <div className="rowflex" style={{ gap: 12, flexWrap: "nowrap", alignItems: "flex-start" }}>
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
                      color: `var(--${type})`,
                    }}
                  >
                    {vpnLogo(type, theme) ? (
                      <img
                        src={vpnLogo(type, theme)}
                        alt={VPN_LABEL[type]}
                        width={26}
                        height={26}
                        style={{ objectFit: "contain", display: "block" }}
                      />
                    ) : (
                      <Icon name={VPN_ICON[type]} size={20} />
                    )}
                  </div>
                  <div
                    style={{ flex: 1, minWidth: 0, cursor: v.installed ? "pointer" : "default" }}
                    onClick={v.installed ? () => setAdvancedVpn(type) : undefined}
                  >
                    <div className="rowflex" style={{ gap: 8 }}>
                      <span style={{ fontWeight: 700, fontSize: 15 }}>{VPN_LABEL[type]}</span>
                      <span className={`badge ${runClass}`}>{runLabel}</span>
                      {v.installed && (
                        <span className="muted-3" style={{ display: "inline-flex" }} title="Расширенные настройки">
                          <Icon name="chevron" size={14} />
                        </span>
                      )}
                    </div>
                    <div className="muted-3" style={{ fontSize: 12.5, marginTop: 2 }}>
                      {VPN_DESC[type]}
                    </div>
                  </div>
                </div>

                {/* Протоколы: ровный список со статус-точкой и пер-протокольными действиями */}
                {(v.installed || installing) && (
                  <div
                    className="stack"
                    style={{ gap: 2, borderTop: "1px solid var(--border)", paddingTop: 10 }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div
                      className="muted-3"
                      style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".04em", textTransform: "uppercase" }}
                    >
                      Протоколы
                    </div>
                    {catalog.map((pr) => {
                      const p = protos.find((x) => x.proto === pr.id);
                      const st = p?.state ?? "absent";
                      const inst = p?.installed ?? false;
                      const running = p?.running ?? false;
                      const ext = p?.externalClients ?? 0;
                      // у установленного показываем работает/остановлен, иначе — состояние установки
                      const stateText = inst ? (running ? "работает" : "остановлен") : (PROTO_STATE_LABEL[st] ?? st);
                      const dotColor =
                        st === "installing"
                          ? "var(--warn)"
                          : inst && running
                            ? "var(--ok)"
                            : inst
                              ? "var(--warn)"
                              : "var(--border-strong)";
                      return (
                        <div
                          key={pr.id}
                          className="rowflex"
                          style={{
                            justifyContent: "space-between",
                            gap: 8,
                            flexWrap: "nowrap",
                            minHeight: 34,
                            opacity: inst || st === "installing" ? 1 : 0.55,
                          }}
                        >
                          <span className="rowflex" style={{ gap: 8, minWidth: 0, flexWrap: "nowrap" }}>
                            <span
                              style={{
                                width: 7,
                                height: 7,
                                borderRadius: 999,
                                flex: "none",
                                background: dotColor,
                              }}
                            />
                            <span
                              style={{
                                fontSize: 13,
                                fontWeight: 600,
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                              }}
                            >
                              {pr.label}
                            </span>
                            <span className="muted-3" style={{ fontSize: 11.5, whiteSpace: "nowrap", flex: "none" }}>
                              {stateText}
                              {ext > 0 ? ` · +${ext} внешн.` : ""}
                            </span>
                          </span>
                          {inst && (
                            <div className="rowflex" style={{ flexWrap: "nowrap", gap: 6, flex: "none" }}>
                              <Btn
                                sm
                                disabled={!online || protoOpMut.isPending}
                                onClick={() =>
                                  protoOpMut.mutate({ proto: pr.id, label: pr.label, op: running ? "stop" : "start" })
                                }
                              >
                                {running ? "Стоп" : "Запустить"}
                              </Btn>
                              <Btn
                                variant="ghost"
                                sm
                                title={`Удалить протокол ${pr.label}`}
                                disabled={removeProtoMut.isPending}
                                onClick={() => setConfirmRemoveProto({ vendor: type, proto: pr.id, label: pr.label })}
                              >
                                <Icon name="trash" size={13} />
                              </Btn>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Диагностика ошибки установки/сбоя протокола */}
                {errored && (
                  <div onClick={(e) => e.stopPropagation()}>
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

                {/* Действия по вендору: докачать / остановить всё / удалить ПО целиком */}
                <div
                  className="rowflex"
                  style={{ gap: 8, borderTop: "1px solid var(--border)", paddingTop: 11 }}
                  onClick={(e) => e.stopPropagation()}
                >
                  {installing ? (
                    <span className="rowflex" style={{ gap: 8 }}>
                      <Spinner />
                      <span className="muted-3" style={{ fontSize: 12.5 }}>
                        Устанавливается…
                      </span>
                    </span>
                  ) : busy ? (
                    <Spinner />
                  ) : (
                    <>
                      {/* fix доступен и в installed-состоянии (частичный сбой: один протокол упал) */}
                      {rem?.canAutoFix && (
                        <Btn variant="primary" sm onClick={() => fixMut.mutate({ type })}>
                          {rem.fixLabel ?? "Исправить"}
                        </Btn>
                      )}
                      {notInstalled.length > 0 && (
                        <Btn
                          variant={v.installed || rem?.canAutoFix ? "ghost" : "primary"}
                          sm
                          onClick={() => {
                            setCheckedProtos(new Set(notInstalled.map((p) => p.id)));
                            setAddProtoVendor(type);
                          }}
                        >
                          {v.installed ? "+ Протоколы" : "Установить"}
                        </Btn>
                      )}
                      {v.installed && (
                        <Btn
                          sm
                          disabled={!online}
                          onClick={() => opMut.mutate({ type, op: v.running ? "stop" : "start" })}
                        >
                          {v.running ? "Остановить всё" : "Запустить всё"}
                        </Btn>
                      )}
                      {v.installed && (
                        <Btn
                          variant="ghost"
                          sm
                          title={`Удалить ${VPN_LABEL[type]} целиком`}
                          style={{ marginLeft: "auto" }}
                          onClick={() => setConfirmRemoveVpn(type)}
                        >
                          <Icon name="trash" size={15} />
                        </Btn>
                      )}
                    </>
                  )}
                </div>
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

      {/* Выбор протоколов для установки/докачки (галочки) */}
      {addProtoVendor && (
        <Modal
          title={`${VPN_LABEL[addProtoVendor]}: установить протоколы`}
          onClose={() => setAddProtoVendor(null)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setAddProtoVendor(null)}>
                Отмена
              </Btn>
              <Btn
                variant="primary"
                disabled={checkedProtos.size === 0 || opMut.isPending}
                onClick={() => {
                  const type = addProtoVendor;
                  const protos = [...checkedProtos];
                  setAddProtoVendor(null);
                  opMut.mutate({ type, op: "install", protos });
                }}
              >
                Установить{checkedProtos.size ? ` (${checkedProtos.size})` : ""}
              </Btn>
            </>
          }
        >
          <div className="stack" style={{ gap: 8 }}>
            <p className="muted" style={{ fontSize: 13 }}>
              Отметьте протоколы для установки — каждый развернётся в своём контейнере. Уже установленные протоколы
              здесь не показаны.
            </p>
            {VENDOR_PROTOCOLS[addProtoVendor]
              .filter((pr) => !protosByVendor(addProtoVendor).find((x) => x.proto === pr.id)?.installed)
              .map((pr) => {
                const on = checkedProtos.has(pr.id);
                return (
                  <label
                    key={pr.id}
                    className="rowflex"
                    style={{
                      gap: 11,
                      cursor: "pointer",
                      padding: "11px 13px",
                      border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`,
                      borderRadius: 10,
                      background: on ? "var(--accent-soft)" : "var(--surface)",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() =>
                        setCheckedProtos((prev) => {
                          const next = new Set(prev);
                          if (on) next.delete(pr.id);
                          else next.add(pr.id);
                          return next;
                        })
                      }
                    />
                    <span style={{ fontWeight: 600, fontSize: 14, flex: 1 }}>{pr.label}</span>
                  </label>
                );
              })}
          </div>
        </Modal>
      )}

      {/* Удаление одного протокола (сносит контейнер + отзывает его конфиги) */}
      {confirmRemoveProto && (
        <Modal
          title={`Удалить ${confirmRemoveProto.label}?`}
          onClose={() => setConfirmRemoveProto(null)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setConfirmRemoveProto(null)}>
                Отмена
              </Btn>
              <Btn
                variant="danger"
                disabled={removeProtoMut.isPending}
                onClick={() => {
                  const { proto, label } = confirmRemoveProto;
                  setConfirmRemoveProto(null);
                  removeProtoMut.mutate({ proto, label });
                }}
              >
                Удалить
              </Btn>
            </>
          }
        >
          <p className="muted">
            Контейнер протокола будет снесён, а выданные по нему конфиги — отозваны. Другие протоколы этого VPN не
            затрагиваются.
          </p>
        </Modal>
      )}

      {/* Снос всего вендора: все его протоколы + групповые доступы разом */}
      {confirmRemoveVpn && (
        <Modal
          title={`Удалить ${VPN_LABEL[confirmRemoveVpn]} целиком?`}
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
                Удалить всё
              </Btn>
            </>
          }
        >
          <p className="muted">
            Будут снесены все протоколы этого VPN, а связанные конфиги и групповые доступы к нему — отозваны.
          </p>
        </Modal>
      )}
    </div>
  );
}
