// Записывает «киношный» тур по VPN Hub через Playwright.
// Хореография (титры, подписи, курсор, подсветки) — через page.evaluate + Web Animations API
// (обходит CSP script-src 'self'). Логин — отдельным контекстом, запись — уже авторизованной.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const BASE = process.env.BASE || "http://127.0.0.1:8000";
const OUT = process.env.OUT || resolve(dirname(fileURLToPath(import.meta.url)), ".build/out");
const PHONE = "+79990000101";
const PASS = "DemoPass123!";
const W = 1600, H = 1000;

mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- директор: всё выполняется в контексте страницы через evaluate ----
async function dirInit(page) {
  await page.addStyleTag({
    content: `
    #reel-cursor{position:fixed;z-index:2147483647;width:22px;height:22px;margin:-11px 0 0 -11px;
      border-radius:50%;background:rgba(20,20,25,.85);box-shadow:0 0 0 6px rgba(120,120,255,.18),0 4px 14px rgba(0,0,0,.35);
      pointer-events:none;left:50%;top:60%;transition:none}
    #reel-cap{position:fixed;z-index:2147483646;left:0;right:0;bottom:46px;display:flex;justify-content:center;pointer-events:none}
    #reel-cap .b{max-width:78%;padding:16px 30px;border-radius:16px;background:rgba(15,16,22,.82);
      color:#fff;font:600 30px/1.25 'Golos Text',-apple-system,Segoe UI,Roboto,sans-serif;
      letter-spacing:.2px;box-shadow:0 12px 40px rgba(0,0,0,.35);backdrop-filter:blur(8px);opacity:0;text-align:center}
    #reel-ring{position:fixed;z-index:2147483645;border:3px solid rgba(108,99,255,.9);border-radius:16px;
      box-shadow:0 0 0 4px rgba(108,99,255,.18);pointer-events:none;opacity:0}
    #reel-title{position:fixed;inset:0;z-index:2147483647;display:flex;flex-direction:column;align-items:center;
      justify-content:center;gap:18px;background:radial-gradient(1200px 700px at 50% 35%,#2b2f6b 0%,#14152a 55%,#0c0d18 100%);
      color:#fff;text-align:center;opacity:0}
    #reel-title .logo{width:96px;height:96px;border-radius:26px;background:#0c0d18;display:flex;align-items:center;
      justify-content:center;font:800 52px/1 'Golos Text',sans-serif;box-shadow:0 20px 60px rgba(0,0,0,.5),inset 0 0 0 1px rgba(255,255,255,.06)}
    #reel-title h1{font:800 68px/1.05 'Golos Text',sans-serif;margin:6px 0 0}
    #reel-title p{font:500 30px/1.3 'Golos Text',sans-serif;opacity:.82;margin:0}
    #reel-title .url{font:600 22px/1 'JetBrains Mono',ui-monospace,monospace;opacity:.6;margin-top:8px}
    `,
  });
  await page.evaluate(() => {
    if (!document.getElementById("reel-cursor")) {
      const c = document.createElement("div"); c.id = "reel-cursor"; document.body.appendChild(c);
      const cap = document.createElement("div"); cap.id = "reel-cap";
      cap.innerHTML = '<div class="b"></div>'; document.body.appendChild(cap);
      const ring = document.createElement("div"); ring.id = "reel-ring"; document.body.appendChild(ring);
    }
  });
}

async function titleCard(page, title, sub, url, ms = 3000) {
  await page.evaluate(({ title, sub, url }) => {
    const el = document.createElement("div"); el.id = "reel-title";
    el.innerHTML = `<div class="logo">V</div><h1>${title}</h1><p>${sub}</p>${url ? `<div class="url">${url}</div>` : ""}`;
    document.body.appendChild(el);
    el.animate([{ opacity: 0, transform: "scale(1.04)" }, { opacity: 1, transform: "scale(1)" }],
      { duration: 600, easing: "cubic-bezier(.2,.7,.2,1)", fill: "forwards" });
    el.querySelector("h1").animate([{ opacity: 0, transform: "translateY(14px)" }, { opacity: 1, transform: "none" }],
      { duration: 700, delay: 150, easing: "cubic-bezier(.2,.7,.2,1)", fill: "backwards" });
    el.querySelector("p").animate([{ opacity: 0, transform: "translateY(12px)" }, { opacity: .82, transform: "none" }],
      { duration: 700, delay: 320, easing: "cubic-bezier(.2,.7,.2,1)", fill: "both" });
  }, { title, sub, url });
  await sleep(ms);
  await page.evaluate(() => {
    const el = document.getElementById("reel-title"); if (!el) return;
    const a = el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 520, easing: "ease", fill: "forwards" });
    a.onfinish = () => el.remove();
  });
  await sleep(560);
}

async function caption(page, text) {
  await page.evaluate((text) => {
    const b = document.querySelector("#reel-cap .b"); if (!b) return;
    b.getAnimations?.().forEach((a) => a.cancel());
    b.textContent = text;
    b.animate([{ opacity: 0, transform: "translateY(16px)" }, { opacity: 1, transform: "none" }],
      { duration: 520, easing: "cubic-bezier(.2,.7,.2,1)", fill: "forwards" });
  }, text);
}
async function captionOut(page) {
  await page.evaluate(() => {
    const b = document.querySelector("#reel-cap .b"); if (!b) return;
    b.animate([{ opacity: 1 }, { opacity: 0, transform: "translateY(10px)" }], { duration: 360, fill: "forwards" });
  });
  await sleep(380);
}

async function cursorTo(page, sel, dur = 900) {
  const box = await page.locator(sel).first().boundingBox().catch(() => null);
  if (!box) return null;
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  await page.evaluate(({ x, y, dur }) => {
    const c = document.getElementById("reel-cursor"); if (!c) return;
    const cur = c.getBoundingClientRect();
    c.animate([{ left: cur.left + "px", top: cur.top + "px" }, { left: x + "px", top: y + "px" }],
      { duration: dur, easing: "cubic-bezier(.5,0,.15,1)", fill: "forwards" });
  }, { x, y, dur });
  await sleep(dur);
  return box;
}

async function ripple(page) {
  await page.evaluate(() => {
    const c = document.getElementById("reel-cursor"); if (!c) return;
    c.animate([{ boxShadow: "0 0 0 6px rgba(120,120,255,.18),0 4px 14px rgba(0,0,0,.35)" },
      { boxShadow: "0 0 0 20px rgba(120,120,255,0),0 4px 14px rgba(0,0,0,.35)" }], { duration: 550, easing: "ease-out" });
  });
  await sleep(280);
}

async function highlight(page, sel, ms = 1600) {
  const box = await page.locator(sel).first().boundingBox().catch(() => null);
  if (!box) return;
  await page.evaluate(({ box, ms }) => {
    const r = document.getElementById("reel-ring"); if (!r) return;
    const pad = 8;
    r.style.left = (box.x - pad) + "px"; r.style.top = (box.y - pad) + "px";
    r.style.width = (box.width + pad * 2) + "px"; r.style.height = (box.height + pad * 2) + "px";
    const a = r.animate([{ opacity: 0, transform: "scale(1.02)" }, { opacity: 1, transform: "scale(1)" }],
      { duration: 420, easing: "cubic-bezier(.2,.7,.2,1)", fill: "forwards" });
    setTimeout(() => r.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 380, fill: "forwards" }), ms);
  }, { box, ms });
}

async function scene(page, url, dataMs = 1400) {
  // networkidle не годится: постоянный SSE /stream не даёт сети «уснуть». Ждём контент явно.
  await page.goto(BASE + url, { waitUntil: "domcontentloaded" });
  await page.locator(".nav-btn").first().waitFor({ timeout: 8000 }).catch(() => {});
  await page.evaluate(() => window.scrollTo(0, 0));
  await sleep(dataMs);
  await dirInit(page);
  await sleep(300);
}

// ---------------------------------------------------------------- run
const browser = await chromium.launch();

// 1) логинимся отдельным контекстом, сохраняем состояние
const authCtx = await browser.newContext({ viewport: { width: W, height: H }, locale: "ru-RU", colorScheme: "light" });
const ap = await authCtx.newPage();
await ap.addInitScript(() => { try { localStorage.setItem("vpnhub.lang", "ru"); localStorage.setItem("vpnhub.theme", "light"); } catch {} });
await ap.goto(BASE + "/", { waitUntil: "domcontentloaded" });
await ap.waitForSelector(".auth-card", { timeout: 15000 });
await ap.locator(".phone-field input").fill(PHONE);
await ap.locator('input[type="password"]').fill(PASS);
await ap.locator('input[type="password"]').press("Enter");
await ap.waitForSelector(".nav-btn", { timeout: 20000 });
const storageState = await authCtx.storageState();
await authCtx.close();

// 2) записывающий контекст — уже авторизован
const ctx = await browser.newContext({
  viewport: { width: W, height: H }, deviceScaleFactor: 1, locale: "ru-RU", colorScheme: "light",
  storageState, recordVideo: { dir: OUT, size: { width: W, height: H } },
});
await ctx.addInitScript(() => { try { localStorage.setItem("vpnhub.lang", "ru"); localStorage.setItem("vpnhub.theme", "light"); } catch {} });
const page = await ctx.newPage();

// --- сценарий ---
// интро: титр показываем сразу (пока /home догружается под ним), без «мелькания»
await page.goto(BASE + "/home", { waitUntil: "domcontentloaded" });
await page.locator(".nav-btn").first().waitFor({ timeout: 8000 }).catch(() => {});
await dirInit(page);
await titleCard(page, "VPN Hub", "Своя VPN-инфраструктура за минуты", "", 2800);
await page.evaluate(() => window.scrollTo(0, 0));
await caption(page, "Одна панель для всей вашей VPN-инфраструктуры");
await cursorTo(page, ".nav-btn"); await sleep(1400); await captionOut(page);

await scene(page, "/servers");
await caption(page, "Свои VPS: Amnezia, OpenVPN, Outline, Hysteria2");
await cursorTo(page, "text=Амстердам-1"); await ripple(page); await sleep(1500); await captionOut(page);

await scene(page, "/servers/demo-ams/protocols", 2000);
await caption(page, "Панель сама ставит и обслуживает VPN по SSH");
await sleep(2600); await captionOut(page);

await scene(page, "/groups/demo-family");
await caption(page, "Раздавайте доступ близким — по ссылке-приглашению");
await cursorTo(page, "text=Пригласить участника"); await ripple(page); await sleep(1500); await captionOut(page);

await scene(page, "/available");
await caption(page, "Готовый конфиг и QR — за пару кликов");
await cursorTo(page, "text=Получить"); await ripple(page); await sleep(1500); await captionOut(page);

await scene(page, "/monitoring", 2200);
await caption(page, "Кто онлайн и сколько трафика — в реальном времени");
await sleep(2600); await captionOut(page);

await scene(page, "/finance", 2200);
await caption(page, "Себестоимость и цена продажи — под контролем");
await sleep(2400); await captionOut(page);

await titleCard(page, "VPN Hub", "Self-hosted · Open source", "github.com/AlexeyShalaev/vpn-hub", 3200);

await sleep(400);
await page.close();
await ctx.close();
await browser.close();
console.log("RECORD_DONE");
