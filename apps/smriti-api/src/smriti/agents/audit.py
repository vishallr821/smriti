"""Hash-chained audit logger (C2 Audit Agent)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from smriti.db.connection import get_pool


def canonical_json(payload: Any) -> str:
    return json.dumps(payload if payload is not None else {}, sort_keys=True, separators=(",", ":"))


class AuditAgent:
    """Writes audit events as an append-only hash chain."""

    async def log(
        self,
        actor_id: str,
        actor_role: str,
        action: str,
        abha_id: str | None = None,
        scope: list[str] | None = None,
        payload: Any = None,
        payload_hash: str | None = None,
        consent_id: str | None = None,
    ) -> str:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                prev_row = await conn.fetchrow(
                    "SELECT this_hash FROM audit_log ORDER BY id DESC LIMIT 1 FOR UPDATE"
                )
                prev_hash = str(prev_row["this_hash"]) if prev_row is not None else "GENESIS"

                timestamp_iso = datetime.now(UTC).isoformat()
                effective_payload_hash = payload_hash or hashlib.sha256(
                    canonical_json(payload).encode("utf-8")
                ).hexdigest()
                material = f"{prev_hash}{effective_payload_hash}{action}{actor_id}{abha_id or ''}{timestamp_iso}"
                this_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()

                await conn.execute(
                    """
                    INSERT INTO audit_log
                    (abha_id, actor_id, actor_role, action, scope, consent_id, payload_hash, prev_hash, this_hash, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6::uuid, $7, $8, $9, $10::text::timestamptz)
                    """,
                    abha_id,
                    actor_id,
                    actor_role,
                    action,
                    scope or [],
                    consent_id,
                    effective_payload_hash,
                    prev_hash,
                    this_hash,
                    timestamp_iso,
                )
                return this_hash


async def verify_chain() -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, abha_id, actor_id, action, payload_hash, prev_hash, this_hash, created_at
            FROM audit_log
            ORDER BY id ASC
            """
        )

    expected_prev = "GENESIS"
    for row in rows:
        if str(row["prev_hash"]) != expected_prev:
            return False
        created_at = row["created_at"]
        created_at_iso = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
        material = (
            f"{expected_prev}{row['payload_hash']}{row['action']}{row['actor_id']}"
            f"{row['abha_id'] or ''}{created_at_iso}"
        )
        recalculated = hashlib.sha256(material.encode("utf-8")).hexdigest()
        if recalculated != row["this_hash"]:
            return False
        expected_prev = str(row["this_hash"])
    return True
