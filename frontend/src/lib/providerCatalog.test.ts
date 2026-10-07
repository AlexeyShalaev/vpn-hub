import { describe, expect, it } from "vitest";
import { EMPTY_CATALOG_FILTER, facetCounts, filterProviders, providerBlurb } from "./providerCatalog";
import type { Provider } from "./types";

function provider(id: string, over: Partial<Provider> = {}): Provider {
  return {
    id,
    name: id,
    url: `https://${id}.example/`,
    blurb: "",
    blurbEn: "",
    tags: [],
    hq: "",
    countries: [],
    payments: [],
    ...over,
  };
}

const list: Provider[] = [
  provider("timeweb", { name: "Timeweb Cloud", hq: "RU", countries: ["RU", "KZ", "NL"], payments: ["ru_card", "sbp"] }),
  provider("vultr", { name: "Vultr", hq: "US", countries: ["US", "NL", "JP", "DE"], payments: ["card", "paypal"] }),
  provider("njalla", { name: "Njalla", hq: "SC", countries: ["SE"], payments: ["crypto"], tags: ["Без KYC"] }),
  provider("beget", { name: "Beget", blurb: "Облачные серверы в Санкт-Петербурге", hq: "RU", countries: ["RU"] }),
];
const live = new Set(["timeweb", "vultr"]);
const hasLive = (p: Provider) => live.has(p.id);
const ids = (ps: Provider[]) => ps.map((p) => p.id);

describe("catalog filtering", () => {
  it("returns everything in catalog order with an empty filter", () => {
    expect(ids(filterProviders(list, EMPTY_CATALOG_FILTER, hasLive))).toEqual(["timeweb", "vultr", "njalla", "beget"]);
  });

  it("matches every query word against name, description and tags, ignoring case and ё", () => {
    const f = { ...EMPTY_CATALOG_FILTER, query: "санкт-петербурге облачные" };
    expect(ids(filterProviders(list, f, hasLive))).toEqual(["beget"]);
    expect(ids(filterProviders(list, { ...EMPTY_CATALOG_FILTER, query: "без kyc" }, hasLive))).toEqual(["njalla"]);
    expect(ids(filterProviders(list, { ...EMPTY_CATALOG_FILTER, query: "VULTR" }, hasLive))).toEqual(["vultr"]);
    expect(ids(filterProviders(list, { ...EMPTY_CATALOG_FILTER, query: "япония" }, hasLive))).toEqual(["vultr"]);
  });

  it("treats countries and payments as any-of and combines groups with AND", () => {
    expect(ids(filterProviders(list, { ...EMPTY_CATALOG_FILTER, countries: ["NL", "SE"] }, hasLive))).toEqual([
      "timeweb",
      "vultr",
      "njalla",
    ]);
    const f = { ...EMPTY_CATALOG_FILTER, countries: ["NL"], payments: ["sbp" as const, "crypto" as const] };
    expect(ids(filterProviders(list, f, hasLive))).toEqual(["timeweb"]);
  });

  it("filters by company country and live-plan support", () => {
    expect(ids(filterProviders(list, { ...EMPTY_CATALOG_FILTER, hq: ["RU"] }, hasLive))).toEqual(["timeweb", "beget"]);
    expect(ids(filterProviders(list, { ...EMPTY_CATALOG_FILTER, liveOnly: true }, hasLive))).toEqual([
      "timeweb",
      "vultr",
    ]);
  });

  it("sorts by name or by number of locations without mutating the input", () => {
    const byName = filterProviders(list, { ...EMPTY_CATALOG_FILTER, sort: "name" }, hasLive);
    expect(ids(byName)).toEqual(["beget", "njalla", "timeweb", "vultr"]);
    const byLocations = filterProviders(list, { ...EMPTY_CATALOG_FILTER, sort: "locations" }, hasLive);
    expect(ids(byLocations)[0]).toBe("vultr");
    expect(ids(list)).toEqual(["timeweb", "vultr", "njalla", "beget"]);
  });
});

describe("facet counts", () => {
  it("counts each value once per provider and sorts by frequency", () => {
    expect(facetCounts([["NL", "RU", "NL"], ["NL"], ["SE"], []])).toEqual([
      ["NL", 2],
      ["RU", 1],
      ["SE", 1],
    ]);
  });
});

describe("bilingual description", () => {
  it("falls back to the Russian blurb when there is no English one", () => {
    const p = provider("x", { blurb: "Русский", blurbEn: "" });
    expect(providerBlurb(p, "en")).toBe("Русский");
    expect(providerBlurb({ ...p, blurbEn: "English" }, "en")).toBe("English");
    expect(providerBlurb({ ...p, blurbEn: "English" }, "ru")).toBe("Русский");
  });
});
