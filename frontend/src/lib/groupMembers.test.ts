import { describe, expect, it } from "vitest";
import { countUniqueNonSelfGroupMembers, hasNonSelfGroupMember } from "./groupMembers";
import type { Group, Member } from "./types";

function member(id: string, userId: string | null, extra: Partial<Member> = {}): Member {
  return {
    id,
    userId,
    name: id,
    role: "member",
    status: "active",
    phone: "",
    maxDevices: null,
    maxBytes: null,
    ...extra,
  };
}

function group(id: string, members: Member[]): Group {
  return {
    id,
    name: id,
    token: `${id}-token`,
    maxDevices: null,
    maxBytes: null,
    members,
    access: { pools: [], servers: {} },
  };
}

describe("group member progress helpers", () => {
  it("does not count the owner auto-member as an invited participant", () => {
    const groups = [group("g1", [member("mb-owner", "u-owner")])];

    expect(hasNonSelfGroupMember(groups, "u-owner")).toBe(false);
    expect(countUniqueNonSelfGroupMembers(groups, "u-owner")).toBe(0);
  });

  it("counts pending invited members without a user id", () => {
    const groups = [group("g1", [member("mb-owner", "u-owner"), member("mb-guest", null, { status: "invited" })])];

    expect(hasNonSelfGroupMember(groups, "u-owner")).toBe(true);
    expect(countUniqueNonSelfGroupMembers(groups, "u-owner")).toBe(1);
  });

  it("deduplicates the same registered user across groups", () => {
    const groups = [
      group("g1", [member("mb-owner", "u-owner"), member("mb-friend-1", "u-friend")]),
      group("g2", [member("mb-friend-2", "u-friend")]),
    ];

    expect(countUniqueNonSelfGroupMembers(groups, "u-owner")).toBe(1);
  });
});
