import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { type ChartLine, LineChart } from "../components/chart";
import { Btn, FilePicker, Icon, KeyInput, Modal, ScreenHeader, Spinner } from "../components/ui";
import { type TFunc, useT } from "../lib/i18n";
import * as q from "../lib/queries";
import { downloadRecoveryKey } from "../lib/recoveryKey";
import {
  bytesToTrafficInput,
  convertTrafficInputUnit,
  TRAFFIC_UNITS,
  type TrafficUnit,
  trafficValueToBytes,
} from "../lib/trafficUnits";
import type { MetricSeries, MetricsRetention, SystemInfo } from "../lib/types";
import { copyText, useStore } from "../store";

const UPGRADE_CMD = "docker compose pull && docker compose up -d";

// человекочитаемые байты (компактно, для строки использования метрик)
function fmtBytes(t: TFunc, n: number | null): string {
  if (n == null) return t("common.none");
  const u = [t("system.unitB"), t("system.unitKB"), t("system.unitMB"), t("system.unitGB"), t("system.unitTB")];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}

// строка «Сейчас: N строк, ~X на диске» (размер только на Postgres)
function metricsUsageLine(t: TFunc, m: MetricsRetention): string {
  const rows = Object.values(m.usage.rows).reduce((a, b) => a + b, 0);
  const size =
    m.usage.totalBytes != null ? t("system.metricsUsageDisk", { size: fmtBytes(t, m.usage.totalBytes) }) : "";
  return t("system.metricsUsageNow", { rows: rows.toLocaleString("ru-RU"), size });
}

// как именно применится обновление — зависит от драйвера на бэкенде (updateMode)
function modeHint(t: TFunc, mode: string): string | undefined {
  if (mode === "command") return t("system.modeHintCommand");
  if (mode === "webhook") return t("system.modeHintWebhook");
  if (mode === "k8s") return t("system.modeHintK8s");
  return undefined;
}

const UPDATE_POLL_MS = 3000;
const UPDATE_TIMEOUT_MS = 5 * 60_000;

const FREQ_OPTIONS = [
  { value: "off", labelKey: "system.freqOff" },
  { value: "daily", labelKey: "system.freqDaily" },
  { value: "weekly", labelKey: "system.freqWeekly" },
  { value: "monthly", labelKey: "system.freqMonthly" },
] as const;

function downloadBackup(id: string) {
  // тянет реальный зашифрованный файл с сервера (cookie-сессия, same-origin)
  const a = document.createElement("a");
  a.href = q.adminDownloadBackupUrl(id);
  a.download = id;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        font: "700 12px/1 var(--font)",
        letterSpacing: ".05em",
        textTransform: "uppercase",
        color: "var(--text-3)",
        marginBottom: 12,
      }}
    >
      {children}
    </div>
  );
}

const METRICS_POLL_MS = 30_000;
const PERIODS: { value: "1h" | "24h" | "7d"; labelKey: "system.period1h" | "period.24h" | "period.7d" }[] = [
  { value: "1h", labelKey: "system.period1h" },
  { value: "24h", labelKey: "period.24h" },
  { value: "7d", labelKey: "period.7d" },
];
const SERVER_COLORS: Record<string, string> = {
  online: "#22c55e",
  offline: "#ef4444",
  unknown: "#94a3b8",
};
const SERVER_LABEL_KEYS: Record<string, "status.online" | "status.offline" | "status.unchecked"> = {
  online: "status.online",
  offline: "status.offline",
  unknown: "status.unchecked",
};

function serverLines(t: TFunc, series: MetricSeries[]): ChartLine[] {
  const lines: ChartLine[] = [];
  for (const status of ["online", "offline", "unknown"]) {
    const s = series.find((x) => x.name === "vpnhub_servers" && x.labels === `status=${status}`);
    if (s?.points.length) {
      lines.push({ points: s.points, color: SERVER_COLORS[status], label: t(SERVER_LABEL_KEYS[status]) });
    }
  }
  return lines;
}

// Мониторинг здоровья самого инстанса панели (не путать с дашбордом VPN-трафика владельца).
function MonitoringSection() {
  const t = useT();
  const [period, setPeriod] = useState<"1h" | "24h" | "7d">("24h");
  const mq = useQuery({
    queryKey: ["adminMetrics", period],
    queryFn: () => q.adminMetrics(period),
    refetchInterval: METRICS_POLL_MS,
    retry: 2, // глобально retry=false → разовый сбой оставлял бы график пустым
  });
  const data = mq.data;
  const lines = data ? serverLines(t, data.series) : [];

  return (
    <div className="card">
      <div
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}
      >
        <SectionLabel>{t("system.monitoring")}</SectionLabel>
        <div style={{ display: "flex", gap: 4, marginBottom: 12 }}>
          {PERIODS.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => setPeriod(p.value)}
              style={{
                font: "600 12px/1 var(--font)",
                padding: "6px 10px",
                borderRadius: 8,
                cursor: "pointer",
                border: "1px solid var(--border)",
                background: period === p.value ? "var(--accent)" : "var(--surface-2)",
                color: period === p.value ? "#fff" : "var(--text-2)",
              }}
            >
              {t(p.labelKey)}
            </button>
          ))}
        </div>
      </div>
      <p style={{ fontSize: 12.5, color: "var(--text-3)", margin: "0 0 14px" }}>{t("system.monitoringHint")}</p>

      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-2)", marginBottom: 8 }}>
        {t("system.serversByStatus")}
      </div>
      {mq.isLoading ? <Spinner /> : <LineChart lines={lines} />}

      {data && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 16 }}>
          {(["online", "offline", "unknown"] as const).map((k) => (
            <div
              key={k}
              style={{
                flex: "1 1 100px",
                padding: "10px 14px",
                border: "1px solid var(--border)",
                borderRadius: 12,
                background: "var(--surface-2)",
              }}
            >
              <div style={{ fontSize: 12, color: "var(--text-3)" }}>{t(SERVER_LABEL_KEYS[k])}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: SERVER_COLORS[k] }}>
                {Math.round(data.servers[k])}
              </div>
            </div>
          ))}
          <div
            style={{
              flex: "1 1 100px",
              padding: "10px 14px",
              border: "1px solid var(--border)",
              borderRadius: 12,
              background: "var(--surface-2)",
            }}
          >
            <div style={{ fontSize: 12, color: "var(--text-3)" }}>{t("system.httpRequestsTotal")}</div>
            <div style={{ fontSize: 22, fontWeight: 700 }}>{Math.round(data.httpTotal).toLocaleString("ru-RU")}</div>
          </div>
        </div>
      )}
    </div>
  );
}

// цвет бейджа способа деплоя: контейнерные — акцент, хост-процесс — нейтрально
const DEPLOY_BADGE: Record<string, { bg: string; fg: string }> = {
  kubernetes: { bg: "var(--accent)", fg: "#fff" },
  docker: { bg: "var(--accent)", fg: "#fff" },
  compose: { bg: "var(--accent)", fg: "#fff" },
  host: { bg: "var(--surface-2)", fg: "var(--text-2)" },
};

// полоса заполнения тома: зелёная/жёлтая/красная по проценту
function UsageBar({ used, total, h = 8 }: { used: number; total: number; h?: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const color = pct >= 90 ? "var(--danger)" : pct >= 75 ? "var(--warn)" : "var(--ok)";
  return (
    <div style={{ height: h, borderRadius: 999, background: "var(--surface-2)", overflow: "hidden" }}>
      <div style={{ width: `${pct}%`, height: "100%", background: color }} />
    </div>
  );
}

// Развёртывание + дисковое использование (GET /admin/system/storage): способ деплоя, куда пишет система,
// свободное место на томах, размер БД по таблицам. Грузится лениво, отдельно от основной сводки.
function StorageSection() {
  const t = useT();
  const sq = useQuery({ queryKey: ["adminStorage"], queryFn: q.adminSystemStorage, staleTime: 30_000, retry: 1 });
  const data = sq.data;

  if (sq.isLoading || !data) {
    return (
      <div className="card">
        <SectionLabel>{t("system.deploymentAndDisk")}</SectionLabel>
        {sq.isLoading ? (
          <div style={{ padding: 20, textAlign: "center" }}>
            <Spinner />
          </div>
        ) : (
          <p style={{ fontSize: 13, color: "var(--text-3)", margin: 0 }}>{t("system.storageLoadFailed")}</p>
        )}
      </div>
    );
  }

  const d = data.deployment;
  const badge = DEPLOY_BADGE[d.method] ?? DEPLOY_BADGE.host;
  const depRows: [string, string, boolean][] = [
    [t("system.host"), d.hostname, true],
    [t("system.platform"), d.platform, false],
    ["Python", d.python, true],
    [
      t("system.cpuRam"),
      t("system.cpuRamValue", { cores: d.cpuCount ?? t("common.none"), mem: fmtBytes(t, d.rssBytes) }),
      false,
    ],
    ["PID", String(d.pid), true],
    [t("system.updateDriver"), d.updateMode, false],
    [t("system.workDir"), d.cwd, true],
    [t("system.timezone"), d.tz, false],
  ];
  if (d.namespace) depRows.splice(1, 0, ["Namespace / Pod", `${d.namespace} / ${d.pod ?? "—"}`, true]);

  return (
    <>
      <div className="card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <SectionLabel>{t("system.deployment")}</SectionLabel>
          <span
            style={{
              font: "700 12px/1 var(--font)",
              padding: "5px 10px",
              borderRadius: 999,
              background: badge.bg,
              color: badge.fg,
              marginBottom: 12,
            }}
          >
            {d.methodLabel}
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          {depRows.map(([k, v, mono], i, arr) => (
            <div
              key={k}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                padding: "10px 0",
                borderBottom: i < arr.length - 1 ? "1px solid var(--border)" : undefined,
              }}
            >
              <span style={{ fontSize: 13.5, color: "var(--text-2)", flex: "none" }}>{k}</span>
              <span
                className={mono ? "mono" : undefined}
                style={{
                  fontSize: mono ? 13 : 13.5,
                  fontWeight: 600,
                  textAlign: "right",
                  flex: 1,
                  minWidth: 0,
                  overflowWrap: "anywhere",
                }}
              >
                {v}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <SectionLabel>{t("system.diskSpace")}</SectionLabel>

        {data.volumes.map((v) => (
          <div key={v.path} style={{ marginBottom: 14 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 8,
                fontSize: 12.5,
                color: "var(--text-2)",
                marginBottom: 6,
              }}
            >
              <span className="mono" style={{ minWidth: 0, overflowWrap: "anywhere" }}>
                {v.path}
              </span>
              <span style={{ flex: "none" }}>
                {t("system.freeOfTotal", { free: fmtBytes(t, v.freeBytes), total: fmtBytes(t, v.totalBytes) })}
              </span>
            </div>
            <UsageBar used={v.usedBytes} total={v.totalBytes} />
          </div>
        ))}

        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-2)", margin: "6px 0 8px" }}>
          {t("system.whereSystemWrites")}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {data.dirs.map((dir) => (
            <div
              key={dir.kind}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                flexWrap: "wrap",
                padding: "8px 10px",
                borderRadius: 10,
                background: "var(--surface-2)",
              }}
            >
              <div style={{ minWidth: 0, flex: "1 1 240px" }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>
                  {dir.label}
                  {!dir.exists && (
                    <span style={{ marginLeft: 6, fontSize: 11, color: "var(--warn)" }}>
                      · {t("system.dirMissing")}
                    </span>
                  )}
                  {dir.exists && !dir.writable && (
                    <span style={{ marginLeft: 6, fontSize: 11, color: "var(--warn)" }}>
                      · {t("system.dirReadOnly")}
                    </span>
                  )}
                </div>
                <div className="mono" style={{ fontSize: 11.5, color: "var(--text-3)", overflowWrap: "anywhere" }}>
                  {dir.path}
                </div>
              </div>
              <div style={{ textAlign: "right", flex: "none" }}>
                <div style={{ fontSize: 13.5, fontWeight: 700 }}>{fmtBytes(t, dir.sizeBytes)}</div>
                <div style={{ fontSize: 11.5, color: "var(--text-3)" }}>{t("system.filesCount", { n: dir.files })}</div>
              </div>
            </div>
          ))}
        </div>

        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-2)", margin: "16px 0 8px" }}>
          {t("system.database")}
          {data.db.totalBytes != null && (
            <span style={{ color: "var(--text-3)", fontWeight: 400 }}> · {fmtBytes(t, data.db.totalBytes)}</span>
          )}
        </div>
        {data.db.totalBytes == null ? (
          <p style={{ fontSize: 12.5, color: "var(--text-3)", margin: 0 }}>{t("system.tableSizePgOnly")}</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {data.db.tables.map((tbl) => {
              const pct = data.db.totalBytes ? Math.round((tbl.sizeBytes / data.db.totalBytes) * 100) : 0;
              return (
                <div key={tbl.name}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 8,
                      fontSize: 12.5,
                      marginBottom: 3,
                    }}
                  >
                    <span className="mono" style={{ color: "var(--text-2)", minWidth: 0, overflowWrap: "anywhere" }}>
                      {tbl.name}
                    </span>
                    <span style={{ color: "var(--text-3)", flex: "none" }}>
                      {t("system.tableSizeRows", {
                        size: fmtBytes(t, tbl.sizeBytes),
                        rows: tbl.rows.toLocaleString("ru-RU"),
                      })}
                    </span>
                  </div>
                  <div style={{ height: 5, borderRadius: 999, background: "var(--surface-2)", overflow: "hidden" }}>
                    <div style={{ width: `${Math.min(100, pct)}%`, height: "100%", background: "var(--accent)" }} />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}

export function SystemScreen() {
  const t = useT();
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();

  const sysQ = useQuery({ queryKey: ["adminSystem"], queryFn: q.adminSystem });

  const [release, setRelease] = useState(false);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [keyOpen, setKeyOpen] = useState(false);
  const [keyValue, setKeyValue] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importKey, setImportKey] = useState("");

  const toastErr = (e: unknown) => toast(e instanceof Error ? e.message : t("common.error"));

  const checkMut = useMutation({
    mutationFn: q.adminCheckUpdates,
    onSuccess: (r) => {
      if (r.checked === false) toast(r.reason || t("system.updateCheckUnavailable"));
      else if (r.available) toast(t("system.versionAvailable", { v: r.latest }));
      else toast(t("system.latestVersionInstalled"));
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
    onError: toastErr,
  });

  // применение принято в фоне → поллим статус до смены версии (панель перезапускается)
  const [updating, setUpdating] = useState<{ target: string; from: string; startedAt: number; done?: boolean } | null>(
    null,
  );
  const [updateError, setUpdateError] = useState<string | null>(null);
  const [devLimit, setDevLimit] = useState("");
  const [userBytesValue, setUserBytesValue] = useState("");
  const [userBytesUnit, setUserBytesUnit] = useState<TrafficUnit>("GB");
  const [metricsDays, setMetricsDays] = useState("");
  const [metricsCap, setMetricsCap] = useState("");
  useEffect(() => {
    const n = sysQ.data?.defaultDevicesPerUser;
    if (n != null) setDevLimit(String(n));
  }, [sysQ.data?.defaultDevicesPerUser]);
  useEffect(() => {
    const b = sysQ.data?.defaultUserBytes;
    const limit = bytesToTrafficInput(b ?? null);
    setUserBytesValue(limit.value);
    setUserBytesUnit(limit.unit);
  }, [sysQ.data?.defaultUserBytes]);
  useEffect(() => {
    const mtr = sysQ.data?.metrics;
    if (!mtr) return;
    setMetricsDays(mtr.rawRetentionDays != null ? String(mtr.rawRetentionDays) : "");
    setMetricsCap(mtr.sizeCapGb > 0 ? String(mtr.sizeCapGb) : "");
  }, [sysQ.data?.metrics]);

  const upgradeMut = useMutation({
    mutationFn: q.adminUpgrade,
    onSuccess: (r) => {
      if (r.accepted && r.target) {
        setRelease(false);
        setUpdating({ target: r.target, from: r.from ?? "", startedAt: Date.now() });
      } else if (r.manual) {
        toast(r.message || t("system.updateImageManually"));
      } else {
        toast(r.message || t("system.updateStartFailed"));
      }
    },
    onError: toastErr,
  });

  useEffect(() => {
    if (!updating || updating.done) return;
    const id = setInterval(async () => {
      if (Date.now() - updating.startedAt > UPDATE_TIMEOUT_MS) {
        setUpdating(null);
        setUpdateError(t("system.updateTimeoutMsg"));
        return;
      }
      try {
        const st = await q.adminUpgradeStatus();
        if (st.state === "failed") {
          setUpdating(null);
          setUpdateError(st.log || t("system.updateFailedGeneric"));
        } else if (st.version !== updating.from) {
          // бэкенд уже новый → перезагружаем страницу, чтобы подтянуть новый фронтенд
          setUpdating({ ...updating, done: true });
          setTimeout(() => window.location.reload(), 1500);
        }
      } catch {
        // панель перезапускается — временные ошибки сети ожидаемы, продолжаем поллинг
      }
    }, UPDATE_POLL_MS);
    return () => clearInterval(id);
  }, [updating]);

  const createMut = useMutation({
    mutationFn: q.adminCreateBackup,
    onSuccess: () => {
      toast(t("system.backupCreated"));
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => q.adminDeleteBackup(id),
    onSuccess: () => {
      setConfirmDel(null);
      toast(t("system.backupDeleted"));
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
    onError: toastErr,
  });

  const freqMut = useMutation({
    mutationFn: (frequency: string) => q.adminSetBackupSettings({ frequency }),
    onSuccess: () => {
      toast(t("system.frequencySaved"));
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
    onError: toastErr,
  });

  const devLimitMut = useMutation({
    mutationFn: (n: number) => q.adminSetDeviceLimit(n),
    onSuccess: () => {
      toast(t("system.deviceLimitSaved"));
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
    onError: toastErr,
  });

  const userBytesMut = useMutation({
    mutationFn: (bytes: number | null) => q.adminSetUserByteLimit(bytes),
    onSuccess: () => {
      toast(t("system.trafficLimitSaved"));
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
    onError: toastErr,
  });

  const metricsMut = useMutation({
    mutationFn: (v: { days: number | null; cap: number }) => q.adminSetMetricsRetention(v.days, v.cap),
    onSuccess: () => {
      toast(t("system.metricsRetentionSaved"));
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
    onError: toastErr,
  });

  const keyMut = useMutation({
    mutationFn: (key: string) => q.adminSetBackupSettings({ key }),
    onSuccess: () => {
      setKeyOpen(false);
      setKeyValue("");
      toast(t("system.masterKeySaved"));
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
    onError: toastErr,
  });

  const importMut = useMutation({
    mutationFn: () => q.adminImportBackup(importFile as File, importKey),
    onSuccess: () => {
      setImportOpen(false);
      setImportFile(null);
      setImportKey("");
      toast(t("system.backupRestored"));
      qc.invalidateQueries();
    },
    onError: toastErr,
  });

  if (sysQ.isLoading) {
    return (
      <div className="stack" style={{ maxWidth: 760, margin: "0 auto", width: "100%" }}>
        <ScreenHeader title={t("nav.system")} sub={t("system.sub")} />
        <div className="card" style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner />
        </div>
      </div>
    );
  }

  const sys = sysQ.data as SystemInfo;
  if (!sys) return null;

  const updateAvailable = sys.updateAvailable;
  const dbConnected = sys.db.status === "connected";
  const dbColor = dbConnected ? "var(--ok)" : "var(--danger)";
  const dbSoft = dbConnected ? "var(--ok-soft)" : "var(--danger-soft)";
  const dbStatusLabel = dbConnected ? t("system.dbConnected") : t("system.dbUnavailable");
  const release0 = sys.releases[0];

  return (
    <div className="stack" style={{ maxWidth: 760, margin: "0 auto", width: "100%" }}>
      <ScreenHeader title={t("nav.system")} sub={t("system.sub")} />

      {/* Предупреждение о небезопасном мастер-ключе */}
      {sys.masterKeyInsecure && (
        <div className="card" style={{ border: "1px solid var(--danger)", background: "var(--danger-soft)" }}>
          <div style={{ fontSize: 13.5, color: "var(--text-2)", lineHeight: 1.5 }}>
            <b style={{ color: "var(--danger)" }}>{t("system.masterKeyNotSetTitle")}</b>{" "}
            {t("system.masterKeyInsecureBefore")} <span className="mono">VPNHUB_MASTER_KEY</span>
            {t("system.masterKeyInsecureAfter")}
          </div>
        </div>
      )}

      {/* (1) Версия и обновления */}
      <div className="card">
        <SectionLabel>{t("system.productVersion")}</SectionLabel>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <span className="mono" style={{ fontSize: 32, fontWeight: 800, letterSpacing: "-.02em" }}>
            {sys.version}
          </span>
          {updateAvailable ? (
            <span className="badge warn">
              <span className="dot" style={{ background: "var(--warn)" }} />
              {t("system.updateAvailableBadge", { v: sys.latest })}
            </span>
          ) : (
            <span className="badge ok">
              <span className="dot online" />
              {t("system.upToDateBadge")}
            </span>
          )}
        </div>
        <div className="mono" style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 8 }}>
          {sys.image}:{sys.version}
        </div>

        {updateAvailable && release0 && (
          <div
            className="card-row"
            style={{
              marginTop: 16,
              padding: 14,
              border: "1px solid var(--border)",
              borderRadius: 14,
              background: "var(--surface-2)",
            }}
          >
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: 11,
                background: "var(--surface)",
                border: "1px solid var(--border)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "var(--warn)",
                flex: "none",
              }}
            >
              <Icon name="download" size={20} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>
                {t("system.versionAvailableTitle", { v: sys.latest })}
              </div>
              <div style={{ fontSize: 12.5, color: "var(--text-3)" }}>{t("system.updateImageHint")}</div>
            </div>
            <Btn variant="primary" sm onClick={() => setRelease(true)}>
              {t("system.update")}
            </Btn>
          </div>
        )}

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 12,
            marginTop: 14,
          }}
        >
          <Btn onClick={() => checkMut.mutate()} disabled={checkMut.isPending}>
            <span className={checkMut.isPending ? "spin" : ""} style={{ display: "inline-flex" }}>
              <Icon name="refresh" size={16} />
            </span>
            {checkMut.isPending ? t("system.checking") : t("system.checkUpdates")}
          </Btn>
          <span style={{ fontSize: 12.5, color: "var(--text-3)" }}>
            {t("system.updateChannel", { channel: sys.channel })}
          </span>
        </div>
      </div>

      {/* (2) Состояние системы */}
      <div className="card">
        <SectionLabel>{t("system.systemStatus")}</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="card-row" style={{ padding: 13, border: "1px solid var(--border)", borderRadius: 13 }}>
            <div
              style={{
                width: 38,
                height: 38,
                borderRadius: 10,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flex: "none",
                background: dbSoft,
                color: dbColor,
              }}
            >
              <Icon name="servers" size={19} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontWeight: 700, fontSize: 14.5 }}>{t("system.database")}</span>
                <span className="badge" style={{ background: dbSoft, color: dbColor }}>
                  <span className="dot" style={{ background: dbColor }} />
                  {dbStatusLabel}
                </span>
              </div>
              <div
                className="mono"
                style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2, overflowWrap: "anywhere" }}
              >
                {sys.db.engine} · {sys.db.host}/{sys.db.name}
              </div>
            </div>
            <span className="mono" style={{ fontSize: 12.5, color: "var(--text-3)", flex: "none" }}>
              {sys.db.latency ?? "—"}
            </span>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))",
              gap: 10,
            }}
          >
            <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "12px 13px" }}>
              <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 4 }}>{t("system.uptime")}</div>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{sys.uptime}</div>
            </div>
            <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "12px 13px" }}>
              <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 4 }}>{t("system.lastDbBackup")}</div>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{sys.lastBackup}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Лимиты на пользователя по умолчанию (глобальный дефолт) */}
      <div className="card">
        <div
          style={{
            font: "700 12px/1 var(--font)",
            letterSpacing: ".05em",
            textTransform: "uppercase",
            color: "var(--text-3)",
            marginBottom: 12,
          }}
        >
          {t("system.defaultUserLimits")}
        </div>
        <p className="muted" style={{ fontSize: 13, marginBottom: 12 }}>
          {t("system.defaultUserLimitsHint")}
        </p>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 10, flexWrap: "wrap" }}>
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }}>
              <span className="muted">{t("system.devicesLabel")}</span>
              <input
                className="input"
                type="number"
                min={1}
                style={{ width: 120 }}
                value={devLimit}
                onChange={(e) => setDevLimit(e.target.value)}
              />
            </label>
            <Btn
              onClick={() => {
                const n = Number.parseInt(devLimit, 10);
                if (!Number.isFinite(n) || n < 1) {
                  toast(t("system.limitMinOne"));
                  return;
                }
                devLimitMut.mutate(n);
              }}
              disabled={devLimitMut.isPending}
            >
              {t("common.save")}
            </Btn>
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 10, flexWrap: "wrap" }}>
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }}>
              <span className="muted">{t("system.trafficPerPeriod")}</span>
              <div style={{ display: "grid", gridTemplateColumns: "140px 92px", gap: 8 }}>
                <input
                  className="input"
                  type="number"
                  min={0}
                  step={userBytesUnit === "B" ? 1 : 0.1}
                  value={userBytesValue}
                  placeholder={t("system.emptyNoLimit")}
                  onChange={(e) => setUserBytesValue(e.target.value)}
                />
                <select
                  className="input"
                  value={userBytesUnit}
                  onChange={(e) => {
                    const unit = e.target.value as TrafficUnit;
                    setUserBytesValue((v) => convertTrafficInputUnit(v, userBytesUnit, unit));
                    setUserBytesUnit(unit);
                  }}
                >
                  {TRAFFIC_UNITS.map((u) => (
                    <option key={u.value} value={u.value}>
                      {u.label}
                    </option>
                  ))}
                </select>
              </div>
            </label>
            <Btn
              onClick={() => {
                userBytesMut.mutate(trafficValueToBytes(userBytesValue, userBytesUnit));
              }}
              disabled={userBytesMut.isPending}
            >
              {t("common.save")}
            </Btn>
          </div>
        </div>
      </div>

      {/* (2b) Хранение метрик: ретеншн по времени/размеру + текущее использование */}
      {sysQ.data?.metrics && (
        <div className="card">
          <div
            style={{
              font: "700 12px/1 var(--font)",
              letterSpacing: ".05em",
              textTransform: "uppercase",
              color: "var(--text-3)",
              marginBottom: 12,
            }}
          >
            {t("system.metricsStorage")}
          </div>
          <p className="muted" style={{ fontSize: 13, marginBottom: 12 }}>
            {t("system.metricsStorageHint")} {metricsUsageLine(t, sysQ.data.metrics)}
          </p>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }}>
              <span className="muted">{t("system.rawRetentionDaysLabel")}</span>
              <input
                className="input"
                type="number"
                min={0}
                style={{ width: 200 }}
                placeholder={t("system.defaultDaysPlaceholder", { n: sysQ.data.metrics.defaultRawRetentionDays })}
                value={metricsDays}
                onChange={(e) => setMetricsDays(e.target.value)}
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }}>
              <span className="muted">{t("system.sizeCapLabel")}</span>
              <input
                className="input"
                type="number"
                min={0}
                step={0.5}
                style={{ width: 200 }}
                placeholder={
                  sysQ.data.metrics.autoSizeCapGb > 0
                    ? t("system.autoCapPlaceholder", {
                        gb: sysQ.data.metrics.autoSizeCapGb,
                        pct: sysQ.data.metrics.diskCapPct,
                      })
                    : t("system.zeroNoLimit")
                }
                value={metricsCap}
                onChange={(e) => setMetricsCap(e.target.value)}
              />
            </label>
            <Btn
              onClick={() => {
                const d = Number.parseInt(metricsDays, 10);
                const cap = Number.parseFloat(metricsCap);
                metricsMut.mutate({
                  days: Number.isFinite(d) && d > 0 ? d : null,
                  cap: Number.isFinite(cap) && cap > 0 ? cap : 0,
                });
              }}
              disabled={metricsMut.isPending}
            >
              {t("common.save")}
            </Btn>
          </div>
          <p className="muted-3" style={{ fontSize: 12, marginTop: 10 }}>
            {t("system.metricsRetentionExplain")}
            {sysQ.data.metrics.sizeCapGb === 0 && sysQ.data.metrics.autoSizeCapGb > 0 && (
              <>
                {" "}
                {t("system.metricsAutoCapActive", {
                  gb: sysQ.data.metrics.autoSizeCapGb,
                  pct: sysQ.data.metrics.diskCapPct,
                  total: sysQ.data.metrics.diskTotalGb
                    ? t("system.diskTotalSuffix", { gb: sysQ.data.metrics.diskTotalGb })
                    : "",
                })}
              </>
            )}
          </p>
        </div>
      )}

      {/* (3) Резервные копии БД */}
      <div className="card">
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            marginBottom: 14,
          }}
        >
          <div
            style={{
              font: "700 12px/1 var(--font)",
              letterSpacing: ".05em",
              textTransform: "uppercase",
              color: "var(--text-3)",
            }}
          >
            {t("system.dbBackups")}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Btn sm variant="ghost" onClick={() => setImportOpen(true)}>
              <Icon name="refresh" size={15} />
              {t("system.import")}
            </Btn>
            <Btn sm onClick={() => createMut.mutate()} disabled={createMut.isPending}>
              <Icon name="plus" size={15} />
              {createMut.isPending ? t("system.creating") : t("system.createBackup")}
            </Btn>
          </div>
        </div>

        {/* частота авто-бэкапа + ключ шифрования */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))",
            gap: 10,
            marginBottom: 14,
          }}
        >
          <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px" }}>
            <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 6 }}>{t("system.autoBackup")}</div>
            <select
              className="input"
              value={sys.backupFrequency}
              disabled={freqMut.isPending}
              onChange={(e) => freqMut.mutate(e.target.value)}
              style={{ width: "100%" }}
            >
              {FREQ_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {t(o.labelKey)}
                </option>
              ))}
            </select>
          </div>
          <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px" }}>
            <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 6 }}>{t("system.masterKey")}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span
                className="badge"
                style={{
                  background: sys.masterKeySet ? "var(--ok-soft)" : "var(--warn-soft)",
                  color: sys.masterKeySet ? "var(--ok)" : "var(--warn)",
                }}
              >
                <span className="dot" style={{ background: sys.masterKeySet ? "var(--ok)" : "var(--warn)" }} />
                {sys.masterKeyFromEnv
                  ? t("system.masterKeyFromEnv")
                  : sys.masterKeySet
                    ? t("system.masterKeySet")
                    : t("system.masterKeyNotSet")}
              </span>
              {!sys.masterKeyFromEnv && (
                <Btn sm variant="ghost" onClick={() => setKeyOpen(true)}>
                  {sys.masterKeySet ? t("system.change") : t("system.setKey")}
                </Btn>
              )}
            </div>
          </div>
        </div>

        {sys.backups.length === 0 ? (
          <div style={{ padding: 20, textAlign: "center", color: "var(--text-3)", fontSize: 13.5 }}>
            {t("system.noBackupsYet")}
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {sys.backups.map((b) => (
              <div
                key={b.id}
                className="card-row"
                style={{ padding: 12, border: "1px solid var(--border)", borderRadius: 12 }}
              >
                <div
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: 9,
                    background: "var(--surface-2)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "var(--text-2)",
                    flex: "none",
                  }}
                >
                  <Icon name="servers" size={18} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{b.at}</div>
                  <div style={{ fontSize: 12, color: "var(--text-3)" }}>
                    {b.size} · {b.kind}
                  </div>
                </div>
                <Btn variant="ghost" sm title={t("system.download")} onClick={() => downloadBackup(b.id)}>
                  <Icon name="download" size={16} />
                </Btn>
                <Btn variant="ghost" sm title={t("common.delete")} onClick={() => setConfirmDel(b.id)}>
                  <Icon name="trash" size={16} />
                </Btn>
              </div>
            ))}
          </div>
        )}

        <p style={{ fontSize: 12, color: "var(--text-3)", marginTop: 12, lineHeight: 1.45 }}>
          {t("system.backupExplain")}
        </p>
      </div>

      {/* (4) Об инстансе */}
      <div className="card">
        <SectionLabel>{t("system.aboutInstance")}</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column" }}>
          {[
            { k: t("system.edition"), v: sys.edition, mono: false },
            { k: t("system.imageLabel"), v: sys.image, mono: true },
            { k: t("system.buildDate"), v: sys.built, mono: false },
            { k: t("system.instanceUrl"), v: sys.baseUrl, mono: true },
          ].map((row, i, arr) => (
            <div
              key={row.k}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                padding: "11px 0",
                borderBottom: i < arr.length - 1 ? "1px solid var(--border)" : undefined,
              }}
            >
              <span style={{ fontSize: 13.5, color: "var(--text-2)", flex: "none" }}>{row.k}</span>
              <span
                className={row.mono ? "mono" : undefined}
                style={{
                  fontSize: row.mono ? 13 : 13.5,
                  fontWeight: 600,
                  textAlign: "right",
                  flex: 1,
                  minWidth: 0,
                  overflowWrap: "anywhere",
                }}
              >
                {row.v}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* (5) Развёртывание + дисковое использование */}
      <StorageSection />

      {/* (6) Мониторинг здоровья инстанса */}
      <MonitoringSection />

      {/* модалка релиза */}
      {release && release0 && (
        <Modal
          title={t("system.updateModalTitle", { v: release0.v })}
          onClose={() => setRelease(false)}
          footer={
            sys.updateSupported ? (
              <>
                <Btn block onClick={() => setRelease(false)}>
                  {t("common.close")}
                </Btn>
                <Btn variant="primary" block onClick={() => upgradeMut.mutate()} disabled={upgradeMut.isPending}>
                  {upgradeMut.isPending ? t("system.updating") : t("system.updateNow")}
                </Btn>
              </>
            ) : (
              <Btn block onClick={() => setRelease(false)}>
                {t("common.close")}
              </Btn>
            )
          }
        >
          <div style={{ fontSize: 12.5, color: "var(--text-3)", marginBottom: 16 }}>
            {t("system.releaseFrom", { date: release0.date })}
          </div>

          <SectionLabel>{t("system.whatsNew")}</SectionLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 18 }}>
            {release0.notes.map((n) => (
              <div key={n} style={{ display: "flex", alignItems: "flex-start", gap: 9 }}>
                <span style={{ color: "var(--ok)", flex: "none", marginTop: 1 }}>
                  <Icon name="check" size={16} />
                </span>
                <span style={{ fontSize: 13.5, color: "var(--text-2)" }}>{n}</span>
              </div>
            ))}
          </div>

          <SectionLabel>{t("system.howToUpdateImage")}</SectionLabel>
          <div
            className="copyable"
            onClick={() => copyText(UPGRADE_CMD, toast, t("system.commandCopied"))}
            style={{
              padding: "10px 14px",
              border: "1px solid var(--border)",
              borderRadius: 12,
              background: "var(--surface-2)",
              marginBottom: 10,
            }}
          >
            <span
              className="mono"
              style={{
                flex: 1,
                minWidth: 0,
                fontSize: 12,
                color: "var(--text-2)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {UPGRADE_CMD}
            </span>
            <Icon name="copy" size={15} />
          </div>
          <p style={{ fontSize: 12, color: "var(--text-3)", margin: 0 }}>
            {sys.updateSupported
              ? (modeHint(t, sys.updateMode) ?? t("system.modeHintDefault"))
              : sys.updateHint || t("system.updateNotConfigured")}
            {t("system.pgDataPreserved")}
          </p>
        </Modal>
      )}

      {/* подтверждение удаления бэкапа */}
      {confirmDel && (
        <Modal
          title={t("system.deleteBackupTitle")}
          onClose={() => setConfirmDel(null)}
          footer={
            <>
              <Btn block onClick={() => setConfirmDel(null)}>
                {t("common.cancel")}
              </Btn>
              <Btn variant="danger" block onClick={() => deleteMut.mutate(confirmDel)} disabled={deleteMut.isPending}>
                {deleteMut.isPending ? t("system.deleting") : t("common.delete")}
              </Btn>
            </>
          }
        >
          <p style={{ margin: 0, fontSize: 14, color: "var(--text-2)" }}>{t("system.deleteBackupConfirm")}</p>
        </Modal>
      )}

      {/* мастер-ключ */}
      {keyOpen && (
        <Modal
          title={sys.masterKeySet ? t("system.changeMasterKeyTitle") : t("system.setMasterKeyTitle")}
          onClose={() => {
            setKeyOpen(false);
            setKeyValue("");
          }}
          footer={
            <>
              <Btn
                block
                onClick={() => {
                  setKeyOpen(false);
                  setKeyValue("");
                }}
              >
                {t("common.cancel")}
              </Btn>
              <Btn
                variant="primary"
                block
                disabled={keyMut.isPending || keyValue.length < 8}
                onClick={() => keyMut.mutate(keyValue)}
              >
                {keyMut.isPending ? t("system.savingEllipsis") : t("common.save")}
              </Btn>
            </>
          }
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <p style={{ margin: 0, fontSize: 13.5, color: "var(--text-2)" }}>{t("system.masterKeyExplain")}</p>
            <KeyInput value={keyValue} placeholder={t("system.minChars8")} onChange={setKeyValue} />
            <Btn sm onClick={() => downloadRecoveryKey(keyValue)} disabled={keyValue.length < 8}>
              <Icon name="download" size={15} />
              {t("system.downloadKeyTxt")}
            </Btn>
            {sys.masterKeySet && (
              <p style={{ margin: 0, fontSize: 12, color: "var(--warn)" }}>{t("system.reencryptWarn")}</p>
            )}
          </div>
        </Modal>
      )}

      {/* импорт (восстановление) бэкапа */}
      {importOpen && (
        <Modal
          title={t("system.importBackupTitle")}
          onClose={() => {
            setImportOpen(false);
            setImportFile(null);
            setImportKey("");
          }}
          footer={
            <>
              <Btn
                block
                onClick={() => {
                  setImportOpen(false);
                  setImportFile(null);
                  setImportKey("");
                }}
              >
                {t("common.cancel")}
              </Btn>
              <Btn
                variant="danger"
                block
                disabled={importMut.isPending || !importFile || !importKey}
                onClick={() => importMut.mutate()}
              >
                {importMut.isPending ? t("system.restoring") : t("system.restore")}
              </Btn>
            </>
          }
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <p style={{ margin: 0, fontSize: 13.5, color: "var(--danger)" }}>{t("system.importWarn")}</p>
            <FilePicker accept=".vhb" file={importFile} onPick={setImportFile} />
            <input
              className="input"
              type="password"
              placeholder={t("system.masterKeyUsedForBackup")}
              value={importKey}
              onChange={(e) => setImportKey(e.target.value)}
            />
          </div>
        </Modal>
      )}

      {/* ошибка применения обновления (лог драйвера) */}
      {updateError && (
        <Modal
          title={t("system.updateFailedTitle")}
          onClose={() => setUpdateError(null)}
          footer={
            <Btn block onClick={() => setUpdateError(null)}>
              {t("common.close")}
            </Btn>
          }
        >
          <pre
            className="mono"
            style={{
              margin: 0,
              padding: "10px 12px",
              fontSize: 12,
              lineHeight: 1.5,
              color: "var(--text-2)",
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: 10,
              whiteSpace: "pre-wrap",
              overflowWrap: "anywhere",
              maxHeight: 260,
              overflowY: "auto",
            }}
          >
            {updateError}
          </pre>
        </Modal>
      )}

      {/* прогресс обновления: запуск → ожидание новой версии → перезагрузка страницы */}
      {(upgradeMut.isPending || updating) && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 70,
            background: "rgba(8,9,12,.55)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            backdropFilter: "blur(3px)",
          }}
        >
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 18,
              padding: "34px 40px",
              background: "var(--surface)",
              borderRadius: 20,
              boxShadow: "var(--shadow-lg)",
              maxWidth: "90vw",
            }}
          >
            {updating?.done ? (
              <span style={{ display: "inline-flex", color: "var(--ok)" }}>
                <Icon name="check" size={40} />
              </span>
            ) : (
              <span className="spin" style={{ display: "inline-flex", color: "var(--text-2)" }}>
                <Icon name="refresh" size={40} />
              </span>
            )}
            <div style={{ textAlign: "center" }}>
              <div style={{ fontWeight: 700, fontSize: 16 }}>
                {updating?.done
                  ? t("system.updatedTo", { v: updating.target })
                  : updating
                    ? t("system.installingVersion", { v: updating.target })
                    : t("system.startingUpdate")}
              </div>
              <div style={{ fontSize: 13, color: "var(--text-3)", marginTop: 5 }}>
                {updating?.done ? t("system.reloadingPage") : t("system.panelRestartingHint")}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
