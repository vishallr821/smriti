"""Asyncpg connection pool helpers for Supabase Postgres."""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import asyncpg

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


def _resolve_dsn() -> str:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    if not supabase_url:
        raise RuntimeError("SUPABASE_URL is required")

    if supabase_url.startswith(("postgres://", "postgresql://")):
        return supabase_url

    parsed = urlparse(supabase_url)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        raise RuntimeError(
            "SUPABASE_URL must be a Postgres connection string for direct asyncpg access"
        )

    raise RuntimeError("SUPABASE_URL must be a valid Supabase Postgres connection string")


def _is_pooler_dsn(dsn: str) -> bool:
    parsed = urlparse(dsn)
    host = (parsed.hostname or "").lower()
    return "pooler.supabase.com" in host or parsed.port == 6543


async def _create_pool(dsn: str, *, use_pooler_mode: bool) -> asyncpg.Pool:
    pool_kwargs: dict[str, object] = {
        "dsn": dsn,
        "min_size": 2,
        "max_size": 10,
        "command_timeout": 30,
    }
    if use_pooler_mode:
        pool_kwargs["statement_cache_size"] = 0
        pool_kwargs["prepared_statement_cache_size"] = 0

    try:
        return await asyncpg.create_pool(**pool_kwargs)
    except TypeError:
        # Some asyncpg versions do not expose prepared_statement_cache_size.
        if use_pooler_mode and "prepared_statement_cache_size" in pool_kwargs:
            pool_kwargs.pop("prepared_statement_cache_size", None)
            return await asyncpg.create_pool(**pool_kwargs)
        raise


async def get_pool() -> asyncpg.Pool:
    """Return a singleton asyncpg pool."""
    global _pool

    if _pool is not None:
        return _pool

    async with _pool_lock:
        if _pool is None:
            dsn = _resolve_dsn()
            use_pooler_mode = _is_pooler_dsn(dsn)

            parsed = urlparse(dsn)
            host = parsed.hostname or "unknown"
            print(f"[DB] Connecting to: {host} (port: {parsed.port or 5432})")

            if use_pooler_mode:
                print("[DB] Using Supabase Transaction Pooler (IPv4)")
            else:
                print("[DB] Using Supabase direct connection")

            try:
                _pool = await _create_pool(dsn, use_pooler_mode=use_pooler_mode)
                print("[DB] Connection pool created successfully")
            except (
                asyncpg.exceptions.DuplicatePreparedStatementError,
                asyncpg.exceptions.InsufficientPrivilegeError,
            ) as exc:
                raise RuntimeError(
                    "Connection failed due to prepared statements or privileges. "
                    "If using Supabase pooler, enable pooler mode settings "
                    "(statement_cache_size=0, prepared_statement_cache_size=0)."
                ) from exc
    return _pool


async def close_pool() -> None:
    """Close the singleton pool if it exists."""
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None