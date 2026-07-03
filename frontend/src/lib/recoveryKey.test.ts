import { describe, expect, it } from "vitest";
import { generateRecoveryKey } from "./recoveryKey";

const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const FORMAT = new RegExp(`^([${ALPHABET}]{5}-){3}[${ALPHABET}]{5}$`);

describe("generateRecoveryKey", () => {
  it("формат: 4 группы по 5 символов через дефис", () => {
    expect(generateRecoveryKey()).toMatch(FORMAT);
  });

  it("алфавит без неоднозначных символов (нет I, O, 0, 1)", () => {
    const joined = Array.from({ length: 50 }, generateRecoveryKey).join("");
    expect(joined).not.toMatch(/[IO01]/);
  });

  it("ключи не повторяются между вызовами (достаточно энтропии)", () => {
    const keys = new Set(Array.from({ length: 200 }, generateRecoveryKey));
    expect(keys.size).toBe(200);
  });
});
