import { tg } from "./i18n";

export type TrafficUnit = "B" | "KB" | "MB" | "GB" | "TB";

const TRAFFIC_UNIT_FACTOR: Record<TrafficUnit, number> = {
  B: 1,
  KB: 1024,
  MB: 1024 ** 2,
  GB: 1024 ** 3,
  TB: 1024 ** 4,
};

const TRAFFIC_UNIT_ORDER: TrafficUnit[] = ["B", "KB", "MB", "GB", "TB"];

export function getTrafficUnits(): { value: TrafficUnit; label: string }[] {
  return [
    { value: "B", label: tg("unit.byte") },
    { value: "KB", label: tg("unit.kilobyte") },
    { value: "MB", label: tg("unit.megabyte") },
    { value: "GB", label: tg("unit.gigabyte") },
    { value: "TB", label: tg("unit.terabyte") },
  ];
}

// Существующие потребители импортируют массив `TRAFFIC_UNITS` напрямую (не как хук),
// поэтому сохраняем то же имя экспорта для совместимости.
export const TRAFFIC_UNITS: { value: TrafficUnit; label: string }[] = getTrafficUnits();

function trimNumber(value: number): string {
  return String(+value.toFixed(2));
}

export function trafficValueToBytes(value: string, unit: TrafficUnit): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!normalized) return null;
  const n = Number.parseFloat(normalized);
  return Number.isFinite(n) && n > 0 ? Math.round(n * TRAFFIC_UNIT_FACTOR[unit]) : null;
}

export function bytesToTrafficInput(bytes: number | null, preferredUnit: TrafficUnit = "GB") {
  if (bytes == null) return { value: "", unit: preferredUnit };
  const unit = [...TRAFFIC_UNIT_ORDER].reverse().find((u) => bytes >= TRAFFIC_UNIT_FACTOR[u]) ?? "B";
  return { value: trimNumber(bytes / TRAFFIC_UNIT_FACTOR[unit]), unit };
}

export function convertTrafficInputUnit(value: string, from: TrafficUnit, to: TrafficUnit): string {
  const bytes = trafficValueToBytes(value, from);
  return bytes == null ? "" : trimNumber(bytes / TRAFFIC_UNIT_FACTOR[to]);
}
