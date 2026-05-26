# Technical Debt Backlog — Posuhtik

*Living document. Updated after every audit / sprint.*
*Last updated: 2026-04-22 (Phase 2B.1 shipped; §5.3 resolved).*

Severity legend:
- **🔴 HIGH** — production risk
- **🟠 MEDIUM** — friction / future pain
- **🟡 LOW** — cosmetic / convention

---

## 1. Test coverage gaps

### 1.1 Schedule-override `expand()` coverage 63% · 🟠 MEDIUM · **~45 min**
`app/services/schedule_service.py` — the four-branch frequency dispatch (daily / alternate / weekly / custom) plus override handling has many permutations. Only the common paths are covered.
**Plan:** add parametrised tests across all four frequencies × (no override | skip override | quantity override | override on unscheduled day).

### 1.2 `middleware/auth.py` coverage 62% · 🟠 MEDIUM · **~20 min**
Refresh-token path, invalid-subject, expired-token, and "not an access token" branches are not tested.
**Plan:** add `tests/test_jwt_edges.py` with each error branch mocked.

### 1.3 Cutoff service coverage 67% · 🟡 LOW · **~15 min**
Deferred per prior decision. `earliest_modifiable_date` + a few helper branches. Core 8 PM cutoff is fully tested.

---

## 2. Test infrastructure

### 2.1 `app.state._disable_scheduler = True` test hack · 🟠 MEDIUM · **~30 min**
`tests/conftest.py` toggles this attribute to suppress APScheduler during pytest. Fragile — relies on mutating app state. Should be proper DI: `get_scheduler()` dependency that returns a no-op in test mode.

### 2.2 `scripts/reset_db.py` asyncpg event-loop bug · 🟠 MEDIUM · **~20 min**
Mixing `asyncio.run(_drop_all())` + `subprocess alembic` + `asyncio.run(seed())` leaves the pre-created `engine` bound to a dead loop. Workaround: use separate process or spawn fresh engine per call.

---

## 3. Frontend

### 3.1 `cutoff.ts` raw `Date.UTC` math · 🟡 LOW · **~30 min**
Works correctly (7 unit tests on backend mirror mathematics) but readability is poor. Should migrate to `date-fns-tz` (already in package.json).

### 3.2 TypeScript `strict: false` — **H5 from audit** · 🔴 HIGH · **~2 hours**
Deferred to post-Phase-2C polish. Requires typing shadcn JSX wrappers or converting to .tsx.

### 3.3 401 auto-refresh in `apiFetch` — **M3 from audit** · 🟠 MEDIUM · **~1 hour**
Folded into Phase 2B frontend work.

### 3.4 `queryClient.ts` not extracted — **M4 from audit** · 🟡 LOW · **~5 min**
Folded into Phase 2B.

### 3.5 Native `<input type="date">` in Skip dialog · 🟡 LOW · **~20 min**
Should use shadcn `Calendar` popover.

---

## 4. Integrations / provider pattern

### 4.1 Five shells in single `real.py` — **M1 from audit** · 🟡 LOW · **~20 min**
Split into `msg91.py, razorpay.py, fcm.py, google_maps.py, s3.py` **only** when wiring the first real provider — that's when the physical separation pays off.

### 4.2 Token revocation uses DB + in-process `cachetools` — **H3 resolution** · 🟠 MEDIUM · **~30 min when Redis is added**
In-process TTL cache works for single-worker deploys. When we scale horizontally, swap to Redis SET with TTL = token expiry. Interface in `services/token_service.py` is isolated — no call-site changes needed.

### 4.3 Admin force-logout uses `is_active=False` sentinel instead of per-JTI revocation · 🟠 MEDIUM · **~1 hour**
The blacklist table only holds JTIs we know about (logouts). For admin-triggered mass-revocation, we flip `User.is_active=False` and rely on `get_current_user`'s active-user check. Side-effect: admin must explicitly `/admin/users/{id}/reactivate` before the user can log in again. Acceptable for v1; future improvement: add `User.tokens_invalid_before` timestamp claim and check inside `get_current_user`.

---

## 5. Security

### 5.1 OTP codes stored plaintext · 🟡 LOW · **~20 min**
5-min TTL + consumed-at mark + 5-attempts cap means realistic exposure is tiny. Still, hashing with a fast-compare scheme (not bcrypt — too slow for OTP) like SHA-256+HMAC would be cleaner.

### 5.2 No 2FA / device binding for admin · 🟠 MEDIUM · **~half day**
Admin login currently uses the same OTP flow as customers. For production, admin should require hardware-key or at minimum bound-device sessions.

### 5.3 No structured audit log of admin actions · ✅ **RESOLVED 2026-04-22 (Phase 2B.1)**
Audit log infrastructure landed in Phase 2B.1:
- Model: `app/models/audit_log.py` · Migration: `alembic/versions/8d4c1a2e5f10_add_audit_log.py`
- Service: `app/services/audit_service.py` · single-choke-point `log_action(...)`
- API: `GET /api/admin/audit-log?from=&to=&actor=&action=&entity_type=&entity_id=`
- Schema: actor_user_id, actor_role, action, entity_type, entity_id, before_state (JSONB), after_state (JSONB), reason, ip_address, user_agent, created_at

**Coverage in Phase 2B.1:** infra only (no call sites yet).
**Remaining (will be wired per sub-milestone 2B.2–2B.8):** decorator/service calls on customer.approve, customer.wallet_adjust, customer.bottle_adjust, delivery_order.override, product.price_change, invoice.regenerate, user.revoke_tokens. Each mutating admin endpoint must call `audit_service.log_action(...)` before flush.
**Next enhancement:** tamper-evident chaining (hash-linked rows) once compliance audit is imminent.

### 5.4 Dev `JWT_SECRET_KEY` committed in `.env` · 🟡 LOW (dev only) · **0 min for dev**
Rotate with a fresh random ≥64-byte value on first production deploy. The `.env` file is in `.gitignore` for real deployments.

### 5.5 No audit trail for customer-facing mutations · 🟡 MEDIUM (becomes 🔴 HIGH once 500+ customers) · **~3 hours**
Customer actions (subscription modify, skip override, address change) are not audit-logged. If a customer disputes "I didn't skip that day", we have no record of when/how the skip was created.
**Plan:** Add generic `audit_log` table (`actor_user_id, action, entity_type, entity_id, before_state_json, after_state_json, ip_address, user_agent, created_at`). Hook via SQLAlchemy event listeners on key tables.
**Cross-ref:** Related to §5.3 admin audit log (same table, different actor role).

---

## 6. Architecture

### 6.1 No API versioning — flat `/api` instead of `/api/v1` · 🟠 MEDIUM · **~30 min**
A mobile app out in the wild with `/api/me` cannot tolerate breaking changes. Should namespace as `/api/v1` now while change cost is low.

### 6.2 DB enum columns store UPPERCASE names (Python enum `.name`) · 🟡 LOW · **~30 min + migration**
API returns lowercase (Pydantic `use_enum_values`). External SQL consumers would see `DELIVERED`, `ACTIVE`, etc. Fix: `SqlEnum(..., values_callable=lambda e: [x.value for x in e])` on every enum column + `USING status::text::new_status` data migration.

### 6.3 `revoke_all_for_user` is a no-op wrapper · 🟠 MEDIUM · **~2 hours (with User.tokens_invalid_before refactor)**
See 4.3. Placeholder lives in `services/token_service.py`.

---

## 7. Observability

### 7.1 No Sentry / error aggregation · 🟠 MEDIUM · **~1 hour**
Unhandled exceptions are logged but not aggregated. First production incident will be painful to diagnose.

### 7.2 No uptime monitoring · 🟠 MEDIUM · **~30 min**
No external ping on `/api/health`. Add UptimeRobot / Better Uptime.

### 7.3 No structured log aggregation · 🟡 LOW · **~2 hours**
Logs are structured JSON via `core/logging_config.py` but only land in supervisor stdout. No Loki / CloudWatch / Axiom sink.

---

## 8. Data / migrations

### 8.1 No data migration plan for Phase 3 schema changes · 🟠 MEDIUM · **n/a yet**
Once real customers are billed, schema changes will need zero-downtime migrations (Alembic expand-contract pattern, feature flags, dual-write periods).

### 8.2 No DB backup strategy defined · 🔴 HIGH · **~1 hour for plan, ~1 day to implement**
See "Production deployment checklist" below.

---

## 9. Explicit carry-over from audit (2026-04-22)

| ID | Title | Status | Severity |
|---|---|---|---|
| H1 | CORS explicit whitelist | **FIXED** | — |
| H2 | OTP rate-limit per phone + per IP | **FIXED** | — |
| H3 | Token revocation (logout + admin force-logout) | **FIXED** (with caveat 4.3) | 🟠 residual |
| H4 | MONGO_URL leftover | **FIXED** | — |
| H5 | TypeScript strict mode | Deferred to post-2C | 🔴 |
| M1 | Provider pattern file layout | Deferred | 🟡 |
| M2 | Billing test magic numbers (₹35) | **FIXED** | — |
| M3 | 401 auto-refresh in apiFetch | Fold into Phase 2B | 🟠 |
| M4 | Extract `lib/queryClient.ts` | Fold into Phase 2B | 🟡 |
| M5 | Cutoff service coverage | Phase 2C polish | 🟡 |
| L1 | DB enum UPPERCASE | See 6.2 | 🟡 |
| L2 | NotificationChannel unified class | Phase 3 | 🟡 |
| L3 | OTP plaintext storage | See 5.1 | 🟡 |
| L4 | Seed 30 days history | **FIXED** | — |
| L5 | /admin/customers/{id} detail | Phase 2B scope | 🟡 |
| L6 | Native date picker in Skip dialog | See 3.5 | 🟡 |

---

## 10. Production deployment checklist (pre-launch gate)

**Before any real customer can sign up.**

### 10.1 Secrets & config
- [ ] Rotate `JWT_SECRET_KEY` to fresh ≥64-byte random
- [ ] Set `APP_ENV=production` (disables dev OTP `123456` backdoor)
- [ ] Set `CORS_ORIGINS` to exact prod frontend URL(s), no wildcards
- [ ] Set `DEBUG=false`
- [ ] Provision real keys: `MSG91_AUTH_KEY`, `MSG91_TEMPLATE_ID`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `GOOGLE_MAPS_API_KEY`, `FCM_SERVICE_ACCOUNT_JSON`, `S3_*`
- [ ] Flip providers: `SMS_PROVIDER=msg91`, `PAYMENT_PROVIDER=razorpay`, `PUSH_PROVIDER=fcm`, `GEOCODER_PROVIDER=google`, `STORAGE_PROVIDER=s3`

### 10.2 Infrastructure
- [ ] Managed Postgres with daily snapshots (7-day retention min) + PITR
- [ ] Redis cluster (for scaling token revocation — see 4.2)
- [ ] HTTPS termination (TLS 1.2+) with HSTS header
- [ ] Rate-limiting at edge (Cloudflare / AWS WAF) on `/auth/*`
- [ ] Container runtime with at least 2 replicas

### 10.3 Monitoring
- [ ] Sentry DSN configured (see 7.1)
- [ ] Uptime ping on `/api/health` (see 7.2)
- [ ] Log aggregation sink (see 7.3)
- [ ] APScheduler job-run Prometheus / StatsD metrics

### 10.4 Data
- [ ] DB backup verified by actual restore rehearsal
- [ ] Invoice PDFs backed up (S3 versioning enabled)

### 10.5 Security
- [ ] Audit log infrastructure live (see 5.3) — **BLOCKER for prod**
- [ ] Penetration test on auth flow + webhook signature verification
- [ ] Razorpay webhook signature verified end-to-end (test + live)
- [ ] Admin accounts have 2FA (see 5.2) — **recommended, not blocker**

### 10.6 Ops runbook
- [ ] Documented procedure for: admin force-logout user, refund via Razorpay, manual invoice regeneration, wallet adjustment, bottle ledger correction
- [ ] Incident escalation contacts

---

## 11. Monitoring gaps (summary)

See sections 7.1–7.3 + 5.3. **Single biggest gap is structured audit log of admin actions (5.3).** Everything else is deferrable; audit log is a compliance prerequisite.
