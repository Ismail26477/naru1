# Emergent-Specific Gotchas

> Everything in this file is an artefact of the Emergent preview container. **None of it should survive** a move to local dev or production hosting. Use this as a pre-flight checklist when handing off the codebase.

## 1. Postgres re-provisioning during long sessions

**Symptom:** Mid-session, `psql`, the `postgres` system user, and the `/var/run/supervisor.sock` disappear. Supervisor refuses to start because `program:postgres` references a non-existent user.

**Observed:** Twice during this project (once in Phase 2B.7, once during Phase 2C live verification).

**Resolution (documented in `/app/memory/PRD.md`):**

```bash
apt-get install -y postgresql-15 postgresql-client-15 redis-server
pg_ctlcluster 15 main start
redis-server --daemonize yes
sudo -u postgres psql -c "CREATE USER posuhtik WITH PASSWORD 'posuhtik_dev' SUPERUSER;"
sudo -u postgres psql -c "CREATE DATABASE posuhtik_dev OWNER posuhtik;"
sudo -u postgres psql -c "CREATE DATABASE posuhtik_test OWNER posuhtik;"
sudo -u postgres psql -d posuhtik_dev  -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
sudo -u postgres psql -d posuhtik_test -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
cd /app/backend && alembic upgrade head && python scripts/seed.py
nohup uvicorn app.main:app --host 0.0.0.0 --port 8001 > /tmp/uvicorn.log 2>&1 &
```

**Action for local/prod:** No action needed. Docker-compose or a managed Postgres (RDS, Cloud SQL, Neon) is inherently stable. Just ensure `pg_trgm` extension is enabled on the `public` schema.

---

## 2. Supervisor config references a missing `postgres` unix user

**Symptom:** `supervisord` refuses to boot with `Error: Invalid user name postgres in section 'program:postgres'` because the container's `postgres` user was never created (despite postgresql-15 being installed).

**Resolution during the session:** ran `uvicorn` directly in the background instead of via supervisor. See the command above.

**Action for local/prod:** **Do not copy `/etc/supervisor/conf.d/*` from the Emergent container.** The supervisor stanza was Emergent-specific. On local, either (a) don't use supervisor at all (two terminals: `uvicorn` + `yarn dev`), or (b) write your own clean supervisor/systemd/pm2 unit per service.

---

## 3. Hard-coded preview URL

**File:** `/app/frontend/.env` — line `REACT_APP_BACKEND_URL=https://milk-console.preview.emergentagent.com`.

**Why:** Emergent injects this on startup so the customer & admin SPA can reach the backend through the ingress proxy. The `(app)/...` and `admin/...` Next.js pages read `process.env.NEXT_PUBLIC_BACKEND_URL` first, then fall back to `REACT_APP_BACKEND_URL` via `lib/api.ts`.

**Action for local/prod:**
- Delete/overwrite both values in `frontend/.env` (or create `frontend/.env.local`).
- Local dev: `NEXT_PUBLIC_BACKEND_URL=http://localhost:8001` and same for `REACT_APP_BACKEND_URL`.
- Production: point at your API domain, e.g. `https://api.posuhtik.com`.

---

## 4. Kubernetes ingress `/api` routing assumption

**What Emergent does:** Incoming requests to `https://<host>/api/*` are rewritten to `:8001/api/*`, everything else goes to `:3000` (Next.js). This is why every backend route is prefixed with `/api`.

**Action for local/prod:** Keep the `/api` prefix — it's an intentional architectural choice, not an Emergent quirk. For production, put Nginx/Caddy/Cloudflare in front with an equivalent rule: `location /api { proxy_pass http://backend:8001; }`.

---

## 5. No `.git` history in the preview container

**Why:** Commits to the working tree are done by Emergent's auto-commit daemon with opaque UUID-named messages (see `git log` for the pattern `auto-commit for <uuid>`), not by the developer. The meaningful milestone commits have human-readable subjects (`Phase 2B.7: Reports...`).

**Action for senior reviewer:**
- After the user runs "Save to GitHub", the pushed repository should have the full history. If only a squashed snapshot arrives, that's a platform limitation, not intentional.
- Milestone-level diffs are recoverable from: `PRD.md` (written to after every phase), `TECH_DEBT.md`, `docs/SCHEDULED_JOBS.md`, `docs/ADMIN_AUDIT_2B8.md`, and the 10 Alembic migration filenames.

---

## 6. `emergentintegrations` library

**Not used** in this project. The stack is FastAPI + weasyprint + pypdf + standard SQLAlchemy. No Emergent-proprietary Python packages were added to `requirements.txt`.

**Action:** None.

---

## 7. Local Storage path for PDFs

**File:** `backend/app/providers/stubs.py` writes PDFs under `backend/local_storage/invoices/{year}/{month}/{id}.pdf` via `LocalStorageProvider`.

**Why it works on Emergent:** `/app/backend/local_storage` is inside the ephemeral pod FS. **PDFs generated in this preview will be lost on container restart.** The DB stores only the storage key (not file content), so the next fetch after a restart hits a "cached path missing on disk" code path and regenerates transparently (you'll see a WARN log line: `invoice_pdf: cached path ... missing on disk; regenerating`).

**Action for production:**
- Swap `STORAGE_STUB=true` → `false` in backend `.env` and supply S3 credentials, **after** implementing `S3StorageProvider.put` and `.get` (both currently raise `NotImplementedError` in `providers/real.py`).
- The `invoices/{year}/{month}/{id}.pdf` key format is already S3-friendly.

---

## 8. Dev OTP `123456`

**File:** `backend/app/services/otp_service.py` — when `settings.DEV_MODE=true`, any requested OTP is logged and **also `123456` is always accepted** during verify. Real MSG91 integration is stubbed.

**Action for production:** Set `DEV_MODE=false` and `STUBS=false`, wire MSG91 credentials into `providers/real.py:MSG91Provider`. **Do not forget** — leaving `DEV_MODE=true` in production is a total auth bypass.

---

## 9. APScheduler in-process

**File:** `backend/app/jobs/scheduler.py` starts an `AsyncIOScheduler` in the same process as the FastAPI app.

**Why it's fine on Emergent:** Single-pod preview, no load balancer.

**Action for production:**
- If running behind a load balancer with multiple pods, the current advisory-lock-per-job design prevents double-execution of `monthly_billing` (transaction-level lock) but `nightly_cutoff` / `morning_reminder` use session-level locks that are released on pod restart — theoretically two pods could race at second zero of the cron tick.
- Simplest prod option: run the scheduler in exactly one pod (set `app.state._disable_scheduler = True` on the others via env flag), OR move to Celery Beat / dedicated worker.

---

## 10. `test_credentials.md`

**File:** `/app/memory/test_credentials.md` — lists seeded phones + the universal dev OTP. Emergent's internal testing agent reads this file.

**Action:** Safe to commit. It contains no secrets — everyone can see seed data.

---

## 11. Jinja2 template path resolution

**File:** `backend/app/services/invoice_pdf_service.py` uses `Path(__file__).resolve().parent.parent / "templates"` to find `invoice_pdf.html`.

**Why it matters:** If the backend is packaged into a container with an altered working-dir layout, this resolution still works because it's relative to the module file, not `cwd`. No action.

---

## 12. `yarn` vs `npm`

**Convention:** This project uses **yarn 1.22** exclusively. `package-lock.json` should **not** exist; only `yarn.lock`.

**Action:** Never `rm yarn.lock && npm install` — that breaks peer-dep resolution in shadcn/Radix.

---

## One-line summary for the reviewer

Of the 12 items above, only **#3 (env URLs)**, **#7 (local storage)**, **#8 (dev OTP)**, and **#9 (scheduler topology)** are actual codebase changes needed for production. Everything else is Emergent-preview operational noise and becomes a non-issue the moment you `git clone` locally.
