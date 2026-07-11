import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Empty, Icon, ScreenHeader, Spinner } from "../components/ui";
import type { TFunc } from "../lib/i18n";
import { useT } from "../lib/i18n";
import * as q from "../lib/queries";
import type { AuditEvent } from "../lib/types";

// Подписи типов событий для фильтра. Держим в синхроне с backend services/audit_types.py.
function typeOptions(t: TFunc): { value: string; label: string }[] {
  return [
    { value: "", label: t("events.allTypes") },
    { value: "auth.login", label: t("events.typeLogin") },
    { value: "group.join", label: t("events.typeJoin") },
    { value: "config.download", label: t("events.typeConfig") },
    { value: "access.revoke", label: t("events.typeRevoke") },
  ];
}

function actorKindLabel(t: TFunc, kind: AuditEvent["actorKind"]): string {
  const map: Record<AuditEvent["actorKind"], string> = {
    admin: t("events.actorAdmin"),
    user: t("events.actorUser"),
    system: t("events.actorSystem"),
  };
  return map[kind];
}

// Локальную дату «дд.мм.гггг» → epoch seconds начала суток (для фильтра since/until).
function dayToEpoch(day: string, endOfDay = false): number | undefined {
  if (!day) return undefined;
  const d = new Date(day);
  if (Number.isNaN(d.getTime())) return undefined;
  if (endOfDay) d.setHours(23, 59, 59, 999);
  return Math.floor(d.getTime() / 1000);
}

/** Компактный список последних событий — переиспользуется на Home. */
export function EventList({ events }: { events: AuditEvent[] }) {
  const t = useT();
  if (events.length === 0) {
    return <Empty title={t("events.emptyTitle")} sub={t("events.emptySub")} />;
  }
  return (
    <div className="stack" style={{ gap: 8 }}>
      {events.map((e) => (
        <EventRow key={e.id} event={e} />
      ))}
    </div>
  );
}

function EventRow({ event }: { event: AuditEvent }) {
  const t = useT();
  return (
    <div className="card" style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "12px 14px" }}>
      <span style={{ color: "var(--text-3)", flex: "none", marginTop: 1 }}>
        <Icon name="events" size={17} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 700, fontSize: 14 }}>{event.label}</span>
          <span style={{ fontSize: 11.5, color: "var(--text-3)" }}>{actorKindLabel(t, event.actorKind)}</span>
        </div>
        <div style={{ fontSize: 12.5, color: "var(--text-2)", marginTop: 2 }}>{event.actorName}</div>
        {event.targetId && (
          <div style={{ fontSize: 11.5, color: "var(--text-3)", marginTop: 2 }}>
            {event.targetKind ?? t("events.resource")}: {event.targetId}
          </div>
        )}
      </div>
      <div style={{ flex: "none", textAlign: "right" }}>
        <div style={{ fontSize: 12, color: "var(--text-2)" }}>{event.rel ?? event.at}</div>
        <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>{event.at}</div>
      </div>
    </div>
  );
}

export function EventsScreen() {
  const t = useT();
  const [type, setType] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");

  const params = useMemo(
    () => ({
      type: type || undefined,
      since: dayToEpoch(since),
      until: dayToEpoch(until, true),
      limit: 200,
    }),
    [type, since, until],
  );

  const { data: events, isLoading } = useQuery({
    queryKey: ["events", params],
    queryFn: () => q.listEvents(params),
    refetchInterval: 30000,
  });

  return (
    <div className="stack">
      <ScreenHeader title={t("events.title")} sub={t("events.sub")} />

      <div className="card" style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 180, flex: 1 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-2)" }}>{t("events.filterType")}</span>
          <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
            {typeOptions(t).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-2)" }}>{t("events.filterFrom")}</span>
          <input className="input" type="date" value={since} onChange={(e) => setSince(e.target.value)} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-2)" }}>{t("events.filterTo")}</span>
          <input className="input" type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
        </label>
      </div>

      {isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner />
        </div>
      ) : (
        <EventList events={events ?? []} />
      )}
    </div>
  );
}
