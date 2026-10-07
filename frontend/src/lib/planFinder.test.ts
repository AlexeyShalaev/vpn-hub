import { describe, expect, it } from "vitest";
import { DEFAULT_PLAN_FILTER, type FinderPlan, rankPlans } from "./planFinder";

function plan(id: string, over: Partial<FinderPlan> = {}): FinderPlan {
  return {
    id,
    name: id,
    region: "Germany",
    cpu: 1,
    ramGb: 1,
    diskGb: 20,
    diskType: "NVMe",
    portMbps: 1000,
    trafficTb: null,
    price: 100,
    currency: "RUB",
    period: "month",
    available: true,
    providerId: "p1",
    providerLabel: "Provider One",
    ...over,
  };
}

const rates = { RUB: 1, USD: 100 };
const all: FinderPlan[] = [
  plan("cheap-rub", { price: 300, ramGb: 1 }),
  plan("usd", { price: 5, currency: "USD", ramGb: 2, cpu: 2, region: "Amsterdam, Netherlands", providerId: "p2" }),
  plan("big", { price: 2000, ramGb: 16, cpu: 8, diskGb: 320, diskType: "SSD", trafficTb: 10 }),
  plan("hdd", { price: 400, ramGb: 2, diskType: "HDD", portMbps: 0, diskGb: 1000 }),
  plan("sold-out", { price: 10, available: false }),
  plan("no-rate", { price: 1, currency: "XYZ" }),
];
const ids = (ps: { id: string }[]) => ps.map((p) => p.id);

describe("plan finder", () => {
  it("sorts by monthly price in one currency, unconvertible plans last, sold-out hidden", () => {
    expect(ids(rankPlans(all, DEFAULT_PLAN_FILTER, rates))).toEqual(["cheap-rub", "hdd", "usd", "big", "no-rate"]);
  });

  it("filters by CPU, disk size, disk type, port speed and unlimited traffic", () => {
    const f = DEFAULT_PLAN_FILTER;
    expect(ids(rankPlans(all, { ...f, cpuMin: "2" }, rates))).toEqual(["usd", "big"]);
    expect(ids(rankPlans(all, { ...f, diskMin: "300" }, rates))).toEqual(["hdd", "big"]);
    expect(ids(rankPlans(all, { ...f, diskTypes: ["SSD", "HDD"] }, rates))).toEqual(["hdd", "big"]);
    expect(ids(rankPlans(all, { ...f, portMin: "100" }, rates))).not.toContain("hdd");
    expect(ids(rankPlans(all, { ...f, unlimitedOnly: true }, rates))).not.toContain("big");
  });

  it("matches query words against plan, location and provider names", () => {
    const f = { ...DEFAULT_PLAN_FILTER, query: "amsterdam" };
    expect(ids(rankPlans(all, f, rates))).toEqual(["usd"]);
    expect(ids(rankPlans(all, { ...DEFAULT_PLAN_FILTER, query: "provider big" }, rates))).toEqual(["big"]);
  });

  it("applies the budget in the chosen currency and filters by canonical region", () => {
    const f = { ...DEFAULT_PLAN_FILTER, currency: "USD", priceMax: "4" };
    expect(ids(rankPlans(all, f, rates))).toEqual(["cheap-rub", "hdd"]);
    expect(ids(rankPlans(all, { ...DEFAULT_PLAN_FILTER, regions: ["NL"] }, rates))).toEqual(["usd"]);
  });

  it("sorts by price per GB of RAM, by RAM and by CPU", () => {
    const f = { ...DEFAULT_PLAN_FILTER, onlyAvailable: true };
    expect(ids(rankPlans(all, { ...f, sort: "pricePerGb" }, rates)).slice(0, 2)).toEqual(["big", "hdd"]);
    expect(ids(rankPlans(all, { ...f, sort: "ram" }, rates))[0]).toBe("big");
    expect(ids(rankPlans(all, { ...f, sort: "cpu" }, rates))[0]).toBe("big");
  });
});
