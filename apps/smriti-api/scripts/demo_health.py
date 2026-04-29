"""Pre-demo dependency health checks."""

from __future__ import annotations

import asyncio
import os
import sys
import time

import asyncpg
import httpx

from smriti.config import settings
from smriti.db.connection import _is_pooler_dsn, _resolve_dsn


async def check_http(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
        return (resp.status_code < 500, f"{url} ({resp.status_code})")
    except Exception as exc:
        return (False, f"{url} ({exc})")


async def check_db() -> tuple[bool, str]:
    try:
        dsn = _resolve_dsn()
        kwargs: dict[str, object] = {"dsn": dsn}
        if _is_pooler_dsn(dsn):
            kwargs["statement_cache_size"] = 0
        conn = await asyncpg.connect(**kwargs)
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        return (True, "pg connection ok")
    except Exception as exc:
        return (False, f"pg connection failed ({exc})")


async def check_groq() -> tuple[bool, str]:
    if not settings.groq_api_key:
        return (False, "missing GROQ_API_KEY")

    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": "ping"}],
        "temperature": 0,
        "max_tokens": 4,
    }
    headers = {"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"}
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code >= 400:
            return (False, f"prompt failed ({resp.status_code})")
        return (True, f"test prompt {elapsed_ms}ms")
    except Exception as exc:
        return (False, f"prompt failed ({exc})")


async def main() -> int:
    checks = [
        ("Smriti API", check_http("http://localhost:8000/health")),
        ("MockABHA", check_http("http://localhost:8001/health")),
        ("HAPI FHIR", check_http("http://localhost:8082/fhir/metadata")),
        ("Supabase DB", check_db()),
        ("Groq", check_groq()),
        ("Ollama", check_http(f"{settings.ollama_base_url.rstrip('/')}/api/tags")),
        ("Smriti Web", check_http("http://localhost:3000")),
    ]

    results: list[tuple[str, bool, str]] = []
    for name, coro in checks:
        ok, msg = await coro
        results.append((name, ok, msg))

    width = max(len(name) for name, _, _ in results) + 2
    for name, ok, msg in results:
        mark = "?" if ok else "?"
        print(f"{name.ljust(width)} {mark} {msg}")

    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
