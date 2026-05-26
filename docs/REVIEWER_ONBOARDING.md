# Reviewer Onboarding — Posuhtik

> **Goal:** get a senior engineer productive in **15 minutes**.
> **As of:** Feb 2026, Phase 2C shipped (158/158 pytests green).

## 1. What you're looking at (60 seconds)

Posuhtik is a **subscription-based fresh-milk delivery platform** operating in Nagpur, India. Real business, real paying customers. The codebase contains three deployed surfaces and one background scheduler:

| Surface | Tech | Purpose |
|---|---|---|
| Customer web app | Next.js 14 App Router · `/app/frontend/app/(app)/*` | Schedule / pause deliveries, view invoices, wallet |
| Admin console | Next.js 14 · `/app/frontend/app/admin/*` (13 pages) | Operations: customers, routes, deliveries, products, billing, reports, invoices |
| Backend API | FastAPI + SQLAlchemy 2.0 async + Alembic | 75+ JSON endpoints, 5 scheduled jobs |
| Scheduler | APScheduler in-process | nightly cutoff · monthly billing · morning reminders · token cleanup |

**Single source of truth** is PostgreSQL 15. No MongoDB. Money stored as integer paise. All dates in IST, persisted UTC.

## 2. Architecture (2 minutes)

```
/app/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # Endpoints (auth, customers, admin_*, delivery)
│   │   ├── services/        # Business logic (the interesting reading)
│   │   ├── models/          # SQLAlchemy async ORM (Postgres only)
│   │   ├── schemas/         # Pydantic I/O models
│   │   ├── jobs/            # APScheduler runners + registration
│   │   ├── middleware/      # Auth & RBAC
│   │   ├── providers/       # Stubs for Razorpay, MSG91, Firebase, S3, Maps
│   │   ├── core/            # config, security, time_utils
│   │   └── templates/       # Jinja2 (invoice_pdf.html)
│   ├── alembic/versions/    # 10 migrations — apply in order
│   ├── scripts/seed.py      # Idempotent dev seed
│   └── tests/               # 158 pytests
├── frontend/
│   ├── app/(app)/           # Customer pages
│   ├── app/admin/           # Admin pages (13)
│   ├── components/          # shadcn/ui + custom
│   └── lib/                 # api.ts (auth-aware fetch), utils, csv
├── docs/                    # This file + TECH_DEBT, SCHEDULED_JOBS, ADMIN_AUDIT_2B8, LOCAL_SETUP, EMERGENT_GOTCHAS
└── memory/                  # PRD.md (living spec), test_credentials.md
```

### Key design decisions worth knowing

- **Provider pattern** for every 3rd-party integration (`app/providers/base.py` → `stubs.py` / `real.py`). Flip `STUBS=false` + supply keys to go live without touching business code.
- **8 PM IST cutoff** for modifying tomorrow's deliveries — enforced by `services/cutoff_service.py` and `DeliveryOrder.cutoff_locked_at`. Violations raise `cutoff_locked`.
- **Billing isolation**: Per-customer atomic. One bad customer lands in `failed[]` of the batch result, doesn't abort the month. Transaction-level advisory lock keyed by `(year*12+month)` prevents concurrent runs.
- **Historical pricing**: Every `InvoiceLineItem` carries `price_paise` as a snapshot. Product price changes never mutate past invoices. `ProductPriceHistory` rows record the change.
- **Audit trail**: Every admin mutation writes to `audit_log(actor_user_id, action, entity_type, entity_id, before, after, ip, user_agent)`. Scheduled jobs use a singleton `is_system=true` user (partial unique index; OTP login blocks this phone).
- **Invoice PDFs**: Lazy-generated via `weasyprint`, cached on disk under `backend/local_storage/invoices/{year}/{month}/{id}.pdf`, invalidated on regenerate / override / status transition. Owner-only customer endpoint returns 404 (not 403) on mismatch — no existence leak.

## 3. Where to start reading (5 minutes)

Reading in this order will give you the entire system in one sitting:

1. **`backend/app/services/cutoff_service.py`** — the 8 PM IST rule, enforced as both a DB column and a service guard. 80 LOC.
2. **`backend/app/services/billing_admin_service.py`** — the money path. `generate_invoices`, `regenerate_invoice`, `flag_post_billing_adjustment`, `apply_wallet_credit`, `_recompute_status`. If a senior reviewer reads nothing else, read this file.
3. **`backend/app/services/invoice_pdf_service.py`** (Phase 2C) — templating, lazy cache, invalidation. 260 LOC.
4. **`backend/app/jobs/runners.py`** — all 4 scheduled jobs, each with advisory locks and audit rows. Cross-reference with `/app/docs/SCHEDULED_JOBS.md`.
5. **`backend/alembic/versions/*`** — schema evolution. Read chronologically; `e5c1b7f2a3d8` (system user + partial unique index) and `f1a3c5e8b2d4` (PDF cache) are the Phase 2B.8 / 2C delta.
6. **`frontend/app/admin/invoices/[id]/page.tsx`** — the richest admin page: regenerate, wallet credits, payments, post-billing callout, PDF download. If the admin UX makes sense here, it'll make sense everywhere.

## 4. Running it (see `/app/docs/LOCAL_SETUP.md`)

Summary:
```bash
# Postgres + Redis up
docker compose up -d                # or native installs

# Backend
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                # edit DATABASE_URL etc.
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --reload --port 8001

# Frontend (separate terminal)
cd frontend && yarn install
cp .env.example .env                # set NEXT_PUBLIC_BACKEND_URL=http://localhost:8001
yarn dev
```

**Test creds** (seeded): admin `+919000000001`, customer `+919000000004`, delivery `+919000000002`, OTP always `123456`.

## 5. Critical services (where the business logic lives)

| File | LOC | Purpose |
|---|---|---|
| `services/cutoff_service.py` | 80 | 8 PM IST cutoff guard |
| `services/billing_admin_service.py` | 670 | Invoice generate · regenerate · pay · wallet credit · post-billing override |
| `services/billing_service.py` | — | **DEPRECATED** — `generate_invoices_for_period` raises `DeprecationWarning`. Keep until Phase 3. |
| `services/invoice_pdf_service.py` | 260 | HTML→PDF with cache + invalidation |
| `services/reports_service.py` | 620 | Revenue, churn, daily delivery, bottle reports + CSV |
| `services/delivery_admin_service.py` | — | Manual override w/ audit; the only way to mutate a cutoff-locked order |
| `services/bottle_service.py` | — | Returnable glass-bottle ledger |
| `services/token_service.py` | — | JWT issuance + DB-backed revocation |

## 6. Test entry points

- **All**: `cd backend && pytest -v` (158 tests, ~55 seconds on modern hardware).
- **Money path only**: `pytest tests/test_admin_billing.py tests/test_invoice_pdf.py tests/test_2b8_scheduler.py -v`.
- **RBAC only**: `pytest -k "rbac or admin_role"`.
- **Reports**: `pytest tests/test_admin_reports.py -v`.
- **Scheduled jobs**: `pytest tests/test_jobs_and_webhooks.py tests/test_2b8_scheduler.py -v`.

Test fixtures (`tests/conftest.py`) use a separate `posuhtik_test` DB and `Base.metadata.create_all` (not Alembic) — this is intentional for speed. Production schema is Alembic-managed.

## 7. Known debt — read before proposing refactors

- **`/app/docs/TECH_DEBT.md`** — the living debt register. `H5` (TypeScript strict mode off) and `§5.5` (audit trail for customer-facing mutations) are explicitly deferred.
- **`billing_service.generate_invoices_for_period`** — deprecated Phase 2B.8; planned removal Phase 3 after a burn-in window.
- **Frontend TS** — shadcn Radix prop spreading emits ~150 pre-existing `tsc --noEmit` warnings. Do not gate reviews on these.

## 8. What's explicitly **out of scope** (for this freeze)

- Live MSG91 / Razorpay / Firebase FCM / Google Maps / S3 — all stubbed behind Provider classes.
- Flutter delivery-boy app — separate project, separate repo.
- Green Pledge Meter / gamification — future Phase 3.
- Dedicated `/admin/audit-log` page — backend endpoint `GET /api/admin/audit-log` exists; only the nav entry was pruned (Phase 2B.8-E).
- A "Post-billing adjustments last 7 days" KPI on the admin dashboard — approved for post-review batch, not built.

## 9. One-line context for the five hot paths

- **Customer schedule change tomorrow, 7:58 PM IST** → ✅ accepted, `delivery_orders.cutoff_locked_at` unset, order mutable.
- **Customer schedule change tomorrow, 8:01 PM IST** → 🔒 rejected with `cutoff_locked`, admin can still `delivery_admin_service.override`.
- **Monthly billing runs at 02:00 on day 1** → singleton system user actor, advisory lock, per-customer atomic, audit row `billing.generate`.
- **Admin regenerates an invoice** → old `InvoiceLineItem`s + `override_adjustment` rows deleted, fresh ones derived from current `delivery_orders`, `regenerated_count++`, PDF cache NULL'd, `wallet_credit` adjustments preserved.
- **Admin overrides delivered→skipped after invoice issued** → `invoice_adjustments` row kind=`override_adjustment` appended, `has_post_billing_adjustments=true`, `total_paise` recomputed, PDF cache NULL'd, admin sees the Phase-C callout with drill-down.

## 10. Where to ask questions

- Business rules / product intent: `/app/memory/PRD.md` (living spec; every completed phase logged).
- Scheduler behaviour / on-call: `/app/docs/SCHEDULED_JOBS.md` (triage runbook + lock-key namespace).
- Admin console quirks: `/app/docs/ADMIN_AUDIT_2B8.md` (13-page audit with per-page verdict).
- Emergent-container specifics before you run anything locally: `/app/docs/EMERGENT_GOTCHAS.md`.

You should be code-productive now. Welcome to Posuhtik.
