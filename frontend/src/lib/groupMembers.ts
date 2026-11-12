import type { Group, Member } from "./types";

export function isNonSelfGroupMember(member: Member, meId: string | null | undefined): boolean {
  if (member.userId === null) return true;
  if (!member.userId || !meId) return false;
  return member.userId !== meId;
}

export function hasNonSelfGroupMember(groups: Group[], meId: string | null | undefined): boolean {
  return groups.some((group) => group.members.some((member) => isNonSelfGroupMember(member, meId)));
}

export function countUniqueNonSelfGroupMembers(groups: Group[], meId: string | null | undefined): number {
  const ids = new Set<string>();
  for (const group of groups) {
    for (const member of group.members) {
      if (!isNonSelfGroupMember(member, meId)) continue;
      ids.add(member.userId ?? (member.phone ? `phone:${member.phone}` : member.id));
    }
  }
  return ids.size;
}

// ── диалог «Добавить участника»: выбор зарегистрированного пользователя или приглашение по телефону ──

export type AddMemberMode = "pick" | "phone";
export type MemberRole = "admin" | "member";

export type AddMemberBody = { userId: string; role: MemberRole } | { name: string; role: MemberRole; phone?: string };

export interface AddMemberForm {
  mode: AddMemberMode;
  role: MemberRole;
  userId: string | null;
  name: string;
  phone: string;
}

/** Режим по умолчанию: выбор из списка, если есть кого выбрать, иначе приглашение по телефону. */
export function defaultAddMemberMode(candidateCount: number): AddMemberMode {
  return candidateCount > 0 ? "pick" : "phone";
}

/** Тело POST /groups/{id}/members из формы диалога, либо ключ ошибки валидации. */
export function buildAddMemberBody(
  form: AddMemberForm,
): { body: AddMemberBody } | { error: "groupDetail.pickUserFirst" | "groupDetail.enterMemberName" } {
  if (form.mode === "pick") {
    return form.userId ? { body: { userId: form.userId, role: form.role } } : { error: "groupDetail.pickUserFirst" };
  }
  const name = form.name.trim();
  if (!name) return { error: "groupDetail.enterMemberName" };
  const phone = form.phone.trim();
  return { body: { name, role: form.role, ...(phone ? { phone } : {}) } };
}
