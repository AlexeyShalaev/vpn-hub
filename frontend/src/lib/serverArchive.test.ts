import { describe, expect, it } from "vitest";
import { archivedDate, isArchived, splitByArchive } from "./serverArchive";

describe("serverArchive", () => {
  it("treats null and undefined archivedAt as active", () => {
    expect(isArchived({ archivedAt: null })).toBe(false);
    expect(isArchived({ archivedAt: undefined })).toBe(false);
    expect(isArchived({ archivedAt: 0 })).toBe(true);
    expect(isArchived({ archivedAt: 1_700_000_000 })).toBe(true);
  });

  it("splits servers and keeps their order", () => {
    const list = [
      { id: "a", archivedAt: null },
      { id: "b", archivedAt: 1 },
      { id: "c", archivedAt: null },
      { id: "d", archivedAt: 2 },
    ];
    const { active, archived } = splitByArchive(list);
    expect(active.map((s) => s.id)).toEqual(["a", "c"]);
    expect(archived.map((s) => s.id)).toEqual(["b", "d"]);
  });

  it("formats the archive date and is empty for active servers", () => {
    expect(archivedDate({ archivedAt: null })).toBe("");
    const at = new Date(2026, 10, 12, 15, 0, 0).getTime() / 1000;
    expect(archivedDate({ archivedAt: at }, "ru-RU")).toBe("12.11.2026");
  });
});
