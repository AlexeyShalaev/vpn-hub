export type TrafficUnit = "B" | "KB" | "MB" | "GB" | "TB";

export const TRAFFIC_UNITS: { value: TrafficUnit; label: string }[] = [
  { value: "B", label: "Б" },
  { value: "KB", label: "КБ" },
  { value: "MB", label: "МБ" },
  { value: "GB", label: "ГБ" },
  { value: "TB", label: "ТБ" },
];

const TRAFFIC_UNIT_FACTOR: Record<TrafficUnit, number> = {
  B: 1,
  KB: 1024,
  MB: 1024 ** 2,
  GB: 1024 ** 3,
  TB: 1024 ** 4,
};

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
  const unit = [...TRAFFIC_UNITS].reverse().find((u) => bytes >= TRAFFIC_UNIT_FACTOR[u.value])?.value ?? "B";
  return { value: trimNumber(bytes / TRAFFIC_UNIT_FACTOR[unit]), unit };
}

export function convertTrafficInputUnit(value: string, from: TrafficUnit, to: TrafficUnit): string {
  const bytes = trafficValueToBytes(value, from);
  return bytes == null ? "" : trimNumber(bytes / TRAFFIC_UNIT_FACTOR[to]);
}
