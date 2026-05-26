"""Reset dev DB: drop all tables, re-run Alembic, then seed.

Usage: python -m scripts.reset_db
"""
from __future__ import annotations
import asyncio
import subprocess
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.session import engine


async def _drop_all():
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO posuhtik"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))


def main():
    print("→ dropping schema")
    asyncio.run(_drop_all())
    print("→ running alembic upgrade head")
    r = subprocess.run(["alembic", "upgrade", "head"], cwd="/app/backend")
    if r.returncode != 0:
        raise SystemExit(r.returncode)
    print("→ seeding")
    from scripts.seed import seed
    asyncio.run(seed())
    print("✓ reset complete")


if __name__ == "__main__":
    main()
