import { describe, expect, it } from "vitest";
import { keysToInvalidate } from "./events";

describe("keysToInvalidate", () => {
  it("server + id → список серверов, конкретный сервер и его доступы", () => {
    expect(keysToInvalidate("server", "srv-1")).toEqual([["servers"], ["server", "srv-1"], ["server-access", "srv-1"]]);
  });

  it("server без id → только список серверов (коарс-грейн сигнал)", () => {
    expect(keysToInvalidate("server", null)).toEqual([["servers"]]);
    expect(keysToInvalidate("server", undefined)).toEqual([["servers"]]);
  });

  it("sync → только список серверов", () => {
    expect(keysToInvalidate("sync", "srv-1")).toEqual([["servers"]]);
  });

  it("неизвестный топик → пусто", () => {
    expect(keysToInvalidate("whatever", "x")).toEqual([]);
  });
});
