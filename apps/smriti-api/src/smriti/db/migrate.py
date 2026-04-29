"""Run Smriti database migrations against Supabase Postgres."""

from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import asyncpg

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
TRACKING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS _migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _resolve_connection_string() -> str:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not supabase_url:
        raise RuntimeError("SUPABASE_URL is required")
    if not service_role_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is required")

    if supabase_url.startswith(("postgres://", "postgresql://")):
        return supabase_url

    raise RuntimeError(
        "SUPABASE_URL must be the Supabase Postgres connection string for migrations"
    )


async def _ensure_tracking_table(connection: asyncpg.Connection) -> None:
    await connection.execute(TRACKING_TABLE_SQL)


def _is_pooler_dsn(dsn: str) -> bool:
    parsed = urlparse(dsn)
    host = (parsed.hostname or "").lower()
    return "pooler.supabase.com" in host or parsed.port == 6543


def _split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []

    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False
    dollar_tag: str | None = None

    i = 0
    n = len(sql_text)
    while i < n:
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < n else ""

        if in_line_comment:
            current.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            current.append(ch)
            if ch == "*" and nxt == "/":
                current.append(nxt)
                i += 2
                in_block_comment = False
            else:
                i += 1
            continue

        if dollar_tag is not None:
            if sql_text.startswith(dollar_tag, i):
                current.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
            else:
                current.append(ch)
                i += 1
            continue

        if in_single_quote:
            current.append(ch)
            if ch == "'":
                if nxt == "'":
                    current.append(nxt)
                    i += 2
                    continue
                in_single_quote = False
            i += 1
            continue

        if in_double_quote:
            current.append(ch)
            if ch == '"':
                in_double_quote = False
            i += 1
            continue

        if ch == "-" and nxt == "-":
            current.append(ch)
            current.append(nxt)
            i += 2
            in_line_comment = True
            continue

        if ch == "/" and nxt == "*":
            current.append(ch)
            current.append(nxt)
            i += 2
            in_block_comment = True
            continue

        if ch == "'":
            current.append(ch)
            in_single_quote = True
            i += 1
            continue

        if ch == '"':
            current.append(ch)
            in_double_quote = True
            i += 1
            continue

        if ch == "$":
            j = i + 1
            while j < n and (sql_text[j].isalnum() or sql_text[j] == "_"):
                j += 1
            if j < n and sql_text[j] == "$":
                tag = sql_text[i : j + 1]
                current.append(tag)
                i = j + 1
                dollar_tag = tag
                continue

        if ch == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)

    return statements


def _has_executable_sql(statement: str) -> bool:
    i = 0
    n = len(statement)
    in_line_comment = False
    in_block_comment = False

    while i < n:
        ch = statement[i]
        nxt = statement[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if ch.isspace():
            i += 1
            continue

        if ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue

        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue

        return True

    return False


async def run_migrations() -> None:
    connection_string = _resolve_connection_string()
    use_pooler_mode = _is_pooler_dsn(connection_string)

    if use_pooler_mode:
        print("Using Supabase Transaction Pooler (IPv4)")
    else:
        print("Using Supabase direct connection")

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    if not migration_files:
        print("No migration files found")
        return

    connect_kwargs: dict[str, object] = {"dsn": connection_string}
    if use_pooler_mode:
        connect_kwargs["statement_cache_size"] = 0

    try:
        connection = await asyncpg.connect(**connect_kwargs)
    except socket.gaierror as exc:
        raise RuntimeError(
            "Could not resolve Supabase Postgres host from SUPABASE_URL. "
            "If your environment has no IPv6 route, use the Supabase connection-pooler "
            "(IPv4) Postgres DSN from the dashboard."
        ) from exc
    except (
        asyncpg.exceptions.DuplicatePreparedStatementError,
        asyncpg.exceptions.InsufficientPrivilegeError,
    ) as exc:
        raise RuntimeError(
            "Connection failed due to prepared statements or privileges. "
            "If using Supabase pooler, enable pooler mode settings "
            "(statement_cache_size=0, prepared_statement_cache_size=0)."
        ) from exc

    try:
        await _ensure_tracking_table(connection)
        applied_rows = await connection.fetch("SELECT filename FROM _migrations")
        applied = {row["filename"] for row in applied_rows}

        for migration_file in migration_files:
            filename = migration_file.name
            if filename in applied:
                print(f"SKIP  {filename}")
                continue

            sql = migration_file.read_text(encoding="utf-8")
            statements = _split_sql_statements(sql)

            async with connection.transaction():
                for statement in statements:
                    if not _has_executable_sql(statement):
                        continue
                    await connection.execute(statement)

                await connection.execute(
                    "INSERT INTO _migrations (filename) VALUES ($1)", filename
                )

            print(f"APPLY {filename}")

    except (
        asyncpg.exceptions.DuplicatePreparedStatementError,
        asyncpg.exceptions.InsufficientPrivilegeError,
    ) as exc:
        raise RuntimeError(
            "Migration failed due to prepared statements or privileges. "
            "If using Supabase pooler, keep pooler mode settings enabled "
            "(statement_cache_size=0, prepared_statement_cache_size=0)."
        ) from exc
    finally:
        await connection.close()


def main() -> None:
    asyncio.run(run_migrations())


if __name__ == "__main__":
    main()