"""Drop and recreate the public schema for deterministic demo resets."""

from __future__ import annotations

import asyncio

import asyncpg

from smriti.db.connection import _is_pooler_dsn, _resolve_dsn


async def main() -> None:
    dsn = _resolve_dsn()
    kwargs: dict[str, object] = {"dsn": dsn}
    if _is_pooler_dsn(dsn):
        kwargs["statement_cache_size"] = 0

    conn = await asyncpg.connect(**kwargs)
    try:
        await conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        await conn.execute("CREATE SCHEMA public")
        await conn.execute("GRANT ALL ON SCHEMA public TO postgres")
        await conn.execute("GRANT ALL ON SCHEMA public TO public")
        print("public schema reset complete")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
