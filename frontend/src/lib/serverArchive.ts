import type { Server } from "./types";

/** Сервер в архиве: выключен и не используется, история сохранена (см. backend ServerService.archive). */
export function isArchived(s: Pick<Server, "archivedAt">): boolean {
  return s.archivedAt != null;
}

/** Разбить список серверов на рабочие и архивные (порядок внутри групп сохраняется). */
export function splitByArchive<T extends Pick<Server, "archivedAt">>(servers: T[]): { active: T[]; archived: T[] } {
  const active: T[] = [];
  const archived: T[] = [];
  for (const s of servers) (isArchived(s) ? archived : active).push(s);
  return { active, archived };
}

/** Дата ухода в архив «дд.мм.гггг» (локальная), пусто — если не в архиве. */
export function archivedDate(s: Pick<Server, "archivedAt">, locale = "ru-RU"): string {
  if (s.archivedAt == null) return "";
  return new Date(s.archivedAt * 1000).toLocaleDateString(locale, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}
