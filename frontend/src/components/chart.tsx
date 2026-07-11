// Лёгкий SVG-график линий без внешних зависимостей (recharts/chart.js не подключаем).
// Корректно деградирует при 0/1 точке (без деления на ноль в масштабировании).
import { useT } from "../lib/i18n";
import type { MetricPoint } from "../lib/types";

export interface ChartLine {
  points: MetricPoint[];
  color: string;
  label: string;
}

const W = 560;
const H = 160;
const PAD = { top: 12, right: 12, bottom: 22, left: 34 };

function niceMax(max: number): number {
  if (max <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(max));
  const n = max / pow;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * pow;
}

export function LineChart({ lines, height = H }: { lines: ChartLine[]; height?: number }) {
  const t = useT();
  const all = lines.flatMap((l) => l.points);
  const hasData = all.length > 0;
  const minAt = hasData ? Math.min(...all.map((p) => p.at)) : 0;
  const maxAt = hasData ? Math.max(...all.map((p) => p.at)) : 1;
  const spanAt = maxAt - minAt || 1; // защита от деления на ноль (одна точка)
  const rawMax = hasData ? Math.max(...all.map((p) => p.value)) : 0;
  const yMax = niceMax(rawMax);

  const plotW = W - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const x = (at: number) => PAD.left + ((at - minAt) / spanAt) * plotW;
  const y = (v: number) => PAD.top + plotH - (v / yMax) * plotH;

  const fmtTime = (at: number) =>
    new Date(at * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });

  return (
    <div style={{ width: "100%", overflowX: "auto" }}>
      <svg
        viewBox={`0 0 ${W} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ width: "100%", height: "auto", display: "block" }}
        role="img"
      >
        {/* сетка Y (0, середина, max) */}
        {[0, yMax / 2, yMax].map((v) => (
          <g key={v}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeWidth={1} />
            <text x={PAD.left - 6} y={y(v) + 3} textAnchor="end" fontSize={9} fill="var(--text-3)">
              {Math.round(v)}
            </text>
          </g>
        ))}
        {/* подписи времени: начало и конец */}
        {hasData && (
          <>
            <text x={PAD.left} y={height - 6} textAnchor="start" fontSize={9} fill="var(--text-3)">
              {fmtTime(minAt)}
            </text>
            <text x={W - PAD.right} y={height - 6} textAnchor="end" fontSize={9} fill="var(--text-3)">
              {fmtTime(maxAt)}
            </text>
          </>
        )}
        {/* линии серий */}
        {lines.map((l) =>
          l.points.length === 0 ? null : l.points.length === 1 ? (
            <circle key={l.label} cx={x(l.points[0].at)} cy={y(l.points[0].value)} r={3} fill={l.color} />
          ) : (
            <polyline
              key={l.label}
              points={l.points.map((p) => `${x(p.at)},${y(p.value)}`).join(" ")}
              fill="none"
              stroke={l.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ),
        )}
        {!hasData && (
          <text x={W / 2} y={height / 2} textAnchor="middle" fontSize={12} fill="var(--text-3)">
            {t("chart.noData")}
          </text>
        )}
      </svg>
      {/* легенда */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 6 }}>
        {lines.map((l) => (
          <span key={l.label} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12 }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: l.color, display: "inline-block" }} />
            <span style={{ color: "var(--text-2)" }}>{l.label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
