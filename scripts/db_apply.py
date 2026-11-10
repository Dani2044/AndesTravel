"""Apply supabase/migrations/*.sql and supabase/seed.sql to TOOLS_DATABASE_URL.

    make db-apply            # reads TOOLS_DATABASE_URL from .env

The migration is idempotent (create ... if not exists) and the seed upserts, so it is
safe to re-run. The URL is never printed.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg

ROOT = Path(__file__).resolve().parent.parent


async def main() -> int:
    url = os.environ.get("TOOLS_DATABASE_URL", "")
    if not url:
        print("TOOLS_DATABASE_URL is not set (put it in .env).", file=sys.stderr)
        return 2
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    files = sorted((ROOT / "supabase" / "migrations").glob("*.sql")) + [
        ROOT / "supabase" / "seed.sql"
    ]
    conn = await asyncpg.connect(url, statement_cache_size=0, timeout=30)
    try:
        for f in files:
            await conn.execute(f.read_text(encoding="utf-8"))
            print(f"applied {f.relative_to(ROOT)}")
        n = await conn.fetchval("select count(*) from packages where active")
        print(f"packages active: {n} (host {urlsplit(url).hostname})")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
