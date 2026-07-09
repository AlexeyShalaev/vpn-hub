import { describe, expect, it } from "vitest";
import {
  dynamicPlanProviderId,
  dynamicPlanProviderIdByName,
  findDynamicPlanProvider,
  providerNameById,
} from "./providerPlans";
import type { Provider } from "./types";

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
