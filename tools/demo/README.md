# tools/demo — демо-данные, скриншоты и промо-ролик

Воспроизводимая генерация маркетинговых материалов VPN Hub из **синтетических** данных
(никаких реальных серверов/пользователей). Всё гоняется на изолированной БД `vpnhub_demo` —
реальные данные не затрагиваются.

```
tools/demo/
├── seed_demo.py            # синтетические данные: серверы, протоколы, трафик, метрики, финансы…
├── run-demo-backend.sh     # изолированный demo-инстанс (vpnhub_demo + backend, monitor/sync off)
├── screenshots/capture.mjs # обход всех экранов → docs/assets/screenshots/*.png
└── reel/                   # промо-ролик
    ├── gen-assets.mjs      #   фон/маска/тень для «плавающего окна» (Playwright-скриншоты)
    ├── record.mjs          #   ХОРЕОГРАФИЯ тура: сцены, титры, подписи, курсор  ← правится здесь
    └── compose.sh          #   ffmpeg: окно на градиенте + тень → docs/assets/reel/{reel.mp4,reel.gif}
```

## Требования

- Локальный Postgres: `make db-up` (контейнер `vpnhub-pg` на :5433).
- `uv` (backend), Node.js, **ffmpeg** (`brew install ffmpeg`).
- Разово: зависимости Playwright
  ```sh
  cd tools/demo && npm install && npx playwright install chromium
  ```

## Как запустить

Два терминала.

**Терминал 1 — демо-инстанс** (создаст `vpnhub_demo`, засеет синтетику, поднимет backend :8000):
```sh
make demo-up          # = ./tools/demo/run-demo-backend.sh
```

**Терминал 2 — материалы:**
```sh
make screenshots      # 22 скрина RU/светлая тема → docs/assets/screenshots/
make reel             # промо-ролик → docs/assets/reel/reel.mp4 + reel.gif
```

Логин на демо-инстансе: `+7 999 000 01 01` / `DemoPass123!`.

## Как переделать анимацию ролика

Вся хореография — в [`reel/record.mjs`](reel/record.mjs):

- **сцены** — массив вызовов `scene(page, url)` + `caption()` / `cursorTo()` / `highlight()` / `titleCard()`;
- **подписи** — текст в `caption(...)`; **тайминги** — `sleep(ms)`;
- **титр/аутро** — `titleCard(title, sub, url, ms)`;
- **вид «окна»** (градиент, скругление, тень) — [`reel/gen-assets.mjs`](reel/gen-assets.mjs);
- **кодек/размер/тайминг GIF** — [`reel/compose.sh`](reel/compose.sh).

Правки в `record.mjs` не требуют перегенерации ассетов:
```sh
node reel/record.mjs && bash reel/compose.sh
```

Анимация делается через `page.evaluate` + Web Animations API — так она обходит CSP приложения
(`script-src 'self'` не даёт инжектить `<script>`; `evaluate` выполняется в изолированном мире).

## Промежуточные файлы

`reel/.build/` (запись `*.webm`, ассеты `*.png`) и `node_modules/` — в `.gitignore`.
В репозитории лежит только итог: `docs/assets/reel/reel.mp4` и `reel.gif`.
