# HTTPS и домен

Как опубликовать панель по **HTTPS на домене**. Reverse-proxy терминирует TLS и проксирует запросы
на приложение, а сам порт приложения наружу не выставляется — прокси ходит к нему по внутренней сети.

## Зачем это нужно

Панель управления VPN — это доступ к SSH-ключам ваших серверов и к бэкапам. Публиковать её по
**голому HTTP** наружу небезопасно. На `https` панель ведёт себя иначе:

- включается **HSTS** (браузер запоминает, что домен только по HTTPS);
- **требуется валидный мастер-ключ** — с дефолтным/пустым ключом панель на `https` не стартует.

Практический вывод: задайте `VPNHUB_BASE_URL=https://ваш-домен`, а порт приложения **не публикуйте
наружу** — держите его на `127.0.0.1` (как в дефолтном compose), и пусть прокси обращается к
приложению по имени сервиса во внутренней docker-сети.

!!! danger "На https нужен валидный мастер-ключ"
    Как только `VPNHUB_BASE_URL` начинается с `https://`, приложение **откажется стартовать** с
    дефолтным/пустым ключом. Сгенерируйте и задайте `VPNHUB_MASTER_KEY` (`openssl rand -hex 32`)
    **до** перехода на HTTPS — см. [Требования → Мастер-ключ](requirements.md#master-key).

## Требования

- Работающий стек VPN Hub (см. [Docker Compose](compose.md)). Приложение слушает **8000** внутри
  контейнера.
- **Домен** и доступ к его DNS: заведите `A`-запись (и `AAAA`, если есть IPv6) на IP этого сервера.
- Открытые на файрволе **80/tcp** и **443/tcp** (80 нужен для выпуска сертификата Let's Encrypt).
- Заданный `VPNHUB_MASTER_KEY` в `.env` (обязателен на `https`).

---

## Способ A — Caddy (проще всего, авто-TLS)

Caddy сам получает и продлевает сертификат Let's Encrypt. В репозитории есть готовый оверлей
`caddy.compose.yaml` + `Caddyfile` — домен подставляется в него из переменной `VPNHUB_DOMAIN`,
редактировать файлы не нужно.

!!! tip "Ставили скриптом? Всё уже сделано"
    `install.sh --domain vpn.example.com` (в том числе повторный запуск поверх живой установки)
    скачивает оверлей, прописывает все переменные и закрепляет его в `COMPOSE_FILE` —
    ничего из этого раздела делать не нужно. См. [Скрипт установки](scripts.md).

Для ручной Compose-установки добавьте три строки в `.env`:

```sh title=".env"
COMPOSE_FILE=compose.yaml:caddy.compose.yaml
VPNHUB_DOMAIN=vpn.example.com
VPNHUB_BASE_URL=https://vpn.example.com
```

`COMPOSE_FILE` закрепляет оверлей за стеком: любой `docker compose up -d` (и `update.sh`) видит
оба файла, двойной `-f` не нужен, обновление не «разберёт» Caddy.

Проверьте, что DNS уже указывает на сервер, а порты 80/443 открыты на файрволе:

```sh
dig +short vpn.example.com      # должен вернуть IP этого сервера
```

Поднимите стек:

```sh
docker compose up -d
```

Убедитесь, что контейнеры подняты, а Caddy слушает 80/443:

```console
$ docker compose ps
NAME            IMAGE                                    STATUS         PORTS
vpnhub-app-1    ghcr.io/alexeyshalaev/vpn-hub:latest     Up (healthy)   127.0.0.1:8000->8000/tcp
vpnhub-caddy-1  caddy:2                                  Up             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
vpnhub-db-1     postgres:17                              Up (healthy)   5432/tcp
```

Откройте `https://vpn.example.com` — панель отдаётся уже по HTTPS с валидным сертификатом; при первом
входе появится setup-экран (или форма логина, если задан первичный админ).

!!! info "Сертификаты живут на томе"
    Выданные сертификаты Caddy хранит на томе `caddy-data`. Он объявлен в оверлее — не удаляйте его:
    при пересоздании контейнера сертификаты переиспользуются, иначе рискуете упереться в
    rate-limit Let's Encrypt. Caddy также слушает `443/udp` — это HTTP/3, отдельной настройки не требует.

!!! tip "Не публикуйте порт приложения наружу"
    В дефолтном `compose.yaml` порт приложения замаплен на `127.0.0.1:8000`, а Caddy ходит к нему по
    внутренней сети как `app:8000`. Так и оставьте: наружу смотрят только 80/443 Caddy. Менять
    `VPNHUB_HTTP_ADDR` на `0.0.0.0` при работе через прокси не нужно.

---

## Способ B — Traefik v3

Если у вас уже есть Traefik v3 как edge-роутер, добавьте приложению **labels** (Traefik сам возьмёт
сертификат через настроенный `certresolver`). Порт приложения — 8000.

```yaml title="фрагмент сервиса app в compose"
services:
  app:
    image: ghcr.io/alexeyshalaev/vpn-hub:${VPNHUB_TAG:-latest}
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.vpnhub.rule=Host(`vpn.example.com`)"
      - "traefik.http.routers.vpnhub.entrypoints=websecure"
      - "traefik.http.routers.vpnhub.tls.certresolver=le"
      - "traefik.http.services.vpnhub.loadbalancer.server.port=8000"
```

Не публикуйте порт приложения через `ports:` — Traefik обращается к контейнеру по общей docker-сети.
В `.env` так же задайте `VPNHUB_BASE_URL=https://vpn.example.com` и `VPNHUB_TRUSTED_PROXY=1`
(панель за прокси — иначе rate-limit будет считать всех клиентов одним IP), а `certresolver`
(здесь `le`) должен быть определён в статической конфигурации самого Traefik.

---

## Способ C — nginx

nginx терминирует TLS и проксирует на приложение. Порт приложения при этом должен быть доступен
nginx: если nginx на том же хосте, оставьте маппинг на `127.0.0.1:8000`.

```nginx title="фрагмент server-блока nginx"
server {
    listen 443 ssl;
    server_name vpn.example.com;

    ssl_certificate     /etc/letsencrypt/live/vpn.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/vpn.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    }
}
```

Сертификат выпускается отдельно (например, `certbot`). Так же задайте
`VPNHUB_BASE_URL=https://vpn.example.com` и `VPNHUB_TRUSTED_PROXY=1` — только тогда панель
поверит `X-Forwarded-For`/`X-Forwarded-Proto` из этого конфига.

---

## Kubernetes

В Kubernetes HTTPS делается не так: TLS терминирует **Ingress**, а сертификат выпускает
**cert-manager**. Домен и TLS настраиваются в `overlays/*/patch-ingress.yaml` (host Ingress) и
`patch-config.yaml` (`VPNHUB_BASE_URL`). Здесь это не дублируем — см. [Kubernetes](kubernetes.md).

---

## Заголовки и HTTPS

Внешнюю схему и адрес приложение берёт из `VPNHUB_BASE_URL`, а **не** из заголовков прокси. Задайте в
нём публичный `https`-адрес — тогда панель, увидев схему `https`:

- отдаёт заголовок **HSTS**;
- помечает сессионную куку флагом **`Secure`**;
- применяет защиту «не стартовать со встроенным ключом на `https`».

Заголовки прокси панель учитывает **только при `VPNHUB_TRUSTED_PROXY=1`** (иначе их можно
подделать снаружи):

- **`X-Forwarded-For`** — реальный IP клиента для ограничения частоты запросов и журналов
  сессий; без него в лимитах и логах будет виден IP прокси, и общий rate-limit начнёт банить
  всех пользователей разом;
- **`X-Forwarded-Proto`** — по нему кука сессии получает флаг `Secure` за TLS-терминирующим
  прокси.

`X-Forwarded-Host` / `Host` не читаются никогда. Оверлей Caddy включает
`VPNHUB_TRUSTED_PROXY=1` сам; за **своим** Traefik/nginx задайте его в `.env` вручную (оба
заголовка в примерах выше уже прокидываются). Не включайте эту переменную при прямом доступе
без прокси — подделанный `X-Forwarded-For` позволит обходить rate-limit.

!!! warning "Схема в VPNHUB_BASE_URL должна совпадать с реальной"
    Если пользователи открывают панель по `https`, то и в `VPNHUB_BASE_URL` должен стоять
    `https://<ваш-домен>`. Иначе панель сочтёт соединение незашифрованным: сессионная кука не получит
    флаг `Secure`, а HSTS не отправится. Домен указывайте свой публичный — он показывается в панели
    как «Адрес инстанса». Ссылки-приглашения панель строит из адреса в браузере, а не из этой
    переменной, поэтому на них домен здесь не влияет.

---

**Дальше:** [Docker Compose →](compose.md) · [Kubernetes →](kubernetes.md) ·
[Требования →](requirements.md)
