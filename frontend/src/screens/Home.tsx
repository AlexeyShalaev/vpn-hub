// Главная-сводка владельца (задача №10): онбординг-чеклист сверху + карточки-ссылки
// с агрегатами по серверам, группам/участникам и последними событиями. Все агрегаты
// считаются на клиенте из уже существующих запросов (listServers/listGroups/listEvents) —
// новых backend-эндпоинтов не заводим.
import { useQuery } from "@tanstack/react-query";
import { OnboardingChecklist } from "../components/OnboardingChecklist";
import { Btn, Icon, ScreenHeader, Spinner } from "../components/ui";
import { countUniqueNonSelfGroupMembers } from "../lib/groupMembers";
import type { TKey } from "../lib/i18n";
import { useT } from "../lib/i18n";
import * as q from "../lib/queries";
import type { Screen } from "../nav";
import { useNav } from "../nav";
import { useStore } from "../store";
import { EventList } from "./Events";

// Карточка-ссылка: клик уводит в соответствующий раздел. Стиль повторяет ServerCard.
function SummaryCard({
  icon,
  title,
  go,
  children,
}: {
  icon: string;
  title: string;
  go: Screen;
  children: React.ReactNode;
}) {
  const nav = useNav((n) => n.go);
  return (
    <button
      onClick={() => nav(go)}
      style={{
        textAlign: "left",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        padding: "var(--pad)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r)",
        background: "var(--surface)",
        boxShadow: "var(--shadow)",
        cursor: "pointer",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ color: "var(--text-3)", display: "inline-flex", flex: "none" }}>
          <Icon name={icon} size={18} />
        </span>
        <span style={{ flex: 1, minWidth: 0, fontWeight: 700, fontSize: 15 }}>{title}</span>
        <span style={{ flex: "none", color: "var(--text-3)", display: "inline-flex" }}>
          <Icon name="chevron" size={16} />
        </span>
      </div>
      {children}
    </button>
  );
}

function Metric({ big, label }: { big: string; label: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: 26, fontWeight: 800, lineHeight: 1, letterSpacing: "-.02em" }}>{big}</span>
      <span style={{ fontSize: 12.5, color: "var(--text-3)" }}>{label}</span>
    </div>
  );
}

function MutedLine({ textKey }: { textKey: TKey }) {
  const t = useT();
  return <span style={{ fontSize: 12.5, color: "var(--text-3)" }}>{t(textKey)}</span>;
}

export function HomeScreen() {
  const t = useT();
  const go = useNav((n) => n.go);
  const meId = useStore((s) => s.me?.id ?? null);

  const { data: servers, isLoading: serversLoading } = useQuery({
    queryKey: ["servers"],
    queryFn: q.listServers,
    refetchInterval: 60000,
  });
  const { data: groups, isLoading: groupsLoading } = useQuery({
    queryKey: ["groups"],
    queryFn: q.listGroups,
  });
  // Последние 5 событий — компактный список через EventList (переиспользуем из Events).
  const eventsParams = { limit: 5 };
  const { data: events } = useQuery({
    queryKey: ["events", eventsParams],
    queryFn: () => q.listEvents(eventsParams),
    refetchInterval: 30000,
  });
  // сводный расход на серверы за 30 дней (accrual, раздельно по валютам)
  const { data: cost } = useQuery({
    queryKey: ["financeCost"],
    queryFn: q.financeCost,
    refetchInterval: 60000,
    retry: 2,
  });
  const costTotals = cost?.totals ?? [];

  const online = (servers ?? []).filter((s) => s.status === "online").length;
  const offline = (servers ?? []).filter((s) => s.status === "offline").length;
  const groupCount = groups?.length ?? 0;
  // Суммарно уникальных приглашённых участников по всем группам, без самого владельца.
  const memberCount = countUniqueNonSelfGroupMembers(groups ?? [], meId);
  const recentEvents = (events ?? []).slice(0, 5);

  return (
    <div className="stack">
      <ScreenHeader title={t("home.title")} sub={t("home.sub")} />

      <OnboardingChecklist />

      <div className="grid">
        <SummaryCard icon="servers" title={t("home.serversTitle")} go="servers">
          {serversLoading ? (
            <Spinner />
          ) : (servers ?? []).length === 0 ? (
            <MutedLine textKey="home.serversEmpty" />
          ) : (
            <div style={{ display: "flex", gap: 24 }}>
              <Metric big={String(online)} label={t("home.serversOnline", { n: online })} />
              <Metric big={String(offline)} label={t("home.serversOffline", { n: offline })} />
            </div>
          )}
        </SummaryCard>

        <SummaryCard icon="groups" title={t("home.groupsTitle")} go="groups">
          {groupsLoading ? (
            <Spinner />
          ) : groupCount === 0 ? (
            <MutedLine textKey="home.groupsEmpty" />
          ) : (
            <div style={{ display: "flex", gap: 24 }}>
              <Metric big={String(groupCount)} label={t("home.groupsCount", { groups: groupCount })} />
              <Metric big={String(memberCount)} label={t("home.membersCount", { members: memberCount })} />
            </div>
          )}
        </SummaryCard>

        <SummaryCard icon="finance" title="Расходы на серверы" go="finance">
          {costTotals.length === 0 ? (
            <div className="muted" style={{ fontSize: 13 }}>
              Задайте цену серверов на их страницах — здесь появится расход за 30 дней.
            </div>
          ) : (
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
              {costTotals.map((c) => (
                <Metric
                  key={c.currency}
                  big={`${c.amount.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ${c.currency}`}
                  label="за 30 дней"
                />
              ))}
            </div>
          )}
        </SummaryCard>
      </div>

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
    </div>
  );
}
