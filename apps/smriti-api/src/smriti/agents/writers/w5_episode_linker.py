"""W5 episode linker (MVP stub)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from smriti.db.connection import get_pool

logger = structlog.get_logger("w5_episode")


class EpisodeLinkerAgent:
    async def run(self, abha_id: str, inserts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        start = time.perf_counter()
        logger.info("entry", agent="w5", abha_id=abha_id, insert_count=len(inserts))
        try:
            links: list[dict[str, Any]] = []
            pool = await get_pool()
            async with pool.acquire() as conn:
                for item in inserts:
                    entity = item.get("entity", {})
                    if entity.get("entity_type") != "condition":
                        continue
                    provider = entity.get("source_provider")
                    code = entity.get("snomed_code") or entity.get("icd10_code")
                    if not code:
                        continue
                    row = await conn.fetchrow(
                        """
                        SELECT id FROM episodes
                        WHERE abha_id = $1
                          AND primary_diagnosis_code = $2
                          AND $3 = ANY(source_providers)
                          AND start_date >= $4
                        ORDER BY start_date DESC
                        LIMIT 1
                        """,
                        abha_id,
                        code,
                        provider,
                        (datetime.now(UTC) - timedelta(days=30)).date(),
                    )
                    if row is None:
                        episode_id = await conn.fetchval(
                            """
                            INSERT INTO episodes (abha_id, primary_diagnosis_code, primary_diagnosis_name, start_date, source_providers, summary)
                            VALUES ($1, $2, $3, $4, $5, $6)
                            RETURNING id
                            """,
                            abha_id,
                            code,
                            entity.get("display_name"),
                            datetime.now(UTC).date(),
                            [provider],
                            "MVP episode",
                        )
                    else:
                        episode_id = row["id"]
                    links.append({"source_record_id": entity.get("source_record_id"), "episode_id": str(episode_id)})
            return links
        finally:
            logger.info("exit", agent="w5", latency_ms=int((time.perf_counter() - start) * 1000))
