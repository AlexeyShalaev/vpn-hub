import { describe, expect, it } from "vitest";
import {
  type AddMemberForm,
  buildAddMemberBody,
  countUniqueNonSelfGroupMembers,
  defaultAddMemberMode,
  hasNonSelfGroupMember,
} from "./groupMembers";
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

const form = (extra: Partial<AddMemberForm> = {}): AddMemberForm => ({
  mode: "pick",
  role: "member",
  userId: null,
  name: "",
  phone: "",
  ...extra,
});

describe("defaultAddMemberMode", () => {
  it("opens the picker when there is someone to pick", () => {
    expect(defaultAddMemberMode(3)).toBe("pick");
  });

  it("falls back to the phone invite when the list is empty", () => {
    expect(defaultAddMemberMode(0)).toBe("phone");
  });
});

describe("buildAddMemberBody", () => {
  it("sends only userId and role in pick mode", () => {
    expect(buildAddMemberBody(form({ userId: "u1", role: "admin", name: "ignored", phone: "+7999" }))).toEqual({
      body: { userId: "u1", role: "admin" },
    });
  });

  it("asks to pick a user when nothing is selected", () => {
    expect(buildAddMemberBody(form())).toEqual({ error: "groupDetail.pickUserFirst" });
  });

  it("sends trimmed name and phone in phone mode", () => {
    expect(buildAddMemberBody(form({ mode: "phone", userId: "u1", name: "  Аня ", phone: " +79991234567 " }))).toEqual({
      body: { name: "Аня", role: "member", phone: "+79991234567" },
    });
  });

  it("omits an empty phone", () => {
    expect(buildAddMemberBody(form({ mode: "phone", name: "Аня", phone: "  " }))).toEqual({
      body: { name: "Аня", role: "member" },
    });
  });

  it("requires a name in phone mode", () => {
    expect(buildAddMemberBody(form({ mode: "phone", name: "   " }))).toEqual({ error: "groupDetail.enterMemberName" });
  });
});
