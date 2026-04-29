"""Deterministic consent authorization checks (C1 Consent Guard)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from smriti.db.connection import get_pool


@dataclass(slots=True)
class ConsentDecision:
    allowed: bool
    reason: str
    applicable_consent_id: UUID | None = None


class ConsentGuard:
    """Rule-based consent gate. No LLM calls."""

    async def check(
        self,
        actor_id: str,
        actor_role: str,
        abha_id: str,
        action: str,
        scope: list[str],
    ) -> ConsentDecision:
        normalized_role = actor_role.strip().lower()
        normalized_action = action.strip().lower()
        requested_scope = {s.strip() for s in scope if s and s.strip()}

        if normalized_role == "patient" and actor_id == abha_id:
            return ConsentDecision(allowed=True, reason="self_access")

        if normalized_role == "emergency":
            return ConsentDecision(allowed=True, reason="break_glass")

        pool = await get_pool()
        async with pool.acquire() as conn:
            if normalized_action.startswith("write."):
                provider = await conn.fetchrow(
                    """
                    SELECT provider_id
                    FROM providers
                    WHERE provider_id = $1 AND active = true
                    """,
                    actor_id,
                )
                if provider is not None:
                    return ConsentDecision(allowed=True, reason="implicit_provider_grant")
                return ConsentDecision(allowed=False, reason="provider_not_registered")

            if normalized_action.startswith("read."):
                now = datetime.now(UTC)
                consent_rows = await conn.fetch(
                    """
                    SELECT id, scope, grantee_class
                    FROM consents
                    WHERE abha_id = $1
                      AND revoked_at IS NULL
                      AND (expires_at IS NULL OR expires_at > $2)
                      AND (
                        grantee_class = 'any_md'
                        OR grantee_class = $3
                      )
                    """,
                    abha_id,
                    now,
                    actor_id,
                )
                for row in consent_rows:
                    grant_scope = set(row["scope"] or [])
                    if requested_scope.issubset(grant_scope):
                        return ConsentDecision(
                            allowed=True,
                            reason="consent_granted",
                            applicable_consent_id=row["id"],
                        )
                return ConsentDecision(allowed=False, reason="consent_missing_or_scope_insufficient")

        return ConsentDecision(allowed=False, reason="denied")
