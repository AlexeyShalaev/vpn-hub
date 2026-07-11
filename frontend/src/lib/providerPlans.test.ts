import { describe, expect, it } from "vitest";
import {
  convertAmount,
  currencySymbol,
  dynamicPlanProviderId,
  dynamicPlanProviderIdByName,
  findDynamicPlanProvider,
  fmtMoney,
  monthlyPrice,
  monthlyPriceIn,
  providerNameById,
} from "./providerPlans";
import type { Provider, ProviderPlan } from "./types";

const DAYS_PER_MONTH = 365.25 / 12;
const basePlan: ProviderPlan = {
  id: "p1",
  name: "Plan",
  region: "Москва",
  cpu: 1,
  ramGb: 2,
  diskGb: 20,
  diskType: "NVMe",
  portMbps: 200,
  trafficTb: 1,
  price: 100,
  currency: "RUB",
  period: "month",
};

const providers: Provider[] = [
  { id: "firstbyte", name: "FirstByte", url: "", blurb: "", tags: [] },
  { id: "ufo", name: "UFO Hosting", url: "", blurb: "", tags: [] },
  { id: "ishosting", name: "ISHOSTING", url: "", blurb: "", tags: [] },
  { id: "ahost", name: "AHost", url: "", blurb: "", tags: [] },
  { id: "serverspace", name: "Serverspace", url: "", blurb: "", tags: [] },
];

describe("provider plan helpers", () => {
  it.each([
    ["FirstByte", "firstbyte"],
    ["UFO Hosting", "ufo"],
    ["ufo-hosting", "ufo"],
    ["ISHOSTING", "ishosting"],
    ["is hosting", "ishosting"],
    ["AHost", "ahost"],
    ["ahost.eu", "ahost"],
    ["Serverspace", "serverspace"],
    ["serverspace.ru", "serverspace"],
  ])("normalizes %s to %s", (name, expected) => {
    expect(dynamicPlanProviderIdByName(name)).toBe(expected);
  });

  it("resolves every built-in dynamic provider from catalog data", () => {
    for (const provider of providers) {
      expect(dynamicPlanProviderId(provider, provider.name)).toBe(provider.id);
      expect(findDynamicPlanProvider(providers, provider.name)?.id).toBe(provider.id);
    }
  });

  it("uses display labels for recognized providers missing from the catalog", () => {
    expect(providerNameById([], "ufo")).toBe("UFO Hosting");
    expect(providerNameById([], "serverspace")).toBe("Serverspace");
  });
});

describe("price normalization to a single currency per month", () => {
  const rates = { RUB: 1, USD: 90, EUR: 100 }; // RUB за 1 единицу валюты

  it("keeps month, scales day and minute, treats unknown period as monthly", () => {
    expect(monthlyPrice(500, "month")).toBe(500);
    expect(monthlyPrice(10, "day")).toBeCloseTo(10 * DAYS_PER_MONTH);
    expect(monthlyPrice(1, "minute")).toBeCloseTo(DAYS_PER_MONTH * 24 * 60);
    expect(monthlyPrice(500, "week")).toBe(500);
  });

  it("converts amounts through the RUB base", () => {
    expect(convertAmount(1, "USD", "RUB", rates)).toBe(90);
    expect(convertAmount(180, "RUB", "USD", rates)).toBe(2);
    expect(convertAmount(100, "EUR", "USD", rates)).toBeCloseTo((100 * 100) / 90);
  });

  it("short-circuits equal currencies without needing a rate", () => {
    expect(convertAmount(42, "GBP", "GBP", {})).toBe(42);
  });

  it("returns null when a rate is missing or non-positive", () => {
    expect(convertAmount(1, "GBP", "RUB", rates)).toBeNull();
    expect(convertAmount(1, "USD", "JPY", rates)).toBeNull();
    expect(convertAmount(1, "USD", "RUB", { RUB: 0, USD: 90 })).toBeNull();
  });

  it("combines period and currency for a plan's monthly price in a target currency", () => {
    expect(monthlyPriceIn({ ...basePlan, price: 2, currency: "USD" }, "RUB", rates)).toBe(180);
    expect(monthlyPriceIn({ ...basePlan, price: 100, currency: "RUB" }, "RUB", rates)).toBe(100);
    expect(monthlyPriceIn({ ...basePlan, price: 3, period: "day", currency: "RUB" }, "RUB", rates)).toBeCloseTo(
      3 * DAYS_PER_MONTH,
    );
    expect(monthlyPriceIn({ ...basePlan, currency: "GBP" }, "RUB", rates)).toBeNull();
  });

  it("formats money with a currency symbol and sensible precision", () => {
    expect(fmtMoney(1234, "RUB")).toContain("₽");
    expect(fmtMoney(1234, "RUB")).not.toContain(".");
    expect(fmtMoney(5.5, "USD")).toContain("$");
    expect(currencySymbol("EUR")).toBe("€");
    expect(currencySymbol("XYZ")).toBe("XYZ");
  });
});
