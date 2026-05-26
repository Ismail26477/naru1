# Local Setup — Posuhtik

> **Target laptop:** fresh macOS or Linux with **Docker + Python 3.11 + Node 20 + yarn 1.22** preinstalled. Windows users: use WSL2 and follow the Linux path.
> **Expected time to green test suite:** ~10 minutes on a modern laptop.

## 0. Prerequisites check

```bash
python3 --version        # 3.11.x
node --version           # v20.x
yarn --version           # 1.22.x
docker --version         # 24.x+
docker compose version   # v2.x
```

If any of these are missing install them first. `nvm install 20 && corepack enable` works well for Node; `pyenv install 3.11.9` for Python.

---

## 1. Start Postgres + Redis via Docker (recommended)

From the project root:

```bash
# Create a compose file if one isn't already present.
cat > docker-compose.yml <<'YAML'
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: posuhtik
      POSTGRES_PASSWORD: posuhtik_dev
      POSTGRES_DB: posuhtik_dev
    ports: ["5432:5432"]
    volumes:
      - posuhtik_pg:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U posuhtik -d posuhtik_dev"]
      interval: 3s
      retries: 10
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
volumes:
  posuhtik_pg: {}
YAML

docker compose up -d
docker compose ps        # both services should be "healthy"
```

### Create the extra test database + enable pg_trgm

```bash
docker compose exec -T postgres psql -U posuhtik -d posuhtik_dev -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
docker compose exec -T postgres psql -U posuhtik -d postgres -c "CREATE DATABASE posuhtik_test OWNER posuhtik;"
docker compose exec -T postgres psql -U posuhtik -d posuhtik_test -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

---

## 2. Backend — install, migrate, seed, run

```bash
cd backend

python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# weasyprint needs native fonts on Linux. macOS bundles them.
# Debian/Ubuntu: sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libcairo2
# Fedora:        sudo dnf install -y pango cairo
# macOS:         no action needed

cp .env.example .env
# Open .env and verify the DATABASE_URL / DATABASE_URL_SYNC / TEST_DATABASE_URL
# point at localhost:5432 and the user/pw match what you set in docker-compose.

# Apply all migrations
alembic upgrade head

# Idempotent dev seed: creates admin, delivery boys, 10 customers, 6 products,
# 2 routes, March 2026 delivery orders, and ONE invoice with
# has_post_billing_adjustments=true (seeded so the Phase-C callout renders).
python scripts/seed.py

# Run the full test suite — expect 158 passed.
pytest -v

# Start the API (hot-reload).
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Health check: `curl http://localhost:8001/api/health` → `{"status":"healthy"}`.

---

## 3. Frontend — install and run

In a **second terminal**:

```bash
cd frontend

yarn install

cp .env.example .env
# Edit .env — set NEXT_PUBLIC_BACKEND_URL=http://localhost:8001
#                REACT_APP_BACKEND_URL=http://localhost:8001

yarn dev                 # Next.js dev server on http://localhost:3000
```

Visit **http://localhost:3000**.

---

## 4. Test credentials (seeded)

| Role | Phone | OTP |
|---|---|---|
| Admin | `+919000000001` | `123456` |
| Delivery boy | `+919000000002` | `123456` |
| Customer | `+919000000004` | `123456` |
| System (login blocked) | `+910000000000` | — |

Login URLs: `/login` (customer) and `/admin/login` (admin). The OTP field accepts `123456` in dev regardless of what the request-otp response returned; this is controlled by `settings.DEV_MODE=true` in `.env`.

---

## 5. Smoke-test the money path (90 seconds)

```bash
# Auth
TOKEN=$(curl -s -X POST http://localhost:8001/api/auth/verify-otp \
  -H "Content-Type: application/json" \
  -d '{"phone":"+919000000001","otp":"123456"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Pick any invoice
INV_ID=$(curl -s "http://localhost:8001/api/admin/invoices?limit=1" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin)['items'][0]['id'])")

# Fetch its PDF
curl -o /tmp/inv.pdf "http://localhost:8001/api/admin/invoices/$INV_ID/pdf" \
  -H "Authorization: Bearer $TOKEN"
file /tmp/inv.pdf        # PDF document, version 1.7
```

Open `/tmp/inv.pdf` in any PDF viewer — you should see the full invoice layout.

---

## 6. Reset the DB (if you break something)

```bash
docker compose down -v          # WARNING: wipes all data
docker compose up -d
docker compose exec -T postgres psql -U posuhtik -d posuhtik_dev -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
docker compose exec -T postgres psql -U posuhtik -d postgres -c "CREATE DATABASE posuhtik_test OWNER posuhtik;"
docker compose exec -T postgres psql -U posuhtik -d posuhtik_test -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
cd backend && alembic upgrade head && python scripts/seed.py
```

---

## 7. Native Postgres (no Docker) — alternative path

If you prefer system Postgres:

```bash
# macOS
brew install postgresql@15 redis
brew services start postgresql@15
brew services start redis
createuser -s posuhtik
psql postgres -c "ALTER USER posuhtik WITH PASSWORD 'posuhtik_dev';"
createdb -O posuhtik posuhtik_dev
createdb -O posuhtik posuhtik_test
psql posuhtik_dev -c "CREATE EXTENSION pg_trgm;"
psql posuhtik_test -c "CREATE EXTENSION pg_trgm;"

# Debian/Ubuntu
sudo apt-get install -y postgresql-15 redis-server
sudo -u postgres psql -c "CREATE USER posuhtik WITH PASSWORD 'posuhtik_dev' SUPERUSER;"
sudo -u postgres psql -c "CREATE DATABASE posuhtik_dev OWNER posuhtik;"
sudo -u postgres psql -c "CREATE DATABASE posuhtik_test OWNER posuhtik;"
sudo -u postgres psql -d posuhtik_dev -c "CREATE EXTENSION pg_trgm;"
sudo -u postgres psql -d posuhtik_test -c "CREATE EXTENSION pg_trgm;"
```

Then resume at **Section 2** above.

---

## 8. Production notes (not implemented, but known)

- The in-process APScheduler must be replaced with a single-worker deployment or Celery/RQ when moving behind a load balancer. Currently, advisory locks in `billing_admin_service.generate_invoices` prevent double-runs even if two pods fire at once, but `nightly_cutoff` uses session-level locks that need a single worker.
- `LocalStorageProvider` in `providers/stubs.py` writes PDFs to `backend/local_storage/`. Swap to `S3StorageProvider` (stub in `providers/real.py`) for production; the DB only stores the storage key, not the URL.
- All 3rd-party providers (MSG91, Razorpay, Firebase FCM, Google Maps) are stubs. See `/app/docs/TECH_DEBT.md` for the swap plan.
