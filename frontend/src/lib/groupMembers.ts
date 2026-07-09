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
