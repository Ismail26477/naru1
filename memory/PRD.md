# Posuhtik — Product Requirements (living doc)

**Type:** Subscription-based fresh milk & dairy delivery platform for Nagpur, India.
**Stack (locked by user):** FastAPI + PostgreSQL 15 (asyncpg, SQLAlchemy 2.0 async, Alembic) + **Next.js 14 App Router + TypeScript + Tailwind + shadcn/ui + React Query + Zod** (customer web). React Native (Flutter, out of scope) for delivery-boy app.

## User personas
- **Customer** — subscribes to products, modifies/pauses, pays monthly.
- **Admin** — approves customers, assigns routes, triggers billing.
- **Delivery boy** — sees today's route, confirms/skips each stop (mobile Flutter app, separate project — NOT in scope here).

## Core business rules (frozen)
1. 8:00 PM IST cutoff locks tomorrow's orders (centralized in `app/services/cutoff_service.py`).
2. Money in integer paise; dates UTC in DB, IST in business rules.
3. Bottle balance per customer; bottled-product delivery adds, returns subtract.
4. Monthly invoicing on 1st for previous month; prepaid wallet OR postpaid.
5. Each customer → exactly one route.
6. Admin must approve customer before subscription endpoints are usable.
7. Admin can pause subscription (vacation mode).

## Phase 1 — DONE (Feb 2026) · backend
- 15 tables, Alembic migration, pg_trgm
- Provider pattern for SMS/Payment/Push/Maps/Storage (all stubbed)
- JWT + OTP auth with dev fixed OTP `123456`
- Full endpoint set (auth/customer/admin/delivery/webhooks)
- Centralized cutoff service (HTTP 409 with ISO cutoff moment)
- Billing & order generation services (idempotent)
- APScheduler: 3 cron jobs w/ Postgres advisory locks + admin manual triggers
- Seed script (Nagpur-specific) + reset_db.py
- **pytest: 31/31 PASSING**

## Phase 2A — DONE (Feb 2026) · customer web app
- **Next.js 14** App Router + TypeScript + Tailwind + shadcn/ui + React Query + Zod, replacing initial CRA scaffold
- Mobile-first (max-w-md), Organic & Earthy theme (cream #FDFBF7 + ochre #D98A3C + sage secondary + terracotta accent for cutoff)
- Fonts: Outfit (display) + Karla (body) + JetBrains Mono (countdown digits)
- All 10 pages:
  1. `/login` — phone + OTP flow (dev OTP 123456 accepted; real OTP also logged & returned)
  2. `/dashboard` — greeting, sticky cutoff timer, bottle + wallet bento, top-3 subs, next 3 deliveries, browse CTA
  3. `/products` — 6-card grid w/ Unsplash imagery, subscribe dialog (qty stepper + frequency + weekday pills)
  4. `/subscriptions` — active/paused/cancelled sections
  5. `/subscriptions/[id]` — modify qty/freq, pause/resume/cancel, skip-a-day dialog, sticky cutoff timer
  6. `/calendar` — 30-day grid, today ring, delivery dots, locked days with hatch overlay, today/tomorrow detail
  7. `/orders` — Upcoming/History tabs, status badges
  8. `/invoices` — outstanding hero card + list with status badges
  9. `/invoices/[id]` — amount card + line-items table + optional PDF download
  10. `/profile` — user card, Balances tab (wallet + bottles + recent txns), Addresses tab (add addr dialog), logout
- Bottom tab bar (Home · Subs · Calendar · Bills · Profile)
- Reusable `CutoffTimer` component with live countdown + PASSED state
- React Query for server state; Zod validates API bodies via Pydantic on backend
- data-testid on every interactive element (login, nav, CTAs, dialogs)
- Loading skeletons on every page; sonner toasts for errors/successes
- Testing agent verdict: **100% pass, zero critical bugs** (iteration_1.json)

## Phase 2B — IN PROGRESS (admin console)
Build per user's earlier "Prompt 3" as a separate route tree (`/admin/*` inside same Next app — option (a) confirmed 2026-04-22).

**Phase 2B.1 — SHIPPED 2026-04-22**
- Backend: `GET /api/admin/dashboard/stats` (KPIs + 3 trend series) + `GET /api/admin/audit-log`
- Audit log infra: `models/audit_log.py`, `services/audit_service.py`, migration `8d4c1a2e5f10` — **closes TECH_DEBT §5.3**
- Frontend: `/admin/login` (strict role check, dark branded), `/admin/*` layout (sidebar + topbar + mobile drawer), `/admin/dashboard` with tabbed chart (Deliveries 14d / Revenue 30d / New customers 30d, saved in localStorage) + 6 KPI cards + manual job trigger panel
- Strict role separation: customer `/login` rejects admin role with redirect hint; admin layout redirects non-admins to `/admin/login?error=not_admin`; customer `(app)/layout` bounces admins to `/admin/dashboard`
- Tests: 44/44 pytest (38 existing + 6 new: 3 RBAC + admin-access + empty-audit-log + no-token)
- E2E verified: admin login → dashboard render (all KPIs, chart, tabs, sidebar nav), non-admin → redirect

**Phase 2B.2 — SHIPPED 2026-04-22 (money-critical, verified)**
- Backend services: `wallet_service.adjust` and `bottle_service.adjust` with `SELECT FOR UPDATE` row-level locking, post-op integrity check (`SUM(ledger) == balance`; raises `*IntegrityError` → rollback), mandatory reason (≥10 chars), `force` flag for negative balance bypass.
- New router `app/api/v1/admin_customers.py`:
  - `GET /admin/customers` paginated + pg_trgm fuzzy search (name/phone/email/address) + status / route / joined_from/to filters
  - `GET /admin/customers/{id}` detail with addresses + counts
  - `GET /admin/customers/{id}/{subscriptions|deliveries|invoices|wallet-transactions|bottle-ledger|audit-log}` paginated children
  - `POST /admin/customers/{id}/wallet-adjustment` · `POST /admin/customers/{id}/bottle-adjustment`
  - `POST /admin/customers/{id}/approve` · `/reject` · `/revoke-tokens` — all write `audit_log` with before/after state, actor, reason, IP, UA
  - `POST /admin/subscriptions/{id}/{pause|resume|cancel}` — differentiated `subscription.admin_{pause,resume,cancel}` audit actions
  - `POST /admin/customers/bulk-approve` (one audit row per customer)
- Frontend: `/admin/customers` dense 40px table with debounced search, status filter, bulk-select + bulk-approve, CSV export, URL-backed pagination; `/admin/customers/[id]` full-page with 7 tabs (Profile, Subscriptions, Deliveries, Invoices, Wallet, Bottles, Audit). Reusable `AdjustmentModal` with live preview, negative warning banner, force checkbox unlocked only by typing `I UNDERSTAND`, char-counted reason.
- Tests: **63/63 pytest** (44 prior + 19 new) — wallet: positive, blocked-negative, forced-negative, reason validation, atomicity (audit failure → rollback), concurrency (gather of 3 adjusts), integrity over mixed batch; bottle parallel set; customer approve/reject audit; admin-pause differentiated; pg_trgm search; parameterised RBAC (customer + delivery × 13 new endpoints).
- Live verified: A happy wallet +10000 → 4-way consistent; B −100000 blocked (0 rows); C bottle +3 + negative blocked; E customer calling admin endpoint → 403.

**Phase 2B.3 — SHIPPED 2026-04-22 (drag-drop live-verified)**
- Backend: 7 new endpoints in `admin_routes.py` (list/create/detail/update/reorder/add-stop/remove-stop/deactivate) + `GET /admin/users?role=delivery`. Migration `c7e91b3a4d22` adds `routes.active`. Reorder validates contiguous 1..N + unique + in-route. Deactivate blocks when tomorrow has pending deliveries (409 with `blocking_orders[]`).
- Audit coverage: `route.create`, `route.update`, `route.reorder` (before/after arrays as JSONB), `route.assign_customer`, `route.remove_customer`, `route.deactivate`.
- Frontend: `/admin/routes` with filters + create dialog; `/admin/routes/[id]` with `@dnd-kit/core` SortableContext optimistic drag (arrayMove → PATCH → revert on failure + toast). Save status indicator; add-customer dialog with debounced search + dedupe; inline delivery-boy reassignment; deactivate dialog with mandatory reason; straight-line distance stub.
- Tests: **80/80 pytest** (63 prior + 17 new — see commit msg for list).
- Live-verified: position 5→1 persisted to DB; 3 rapid reorders → last-write-wins correct; non-contiguous → 400 `non_contiguous`; on_other_route → 400 with `other_route_id`; middle-stop removal renumbers remaining to contiguous 1..N; audit log snapshot shows `route.reorder=4, route.create=2, route.remove_customer=1` after live run.

**Phase 2B.4 — SHIPPED 2026-04-22 (5-scenario live-verified)**
- Backend: `delivery_admin_service.override()` with `SELECT FOR UPDATE`, state-transition allow-list, compensating bottle-ledger entries on revert (never deletes), `OVERRIDE_MAX_DAYS_BACK=7` env gate, audit flag `bypassed_cutoff`. Endpoints: `GET /admin/delivery-orders/board` (filters + KPIs), `GET /admin/delivery-orders/{id}/admin-detail` (full context + audit), `POST /admin/delivery-orders/{id}/override`, `POST /admin/delivery-orders/bulk-skip` (shared `bulk_operation_id`).
- Frontend: `/admin/delivery-orders` board (date picker + route/status/boy filters + 5 KPI cards + bulk-skip modal); `/admin/delivery-orders/[id]` detail with audit timeline and cutoff-bypass badge. Reusable `OverrideModal` with live side-effects preview, compensating-entry warning, cutoff banner.
- Tests: **94/94 pytest** (80 prior + 14 new).
- Live-verified on +919000000004: A pending→delivered (+1 ledger row, audit.ledger_delta=1); B delivered→pending (compensating -1, original +1 intact, 5→10 rows after full cycle); C cutoff bypassed (audit.bypassed_cutoff=true); D missing qty → 400 `missing_quantity`; E 9-char reason → 422, 10-char → 200.

**Phase 2B.5 — SHIPPED 2026-04-22 (historical pricing live-verified)**
- Backend (from earlier in the session): `product_price_history` table + `product_pricing_service.effective_price_on()` snapshot; `admin_products.py` (list/detail/create/update/price-change/price-history); `delivery_orders.unit_price_paise` locked at generation time via effective-price lookup.
- Frontend: `/admin/products` dense catalogue with name/SKU search + active filter + CSV + New product dialog (₹↔paise); `/admin/products/[id]` with hero current-price card, impact card (active subs / bottle / history count), metadata edit form (SKU + unit deliberately locked), price-history timeline with Applied/Scheduled badges, and a dedicated **price-change modal** featuring live diff (+/- ₹ & %), today-vs-future preview banner, subscriber-impact count, 10-500 char reason, and an AlertDialog confirmation gate.
- Tests: **105/105 pytest** (94 prior + 11 new covering create/update audit, backdate guard, future-vs-immediate price change, history lookup, delivery-order price lock, SKU conflict, RBAC).
- Live verified on preview (admin `+919000000001`):
  - **S1** Create "Test Ghee 250g" + update description/image → audit emits `product.create` + `product.update` only, no `product.price_change`.
  - **S2** Cow Milk 500ml +future price ₹39.00 eff 2026-04-23 → `products.price_paise` stays at 3500, history row written, `audit.after_state.applied_immediately=false`.
  - **S3** Cow Milk 1L → ₹99.99 effective today; `products.price_paise` jumps to 9999, `/admin/delivery-orders/generate` locks 5 tomorrow orders at 9999, past delivery orders stay at 7000 (6 dates checked), `audit.after_state.applied_immediately=true`. Price reverted to 7000 post-verification to keep demo clean.

**Phase 2B.6 — SHIPPED 2026-04-22 (6-scenario money-safety live-verified)**
- Migration `d8f2a4b1c7e9`: `invoices` += `regenerated_count`, `has_post_billing_adjustments`, `amount_paid_paise`, `last_regenerated_at/by`; `invoice_status` += `partially_paid`; `payment_method` += `upi`, `bank_transfer`; `payments` += `reference`; new signed-ledger `invoice_adjustments` (kinds: wallet_credit / manual_credit / manual_debit / override_adjustment).
- `billing_admin_service.py`: `generate()` with **pg_try_advisory_xact_lock** keyed on `(7234891, year*12+month)` → 409 on concurrent; `regenerate=true` preserves payments + manual/wallet adjustments, drops only override-adjustment rows; per-customer atomicity (failures isolated to `failed[]`). `mark_invoice_paid()` uses `SELECT FOR UPDATE`; when method=wallet, wallet_service.adjust fires first so insufficient balance short-circuits without payment row. `apply_wallet_credit()` is atomic (wallet ↓ + invoice_adjustment=−amount + total recompute). `flag_post_billing_adjustment()` hook invoked from `delivery_admin_service.override()` on any billable delta.
- Frontend: `/admin/billing` (period KPI card, GenerateDialog with regenerate-requires-reason + AlertDialog confirm, invoices table with filters + CSV, overdue-customers table) and `/admin/invoices/[id]` (status badges, post-billing + overdue banners, financial summary with adjustments breakdown, line items with snapshot prices, payments, audit timeline, MarkPaidModal + WalletCreditModal + RegenerateDialog).
- Tests: **125/125 pytest** (105 prior + 20 new).
- Live-verified (admin `+919000000001`, preview): **A** Mar-2026 generate → 10 invoices, subtotal = SUM(line_items), line prices = delivery snapshots. **B** Re-run without flag → 409 `invoices_already_exist`. **C** Regenerate with flag → 10 regenerated, `before_state.line_items` captured. **D** Mark-paid full (₹2,960 cash) → status=PAID, payment SUCCESS. **E** Apply ₹5 wallet credit → invoice total 60000→59500 paise, wallet 10000→9500 paise, invariant `SUM(tx)==balance` holds. **F** Override 2026-04-18 delivered→skipped → `has_post_billing_adjustments=true`, override_adjustment row with amount_paise=-7000, audit `billable_delta_paise=-7000` + `flagged_invoice_id` set. Audit snapshot: `billing.generate=2, billing.regenerate=1, invoice.mark_paid=1, invoice.apply_wallet_credit=1, invoice.regenerate=10`.

**Phase 2B.7 — SHIPPED 2026-04-22 (read-only, 3-scenario live-verified)**
- Services: `reports_service.py` (revenue / churn / daily-delivery / bottle-outstanding) + `csv_export_service.py` (StreamingResponse + UTF-8 BOM for Excel, row-by-row generator, no full materialisation).
- API: 4 GET JSON + 5 GET /export streaming endpoints + migrated `/admin/billing/register/export` from client-side (2B.6) to server-side streaming. Admin RBAC on every endpoint.
- Critical semantics: Revenue filters by `Invoice.issued_at` (per spec: "invoices issued in period"), zero-fills daily series for charts. By-product groups `InvoiceLineItem` joined to Invoice to isolate to period. Churn "active on D" = `start_date ≤ D AND (end_date IS NULL OR end_date > D)` — historical accuracy (a sub currently CANCELLED with end_date > D was active on D). Daily-delivery supports route_id + delivery_boy_id filters, computes completion_rate. Bottle-outstanding = `SUM(bottle_ledger.change) HAVING > 0` point-in-time; days_since_return from last `change<0` or first-delivery fallback with `ever_returned` flag.
- Frontend: `/admin/reports` tabbed page (Revenue / Churn / Deliveries / Bottles). Recharts LineChart for revenue, stacked BarChart for delivery status. Each tab has Export CSV that streams the server endpoint via fetch+blob (captures Content-Disposition filename).
- Tests: **137/137 pytest** (125 prior + 12 new): revenue basic, group-by-month, by-product, churn basic, churn-active-at-start-required, daily-delivery, bottle point-in-time, bottle days-since-return (never-returned path), csv streaming (BOM + headers + data), csv respects filters, RBAC 9×2, empty-period zero-fill.
- Live-verified (preview, admin `+919000000001`, container freshly reprovisioned mid-session):
  - **S1** Revenue Apr 2026 → API `invoice_count=10, total_revenue=1,329,500` paise matches SQL `SUM(total_paise)`. Series = 30 daily points. by_product = 6 entries. CSV export 200 OK, 1297 B, BOM `ef bb bf`, structured Summary + Series + By-product.
  - **S2** Bottle outstanding → API `total=14, customers=7` matches SQL `SUM(bal HAVING bal>0) + COUNT`. CSV rows sorted by bottles DESC (Sneha=4, Vikram=3, Amit=2…).
  - **S3** Churn 2026-03 → API `active_start=0, active_end=10, new=10, churned=0, net=+10` matches SQL `COUNT(DISTINCT customer_id)` with the date-range predicate at month boundaries.
- Infrastructure note: the container lost its Postgres install mid-session; reinstalled postgresql-15 + redis-server, recreated `posuhtik`/`posuhtik_dev`/`posuhtik_test`, re-applied all Alembic migrations, re-ran `scripts/seed.py`. All 137 tests green on fresh DB.

**Phase 2B.8 — SHIPPED 2026-02 (scheduler hardening + admin polish, 6 sub-phases)**
- **Phase A (Scheduler migration, P0)**: `jobs/runners.py:monthly_billing` now calls `billing_admin_service.generate_invoices(actor=system_user)` with advisory-lock, audit trail, per-customer atomicity, and retry-once-on-lock-contention. Added `users.is_system` boolean + partial unique index `uq_users_is_system_true` (at most one system user). Migration `e5c1b7f2a3d8` seeds `+910000000000 / System (Automated) / ADMIN / is_system=true`. OTP endpoints return 403 `system_account_no_login` when hit with the system phone. `billing_service.generate_invoices_for_period` now emits `DeprecationWarning` (slated for Phase 3 removal). **Bug found & fixed**: `User` model had duplicate `__table_args__` declarations — second silently overwriting first; merged into one tuple containing both `ix_users_name_trgm` and the partial unique index.
- **Phase B (Audit sweep)**: Verified `nightly_cutoff` emits `orders.generated` and `morning_reminder` emits `reminder.sent`, both with actor=system. `revoked_token_cleanup` deliberately un-audited (pure housekeeping). Documented every scheduled job in `/app/docs/SCHEDULED_JOBS.md` with an 8-column registry (Name, Schedule, Trigger, Lock Key, Audit Action, Mutations, Idempotent, Retry Behavior), lock-key namespace table, common-failure triage runbook, manual-trigger URLs, and deprecation notice.
- **Phase C (Override-adjustments callout)**: Replaced the thin post-billing banner on `/admin/invoices/[id]` with a richer `post-billing-callout` card: shows count + signed ₹ delta total, lists each `override_adjustment` row (amount, reason, actor, timestamp), adds "View order" drill-down links to `/admin/delivery-orders/{reference_id}`, plus a "Regenerate to sync" shortcut opening the existing `RegenerateDialog`. No new API calls (uses existing `adjustments` payload).
- **Phase D (Revenue `view_mode` toggle)**: `GET /api/admin/reports/revenue` and `/export` accept `view_mode ∈ {issued_date, bill_period}`. `bill_period` filters by `(Invoice.year, Invoice.month)`, forces monthly aggregation, zero-fills missing months. Pill toggle on `/admin/reports` Revenue tab (`data-testid="revenue-view-mode-issued|billperiod"`) with explanatory subcopy; group-by Select auto-disables in bill-period mode; CSV filename reflects mode. 3 new tests added (filter correctness + zero-fill, invalid=422, CSV echoes mode).
- **Phase E (Sanity audit)**: Audited all 13 admin pages. Fixed 2 issues: `/admin/delivery-orders/[id]` had forever-loading spinner on 404 → added `delivery-detail-error` branch; dead `/admin/audit-log` nav entry (page never existed) → removed from sidebar, pruned unused `ShieldAlert` import. Documented in `/app/docs/ADMIN_AUDIT_2B8.md` (13-row results table, RBAC verification, loading/empty/error conventions, a11y spot-checks, deliberate out-of-scope list).
- **Phase F (Full regression)**: Backend **146/146 pytest green** (125 prior + 12 Phase 2B.7 + 6 Phase 2B.8-A + 3 Phase 2B.8-D). Frontend E2E via testing_agent_v3_fork verified all 6 Phase 2B.8 UI stories on preview URL; one minor deviation fixed post-review (admin layout now uses `window.location.replace` to guarantee `?error=not_admin` query string is preserved on non-admin redirect).

Deferred (per user): MSG91/Razorpay live wiring, wallet recharge, Green Pledge Meter. Flutter delivery-boy app is a separate project — not in this repo.

## Phase 2C — SHIPPED 2026-02 (invoice PDF generation)
- **Library**: `weasyprint 68.1` (HTML → PDF, chosen over reportlab for template fidelity). Installed successfully in the Emergent container; no fallback needed.
- **Template**: `/app/backend/app/templates/invoice_pdf.html` — single-file Jinja2 template with all 9 required sections (header w/ wordmark logo + business info; invoice meta block with status badge and regen note; bill-to + summary two-col; line items table using `price_paise` snapshot; adjustments table when present; totals stack with Grand Total, Paid, Balance Due; bottle-balance section; UPI QR placeholder + bank details; footer with page counter).
- **Service**: `app/services/invoice_pdf_service.py` with `generate_invoice_pdf` (pure render), `get_or_generate` (lazy + cache), `invalidate` (clears both cache columns).
- **Caching**: migration `f1a3c5e8b2d4` adds `invoices.pdf_generated_at` + `invoices.pdf_storage_path`. First fetch renders + writes via `LocalStorageProvider` at key `invoices/{year}/{month}/{id}.pdf`. Subsequent fetches stream from storage; if the file disappeared out-of-band, regenerates automatically.
- **Invalidation hooks**: invoice regenerate, `flag_post_billing_adjustment` (override), and any status change inside `_recompute_status` (payment / wallet credit) all NULL the two cache columns. File is not deleted on invalidate (stable key → next generate overwrites).
- **StorageProvider**: extended abstract base with `get(key) -> bytes | None`; implemented in `LocalStorageProvider`; S3 stub raises `NotImplementedError` (consistent with existing `put` stub).
- **Endpoints**: `GET /api/me/invoices/{id}/pdf` (customer, owner-only — returns 404 on non-owner so no existence leak) and `GET /api/admin/invoices/{id}/pdf` (admin, any invoice). Both support `?download=true` for `Content-Disposition: attachment`, inline by default.
- **Frontend wiring**: `/admin/invoices/[id]` "PDF" button (`data-testid="invoice-pdf-button"`) now performs an authenticated blob fetch + download. Customer `/invoices/[id]` "Download PDF" button uses the same pattern against the customer endpoint.
- **Tests**: 12 new (`tests/test_invoice_pdf.py`) — basic rendering + `%PDF` magic bytes; content fidelity (API totals match PDF text extracted via `pypdf`); price-snapshot preserved across product price changes; lazy caching (`pdf_generated_at` stable on 2nd fetch); regenerate invalidation; post-billing override invalidation; adjustments rendering (both wallet_credit and override_adjustment); bottle summary with ledger math; customer RBAC (404 not 403 on non-owner); admin can fetch any (+ download mode); storage path verification (file exists on disk); owner can fetch own.
- **Seed update** (`scripts/seed.py`): after generating prev-month invoices, now picks one invoice and applies `flag_post_billing_adjustment(-3500)` so a fresh seed always has one invoice with `has_post_billing_adjustments=true` for the Phase-C callout + Phase 2C override invalidation path. Idempotent — skips if already applied.
- **Live scenarios verified on preview URL**:
  - **S1 (basic)**: Admin fetches PDF for post-billing invoice → 39KB valid PDF, `%PDF` magic, pypdf text extraction shows full layout (header, invoice meta `INV-2026-03-5C0E`, Bill To, 11 line items @ ₹70/L = ₹2,960 subtotal, `Override Adjustment −₹35.00`, Grand Total ₹2,925, Bottle balance +11 delivered / −2 returned / closing 9, UPI QR ₹2,925, footer).
  - **S2 (regenerate invalidation)**: Pre-regen cache populated (`gen=04:34:21`, path set) → `POST /admin/invoices/{id}/regenerate` → cache cleared (both NULL, `regenerated_count=1`) → 2nd fetch regenerates with fresh `gen=04:34:22`.
  - **S3 (post-billing override)**: Pre-override cache POPULATED → `flag_post_billing_adjustment(-14000)` → cache NULL, `has_post_billing=true`, `total_paise` drops from 112000 to 98000 → 2nd PDF fetch shows `Adjustments ₹-140.00`, `Grand total ₹980.00`, override reason "Scenario 3…" embedded in PDF.
- **Regression**: **158/158 pytest green** (146 prior + 12 Phase 2C).
- **Infra note (known recurrence)**: Container lost Postgres mid-session for the second time; reinstalled postgresql-15 + redis-server + pg_trgm, re-applied all migrations through `f1a3c5e8b2d4`, re-ran seed, started backend via uvicorn.

## Phase 3 (later)
- MSG91 wiring (user provides keys)
- Razorpay wiring (user provides test keys)
- Wallet recharge flow
- Green Pledge Meter gamification
- Flutter delivery-boy app (separate project)
- Dedicated `/admin/audit-log` page (backend endpoint already exists; nav entry removed in Phase 2B.8-E)
- **Post-2C polish**: "Post-billing adjustments (last 7 days)" KPI card on `/admin/dashboard` (one-line SQL, approved for post-2C batch — not part of 2C itself).
- TS strict mode (`TECH_DEBT.md §H5`)
- Remove `billing_service.generate_invoices_for_period` now that Phase 2B.8 deprecated it.

## Next immediate actions
1. **Hand off to senior engineer review** — Phase 2C closes the last milestone in this scope per user. No Phase 3 work to propose.
