// «Главная» как супер-апп-лаунчер: сетка плиток-разделов (навигация по всему проекту, как в Yandex Go) +
// онбординг и последние события для владельца. Мобильная нижняя навигация оставляет только
// Главная/Серверы/Профиль, а всё остальное открывается отсюда. Агрегаты (серверы/расходы/группы)
// считаются на клиенте из уже существующих запросов — новых backend-эндпоинтов не заводим.
import { useQuery } from "@tanstack/react-query";
import { OnboardingChecklist } from "../components/OnboardingChecklist";
import { Btn, Icon, ScreenHeader } from "../components/ui";
import { countUniqueNonSelfGroupMembers } from "../lib/groupMembers";
import { useT } from "../lib/i18n";
import * as q from "../lib/queries";
import { NAV_META, type Screen, useNav } from "../nav";
import { useStore } from "../store";
import { EventList } from "./Events";

interface Tile {
  id: Screen;
  sub: string;
}

export function HomeScreen() {
  const t = useT();
  const go = useNav((n) => n.go);
  const meId = useStore((s) => s.me?.id ?? null);
  const isAdmin = useStore((s) => s.me?.isAdmin ?? false);
  const isOwner = useStore((s) => s.viewRole) === "owner";

  // владельческие агрегаты грузим только для владельца (у участника этих эндпоинтов нет)
  const { data: servers } = useQuery({
    queryKey: ["servers"],
    queryFn: q.listServers,
    refetchInterval: 60000,
    enabled: isOwner,
  });
  const { data: groups } = useQuery({ queryKey: ["groups"], queryFn: q.listGroups, enabled: isOwner });
  const eventsParams = { limit: 5 };
  const { data: events } = useQuery({
    queryKey: ["events", eventsParams],
    queryFn: () => q.listEvents(eventsParams),
    refetchInterval: 30000,
    enabled: isOwner,
  });
  const { data: cost } = useQuery({
    queryKey: ["financeCost"],
    queryFn: q.financeCost,
    refetchInterval: 60000,
    retry: 2,
    enabled: isOwner,
  });

  const online = (servers ?? []).filter((s) => s.status === "online").length;
  const total = (servers ?? []).length;
  const groupCount = groups?.length ?? 0;
  const memberCount = countUniqueNonSelfGroupMembers(groups ?? [], meId);
  const costLabel = (cost?.totals ?? [])
    .map((c) => `${c.amount.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ${c.currency}`)
    .join(" · ");
  const recentEvents = (events ?? []).slice(0, 5);

  // Плитки лаунчера: раздел + короткая подпись (живой агрегат либо описание). Разные для владельца/участника.
  const adminTiles: Tile[] = isAdmin
    ? [
        { id: "users", sub: t("home.tileUsers") },
        { id: "system", sub: t("home.tileSystem") },
      ]
    : [];
  const tiles: Tile[] = isOwner
    ? [
        { id: "servers", sub: total ? t("home.tileServers", { online, total }) : t("home.tileServersEmpty") },
        { id: "monitoring", sub: t("home.tileMonitoring") },
        { id: "finance", sub: costLabel || t("home.tileFinance") },
        {
          id: "groups",
          sub: groupCount
            ? t("home.tileGroups", { groups: groupCount, members: memberCount })
            : t("home.tileGroupsEmpty"),
        },
        { id: "access", sub: t("home.tileAccess") },
        { id: "events", sub: t("home.tileEvents") },
        ...adminTiles,
      ]
    : [
        { id: "available", sub: t("home.tileAvailable") },
        { id: "devices", sub: t("home.tileDevices") },
        { id: "setup", sub: t("home.tileSetup") },
      ];

  return (
    <div className="stack">
      <ScreenHeader title={t("home.title")} sub={t("home.sub")} />
      {isOwner && <OnboardingChecklist />}

      <div className="launcher-grid">
        {tiles.map(({ id, sub }) => (
          <button key={id} type="button" className="launcher-tile" onClick={() => go(id)}>
            <span className="launcher-icon">
              <Icon name={NAV_META[id].icon} size={24} />
            </span>
            <span className="launcher-label">{t(NAV_META[id].labelKey)}</span>
            <span className="launcher-sub">{sub}</span>
          </button>
        ))}
      </div>

      {isOwner && (
        <div className="stack" style={{ gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ flex: 1, fontWeight: 700, fontSize: 15 }}>{t("home.eventsTitle")}</span>
            <Btn variant="ghost" sm onClick={() => go("events")}>
              {t("home.eventsAll")}
              <Icon name="chevron" size={15} />
            </Btn>
          </div>
          <EventList events={recentEvents} />
        </div>
      )}
    </div>
  );
}
