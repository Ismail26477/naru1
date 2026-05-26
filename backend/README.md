# Posuhtik — Backend (Phase 1)

**Subscription-based fresh milk & dairy delivery for Nagpur, India.**

FastAPI + PostgreSQL + SQLAlchemy 2.0 async + Alembic + APScheduler.
Phase 1 delivers the full backend API, database, auth, RBAC, seed data,
and pytest test suite. All third-party integrations (SMS, payment, push,
maps, storage) are **stubbed** behind provider interfaces — switchable
to real implementations via a single `.env` flag, zero code changes.

---

## Tech stack

| Layer | Choice |
|---|---|
| Web framework | **FastAPI** (async) |
| DB | **PostgreSQL 15**, asyncpg driver (min=5 / max=20 pool) |
| ORM | **SQLAlchemy 2.0 async** + **Alembic** |
| Auth | JWT (access + refresh), OTP login via MSG91 (stubbed) |
| Scheduling | **APScheduler** in-process (cron, IST tz) |
| Money | Integer paise (never float) |
| Timezone | Asia/Kolkata business rules; UTC in DB |
| Integrations | Razorpay / MSG91 / FCM / Google Maps / S3 — all provider-stubbed |
| Storage (Phase 1) | Local filesystem for invoice PDFs |

---

## Quick start

```bash
# 1. Start PostgreSQL 15 and Redis (supervisor manages them in this container)
sudo supervisorctl status postgres redis

# 2. Create DB + user (one-time)
sudo -u postgres psql <<EOF
CREATE USER posuhtik WITH PASSWORD 'posuhtik_dev' CREATEDB;
CREATE DATABASE posuhtik_dev OWNER posuhtik;
CREATE DATABASE posuhtik_test OWNER posuhtik;
EOF

# 3. Install deps
cd /app/backend
pip install -r requirements.txt

# 4. Run migrations
alembic upgrade head

# 5. Seed dev data (Nagpur customers, products, routes, subscriptions + 15 days delivery history)
python scripts/seed.py

# 6. The API is served by supervisor on :8001 (hot-reload).
curl http://localhost:8001/api/
```

### Reset everything (dev only)

```bash
python scripts/reset_db.py   # drops schema → upgrade → seed
```

---

## Environment

Copy `.env.example` to `.env` and adjust. Key switches:

| Variable | Values | Meaning |
|---|---|---|
| `APP_ENV` | `development` / `production` | in dev, OTP `123456` is accepted |
| `SMS_PROVIDER` | `stub` / `msg91` | |
| `PAYMENT_PROVIDER` | `stub` / `razorpay` | |
| `PUSH_PROVIDER` | `stub` / `fcm` | |
| `GEOCODER_PROVIDER` | `stub` / `google` | |
| `STORAGE_PROVIDER` | `local` / `s3` | |
| `CUTOFF_HOUR_IST` | `20` | 8:00 PM IST cutoff |
| `BILLING_DAY_OF_MONTH` | `1` | monthly invoice generation day |

See [`app/providers/base.py`](app/providers/base.py) for interfaces; swapping to a real
provider only requires filling in [`app/providers/real.py`](app/providers/real.py) — **no business-logic change**.

---

## Business rules (enforced in code)

1. **Cutoff** is centralized in [`app/services/cutoff_service.py`](app/services/cutoff_service.py).
   Modifying tomorrow's order at 19:59 IST today works; at 20:00 IST sharp (or later) returns **HTTP 409**.
2. **Bottle tracking** via [`app/services/bottle_service.py`](app/services/bottle_service.py):
   delivering a `requires_bottle=true` product adds `+qty` to the ledger;
   `bottles_returned` at confirmation time subtracts.
3. **Billing** ([`app/services/billing_service.py`](app/services/billing_service.py)) reads **only
   DELIVERED** orders in the period. 30 deliveries × ₹30 = ₹900 (90000 paise). Idempotent.
4. **Order generation** ([`app/services/order_service.py`](app/services/order_service.py)) is
   idempotent and respects pauses/overrides.
5. **RBAC**: every protected endpoint uses a role-enforcing FastAPI dependency
   ([`app/middleware/auth.py`](app/middleware/auth.py)).

---

## Background jobs (APScheduler, IST cron)

| Job | Schedule | Body |
|---|---|---|
| `nightly_cutoff` | `20:00` daily | Generate missing orders for tomorrow + stamp `cutoff_locked_at` |
| `monthly_billing` | 1st @ `02:00` | Generate invoices for the previous month |
| `morning_reminder` | `07:00` daily | Push reminder to each delivery boy's route |

Each job wraps its body in a Postgres advisory lock (`pg_try_advisory_lock`) so it's safe if multiple workers run in parallel later. Admin can manually trigger any job:

```bash
POST /api/admin/jobs/{nightly_cutoff|monthly_billing|morning_reminder}/trigger
```

---

## API surface (all under `/api` prefix)

### Auth
- `POST /auth/request-otp` → sends OTP (dev: returned in response)
- `POST /auth/verify-otp` → `{access_token, refresh_token, ...}`
- `POST /auth/refresh`

### Customer (role: customer)
- `GET /me`, `PATCH /me`
- `GET /me/addresses`, `POST /me/addresses`
- `GET /products`
- `GET /me/subscriptions`, `POST /me/subscriptions`
- `PATCH /me/subscriptions/{id}` (pause/resume/modify)
- `POST /me/subscriptions/{id}/schedule-override` (skip/modify a date — **respects cutoff**)
- `GET /me/delivery-orders?from=&to=`
- `GET /me/invoices`, `GET /me/invoices/{id}`
- `GET /me/wallet`, `GET /me/bottle-balance`

### Admin (role: admin)
- `GET /admin/customers?status=&search=`
- `POST /admin/customers/{id}/approve`
- `GET /admin/subscriptions`
- `GET /admin/routes`, `POST /admin/routes`
- `PATCH /admin/routes/{id}/stops`
- `GET /admin/delivery-orders?date=&route_id=`
- `POST /admin/delivery-orders/generate?target_date=`
- `GET /admin/invoices`
- `POST /admin/invoices/generate?month=&year=`
- `POST /admin/products`
- `GET /admin/reports/daily-delivery?date=`
- `GET /admin/reports/bottle-outstanding`
- `POST /admin/jobs/{name}/trigger`

### Delivery (role: delivery)
- `GET /delivery/my-route?date=`
- `POST /delivery/orders/{id}/confirm`
- `POST /delivery/orders/{id}/skip`

### Webhooks
- `POST /webhooks/razorpay` (signature verified; stub accepts any)

OpenAPI docs at **`http://<host>/docs`**.

---

## Seeded data (after `scripts/seed.py`)

| Role | Phone | Name |
|---|---|---|
| admin | `+919000000001` | Admin User |
| delivery | `+919000000002` | Ramesh Patil |
| delivery | `+919000000003` | Suresh Deshmukh |
| customer | `+919000000004`–`+919000000013` | Amit Kulkarni, Priya Sharma, Rahul Joshi, Sneha Deshpande, Vikram Bhoyar, Anjali Tiwari, Manish Agrawal, Kavita Meshram, Deepak Raut, Swati Wankhede |

**Dev OTP is always `123456`** (real OTP is also sent and logged, but the fixed one is also accepted).

Products: Cow Milk 500ml (₹35), Cow Milk 1L (₹70), A2 Ghee 500ml (₹1200), A2 Ghee 1L (₹2300), Paneer 250g (₹110), Buttermilk 500ml (₹25).

Routes: "Dharampeth Morning" (Ramesh) • "Sadar East" (Suresh).

Seed also backfills 15 days of delivery history + bottle ledger entries.

---

## Tests

```bash
cd /app/backend
pytest -v
```

**31 tests** covering:
- **Auth**: request OTP, dev OTP `123456`, wrong OTP rejected, `/me` protected, refresh.
- **Cutoff**: 19:59 IST works, 20:01 IST fails, 20:00 sharp fails, `assert_modifiable` raises 409.
- **Billing**: 30×₹30=₹900, 25 delivered + 5 skipped=₹750, invoice generation, idempotency.
- **Bottle ledger**: delivery increments, return decrements, net balance.
- **RBAC**: customer blocked on admin & delivery endpoints, delivery blocked on admin, admin allowed, unauth→401.
- **Subscription pause**: paused subs yield no orders, pause-window respected, order generation idempotent.

---

## Project structure

```
/app/backend/
├── app/
│   ├── core/         # config, security, logging, time_utils
│   ├── db/           # base, async session
│   ├── models/       # SQLAlchemy 2.0 models (users, products, subscriptions, …)
│   ├── schemas/      # Pydantic request/response
│   ├── providers/    # abstract interfaces + stubs + real shells
│   ├── services/     # cutoff, otp, billing, bottle, order, schedule
│   ├── middleware/   # auth / RBAC dependencies
│   ├── api/v1/       # auth, customers, admin, delivery, webhooks
│   ├── jobs/         # APScheduler setup + runners
│   └── main.py       # FastAPI app factory
├── alembic/          # migrations
├── tests/            # pytest suite
├── scripts/          # seed.py, reset_db.py
├── storage/          # local invoice PDFs
├── server.py         # uvicorn entry (imports app.main.app)
├── alembic.ini
├── pytest.ini
├── requirements.txt
└── .env / .env.example
```

---

## Next (Phase 2+)

- Wire MSG91 real provider (`app/providers/real.py::Msg91SMSProvider`)
- Wire Razorpay + webhook (`RazorpayPaymentProvider`)
- Implement Firebase FCM (`FcmPushProvider`)
- Google Maps geocoding (`GoogleGeocoder`) — addresses have `geocoding_pending=true` ready
- S3 provider for invoice PDFs
- Next.js admin + customer web app
- React Native mobile (Expo)
