# Posuhtik — Scheduled Jobs Reference

> **Audience:** Senior reviewers and on-call engineers debugging production cron behaviour.
> **Last reviewed:** Phase 2B.8 (Feb 2026).
> **Source files:** `app/jobs/scheduler.py` (registration), `app/jobs/runners.py` (bodies).

APScheduler (`AsyncIOScheduler`) is started in-process from `app/main.py` unless
`app.state._disable_scheduler` is set (tests). All triggers are in IST
(`Asia/Kolkata`). Each run opens a dedicated `AsyncSessionLocal`, commits on
success, rolls back on exception.

## Job registry

| Job Name | Schedule (IST) | Trigger Type | Lock Key | Audit Action | Mutations | Idempotent | Retry Behavior |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `nightly_cutoff` | 20:00 daily (`CUTOFF_HOUR_IST`) | cron (hour, minute=0) | `pg_try_advisory_lock(7101)` (session-level) | `orders.generated` — actor=system, entity=`delivery_batch:<YYYY-MM-DD>`, after_state `{date, created, locked}` | Inserts missing `delivery_orders` for tomorrow and stamps `cutoff_locked_at`. No deletes. | **Yes.** `generate_orders_for_date` upserts by `(subscription_id, delivery_date)`; `lock_orders_for_date` only sets `cutoff_locked_at` if `NULL`. | If advisory lock held → logs WARN, returns `JobRunResult(job="skipped")`, no retry (next day's cron covers; manual admin trigger available). |
| `monthly_billing` | 02:00 on day 1 (`BILLING_DAY_OF_MONTH`) | cron (day, hour, minute=0) | `pg_try_advisory_xact_lock(7234891, year*12+month)` (inside `billing_admin_service.generate_invoices`) | `billing.generate` — actor=system, entity=`<YYYY-MM>`, after_state includes `created_count`, `skipped_customers`, `failed[]` | Inserts `invoices` + `invoice_line_items` for previous month. Per-customer atomic: one bad customer lands in `failed[]` without aborting the batch. | **Yes.** If invoices already exist for `(year, month)` → raises HTTP 409 `invoices_already_exist`; the runner catches this, logs WARN, and returns `status=already_exists_skipped`. | On 409 `billing_generation_locked` → `asyncio.sleep(30)` and retry once. If still locked → logs ERROR + returns `status=lock_contention_gave_up` (next scheduled run or manual admin action recovers). |
| `morning_reminder` | 07:00 daily | cron (hour, minute=0) | `pg_try_advisory_lock(7103)` (session-level) | `reminder.sent` — actor=system, entity=`reminder_batch:<YYYY-MM-DD>`, after_state `{date, sent}` | Inserts one `notifications_log` row per route with an assigned delivery boy (push template `delivery_reminder`). No deletes. Currently stubbed provider (no real FCM). | **Per tick.** Advisory lock guarantees single run per cron tick; audit action is *not* idempotent across different ticks (a second manual run for the same day would produce a second batch of `reminder.sent` rows). Acceptable — reminders are informational. | Lock held → logs WARN, returns `JobRunResult(job="skipped")`, no retry. |
| `revoked_token_cleanup` | 03:30 daily | cron (hour, minute=30) | `pg_try_advisory_lock(7104)` (session-level) | **N/A (read/cleanup)** — see note below. | `DELETE FROM revoked_tokens WHERE expires_at < NOW()` via `token_service.cleanup_expired`. | **Yes.** Deleting already-expired rows is naturally idempotent. | Lock held → logs WARN, returns `JobRunResult(job="skipped")`, no retry. |

> **Note on `revoked_token_cleanup` audit exemption:** This job performs no
> business-meaningful mutation. Expired rows in `revoked_tokens` are dead weight
> whose retention has no security or financial value, so deletion is a pure
> housekeeping operation. Per Posuhtik's audit policy (`TECH_DEBT §5.3`), only
> money-path and customer-state mutations require audit rows. Recording a
> `token_cleanup.swept` action would add volume without adding forensic value.

## Lock key namespace

| Key | Owner | Scope |
| --- | --- | --- |
| `7101` | `nightly_cutoff` | session-level advisory lock |
| `7102` | (reserved for `monthly_billing` — currently **unused**; `generate_invoices` uses transaction-level advisory lock with a different key) | reserved |
| `7103` | `morning_reminder` | session-level advisory lock |
| `7104` | `revoked_token_cleanup` | session-level advisory lock |
| `(7234891, y*12+m)` | `billing_admin_service.generate_invoices` | transaction-level (`pg_try_advisory_xact_lock`); auto-released on commit/rollback |

## Common failure modes & triage

1. **`monthly_billing` silently skipped.** Check logs for `invoices already exist` — means a human admin ran `/api/admin/billing/generate` before the cron fired. Check `audit_log` for a human actor on `billing.generate` for the relevant `(year, month)`. This is expected behaviour.
2. **`nightly_cutoff` skipped.** Grep for `advisory lock 7101 held by another worker`. If running a single pod, this means the previous run never released (e.g., pod crashed mid-job). Sessions reconnect → lock auto-released. No manual intervention.
3. **`morning_reminder` sent zero notifications.** Verify at least one `routes.delivery_boy_id IS NOT NULL`. Reminder currently targets route-assigned boys only.
4. **Duplicate audit rows for the same `(action, entity_id)`.** Expected on manual re-run after a pod restart. Differentiate by `actor_user_id` (system vs. human admin) and `created_at`.

## Testing

- `tests/test_2b8_scheduler.py` covers: system-user seeding, partial-unique-index singleton, OTP-block for `is_system=true`, audit row emission from `monthly_billing`, already-exists skip path, and `DeprecationWarning` on the legacy `billing_service.generate_invoices_for_period`.
- `tests/test_jobs_and_webhooks.py` covers nightly cutoff order generation and locking.

## Manual triggers

Admins can invoke any job on demand via:
- `POST /api/admin/jobs/nightly_cutoff/trigger`
- `POST /api/admin/jobs/monthly_billing/trigger`
- `POST /api/admin/jobs/morning_reminder/trigger`
- `POST /api/admin/jobs/revoked_token_cleanup/trigger`

Manual triggers produce audit rows with the admin's user id as `actor_user_id`
(not the system user). Useful for forensic distinction during incident replay.

## Deprecations

- `app.services.billing_service.generate_invoices_for_period` — deprecated in Phase 2B.8. Emits `DeprecationWarning`. Slated for removal in Phase 3. **Do not call from new code.** All new billing flows must go through `billing_admin_service.generate_invoices`.
