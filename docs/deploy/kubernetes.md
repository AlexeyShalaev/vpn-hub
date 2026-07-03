# Kubernetes

Разворачивает VPN Hub в вашем кластере через готовые манифесты **Kustomize** (`deploy/k8s/`).
Выбирайте этот способ, если у вас уже есть кластер, Ingress-контроллер и привычка катить приложения
через `kubectl` / GitOps. Для одного VPS проще [Docker Compose](compose.md).

## Требования

- **Кластер Kubernetes 1.27+** (используются только стабильные API).
- **`kubectl`** — Kustomize встроен, применяем через `kubectl apply -k` (отдельный `kustomize` не нужен).
- **Ingress-контроллер** (например, ingress-nginx) — базовые манифесты рассчитаны на `ingressClassName: nginx`.
- **cert-manager + ClusterIssuer** для автоматического TLS (в Ingress прописан
  `cert-manager.io/cluster-issuer: letsencrypt-prod`).
- **StorageClass** с `ReadWriteOnce`-томами — под PVC панели и (для встроенной БД) том PostgreSQL.
- **Мастер-ключ восстановления** — сгенерируйте заранее: `openssl rand -hex 32`
  (см. [Требования → Мастер-ключ](requirements.md#master-key)).

!!! info "Namespace в режиме restricted"
    Namespace `vpnhub` помечен Pod Security Standard **`restricted`**. Все манифесты (панель и Postgres)
    написаны под него: контейнеры работают non-root, без привилегий, с `drop: ["ALL"]`. Свои патчи
    держите в тех же рамках, иначе поды не пройдут admission.

## 1. Получите манифесты

Склонируйте репозиторий (или скачайте каталог `deploy/k8s/`) и перейдите в него. Все дальнейшие
команды выполняются относительно `deploy/k8s/`.

```sh
git clone https://github.com/AlexeyShalaev/vpn-hub.git
cd vpn-hub/deploy/k8s
```

Структура каталога:

| Путь | Что внутри |
|---|---|
| `base/` | namespace, configmap, PVC панели, Deployment, Service, Ingress + `kustomization.yaml`. БД-агностично. |
| `base/secret.example.yaml` | **шаблон** Secret — копируется в `secret.yaml` и применяется вручную. |
| `overlays/bundled-db/` | база + встроенный **PostgreSQL 17** (Service + StatefulSet). |
| `overlays/external-db/` | база без БД — адрес вашего Postgres берётся из `DATABASE_URL`. |

## 2. Создайте namespace и Secret

Сначала создайте namespace — Secret и всё остальное живут внутри него.

```sh
kubectl apply -f base/namespace.yaml
```

Затем скопируйте шаблон Secret в `secret.yaml` и заполните его.

```sh
cp base/secret.example.yaml base/secret.yaml
```

Откройте `base/secret.yaml` и подставьте значения в `stringData`:

| Ключ | Значение |
|---|---|
| `VPNHUB_MASTER_KEY` | результат `openssl rand -hex 32`. **Обязателен на `https`.** |
| `POSTGRES_PASSWORD` | пароль встроенного Postgres (для `overlays/external-db` не нужен). |
| `DATABASE_URL` | DSN с драйвером `asyncpg`. Для встроенной БД host = **`vpnhub-postgres`** (имя Service). Для внешней — хост managed-Postgres, обычно `?ssl=require`. |

Для встроенной БД строка выглядит так (пароль должен совпадать с `POSTGRES_PASSWORD`):

```
postgresql+asyncpg://vpnhub:ВАШ_ПАРОЛЬ@vpnhub-postgres:5432/vpnhub
```

Первичного админа можно задать здесь же (`VPNHUB_ADMIN_PHONE` + `VPNHUB_ADMIN_PASSWORD`) — иначе при
первом входе откроется setup-экран. Задавайте либо **обе** переменные, либо ни одной.

Примените Secret:

```sh
kubectl apply -f base/secret.yaml
```

!!! danger "Не коммитьте `secret.yaml`"
    `secret.yaml` содержит мастер-ключ и пароль БД в открытом виде. Добавьте его в `.gitignore`.
    Для GitOps не кладите секреты в репозиторий как есть — используйте **SOPS**, **Sealed Secrets**
    или **External Secrets Operator**.

!!! danger "Мастер-ключ восстановления"
    Из `VPNHUB_MASTER_KEY` выводятся ключи шифрования **SSH-доступов к вашим серверам** и
    **резервных копий**. **Потеря ключа = потеря доступа к секретам и невозможность восстановить
    бэкапы.** Сохраните его в менеджере паролей отдельно от кластера. На `https` панель **не
    стартует** с дефолтным/пустым ключом.

## 3. Выберите overlay и настройте домен

Есть два overlay:

=== "Встроенная БД (`bundled-db`)"

    Разворачивает панель **и** PostgreSQL 17 как StatefulSet со своим томом. Ничего внешнего не нужно.

=== "Внешняя БД (`external-db`)"

    Только панель. Адрес вашей БД берётся из `DATABASE_URL` в Secret (managed RDS / Cloud SQL / Neon /
    свой Postgres). `POSTGRES_PASSWORD` не нужен. Подробности — [Внешняя база данных](external-db.md).

**Запиньте версию образа.** В `overlays/<выбранный>/kustomization.yaml` замените `latest` на
конкретный релиз (semver или `major.minor`) — так `apply` детерминирован и обновление контролируемо:

```yaml
images:
  - name: ghcr.io/alexeyshalaev/vpn-hub
    newTag: "1.2.3"
```

**Пропишите свой домен.** В `overlays/<выбранный>/patch-hostname.yaml` замените `vpn.example.com` на
ваш FQDN — один патч правит Ingress (host + TLS-`secretName`) и `VPNHUB_BASE_URL` разом. Меняйте домен
**в обоих** документах файла.

!!! warning "Домен, Ingress и мастер-ключ должны сойтись"
    `VPNHUB_BASE_URL` должен совпадать с `host` в Ingress. На `https` (а прод — всегда `https`) панель
    требует валидный `VPNHUB_MASTER_KEY` — без него под не поднимется. Если `ingressClassName` вашего
    контроллера не `nginx` или ClusterIssuer называется не `letsencrypt-prod`, поправьте
    `base/ingress.yaml` под свой кластер.

## 4. Установите в кластер

Примените выбранный overlay (`base/namespace.yaml` и Secret вы уже применили выше):

=== "Встроенная БД"

    ```sh
    kubectl apply -k overlays/bundled-db
    ```

=== "Внешняя БД"

    ```sh
    kubectl apply -k overlays/external-db
    ```

Дождитесь готовности rollout — панель на старте накатывает миграции, это может занять до нескольких минут:

```sh
kubectl -n vpnhub rollout status deploy/vpnhub
```

Проверьте, что поды в статусе `Running`:

```sh
kubectl -n vpnhub get pods
```

Ожидаемый вывод (для встроенной БД — плюс под Postgres):

```
NAME                      READY   STATUS    RESTARTS   AGE
vpnhub-6f8c9d7b5f-abcde   1/1     Running   0          2m
vpnhub-postgres-0         1/1     Running   0          2m
```

Откройте `https://<ваш-домен>` — увидите форму входа (или **setup-экран**, если не задавали
`VPNHUB_ADMIN_*`), где нужно ввести мастер-ключ и создать администратора.

!!! danger "Держите панель на `replicas: 1`"
    Фоновый **планировщик** (бэкапы, мониторинг, синхронизация) запускается **в каждом поде** —
    лидер-элекшена нет. При `replicas > 1` задачи начнут дублироваться: лишняя SSH-нагрузка на ваши
    серверы и конкуренция за том бэкапов. В манифесте `replicas: 1` и `strategy: Recreate` заданы
    осознанно — не увеличивайте реплики, пока планировщик не вынесен отдельно.

!!! info "Миграции при масштабировании безопасны, планировщик — нет"
    Миграции на старте сериализованы транзакционным advisory-lock: даже если поды случайно поднимутся
    параллельно, второй дождётся первого и увидит уже накатанную схему. А вот планировщик так не
    защищён — это ещё одна причина держать `replicas: 1`.

!!! info "Пробы: `/readyz` и `/healthz`"
    readinessProbe ходит на `/readyz` — он проверяет БД и отвечает **503 при недоступной базе**,
    поэтому под корректно выводится из эндпоинтов Service, пока БД недоступна. startupProbe и
    livenessProbe ходят на `/healthz` (без БД) — старт и рестарты не зависят от временных проблем
    с базой. Логи — `kubectl -n vpnhub logs`, метрики — `/metrics`.

## Встроенный PostgreSQL

Overlay `bundled-db` поднимает `postgres:17` одним StatefulSet с `ReadWriteOnce`-томом (10Gi по
умолчанию, `volumeClaimTemplates`). Панель ходит на него по имени Service `vpnhub-postgres:5432`.

!!! warning "PGDATA — подкаталог тома (уже сделано)"
    В StatefulSet `PGDATA=/var/lib/postgresql/data/pgdata` — данные лежат в **подкаталоге** тома, а не
    в его корне. Иначе `initdb` спотыкается о `lost+found` на свежем PVC. Это уже прописано в манифесте
    — не убирайте.

!!! danger "Один StatefulSet = один primary без failover"
    `vpnhub-postgres` — одиночный инстанс (`replicas: 1`), без реплик и автоматического переключения.
    Для семьи/друзей этого достаточно; для HA-БД используйте оператор **CloudNativePG** (реплики,
    failover, backup) и подключите панель как к внешней БД через `DATABASE_URL` — это advanced-сценарий,
    см. [Внешняя база данных](external-db.md).

## Обновление и откат

Обновление — это смена тега образа и повторный `apply`. Сначала обновите `newTag` в
`overlays/<выбранный>/kustomization.yaml` на новую версию, затем примените и дождитесь rollout:

```sh
kubectl apply -k overlays/bundled-db
kubectl -n vpnhub rollout status deploy/vpnhub
```

Разово (без правки файла) образ можно сменить и так:

```sh
kubectl -n vpnhub set image deploy/vpnhub vpnhub=ghcr.io/alexeyshalaev/vpn-hub:1.2.4
```

Если что-то пошло не так — откатите Deployment на предыдущую ревизию:

```sh
kubectl -n vpnhub rollout undo deploy/vpnhub
```

!!! danger "Сделайте бэкап перед обновлением"
    Обновление накатывает миграции БД. Перед сменой версии снимите `.vhb`-бэкап (из панели или CLI) и
    убедитесь, что мастер-ключ сохранён — без него бэкап не восстановить. Подробнее про порядок
    обновления и pre-flight — [Обновление](updates.md).

## Ingress: смотрите вперёд

!!! warning "ingress-nginx: конец жизни в марте 2026"
    Проект **ingress-nginx** объявлен EOL (~март 2026). Сам **Ingress API** остаётся стабильным и
    рабочим — манифесты продолжат применяться. Но на **новых** кластерах предпочтите **Gateway API**
    или другой поддерживаемый Ingress-контроллер (Traefik, Envoy Gateway и т. п.). Для перевода
    существующих Ingress на Gateway API есть утилита **`ingress2gateway`**. Если у вас уже стоит
    ingress-nginx — можно оставаться на нём до миграции, ничего срочно ломать не нужно.

---

**Дальше:** настройте [HTTPS и домен →](reverse-proxy.md) или загляните в справочник
[Переменные окружения →](configuration.md).
