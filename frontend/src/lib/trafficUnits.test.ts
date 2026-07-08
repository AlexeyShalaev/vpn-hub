import { describe, expect, it } from "vitest";
import { bytesToTrafficInput, convertTrafficInputUnit, trafficValueToBytes } from "./trafficUnits";

describe("trafficUnits", () => {
  it("converts entered values to bytes", () => {
    expect(trafficValueToBytes("1", "B")).toBe(1);
    expect(trafficValueToBytes("1.5", "KB")).toBe(1536);
    expect(trafficValueToBytes("2", "TB")).toBe(2 * 1024 ** 4);
    expect(trafficValueToBytes("", "GB")).toBeNull();
  });

  it("picks a readable unit for existing byte limits", () => {
    expect(bytesToTrafficInput(null)).toEqual({ value: "", unit: "GB" });
    expect(bytesToTrafficInput(512)).toEqual({ value: "512", unit: "B" });
    expect(bytesToTrafficInput(1536)).toEqual({ value: "1.5", unit: "KB" });
    expect(bytesToTrafficInput(2 * 1024 ** 4)).toEqual({ value: "2", unit: "TB" });
  });

  it("converts a typed value when the user changes the unit", () => {
    expect(convertTrafficInputUnit("1024", "GB", "TB")).toBe("1");
    expect(convertTrafficInputUnit("1.5", "TB", "GB")).toBe("1536");
  });
});
