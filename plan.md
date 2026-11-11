# План выполнения: Асинхронный сервис процессинга платежей

## 1. Инициализация проекта

### 1.1. Структура проекта
```
payment_service/
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app factory, lifespan
│   ├── config.py                # pydantic-settings Settings
│   ├── logging.py               # structlog конфигурация
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py              # Декларативный Base, engine, session factory
│   │   ├── models.py            # Payment, OutboxEvent (в одном файле)
│   │   └── enums.py             # Currency, PaymentStatus, NotificationStatus, OutboxStatus
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── payment.py           # Pydantic v2 DTO (Create, Response, Detail)
│   │   └── errors.py            # Единый формат ошибок
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py              # API Key (secrets.compare_digest), get_session
│   │   ├── errors.py            # Exception handlers
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py        # APIRouter
│   │       └── payments.py      # Эндпоинты платежей
│   ├── services/
│   │   ├── __init__.py
│   │   ├── payment_service.py   # create_payment, get_payment
│   │   ├── idempotency.py       # SHA-256 хеширование + логика идемпотентности
│   │   ├── outbox.py            # Запись в outbox
│   │   └── webhook.py           # Отправка webhook + retry + HMAC-подпись
│   ├── consumer/
│   │   ├── __init__.py
│   │   ├── app.py               # FastStream приложение
│   │   └── handler.py           # Обработчик payments.new
│   ├── outbox_relay/
│   │   ├── __init__.py
│   │   └── app.py               # Отдельный воркер outbox relay
│   └── broker/
│       ├── __init__.py
│       ├── topology.py           # Объявление exchange/queue/DLQ/DLX
│       └── publisher.py          # Publish helper
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_idempotency.py
│   │   └── test_webhook.py
│   └── integration/
│       ├── __init__.py
│       ├── test_full_flow.py
│       └── test_consumer.py
├── scripts/
│   └── entrypoint.sh
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_init.py
├── alembic.ini
├── docker-compose.yml
├── Dockerfile.api               # FastAPI сервис
├── Dockerfile.consumer          # Consumer сервис
├── Dockerfile.outbox-relay      # Outbox relay сервис
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

### 1.2. Файлы конфигурации
- [ ] `pyproject.toml` — зависимости: fastapi, uvicorn[standard], pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic, faststream[rabbit], httpx, structlog, python-dotenv; dev: pytest, pytest-asyncio, httpx (для тестов), ruff, mypy
- [ ] `.env.example` — DATABASE_URL, RABBITMQ_URL, API_KEY, WEBHOOK_HMAC_SECRET, WEBHOOK_TIMEOUT, RETRY_MAX_ATTEMPTS, SSRF_ALLOW_PRIVATE (для тестов)
- [ ] `.gitignore` — исключить venv/, .env, __pycache__/, *.pyc, .pytest_cache/, .mypy_cache/, .ruff_cache/, dist/
- [ ] `alembic.ini` + `alembic/env.py` — асинхронная конфигурация

---

## 2. Модели и миграции

### 2.1. Модель Payment (`src/db/models.py`)
Поля:
- `id` — UUID, primary key, default=uuid4
- `amount` — Numeric(18, 2), > 0, максимум 2 знака после запятой, ≤ 10^16
- `currency` — Enum (RUB, USD, EUR)
- `description` — String(512), nullable
- `metadata_` — JSONB, nullable, до 4 КБ сериализованного JSON
- `status` — Enum (pending, succeeded, failed), default=pending
- `idempotency_key` — String(255), unique index, not null
- `request_hash` — String(64), SHA-256 хеш нормализованного тела запроса (для 409 Conflict)
- `webhook_url` — String(2048), валидный http/https
- `created_at` — DateTime(timezone=True), server_default=now()
- `processed_at` — DateTime(timezone=True), nullable
- `notification_status` — Enum (pending, delivered, exhausted), nullable, default=pending
- `notification_attempts` — Integer, default=0
- `notification_last_error` — Text, nullable
- `notification_event_id` — UUID, nullable (стабильный event_id для идемпотентной доставки webhook)

### 2.2. Модель OutboxEvent (`src/db/models.py`)
Поля:
- `id` — UUID, primary key
- `event_type` — String(100) (напр. "payment.created")
- `aggregate_id` — UUID (id платежа)
- `payload` — JSONB
- `status` — Enum (pending, published), default=pending
- `created_at` — DateTime(timezone=True), server_default=now()
- `published_at` — DateTime(timezone=True), nullable
- `attempts` — Integer, default=0

### 2.3. Enums (`src/db/enums.py`)
- `Currency`: RUB, USD, EUR
- `PaymentStatus`: pending, succeeded, failed
- `NotificationStatus`: pending, delivered, exhausted
- `OutboxStatus`: pending, published

### 2.4. Миграции Alembic
- [ ] `alembic init alembic`
- [ ] Настроить `env.py` на асинхронный движок
- [ ] Создать первую миграцию: `alembic revision --autogenerate -m "initial"`
- [ ] Проверить миграцию: таблицы `payments` и `outbox_events`

---

## 3. API эндпоинты

### 3.1. Аутентификация (`src/api/deps.py`)
- [ ] `verify_api_key` — зависимость через `APIKeyHeader(auto_error=False)` + `Security`, сравнение через `secrets.compare_digest` (защита от timing-атак)
- [ ] `get_db_session` — async generator для сессии SQLAlchemy

### 3.2. Единый формат ошибок (`src/schemas/errors.py` + `src/api/errors.py`)
```json
{"error": {"code": "payment_not_found", "message": "...", "request_id": "..."}}
```
- `401` — `invalid_api_key`
- `404` — `payment_not_found`
- `409` — `idempotency_conflict`
- `422` — стандартный от Pydantic, обёрнутый в общий формат через exception handler

### 3.3. POST /api/v1/payments (`src/api/v1/payments.py`)
**Заголовки:**
- `X-API-Key` (обязательный)
- `Idempotency-Key` (обязательный, UUID v4 или `[A-Za-z0-9_-]{1,255}`)

**Логика (всё в одной транзакции):**
1. Проверить API Key
2. Валидировать входные данные через Pydantic v2 схему
3. Вычислить `request_hash = sha256(канонический_JSON({amount, currency, description, metadata, webhook_url}))`
4. Попробовать INSERT платежа. При `IntegrityError` (дубликат `idempotency_key`):
   - `SELECT` существующего платежа по `idempotency_key`
   - Если `request_hash` совпадает → вернуть `202` + тот же `payment_id` + заголовок `Idempotency-Replayed: true`
   - Иначе → `409 Conflict` (тот же ключ, другое тело)
5. В той же транзакции — INSERT в `outbox_events` события `payment.created`
6. COMMIT
7. Вернуть 202 Accepted: `{ payment_id, status: "pending", created_at }`

**Pydantic схемы:**
- `PaymentCreateRequest` — amount (Decimal > 0), currency (Literal), description (str | None), metadata (dict | None), webhook_url (HttpUrl)
- `PaymentCreateResponse` — payment_id, status, created_at

**Валидация:**
- `amount`: Decimal > 0, ≤ 10^16, максимум 2 знака после запятой
- `currency`: только RUB, USD, EUR
- `webhook_url`: http/https, SSRF-защита (запрет localhost, 127.0.0.0/8, приватных CIDR — конфигурируемо через env `SSRF_ALLOW_PRIVATE`)
- `metadata`: объект, до 4 КБ сериализованного JSON
- `Idempotency-Key`: непустая строка до 255 символов, `[A-Za-z0-9_-]+`

### 3.4. GET /api/v1/payments/{payment_id} (`src/api/v1/payments.py`)
**Логика:**
1. Проверить API Key
2. Найти платеж по UUID
3. Если не найден → 404
4. Вернуть полную информацию: `PaymentDetailResponse`

**Pydantic схемы:**
- `PaymentDetailResponse` — все поля модели, включая notification_status, notification_attempts

### 3.5. GET /health (`src/main.py`)
- [ ] Без API-ключа
- [ ] `200` при доступности БД (`SELECT 1`)
- [ ] `503` при недоступности

---

## 4. Outbox Relay (отдельный процесс)

### 4.1. Outbox Relay (`src/outbox_relay/app.py`)
**Отдельный воркер (не внутри FastAPI):**
1. Бесконечный цикл с интервалом 1-2 сек
2. `SELECT id, event_type, aggregate_id, payload FROM outbox_events WHERE status='pending' ORDER BY created_at LIMIT 100 FOR UPDATE SKIP LOCKED`
3. Для каждой записи:
   - Опубликовать сообщение в RabbitMQ через FastStream publisher с publisher confirm
   - При успехе: `UPDATE outbox_events SET status='published', published_at=now()`
   - При ошибке: `attempts += 1`, оставить `pending`
4. COMMIT после каждого сообщения
5. Логировать каждую итерацию (без спама: раз в 30 сек, если пусто)

### 4.2. RabbitMQ Topology (`src/broker/topology.py`)
- [ ] Exchange `payments` (direct — обоснование: один тип событий, один routing key)
- [ ] Очередь `payments.new` с аргументами:
  - `x-dead-letter-exchange: payments.dlx`
  - `x-dead-letter-routing-key: payments.dlq`
- [ ] DLX `payments.dlx` (direct)
- [ ] DLQ `payments.dlq`

### 4.3. Publisher (`src/broker/publisher.py`)
- [ ] FastStream RabbitBroker
- [ ] Метод `publish_payment_created(payment_id, payload)` → exchange `payments`, routing_key `payments.new`
- [ ] Publisher confirm включён

---

## 5. Consumer

### 5.1. Точка входа (`src/consumer/app.py`)
- [ ] Отдельное FastStream приложение
- [ ] Подключается к RabbitMQ
- [ ] Subscriber на очередь `payments.new`, `retry=3` (FastStream-level retry при технических ошибках)

### 5.2. Обработчик (`src/consumer/handler.py`)
**Логика одного consumer'а (делает всё):**
1. Получить сообщение из `payments.new`, десериализовать payload → `payment_id`
2. `SELECT Payment FOR UPDATE` по `payment_id`
3. **Проверка идемпотентности:**
   - Если `status in (succeeded, failed)` и `notification_status == delivered` → ack, выход
   - Если `status in (succeeded, failed)` и `notification_status != delivered` → пропустить эмуляцию, перейти к шагу 5 (отправка webhook)
4. **Эмуляция обработки платежа** (только если `status == pending`):
   - **Детерминированный исход:** `h = sha256(payment_id.hex)`; `success = int(h[:2], 16) % 100 < 90`
   - **Задержка:** `2 + int(h[2:4], 16) % 4` секунд (2–5 сек)
   - `UPDATE status = succeeded/failed, processed_at = now()`
5. **Отправка webhook** (если ещё не delivered):
   - Сгенерировать `event_id = uuid4()` (сохранить в `notification_event_id`, если ещё нет)
   - Body: `{ event_id, payment_id, status, amount, currency, processed_at }`
   - Заголовки: `X-Webhook-Id`, `X-Webhook-Timestamp`, `X-Webhook-Signature: v1=<hmac_sha256(secret, timestamp + "." + body)>`
   - Retry-политика (3 попытки, экспоненциальная задержка 1с/2с/4с + jitter 0-250мс):
     - **Retry при:** 408, 429, 5xx, таймаут, ошибка соединения
     - **Без retry при:** 2xx (успех), прочие 4xx (финальная ошибка)
   - Обновить `notification_status`, `notification_attempts`, `notification_last_error`
6. **Ack** сообщения
7. **При исключениях** (DB unavailable, bug) — не глотать, `raise` → FastStream сделает nack и retry; после 3 попыток → `payments.dlq`

**Важно:** эмуляция и webhook разделены. При падении после шага 4 и повторной доставке — consumer пропускает эмуляцию и начинает с webhook.

### 5.3. Webhook клиент (`src/services/webhook.py`)
- [ ] Асинхронный httpx клиент с таймаутом
- [ ] POST на webhook_url с HMAC-подписью
- [ ] Retry логика: только 408/429/5xx/таймаут, 3 попытки с экспоненциальной задержкой + jitter
- [ ] 4xx (кроме 408/429) — без retry, сразу exhausted

---

## 6. Retry логика и Dead Letter Queue

### 6.1. Два уровня retry
**Уровень 1 — FastStream retry (технические ошибки consumer'а):**
- `subscriber(..., retry=3)` — при необработанных исключениях (БД недоступна, баг)
- После 3 попыток → RabbitMQ отправляет в `payments.dlq` через `x-dead-letter-exchange`

**Уровень 2 — Webhook retry (бизнес-логика):**
- 3 попытки отправки webhook с экспоненциальной задержкой: 1с → 2с → 4с + jitter 0-250мс
- Retry только на: 408, 429, 5xx, таймаут, ошибка соединения
- 4xx (кроме 408/429) — без retry, сразу `notification_status=exhausted`
- После 3 неудачных попыток → `notification_status=exhausted`

### 6.2. Dead Letter Queue
- [ ] DLX `payments.dlx` (direct), очередь `payments.dlq`
- [ ] Настроена через аргументы очереди `payments.new`:
  - `x-dead-letter-exchange: payments.dlx`
  - `x-dead-letter-routing-key: payments.dlq`
- [ ] Сообщения в DLQ хранятся для ручного анализа
- [ ] Логирование всех сообщений, попавших в DLQ

---

## 7. Docker

### 7.1. docker-compose.yml
Сервисы:
- `postgres` — image: `postgres:16-alpine`, env: POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD, volume `pgdata`, healthcheck: `pg_isready -U user -d payment_db`
- `rabbitmq` — image: `rabbitmq:3.13-management-alpine`, ports: 5672, 15672, healthcheck: `rabbitmq-diagnostics check_port_connectivity`
- `migrate` — build: `dockerfile: Dockerfile.api`, `command: alembic upgrade head`, `depends_on: postgres (healthy)`, `restart: no`
- `api` — build: `dockerfile: Dockerfile.api`, ports: 8000, `depends_on: {postgres: healthy, rabbitmq: healthy, migrate: completed}`, `restart: unless-stopped`
- `consumer` — build: `dockerfile: Dockerfile.consumer`, `depends_on: {postgres: healthy, rabbitmq: healthy, migrate: completed}`, `restart: unless-stopped`
- `outbox-relay` — build: `dockerfile: Dockerfile.outbox-relay`, `depends_on: {postgres: healthy, rabbitmq: healthy, migrate: completed}`, `restart: unless-stopped`

Все сервисы читают `.env` через `env_file`.

### 7.2. Dockerfile.api
```dockerfile
FROM python:3.12-slim
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .
COPY . .
RUN chown -R app:app /app
USER app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 7.3. Dockerfile.consumer
```dockerfile
FROM python:3.12-slim
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .
COPY . .
RUN chown -R app:app /app
USER app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "src.consumer.app"]
```

### 7.4. Dockerfile.outbox-relay
```dockerfile
FROM python:3.12-slim
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .
COPY . .
RUN chown -R app:app /app
USER app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "src.outbox_relay.app"]
```

---

## 8. Логирование и безопасность

### 8.1. Логирование (`src/logging.py`)
- [ ] `structlog` в JSON-формате
- [ ] Поля: `timestamp`, `level`, `event`, `request_id`, `payment_id`, `event_id`, `logger`
- [ ] Middleware в FastAPI: генерация `request_id` (uuid4 или из заголовка `X-Request-ID`), проброс в логи и в ответ (заголовок `X-Request-ID`)

### 8.2. Безопасность
- [ ] `X-API-Key` через `APIKeyHeader(auto_error=False)` + `Security`; сравнение через `secrets.compare_digest`
- [ ] HMAC-подпись webhook: `v1=<hmac_sha256(WEBHOOK_HMAC_SECRET, timestamp + "." + body)>`
- [ ] SSRF-защита для `webhook_url`: запрет localhost, 127.0.0.0/8, приватных CIDR (конфигурируемо через `SSRF_ALLOW_PRIVATE`)
- [ ] Non-root user в Docker

---

## 9. Тесты

### 9.1. Конфигурация
- [ ] `pytest.ini` / `pyproject.toml` с `asyncio_mode=auto`
- [ ] `conftest.py` с фикстурами: async DB session, FastAPI TestClient, mocked RabbitMQ publisher

### 9.2. Unit-тесты (`tests/unit/`)
- [ ] `test_idempotency_replay` — повторный POST с тем же ключом и телом → 202 + `Idempotency-Replayed: true`
- [ ] `test_idempotency_conflict` — тот же ключ, другое тело → 409
- [ ] `test_webhook_retry_success_on_3rd` — 500, 500, 200 → delivered, attempts=3
- [ ] `test_webhook_exhausted` — три 500 → exhausted, attempts=3
- [ ] `test_webhook_4xx_no_retry` — 400 → exhausted, attempts=1

### 9.3. Интеграционные тесты (`tests/integration/`)
- [ ] `test_full_flow` — POST → outbox → relay → consumer → webhook receiver → GET → succeeded
- [ ] `test_consumer_idempotent_on_redelivery` — повторная доставка сообщения не переэмулирует платёж
- [ ] `test_dlq_after_3_failures` — при постоянных ошибках consumer сообщение попадает в `payments.dlq`
- [ ] `test_concurrent_idempotency` — 10 параллельных POST с одним ключом → 1 платёж в БД

---

## 10. README.md

Обязательные разделы:
- [ ] **Overview** — 2 абзаца о сервисе и гарантиях (at-least-once + идемпотентность)
- [ ] **Architecture** — ASCII-схема компонентов и поток сообщения
- [ ] **Запуск** — `cp .env.example .env && docker compose up --build`
- [ ] **Переменные окружения** — таблица всех env-переменных
- [ ] **Примеры curl** — создание (с Idempotency-Key), повтор, получение, ошибки (401, 409, 422)
- [ ] **Принятые решения** — почему outbox, почему разделены retry webhook и retry consumer, как обеспечена детерминированность эмуляции, почему DLQ через x-dead-letter-exchange, почему direct exchange
- [ ] **Тесты** — команда запуска
- [ ] **Ограничения и возможные улучшения** — честный список

---

## 11. Порядок выполнения (рекомендуемый)

| Шаг | Задача | Зависимости |
|-----|--------|-------------|
| 1 | Инициализация проекта: `pyproject.toml`, структура папок, `.env.example`, `.gitignore` | — |
| 2 | `src/config.py` (pydantic-settings) | 1 |
| 3 | `src/db/base.py` (engine, session factory) | 2 |
| 4 | `src/db/enums.py` + `src/db/models.py` (Payment, OutboxEvent) | 3 |
| 5 | Alembic init + миграция | 4 |
| 6 | `src/schemas/payment.py` + `src/schemas/errors.py` (Pydantic v2) | 4 |
| 7 | `src/api/deps.py` (API Key, DB session) + `src/api/errors.py` | 3, 6 |
| 8 | `src/services/idempotency.py` (SHA-256 хеширование) | 4 |
| 9 | `src/services/payment_service.py` (create_payment с outbox) | 5, 6, 8 |
| 10 | `src/api/v1/payments.py` (POST + GET эндпоинты) | 7, 9 |
| 11 | `src/main.py` (FastAPI app factory, lifespan, /health) | 10 |
| 12 | `src/broker/topology.py` + `src/broker/publisher.py` | 2 |
| 13 | `src/outbox_relay/app.py` (отдельный воркер) | 4, 12 |
| 14 | `src/services/webhook.py` (httpx + retry + HMAC) | 2 |
| 15 | `src/consumer/handler.py` + `src/consumer/app.py` | 4, 14 |
| 16 | `src/logging.py` (structlog + request_id middleware) | 11 |
| 17 | `Dockerfile` (multi-stage, non-root) | 11, 13, 15 |
| 18 | `docker-compose.yml` (6 сервисов) | 17 |
| 19 | `tests/conftest.py` + unit-тесты | 10, 14 |
| 20 | Интеграционные тесты | 18, 19 |
| 21 | `README.md` | все |

---

## 12. Ключевые моменты реализации

### Идемпотентность
- Уникальный индекс на `idempotency_key` в БД
- `request_hash = sha256(канонический_JSON тела)` — для детекта конфликта тел
- При повторном запросе с тем же ключом и телом → 202 + заголовок `Idempotency-Replayed: true`
- При том же ключе, но другом теле → 409 Conflict
- В consumer'е: проверять статус; если терминальный + webhook delivered → ack; если терминальный без webhook → только доотправить webhook

### Outbox Pattern
- Запись в `payments` и `outbox_events` — в одной транзакции (atomic)
- Отдельный процесс `outbox-relay` читает `outbox_events` с `FOR UPDATE SKIP LOCKED`
- Публикация с publisher confirm; после ACK → `status=published`
- Гарантия: сообщение будет опубликовано даже при сбое после коммита транзакции

### Детерминированная эмуляция
- `h = sha256(payment_id.hex)`
- Успех: `int(h[:2], 16) % 100 < 90` (90%)
- Задержка: `2 + int(h[2:4], 16) % 4` секунд (2–5)
- При повторной доставке сообщения результат всегда одинаковый

### Retry + DLQ (два уровня)
- **Уровень 1 (FastStream):** `retry=3` при технических ошибках → DLQ
- **Уровень 2 (webhook):** 3 попытки с экспоненциальной задержкой + jitter, только на 408/429/5xx/таймаут
- DLQ через `x-dead-letter-exchange` / `x-dead-letter-routing-key`

### Безопасность
- `X-API-Key` через `secrets.compare_digest` (timing-safe)
- HMAC-подпись webhook уведомлений
- SSRF-защита для `webhook_url`
- Non-root user в Docker-контейнере
- Экспоненциальная задержка: 2^retry_count * base_delay
- После исчерпания попыток → DLQ
- Логирование на каждом этапе

### Безопасность
- X-API-Key на всех эндпоинтах
- Валидация валюты (RUB, USD, EUR)
- Валидация webhook_url (http/https)