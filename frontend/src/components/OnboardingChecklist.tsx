// Онбординг-чеклист для нового владельца: пять шагов первого запуска.
// Прогресс НЕ хранится — он ВЫЧИСЛЯЕТСЯ из реальных данных (серверы + группы),
// поэтому чеклист «сам» отмечает шаги по мере того, как владелец их проходит,
// и полностью скрывается, когда все шаги пройдены. Компонент самодостаточен:
// его переиспользует будущий экран Home (задача №10) — здесь он лишь встроен
// вверху экрана Servers для владельца.
import { useQuery } from "@tanstack/react-query";
import { useT } from "../lib/i18n";
import type { TKey } from "../lib/i18n";
import * as q from "../lib/queries";
import type { Group, Server } from "../lib/types";
import type { Screen } from "../nav";
import { useNav } from "../nav";
import { useStore } from "../store";
import { Icon } from "./ui";

interface Step {
  key: string;
  titleKey: TKey;
  subKey: TKey;
  done: boolean;
  go: Screen;
}

// Чистая функция: из данных (серверы, группы, id владельца) — список шагов со статусом.
// Экспортируется, чтобы Home (№10) мог переиспользовать ту же логику прогресса.
export function computeSteps(servers: Server[], groups: Group[], meId: string | null): Step[] {
  const hasServer = servers.length > 0;
  const hasInstalled = servers.some((s) => s.protocols.some((p) => p.state === "installed"));
  const hasGroup = groups.length > 0;
  // Участник «кроме самого владельца»: любой member группы с id, отличным от владельца.
  const hasMember = groups.some((g) => g.members.some((m) => m.id !== meId));
  // Доступ выдан: группе открыт пул ИЛИ хотя бы один сервер.
  const hasAccess = groups.some(
    (g) => g.access.pools.length > 0 || Object.keys(g.access.servers).length > 0,
  );
  return [
    { key: "server", titleKey: "onboarding.stepServer", subKey: "onboarding.stepServerSub", done: hasServer, go: "serverForm" },
    { key: "install", titleKey: "onboarding.stepInstall", subKey: "onboarding.stepInstallSub", done: hasInstalled, go: "servers" },
    { key: "group", titleKey: "onboarding.stepGroup", subKey: "onboarding.stepGroupSub", done: hasGroup, go: "groups" },
    { key: "invite", titleKey: "onboarding.stepInvite", subKey: "onboarding.stepInviteSub", done: hasMember, go: "groups" },
    { key: "access", titleKey: "onboarding.stepAccess", subKey: "onboarding.stepAccessSub", done: hasAccess, go: "access" },
  ];
}

function StepRow({ step }: { step: Step }) {
  const t = useT();
  const go = useNav((n) => n.go);
  return (
    <button
      onClick={() => go(step.go)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        width: "100%",
        textAlign: "left",
        padding: "11px 12px",
        border: "none",
        borderRadius: "var(--r-sm)",
        background: "transparent",
        cursor: "pointer",
        opacity: step.done ? 0.65 : 1,
      }}
    >
      <span
        style={{
          flex: "none",
          width: 26,
          height: 26,
          borderRadius: "50%",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          border: step.done ? "none" : "2px solid var(--border-strong)",
          background: step.done ? "var(--accent)" : "transparent",
          color: step.done ? "#fff" : "var(--text-3)",
        }}
      >
        {step.done && <Icon name="check" size={15} />}
      </span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span
          style={{
            display: "block",
            fontWeight: 600,
            fontSize: 14.5,
            textDecoration: step.done ? "line-through" : "none",
          }}
        >
          {t(step.titleKey)}
        </span>
        <span style={{ display: "block", fontSize: 12.5, color: "var(--text-3)", marginTop: 1 }}>
          {t(step.subKey)}
        </span>
      </span>
      <span style={{ flex: "none", color: "var(--text-3)", display: "inline-flex" }}>
        <Icon name="chevron" size={16} />
      </span>
    </button>
  );
}

export function OnboardingChecklist() {
  const t = useT();
  const meId = useStore((s) => s.me?.id ?? null);

  const { data: servers } = useQuery({ queryKey: ["servers"], queryFn: q.listServers });
  const { data: groups } = useQuery({ queryKey: ["groups"], queryFn: q.listGroups });

  // Пока данные не пришли — не мигаем чеклистом (иначе он вспыхнет и свернётся).
  if (servers === undefined || groups === undefined) return null;

  const steps = computeSteps(servers, groups, meId);
  const done = steps.filter((s) => s.done).length;

  // Пройден целиком — скрываем полностью.
  if (done === steps.length) return null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        border: "1px solid var(--border)",
        borderRadius: "var(--r)",
        background: "var(--surface)",
        boxShadow: "var(--shadow)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "14px 16px",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <span style={{ color: "var(--accent)", display: "inline-flex", flex: "none" }}>
          <Icon name="sparkles" size={20} />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 16 }}>{t("onboarding.title")}</div>
          <div style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 1 }}>{t("onboarding.sub")}</div>
        </div>
        <span
          style={{
            flex: "none",
            fontSize: 12.5,
            fontWeight: 700,
            color: "var(--text-2)",
            background: "var(--surface-2)",
            borderRadius: 999,
            padding: "4px 10px",
          }}
        >
          {t("onboarding.progress", { done, total: steps.length })}
        </span>
      </div>
      <div style={{ padding: 6 }}>
        {steps.map((s) => (
          <StepRow key={s.key} step={s} />
        ))}
      </div>
    </div>
  );
}
