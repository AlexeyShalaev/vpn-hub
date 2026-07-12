// Playwright-скрипт снятия скриншотов всех экранов VPN Hub для документации.
// Логинится реальной формой (CSRF через фронт), форсит RU + светлую тему, снимает full-page.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const BASE = process.env.BASE || "http://127.0.0.1:8000";
const OUT = process.env.OUT || resolve(dirname(fileURLToPath(import.meta.url)), "../../../docs/assets/screenshots");
const PHONE = "+79990000101";
const PASS = "DemoPass123!";

const AMS = "demo-ams"; // Амстердам-1 (awg+xray+openvpn, здоров)
const MSK = "demo-msk"; // Москва-1 (xray + hysteria2-ошибка + мультихоп)
const FAMILY = "demo-family";

// [файл, url, ждать-селектор?]
const SCREENS = [
  ["02-home", "/home"],
  ["03-servers", "/servers"],
  ["04-server-connection", `/servers/${AMS}`],
  ["05-server-protocols", `/servers/${AMS}/protocols`],
  ["06-server-monitoring", `/servers/${AMS}/monitoring`],
  ["07-server-access", `/servers/${AMS}/access`],
  ["08-server-protocols-error", `/servers/${MSK}/protocols`],
  ["09-monitoring", "/monitoring"],
  ["10-finance", "/finance"],
  ["11-access", "/access"],
  ["12-events", "/events"],
  ["13-groups", "/groups"],
  ["14-group-detail", `/groups/${FAMILY}`],
  ["15-catalog", "/catalog"],
  ["16-server-form", "/servers/new"],
  ["17-users", "/users"],
  ["18-system", "/system"],
  ["19-profile", "/profile"],
  ["20-available", "/available"],
  ["21-devices", "/devices"],
  ["22-setup", "/setup"],
];

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
  colorScheme: "light",
  locale: "ru-RU",
});
// форсим язык RU и светлую тему до загрузки приложения
await ctx.addInitScript(() => {
  try {
    localStorage.setItem("vpnhub.lang", "ru");
    localStorage.setItem("vpnhub.theme", "light");
    localStorage.setItem("theme", "light");
  } catch {}
});

const page = await ctx.newPage();

// --- login ---
await page.goto(BASE + "/", { waitUntil: "networkidle" });
await page.waitForSelector(".auth-card", { timeout: 15000 });
await page.screenshot({ path: `${OUT}/01-login.png`, fullPage: true });
console.log("shot 01-login");

await page.locator(".phone-field input").click();
await page.locator(".phone-field input").fill(PHONE);
await page.locator('input[type="password"]').fill(PASS);
await page.locator('input[type="password"]').press("Enter");
// дождаться загрузки приложения (появился сайдбар)
await page.waitForSelector(".nav-btn", { timeout: 20000 });
await page.waitForLoadState("networkidle");
console.log("logged in");

// --- screens ---
for (const [name, url] of SCREENS) {
  try {
    await page.goto(BASE + url, { waitUntil: "networkidle" });
    await page.waitForTimeout(1500); // дать графикам/анимациям устаканиться
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
    console.log("shot", name);
  } catch (e) {
    console.log("FAIL", name, String(e).slice(0, 120));
  }
}

await browser.close();
console.log("DONE");
