import { describe, expect, it } from "vitest";
import { canonicalLocation, countryLabel, flagEmoji, normLoc } from "./locations";

describe("location canonicalization", () => {
  it("normalizes case, ё, brackets and punctuation", () => {
    expect(normLoc("Австрия (Вена)")).toBe("австрия вена");
    expect(normLoc("Россия, Москва")).toBe("россия москва");
    expect(normLoc("  Hong  Kong ")).toBe("hong kong");
  });

  it("merges every UAE variant across providers into one key + bilingual label", () => {
    const keys = ["ОАЭ", "UAE", "Арабские Эмираты", "Дубай"].map((r) => canonicalLocation(r));
    for (const k of keys) {
      expect(k.key).toBe("AE");
      expect(k.label).toBe("ОАЭ / UAE");
    }
  });

  it.each([
    // раскладка «сырой регион → код страны» по реальным данным провайдеров
    ["Мадрид", "ES"],
    ["Spain", "ES"],
    ["Испания", "ES"],
    ["Париж", "FR"],
    ["France", "FR"],
    ["Германия", "DE"],
    ["Germany", "DE"],
    ["Нидерланды", "NL"],
    ["Netherlands", "NL"],
    ["Амстердам", "NL"],
    ["США", "US"],
    ["USA", "US"],
    ["Нью-Джерси", "US"],
    ["Азия, Сингапур", "SG"],
    ["Singapore", "SG"],
    ["Сингапур", "SG"],
    ["Россия, Москва", "RU"],
    ["Россия (Санкт-Петербург)", "RU"],
    ["Москва, 2nd Gen Intel", "RU"],
    ["Казахстан", "KZ"],
    ["Алматы", "KZ"],
    ["kzg3", "KZ"],
    ["Ташкент", "UZ"],
    ["Торонто", "CA"],
    ["Сан-Паулу", "BR"],
    ["United Kingdom", "GB"],
    ["Великобритания", "GB"],
    ["Czech Republic", "CZ"],
    ["Hong Kong", "HK"],
    ["Австрия (Вена)", "AT"],
    ["Австрия (Грац)", "AT"],
    ["Италия (Милан)", "IT"],
    // формат UltaHost «Город, Страна» + новые страны (SA/ZA/NG/KR)
    ["Frankfurt, Germany", "DE"],
    ["Amsterdam, Netherlands", "NL"],
    ["Seattle, USA", "US"],
    ["Chicago, USA", "US"],
    ["Toronto, Canada", "CA"],
    ["Sao Paulo, Brazil", "BR"],
    ["Bogota, Colombia", "CO"],
    ["Mexico City, Mexico", "MX"],
    ["Riyadh, Saudi Arabia", "SA"],
    ["Johannesburg, South Africa", "ZA"],
    ["Lagos, Nigeria", "NG"],
    ["Istanbul, Turkey", "TR"],
    ["New Delhi, India", "IN"],
    ["Kuala Lumpur, Malaysia", "MY"],
    ["Seoul, South Korea", "KR"],
    ["Tokyo, Japan", "JP"],
    ["Sydney, Australia", "AU"],
    // локации 62YUN (русские названия стран)
    ["Финляндия", "FI"],
    ["Гонконг", "HK"],
    ["Германия", "DE"],
    ["США", "US"],
  ])("maps %s -> %s", (raw, code) => {
    expect(canonicalLocation(raw).key).toBe(code);
  });

  it("keeps two Austrian cities as ONE Austria group", () => {
    expect(canonicalLocation("Австрия (Вена)").key).toBe(canonicalLocation("Австрия (Грац)").key);
  });

  it("does not merge unrecognized regions — each stays separate as itself", () => {
    const a = canonicalLocation("Марс, кратер Гейла");
    const b = canonicalLocation("Неизвестная зона 51");
    expect(a.key).not.toBe(b.key);
    expect(a.key.startsWith("x:")).toBe(true);
    expect(a.label).toBe("Марс, кратер Гейла");
  });

  it("does not false-match Austria vs Australia", () => {
    expect(canonicalLocation("Австрия").key).toBe("AT");
    expect(canonicalLocation("Австралия").key).toBe("AU");
  });

  it("does not merge a generic 'Republic' into Czech Republic", () => {
    expect(canonicalLocation("Dominican Republic").key).toBe("DO");
    expect(canonicalLocation("Republic").key.startsWith("x:")).toBe(true);
  });
});

describe("world-wide country coverage", () => {
  it.each([
    ["Lisbon, Portugal", "PT"],
    ["Португалия", "PT"],
    ["Hanoi, Vietnam", "VN"],
    ["Manila, Philippines", "PH"],
    ["Tbilisi", "GE"],
    ["Грузия", "GE"],
    ["Atlanta, Georgia, USA", "US"], // штат Джорджия не путаем со страной
    ["Нью-Джерси", "US"], // и Нью-Джерси — с островом Джерси
    ["New Jersey", "US"],
  ])("maps %s to %s", (region, code) => {
    expect(canonicalLocation(region).key).toBe(code);
  });

  it("labels any ISO code bilingually and keeps manual labels", () => {
    expect(countryLabel("pt")).toBe("Португалия / Portugal");
    expect(countryLabel("AE")).toBe("ОАЭ / UAE");
    expect(countryLabel("XX")).toBe("XX");
  });

  it("builds flag emoji from a country code", () => {
    expect(flagEmoji("de")).toBe("🇩🇪");
    expect(flagEmoji("nope")).toBe("");
  });
});
