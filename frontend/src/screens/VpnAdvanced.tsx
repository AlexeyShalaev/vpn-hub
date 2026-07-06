import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Btn, Field, Icon, Modal, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import * as q from "../lib/queries";
import type { VpnAdvancedProtocol, VpnType } from "../lib/types";
import { VPN_LABEL } from "../lib/types";
import { copyText, useStore } from "../store";

// пресеты зеркалят бэкенд (infra/provisioning/awg_params.py); значения применяет сервер.
const AWG_PRESETS: { id: string; label: string; hint: string }[] = [
  { id: "default", label: "По умолчанию", hint: "сгенерировать заново" },
  { id: "aggressive", label: "Агрессивный", hint: "больше junk, сильнее маскировка" },
  { id: "mobile", label: "Мобильный", hint: "минимальный оверхед" },
];

// редактируемые obfuscation-поля (subnet/i-junk/protocol_version править нельзя — их хранит бэкенд).
const AWG_FIELDS_BASE = ["Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4"];
const AWG_FIELDS_AWG2 = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4"];

// awg2 → H1..H4 диапазоны "a-b", S3/S4 присутствуют; awg_legacy → одиночные H, без S3/S4.
function ObfuscationForm({ serverId, vtype, proto }: { serverId: string; vtype: VpnType; proto: VpnAdvancedProtocol }) {
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();
  const params = proto.params ?? {};
  const isAwg2 = "S3" in params || "S4" in params;
  const fields = isAwg2 ? AWG_FIELDS_AWG2 : AWG_FIELDS_BASE;
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f, params[f] ?? ""])),
  );

  const mut = useMutation({
    mutationFn: (body: { preset?: string; values?: Record<string, string> }) =>
      q.setProtocolParams(serverId, proto.proto, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vpn-advanced", serverId, vtype] });
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      toast("Параметры обфускации применены");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Ошибка"),
  });

  // форма недоступна, пока протокол не запущен (бэкенд требует online-сервер и running-протокол).
  const disabled = mut.isPending || !proto.running;

  return (
    <details>
      <summary style={{ cursor: "pointer", fontSize: 12.5, color: "var(--text-2)" }}>Параметры обфускации</summary>
      <div className="stack" style={{ marginTop: 8, gap: 10 }}>
        <div
          style={{
            fontSize: 12,
            color: "var(--danger)",
            border: "1px solid var(--danger)",
            borderRadius: 8,
            padding: "7px 9px",
            background: "color-mix(in srgb, var(--danger) 8%, transparent)",
          }}
        >
          Смена параметров обфускации сделает уже выданные конфиги нерабочими — пользователям нужно заново скачать
          конфиг.
        </div>
        {!proto.running && (
          <div className="muted-3" style={{ fontSize: 12 }}>
            Протокол остановлен или сервер офлайн — смена параметров недоступна.
          </div>
        )}
        <div className="rowflex" style={{ gap: 6, flexWrap: "wrap" }}>
          {AWG_PRESETS.map((p) => (
            <Btn key={p.id} sm disabled={disabled} title={p.hint} onClick={() => mut.mutate({ preset: p.id })}>
              {p.label}
            </Btn>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(110px,1fr))", gap: 8 }}>
          {fields.map((f) => (
            <Field key={f} label={f}>
              <input
                className="input"
                value={values[f] ?? ""}
                disabled={disabled}
                onChange={(e) => setValues((v) => ({ ...v, [f]: e.target.value }))}
              />
            </Field>
          ))}
        </div>
        <Btn
          sm
          disabled={disabled}
          onClick={() =>
            mut.mutate({
              values: Object.fromEntries(fields.map((f) => [f.toLowerCase(), values[f] ?? ""])),
            })
          }
        >
          Применить вручную
        </Btn>
      </div>
    </details>
  );
}

// Управление Xray-Reality: ротация shortId и смена SNI/dest (маскировочный домен) с reprovision.
// short_id/site приходят из proto.keys (публичный материал); значения применяет сервер.
function RealityForm({ serverId, vtype, proto }: { serverId: string; vtype: VpnType; proto: VpnAdvancedProtocol }) {
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();
  const [sni, setSni] = useState<string>(() => proto.keys.site ?? "");
  const currentShortId = proto.keys.short_id ?? "";

  const mut = useMutation({
    mutationFn: (body: { rotate_short_id?: boolean; short_id?: string; sni?: string }) =>
      q.setReality(serverId, proto.proto, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vpn-advanced", serverId, vtype] });
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      toast("Параметры Reality применены");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Ошибка"),
  });

  // форма недоступна, пока протокол не запущен (бэкенд требует online-сервер и running-протокол).
  const disabled = mut.isPending || !proto.running;

  return (
    <details>
      <summary style={{ cursor: "pointer", fontSize: 12.5, color: "var(--text-2)" }}>Параметры Reality</summary>
      <div className="stack" style={{ marginTop: 8, gap: 10 }}>
        <div
          style={{
            fontSize: 12,
            color: "var(--danger)",
            border: "1px solid var(--danger)",
            borderRadius: 8,
            padding: "7px 9px",
            background: "color-mix(in srgb, var(--danger) 8%, transparent)",
          }}
        >
          Смена shortId или SNI сделает уже выданные конфиги нерабочими и перезапустит Xray (активные сессии оборвутся)
          — пользователям нужно заново скачать конфиг.
        </div>
        {!proto.running && (
          <div className="muted-3" style={{ fontSize: 12 }}>
            Протокол остановлен или сервер офлайн — смена параметров недоступна.
          </div>
        )}
        <div className="rowflex" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span className="muted-3" style={{ fontSize: 12 }}>
            shortId: <code>{currentShortId || "—"}</code>
          </span>
          <Btn sm disabled={disabled} onClick={() => mut.mutate({ rotate_short_id: true })}>
            Ротировать shortId
          </Btn>
        </div>
        <Field label="Маскировочный домен (SNI/dest)">
          <input
            className="input"
            value={sni}
            disabled={disabled}
            placeholder="www.googletagmanager.com"
            onChange={(e) => setSni(e.target.value)}
          />
        </Field>
        <Btn sm disabled={disabled || !sni.trim()} onClick={() => mut.mutate({ sni: sni.trim() })}>
          Применить SNI
        </Btn>
      </div>
    </details>
  );
}

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
                    {/* Xray (xray/xray_xhttp) — управление Reality (shortId, SNI/dest); материала в params нет. */}
                    {(p.proto === "xray" || p.proto === "xray_xhttp") && (
                      <RealityForm serverId={serverId} vtype={vtype} proto={p} />
                    )}
                    {p.params &&
                      Object.keys(p.params).length > 0 &&
                      // AWG (awg/awg_legacy) — редактируемая форма пресетов; прочие протоколы — read-only.
                      (p.proto === "awg" || p.proto === "awg_legacy" ? (
                        <ObfuscationForm serverId={serverId} vtype={vtype} proto={p} />
                      ) : (
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
                      ))}
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
