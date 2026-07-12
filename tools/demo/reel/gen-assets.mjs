// Генерирует ассеты для «киношного» фрейма через Playwright-скриншоты (полный контроль CSS).
// bg.png — градиентный фон 1920x1080; mask.png — белый скруглённый прямоугольник на чёрном
// (для ffmpeg alphamerge по luma); shadow.png — мягкая тень окна на прозрачном фоне.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
const OUT = process.env.ASSETS_DIR || resolve(dirname(fileURLToPath(import.meta.url)), ".build/assets");
mkdirSync(OUT, { recursive: true });

const FRAME_W = 1920, FRAME_H = 1080, WIN_W = 1600, WIN_H = 1000, R = 22;
const browser = await chromium.launch();

async function shot(html, w, h, file, omit = false) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  const p = await ctx.newPage();
  await p.setContent(`<!doctype html><html><head><style>*{margin:0;padding:0;box-sizing:border-box}</style></head><body>${html}</body></html>`);
  await p.screenshot({ path: `${OUT}/${file}`, omitBackground: omit, clip: { x: 0, y: 0, width: w, height: h } });
  await ctx.close();
}

// фон: тёмный радиальный градиент в тон титрам
await shot(
  `<div style="width:${FRAME_W}px;height:${FRAME_H}px;background:
     radial-gradient(1400px 850px at 50% 22%, #262a57 0%, #16182e 52%, #0b0c16 100%)"></div>`,
  FRAME_W, FRAME_H, "bg.png");

// маска для alphamerge (luma): белое скруглённое окно на чёрном
await shot(
  `<div style="width:${WIN_W}px;height:${WIN_H}px;background:#000">
     <div style="width:${WIN_W}px;height:${WIN_H}px;border-radius:${R}px;background:#fff"></div></div>`,
  WIN_W, WIN_H, "mask.png");

// тень: мягкий тёмный блоб на месте окна, на прозрачном фоне
await shot(
  `<div style="position:relative;width:${FRAME_W}px;height:${FRAME_H}px">
     <div style="position:absolute;left:${(FRAME_W - WIN_W) / 2}px;top:${(FRAME_H - WIN_H) / 2 + 22}px;
       width:${WIN_W}px;height:${WIN_H}px;border-radius:${R}px;background:rgba(0,0,0,.62);filter:blur(34px)"></div></div>`,
  FRAME_W, FRAME_H, "shadow.png", true);

await browser.close();
console.log("ASSETS_DONE");
