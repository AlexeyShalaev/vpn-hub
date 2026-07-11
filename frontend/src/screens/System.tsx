import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { type ChartLine, LineChart } from "../components/chart";
import { Btn, FilePicker, Icon, KeyInput, Modal, ScreenHeader, Spinner } from "../components/ui";
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
function fmtBytes(n: number | null): string {
  if (n == null) return "—";
  const u = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}

// строка «Сейчас: N строк, ~X на диске» (размер только на Postgres)
function metricsUsageLine(m: MetricsRetention): string {
  const rows = Object.values(m.usage.rows).reduce((a, b) => a + b, 0);
  const size = m.usage.totalBytes != null ? `, ~${fmtBytes(m.usage.totalBytes)} на диске` : "";
  return `Сейчас: ${rows.toLocaleString("ru-RU")} строк${size}.`;
}

// как именно применится обновление — зависит от драйвера на бэкенде (updateMode)
const MODE_HINT: Record<string, string> = {
  command: "Кнопка «Обновить сейчас» выполнит настроенную на сервере команду обновления. ",
  webhook:
    "Кнопка «Обновить сейчас» запустит апдейтер: он скачает новый образ и пересоздаст контейнер панели (короткий перерыв в работе). ",
  k8s: "Кнопка «Обновить сейчас» перезапустит панель с новым образом через Kubernetes (короткий перерыв в работе). ",
};

const UPDATE_POLL_MS = 3000;
const UPDATE_TIMEOUT_MS = 5 * 60_000;

const FREQ_OPTIONS = [
  { value: "off", label: "Выкл" },
  { value: "daily", label: "Раз в день" },
  { value: "weekly", label: "Раз в неделю" },
  { value: "monthly", label: "Раз в месяц" },
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
const PERIODS: { value: "1h" | "24h" | "7d"; label: string }[] = [
  { value: "1h", label: "1 час" },
  { value: "24h", label: "24 часа" },
  { value: "7d", label: "7 дней" },
];
const SERVER_COLORS: Record<string, string> = {
  online: "#22c55e",
  offline: "#ef4444",
  unknown: "#94a3b8",
};
const SERVER_LABELS: Record<string, string> = {
  online: "Онлайн",
  offline: "Офлайн",
  unknown: "Не проверено",
};

function serverLines(series: MetricSeries[]): ChartLine[] {
  const lines: ChartLine[] = [];
  for (const status of ["online", "offline", "unknown"]) {
    const s = series.find((x) => x.name === "vpnhub_servers" && x.labels === `status=${status}`);
    if (s?.points.length) {
      lines.push({ points: s.points, color: SERVER_COLORS[status], label: SERVER_LABELS[status] });
    }
  }
  return lines;
}

// Мониторинг здоровья самого инстанса панели (не путать с дашбордом VPN-трафика владельца).
function MonitoringSection() {
  const [period, setPeriod] = useState<"1h" | "24h" | "7d">("24h");
  const mq = useQuery({
    queryKey: ["adminMetrics", period],
    queryFn: () => q.adminMetrics(period),
    refetchInterval: METRICS_POLL_MS,
    retry: 2, // глобально retry=false → разовый сбой оставлял бы график пустым
  });
  const data = mq.data;
  const lines = data ? serverLines(data.series) : [];

  return (
    <div className="card">
      <div
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}
      >
        <SectionLabel>Мониторинг</SectionLabel>
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
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <p style={{ fontSize: 12.5, color: "var(--text-3)", margin: "0 0 14px" }}>
        Здоровье этого инстанса панели: серверы по статусу и накопленная нагрузка на API. Это не VPN-трафик клиентов —
        его смотрит владелец на своих серверах.
      </p>

      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-2)", marginBottom: 8 }}>Серверы по статусу</div>
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
              <div style={{ fontSize: 12, color: "var(--text-3)" }}>{SERVER_LABELS[k]}</div>
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
            <div style={{ fontSize: 12, color: "var(--text-3)" }}>HTTP-запросов всего</div>
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
  const sq = useQuery({ queryKey: ["adminStorage"], queryFn: q.adminSystemStorage, staleTime: 30_000, retry: 1 });
  const data = sq.data;

  if (sq.isLoading || !data) {
    return (
      <div className="card">
        <SectionLabel>Развёртывание и диск</SectionLabel>
        {sq.isLoading ? (
          <div style={{ padding: 20, textAlign: "center" }}>
            <Spinner />
          </div>
        ) : (
          <p style={{ fontSize: 13, color: "var(--text-3)", margin: 0 }}>Не удалось загрузить сведения о системе.</p>
        )}
      </div>
    );
  }

  const d = data.deployment;
  const badge = DEPLOY_BADGE[d.method] ?? DEPLOY_BADGE.host;
  const depRows: [string, string, boolean][] = [
    ["Хост", d.hostname, true],
    ["Платформа", d.platform, false],
    ["Python", d.python, true],
    ["CPU / RAM", `${d.cpuCount ?? "—"} ядер · ${fmtBytes(d.rssBytes)}`, false],
    ["PID", String(d.pid), true],
    ["Драйвер обновлений", d.updateMode, false],
    ["Рабочий каталог", d.cwd, true],
    ["Часовой пояс", d.tz, false],
  ];
  if (d.namespace) depRows.splice(1, 0, ["Namespace / Pod", `${d.namespace} / ${d.pod ?? "—"}`, true]);

  return (
    <>
      <div className="card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <SectionLabel>Развёртывание</SectionLabel>
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
        <SectionLabel>Дисковое пространство</SectionLabel>

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
                свободно {fmtBytes(v.freeBytes)} из {fmtBytes(v.totalBytes)}
              </span>
            </div>
            <UsageBar used={v.usedBytes} total={v.totalBytes} />
          </div>
        ))}

        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-2)", margin: "6px 0 8px" }}>
          Куда пишет система
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
                  {!dir.exists && <span style={{ marginLeft: 6, fontSize: 11, color: "var(--warn)" }}>· нет</span>}
                  {dir.exists && !dir.writable && (
                    <span style={{ marginLeft: 6, fontSize: 11, color: "var(--warn)" }}>· только чтение</span>
                  )}
                </div>
                <div className="mono" style={{ fontSize: 11.5, color: "var(--text-3)", overflowWrap: "anywhere" }}>
                  {dir.path}
                </div>
              </div>
              <div style={{ textAlign: "right", flex: "none" }}>
                <div style={{ fontSize: 13.5, fontWeight: 700 }}>{fmtBytes(dir.sizeBytes)}</div>
                <div style={{ fontSize: 11.5, color: "var(--text-3)" }}>{dir.files.toLocaleString("ru-RU")} файл.</div>
              </div>
            </div>
          ))}
        </div>

        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-2)", margin: "16px 0 8px" }}>
          База данных
          {data.db.totalBytes != null && (
            <span style={{ color: "var(--text-3)", fontWeight: 400 }}> · {fmtBytes(data.db.totalBytes)}</span>
          )}
        </div>
        {data.db.totalBytes == null ? (
          <p style={{ fontSize: 12.5, color: "var(--text-3)", margin: 0 }}>
            Размер таблиц доступен только на PostgreSQL.
          </p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {data.db.tables.map((t) => {
              const pct = data.db.totalBytes ? Math.round((t.sizeBytes / data.db.totalBytes) * 100) : 0;
              return (
                <div key={t.name}>
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
                      {t.name}
                    </span>
                    <span style={{ color: "var(--text-3)", flex: "none" }}>
                      {fmtBytes(t.sizeBytes)} · ~{t.rows.toLocaleString("ru-RU")} строк
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

  const toastErr = (e: unknown) => toast(e instanceof Error ? e.message : "Ошибка");

  const checkMut = useMutation({
    mutationFn: q.adminCheckUpdates,
    onSuccess: (r) => {
      if (r.checked === false) toast(r.reason || "Проверка обновлений недоступна");
      else if (r.available) toast(`Доступна версия ${r.latest}`);
      else toast("Установлена последняя версия");
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
        toast(r.message || "Обновите образ вручную командой ниже");
      } else {
        toast(r.message || "Не удалось запустить обновление");
      }
    },
    onError: toastErr,
  });

  useEffect(() => {
    if (!updating || updating.done) return;
    const id = setInterval(async () => {
      if (Date.now() - updating.startedAt > UPDATE_TIMEOUT_MS) {
        setUpdating(null);
        setUpdateError(
          "Панель не вернулась с новой версией за 5 минут. Проверьте состояние на хосте. " +
            "Если тег образа зафиксирован (VPNHUB_TAG или newTag в overlay), обновление по кнопке невозможно — переключите тег вручную.",
        );
        return;
      }
      try {
        const st = await q.adminUpgradeStatus();
        if (st.state === "failed") {
          setUpdating(null);
          setUpdateError(st.log || "Обновление завершилось с ошибкой");
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
      toast("Бэкап создан");
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => q.adminDeleteBackup(id),
    onSuccess: () => {
      setConfirmDel(null);
      toast("Бэкап удалён");
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
    onError: toastErr,
  });

  const freqMut = useMutation({
    mutationFn: (frequency: string) => q.adminSetBackupSettings({ frequency }),
    onSuccess: () => {
      toast("Частота сохранена");
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
    onError: toastErr,
  });

  const devLimitMut = useMutation({
    mutationFn: (n: number) => q.adminSetDeviceLimit(n),
    onSuccess: () => {
      toast("Лимит устройств сохранён");
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
    onError: toastErr,
  });

  const userBytesMut = useMutation({
    mutationFn: (bytes: number | null) => q.adminSetUserByteLimit(bytes),
    onSuccess: () => {
      toast("Лимит трафика сохранён");
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
    onError: toastErr,
  });

  const metricsMut = useMutation({
    mutationFn: (v: { days: number | null; cap: number }) => q.adminSetMetricsRetention(v.days, v.cap),
    onSuccess: () => {
      toast("Хранение метрик сохранено");
      qc.invalidateQueries({ queryKey: ["adminSystem"] });
    },
    onError: toastErr,
  });

  const keyMut = useMutation({
    mutationFn: (key: string) => q.adminSetBackupSettings({ key }),
    onSuccess: () => {
      setKeyOpen(false);
      setKeyValue("");
      toast("Мастер-ключ сохранён");
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
      toast("Бэкап восстановлен — рекомендуется перезапустить сервис");
      qc.invalidateQueries();
    },
    onError: toastErr,
  });

  if (sysQ.isLoading) {
    return (
      <div className="stack" style={{ maxWidth: 760, margin: "0 auto", width: "100%" }}>
        <ScreenHeader title="Система" sub="Версия, состояние и резервные копии" />
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
  const dbStatusLabel = dbConnected ? "подключена" : "недоступна";
  const release0 = sys.releases[0];

  return (
    <div className="stack" style={{ maxWidth: 760, margin: "0 auto", width: "100%" }}>
      <ScreenHeader title="Система" sub="Версия, состояние и резервные копии" />

      {/* Предупреждение о небезопасном мастер-ключе */}
      {sys.masterKeyInsecure && (
        <div className="card" style={{ border: "1px solid var(--danger)", background: "var(--danger-soft)" }}>
          <div style={{ fontSize: 13.5, color: "var(--text-2)", lineHeight: 1.5 }}>
            <b style={{ color: "var(--danger)" }}>Мастер-ключ не задан.</b> SSH-доступы к серверам сейчас зашифрованы
            дефолтным ключом из репозитория — фактически в открытом виде. Задайте мастер-ключ (кнопка «Задать» ниже или
            переменная <span className="mono">VPNHUB_MASTER_KEY</span>) — им же шифруются бэкапы.
          </div>
        </div>
      )}

      {/* (1) Версия и обновления */}
      <div className="card">
        <SectionLabel>Версия продукта</SectionLabel>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <span className="mono" style={{ fontSize: 32, fontWeight: 800, letterSpacing: "-.02em" }}>
            {sys.version}
          </span>
          {updateAvailable ? (
            <span className="badge warn">
              <span className="dot" style={{ background: "var(--warn)" }} />
              доступно обновление {sys.latest}
            </span>
          ) : (
            <span className="badge ok">
              <span className="dot online" />
              актуальная версия
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
              <div style={{ fontWeight: 700, fontSize: 15 }}>Версия {sys.latest} доступна</div>
              <div style={{ fontSize: 12.5, color: "var(--text-3)" }}>
                Обновление образа с новыми функциями и исправлениями
              </div>
            </div>
            <Btn variant="primary" sm onClick={() => setRelease(true)}>
              Обновить
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
            {checkMut.isPending ? "Проверяем…" : "Проверить обновления"}
          </Btn>
          <span style={{ fontSize: 12.5, color: "var(--text-3)" }}>Канал обновлений: {sys.channel}</span>
        </div>
      </div>

      {/* (2) Состояние системы */}
      <div className="card">
        <SectionLabel>Состояние системы</SectionLabel>
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
                <span style={{ fontWeight: 700, fontSize: 14.5 }}>База данных</span>
                <span className="badge" style={{ background: dbSoft, color: dbColor }}>
                  <span className="dot" style={{ background: dbColor }} />
                  {dbStatusLabel}
                </span>
              </div>
              <div className="mono" style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2 }}>
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
              <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 4 }}>Аптайм</div>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{sys.uptime}</div>
            </div>
            <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "12px 13px" }}>
              <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 4 }}>Последний бэкап БД</div>
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
          Лимиты на пользователя по умолчанию
        </div>
        <p className="muted" style={{ fontSize: 13, marginBottom: 12 }}>
          Глобальные дефолты: сколько устройств и трафика (за период на сервер) доступно пользователю. Владелец может
          переопределить их для группы или конкретного участника.
        </p>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 10 }}>
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }}>
              <span className="muted">Устройств</span>
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
                  toast("Лимит должен быть не меньше 1");
                  return;
                }
                devLimitMut.mutate(n);
              }}
              disabled={devLimitMut.isPending}
            >
              Сохранить
            </Btn>
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 10 }}>
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }}>
              <span className="muted">Трафик за период</span>
              <div style={{ display: "grid", gridTemplateColumns: "140px 92px", gap: 8 }}>
                <input
                  className="input"
                  type="number"
                  min={0}
                  step={userBytesUnit === "B" ? 1 : 0.1}
                  value={userBytesValue}
                  placeholder="пусто — без лимита"
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
              Сохранить
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
            Хранение метрик
          </div>
          <p className="muted" style={{ fontSize: 13, marginBottom: 12 }}>
            Метрики трафика и ресурсов серверов хранятся ярусно (сырьё → почасовые → посуточные агрегаты). Ограничьте
            хранение по времени или по размеру диска. {metricsUsageLine(sysQ.data.metrics)}
          </p>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }}>
              <span className="muted">Хранить подробные метрики, дней</span>
              <input
                className="input"
                type="number"
                min={0}
                style={{ width: 200 }}
                placeholder={`по умолчанию ${sysQ.data.metrics.defaultRawRetentionDays}`}
                value={metricsDays}
                onChange={(e) => setMetricsDays(e.target.value)}
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13 }}>
              <span className="muted">Лимит размера, ГБ (0 — без лимита)</span>
              <input
                className="input"
                type="number"
                min={0}
                step={0.5}
                style={{ width: 200 }}
                placeholder="0 — без лимита"
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
              Сохранить
            </Btn>
          </div>
          <p className="muted-3" style={{ fontSize: 12, marginTop: 10 }}>
            «Дней» применяется к сырью (детальные точки); агрегаты хранятся дольше. Лимит по размеру срезает старейшее
            сырьё, если суммарный размер превышен (доступен на Postgres).
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
            Резервные копии БД
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Btn sm variant="ghost" onClick={() => setImportOpen(true)}>
              <Icon name="refresh" size={15} />
              Импорт
            </Btn>
            <Btn sm onClick={() => createMut.mutate()} disabled={createMut.isPending}>
              <Icon name="plus" size={15} />
              {createMut.isPending ? "Создаём…" : "Создать бэкап"}
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
            <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 6 }}>Автоматический бэкап</div>
            <select
              className="input"
              value={sys.backupFrequency}
              disabled={freqMut.isPending}
              onChange={(e) => freqMut.mutate(e.target.value)}
              style={{ width: "100%" }}
            >
              {FREQ_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px" }}>
            <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 6 }}>Мастер-ключ</div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span
                className="badge"
                style={{
                  background: sys.masterKeySet ? "var(--ok-soft)" : "var(--warn-soft)",
                  color: sys.masterKeySet ? "var(--ok)" : "var(--warn)",
                }}
              >
                <span className="dot" style={{ background: sys.masterKeySet ? "var(--ok)" : "var(--warn)" }} />
                {sys.masterKeyFromEnv ? "из env" : sys.masterKeySet ? "задан" : "не задан"}
              </span>
              {!sys.masterKeyFromEnv && (
                <Btn sm variant="ghost" onClick={() => setKeyOpen(true)}>
                  {sys.masterKeySet ? "Сменить" : "Задать"}
                </Btn>
              )}
            </div>
          </div>
        </div>

        {sys.backups.length === 0 ? (
          <div style={{ padding: 20, textAlign: "center", color: "var(--text-3)", fontSize: 13.5 }}>Копий пока нет</div>
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
                <Btn variant="ghost" sm title="Скачать" onClick={() => downloadBackup(b.id)}>
                  <Icon name="download" size={16} />
                </Btn>
                <Btn variant="ghost" sm title="Удалить" onClick={() => setConfirmDel(b.id)}>
                  <Icon name="trash" size={16} />
                </Btn>
              </div>
            ))}
          </div>
        )}

        <p style={{ fontSize: 12, color: "var(--text-3)", marginTop: 12, lineHeight: 1.45 }}>
          Бэкап — логический дамп базы (строки всех таблиц, не зависит от версии PostgreSQL), зашифрованный ключом
          (AES-256-GCM). Файлы хранятся в томе контейнера; для восстановления на другом хосте нужен тот же ключ.
          Настройте выгрузку тома во внешнее хранилище для надёжности.
        </p>
      </div>

      {/* (4) Об инстансе */}
      <div className="card">
        <SectionLabel>Об инстансе</SectionLabel>
        <div style={{ display: "flex", flexDirection: "column" }}>
          {[
            { k: "Редакция", v: sys.edition, mono: false },
            { k: "Образ", v: sys.image, mono: true },
            { k: "Дата сборки", v: sys.built, mono: false },
            { k: "Адрес инстанса", v: sys.baseUrl, mono: true },
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
          title={`Обновление ${release0.v}`}
          onClose={() => setRelease(false)}
          footer={
            sys.updateSupported ? (
              <>
                <Btn block onClick={() => setRelease(false)}>
                  Закрыть
                </Btn>
                <Btn variant="primary" block onClick={() => upgradeMut.mutate()} disabled={upgradeMut.isPending}>
                  {upgradeMut.isPending ? "Обновляем…" : "Обновить сейчас"}
                </Btn>
              </>
            ) : (
              <Btn block onClick={() => setRelease(false)}>
                Закрыть
              </Btn>
            )
          }
        >
          <div style={{ fontSize: 12.5, color: "var(--text-3)", marginBottom: 16 }}>релиз от {release0.date}</div>

          <SectionLabel>Что нового</SectionLabel>
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

          <SectionLabel>Как обновить образ</SectionLabel>
          <div
            className="copyable"
            onClick={() => copyText(UPGRADE_CMD, toast, "Команда скопирована")}
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
              ? (MODE_HINT[sys.updateMode] ?? "Кнопка «Обновить сейчас» применит обновление автоматически. ")
              : sys.updateHint ||
                "Обновление из панели не настроено — примените команду вручную на хосте (как включить кнопку — docs/deploy/updates). "}
            Данные в PostgreSQL сохраняются, миграции применятся автоматически при старте.
          </p>
        </Modal>
      )}

      {/* подтверждение удаления бэкапа */}
      {confirmDel && (
        <Modal
          title="Удалить бэкап?"
          onClose={() => setConfirmDel(null)}
          footer={
            <>
              <Btn block onClick={() => setConfirmDel(null)}>
                Отмена
              </Btn>
              <Btn variant="danger" block onClick={() => deleteMut.mutate(confirmDel)} disabled={deleteMut.isPending}>
                {deleteMut.isPending ? "Удаляем…" : "Удалить"}
              </Btn>
            </>
          }
        >
          <p style={{ margin: 0, fontSize: 14, color: "var(--text-2)" }}>
            Резервная копия будет удалена без возможности восстановления.
          </p>
        </Modal>
      )}

      {/* мастер-ключ */}
      {keyOpen && (
        <Modal
          title={sys.masterKeySet ? "Сменить мастер-ключ" : "Задать мастер-ключ"}
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
                Отмена
              </Btn>
              <Btn
                variant="primary"
                block
                disabled={keyMut.isPending || keyValue.length < 8}
                onClick={() => keyMut.mutate(keyValue)}
              >
                {keyMut.isPending ? "Сохраняем…" : "Сохранить"}
              </Btn>
            </>
          }
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <p style={{ margin: 0, fontSize: 13.5, color: "var(--text-2)" }}>
              Мастер-ключом шифруются SSH-доступы к серверам и бэкапы. Сохраните его в надёжном месте — без него нельзя
              восстановить копию или расшифровать секреты при переносе.
            </p>
            <KeyInput value={keyValue} placeholder="Минимум 8 символов" onChange={setKeyValue} />
            <Btn sm onClick={() => downloadRecoveryKey(keyValue)} disabled={keyValue.length < 8}>
              <Icon name="download" size={15} />
              Скачать ключ (.txt)
            </Btn>
            {sys.masterKeySet && (
              <p style={{ margin: 0, fontSize: 12, color: "var(--warn)" }}>
                Секреты серверов будут перешифрованы новым ключом; старые бэкапы останутся под прежним.
              </p>
            )}
          </div>
        </Modal>
      )}

      {/* импорт (восстановление) бэкапа */}
      {importOpen && (
        <Modal
          title="Импорт бэкапа"
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
                Отмена
              </Btn>
              <Btn
                variant="danger"
                block
                disabled={importMut.isPending || !importFile || !importKey}
                onClick={() => importMut.mutate()}
              >
                {importMut.isPending ? "Восстанавливаем…" : "Восстановить"}
              </Btn>
            </>
          }
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <p style={{ margin: 0, fontSize: 13.5, color: "var(--danger)" }}>
              Текущие данные будут заменены содержимым бэкапа. Действие необратимо — рекомендуется перезапустить сервис
              после восстановления.
            </p>
            <FilePicker accept=".vhb" file={importFile} onPick={setImportFile} />
            <input
              className="input"
              type="password"
              placeholder="Мастер-ключ (которым сделан бэкап)"
              value={importKey}
              onChange={(e) => setImportKey(e.target.value)}
            />
          </div>
        </Modal>
      )}

      {/* ошибка применения обновления (лог драйвера) */}
      {updateError && (
        <Modal
          title="Обновление не применилось"
          onClose={() => setUpdateError(null)}
          footer={
            <Btn block onClick={() => setUpdateError(null)}>
              Закрыть
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
                  ? `Обновлено до ${updating.target}`
                  : updating
                    ? `Устанавливаем ${updating.target}…`
                    : "Запускаем обновление…"}
              </div>
              <div style={{ fontSize: 13, color: "var(--text-3)", marginTop: 5 }}>
                {updating?.done
                  ? "Перезагружаем страницу…"
                  : "Панель перезапустится — страница обновится автоматически, не закрывайте её"}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
