# Payment Processing Service

Асинхронный сервис процессинга платежей с гарантией at-least-once доставки и идемпотентной обработкой.

## Overview

Сервис принимает запросы на создание платежей через REST API, сохраняет их в PostgreSQL и асинхронно обрабатывает через RabbitMQ. Обработка платежа эмулируется детерминированно (90% успех, задержка 2–5 сек), после чего отправляется webhook-уведомление с HMAC-подписью.

**Гарантии:**
- **At-least-once доставка** сообщений через Outbox Pattern + Publisher Confirms
- **Идемпотентность** на уровне API (SHA-256 хеш тела) и consumer'а (проверка статуса)
- **Два уровня retry**: FastStream (технические ошибки → DLQ) + webhook retry (бизнес-логика)
- **Детерминированная эмуляция**: исход зависит только от `payment_id`, повторная обработка даёт тот же результат

## Architecture

```
┌──────────┐     HTTP      ┌──────────┐    SQL     ┌────────────┐
│  Client  │ ──────────────→│   API    │───────────→│ PostgreSQL │
│          │←──────────────│ (FastAPI)│←───────────│            │
└──────────┘               └──────────┘            └────────────┘
                                 │                       ↑
                                 │ INSERT outbox          │ SELECT FOR UPDATE SKIP LOCKED
                                 ↓                       │
                            ┌──────────┐           ┌──────────────┐
                            │ RabbitMQ │←──────────│ Outbox Relay │
                            │          │  publish  │  (worker)    │
                            └──────────┘           └──────────────┘
                                 │
                                 │ consume
                                 ↓
                            ┌──────────┐    HTTP+HMAC    ┌─────────┐
                            │ Consumer │ ───────────────→│ Webhook │
                            │ (worker) │                 │ Server  │
                            └──────────┘                 └─────────┘
                                 │
                                 │ after 3 retries
                                 ↓
                            ┌──────────┐
                            │   DLQ    │
                            └──────────┘
```

**Поток сообщения:**
1. `POST /api/v1/payments` → INSERT в `payments` + `outbox_events` (одна транзакция)
2. Outbox Relay читает `outbox_events` (`FOR UPDATE SKIP LOCKED`) → публикует в RabbitMQ
3. Consumer получает сообщение → эмулирует обработку → отправляет webhook
4. При ошибках consumer'а → retry (3 попытки) → DLQ

## Quick Start

```bash
# 1. Клонировать репозиторий
git clone <repo-url> && cd payment_service_test_task

# 2. Создать .env
cp .env.example .env

# 3. Запустить все сервисы
docker compose up --build

# 4. Проверить здоровье
curl http://localhost:8000/health
```

## Environment Variables

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `DATABASE_URL` | URL подключения к PostgreSQL (asyncpg) | `postgresql+asyncpg://payment_user:payment_pass@localhost:5432/payment_db` |
| `RABBITMQ_URL` | URL подключения к RabbitMQ | `amqp://guest:guest@localhost:5672/` |
| `API_KEY` | Ключ для аутентификации API | `test-api-key-change-in-production` |
| `WEBHOOK_HMAC_SECRET` | Секрет для HMAC-подписи webhook | `webhook-secret-change-in-production` |
| `WEBHOOK_TIMEOUT` | Таймаут HTTP-запроса webhook (сек) | `10` |
| `SSRF_ALLOW_PRIVATE` | Разрешить приватные IP в webhook_url | `false` |
| `LOG_LEVEL` | Уровень логирования | `INFO` |

## API Examples

### Создание платежа

```bash
curl -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: test-api-key-change-in-production" \
  -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "100.50",
    "currency": "RUB",
    "description": "Order #12345",
    "webhook_url": "https://example.com/webhook"
  }'
```

**Ответ (202 Accepted):**
```json
{
  "payment_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "pending",
  "created_at": "2024-01-01T00:00:00+00:00"
}
```

### Идемпотентный повтор

```bash
# Тот же запрос → 202 + заголовок Idempotency-Replayed: true
curl -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: test-api-key-change-in-production" \
  -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -d '{"amount": "100.50", "currency": "RUB", "webhook_url": "https://example.com/webhook"}'
```

### Конфликт идемпотентности (409)

```bash
# Тот же ключ, другое тело → 409 Conflict
curl -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: test-api-key-change-in-production" \
  -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -d '{"amount": "200.00", "currency": "USD", "webhook_url": "https://example.com/webhook"}'
```

### Получение статуса платежа

```bash
curl http://localhost:8000/api/v1/payments/660e8400-e29b-41d4-a716-446655440001 \
  -H "X-API-Key: test-api-key-change-in-production"
```

### Ошибки

**401 Unauthorized:**
```json
{"error": {"code": "invalid_api_key", "message": "Invalid or missing API key", "request_id": "..."}}
```

**404 Not Found:**
```json
{"error": {"code": "payment_not_found", "message": "Payment not found", "request_id": "..."}}
```

**409 Conflict:**
```json
{"error": {"code": "idempotency_conflict", "message": "Idempotency key reused with different body", "request_id": "..."}}
```

## Design Decisions

### Почему Outbox Pattern?
Прямая публикация в RabbitMQ из API-транзакции ненадёжна: коммит может пройти, а публикация — нет (или наоборот). Outbox гарантирует, что событие будет опубликовано ровно тогда, когда транзакция закоммичена. Отдельный процесс читает `outbox_events` с `FOR UPDATE SKIP LOCKED` и публикует с publisher confirm.

### Почему разделены retry webhook и retry consumer?
- **FastStream retry** — для технических ошибок (БД недоступна, баг в коде). После 3 попыток → DLQ.
- **Webhook retry** — для бизнес-ошибок (внешний сервис недоступен). 3 попытки с экспоненциальной задержкой + jitter. После исчерпания → `notification_status=exhausted`.

Разделение позволяет не терять сообщения из-за проблем с внешним webhook-сервером.

### Как обеспечена детерминированность эмуляции?
Исход обработки зависит только от `payment_id`:
```python
h = sha256(payment_id.hex)
success = int(h[:2], 16) % 100 < 90  # 90%
delay = 2 + int(h[2:4], 16) % 4      # 2-5 сек
```
При повторной доставке сообщения результат всегда одинаковый.

### Почему DLQ через x-dead-letter-exchange?
Нативный механизм RabbitMQ — не требует дополнительного кода. Сообщение автоматически попадает в DLQ после исчерпания retry. Сообщения в DLQ хранятся для ручного анализа и переотправки.

### Почему Direct Exchange?
В системе один тип событий (`payment.created`) и один routing key (`payments.new`). Direct exchange — самый простой и производительный вариант для этого сценария.

## Running Tests

```bash
# Unit-тесты
pytest tests/unit/ -v

# Интеграционные тесты (требуют PostgreSQL)
DATABASE_URL=postgresql+asyncpg://payment_user:payment_pass@localhost:5432/payment_db_test pytest tests/integration/ -v

# Все тесты
pytest -v
```

## Project Structure

```
├── src/
│   ├── main.py              # FastAPI app, lifespan, /health
│   ├── config.py             # pydantic-settings
│   ├── logging.py            # structlog JSON-логирование
│   ├── api/
│   │   ├── deps.py           # API Key auth, DB session
│   │   ├── errors.py         # RequestIDMiddleware, error helpers
│   │   └── v1/
│   │       ├── router.py     # APIRouter
│   │       └── payments.py   # POST + GET эндпоинты
│   ├── db/
│   │   ├── base.py           # Engine, session factory
│   │   ├── enums.py          # Currency, PaymentStatus, etc.
│   │   └── models.py         # Payment, OutboxEvent
│   ├── schemas/
│   │   ├── payment.py        # Pydantic v2 DTO
│   │   └── errors.py         # ErrorDetail, ErrorResponse
│   ├── services/
│   │   ├── idempotency.py    # SHA-256 хеширование
│   │   ├── payment_service.py
│   │   └── webhook.py        # HTTP client + retry + HMAC
│   ├── broker/
│   │   ├── topology.py       # Exchange/Queue/DLQ/DLX
│   │   └── publisher.py      # RabbitMQ publisher
│   ├── consumer/
│   │   ├── app.py            # FastStream subscriber
│   │   └── handler.py        # Логика обработки
│   └── outbox_relay/
│       └── app.py            # Outbox polling worker
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_idempotency.py
│   │   └── test_webhook.py
│   └── integration/
│       ├── test_full_flow.py
│       └── test_consumer.py
├── alembic/
│   ├── env.py
│   └── versions/
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.consumer
├── Dockerfile.outbox-relay
└── pyproject.toml
```

## Limitations & Future Improvements

- **Эмуляция вместо реального процессинга** — заменить на интеграцию с платёжным шлюзом
- **DLQ — хранение без автоматической переотправки** — добавить UI/CLI для ручной переотправки сообщений из DLQ
- **Мониторинг** — добавить Prometheus-метрики (latency, throughput, error rate) и health-check эндпоинты для Kubernetes
- **Graceful shutdown** — улучшить обработку SIGTERM с drain-периодом для consumer'а
- **Трассировка** — добавить OpenTelemetry для сквозной трассировки запросов
- **Горизонтальное масштабирование consumer'ов** — добавить consumer group и партиционирование
- **Валидация webhook_url** — добавить SSRF-защиту на уровне IP-резолвинга (запрет private CIDR)
- **Метрики и алерты** — Prometheus + Grafana дашборды, алерты на рост DLQ и ошибки webhook