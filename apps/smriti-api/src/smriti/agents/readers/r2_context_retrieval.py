"""R2 context retrieval agent (SQL-only, parameterized)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from smriti.db.connection import get_pool
from smriti.schemas.encounter import Fact, RetrievedContext, RetrievalPlan, SourceRef

logger = structlog.get_logger("r2_context_retrieval")


class ContextRetrievalAgent:
    def _to_source(self, table: str, row: dict[str, Any]) -> SourceRef:
        row_id = row.get("id")
        if not isinstance(row_id, UUID):
            row_id = UUID(str(row_id))
        row_date = row.get("observed_at") or row.get("ingested_at") or row.get("detected_at") or datetime.now(UTC)
        if not isinstance(row_date, datetime):
            row_date = datetime.now(UTC)
        return SourceRef(
            table=table,
            id=row_id,
            provider=str(row.get("source_provider", "unknown")),
            date=row_date,
        )

    def _fact_line(self, row: dict[str, Any], source: SourceRef) -> str:
        dt = source.date.date().isoformat()
        provider = source.provider
        if row.get("loinc_code"):
            abnormal = " (high)" if row.get("abnormal_flag") else ""
            value = row.get("value_numeric") if row.get("value_numeric") is not None else row.get("value_text")
            unit = row.get("unit") or ""
            return f"On {dt}, {row.get('display_name')} was {value}{unit}{abnormal} at {provider}."
        return f"On {dt}, {row.get('display_name') or row.get('substance_name')} was recorded at {provider}."

    async def _fetch_general(self, conn, abha_id: str) -> dict[str, list[dict[str, Any]]]:
        conditions = await conn.fetch(
            """
            SELECT * FROM conditions
            WHERE abha_id = $1 AND status = 'active'
            ORDER BY ingested_at DESC
            LIMIT 5
            """,
            abha_id,
        )
        medications = await conn.fetch(
            """
            SELECT * FROM medications
            WHERE abha_id = $1 AND (end_date IS NULL OR end_date >= CURRENT_DATE)
            ORDER BY COALESCE(start_date, CURRENT_DATE) DESC
            """,
            abha_id,
        )
        observations = await conn.fetch(
            """
            SELECT * FROM observations
            WHERE abha_id = $1 AND abnormal_flag IS NOT NULL
            ORDER BY observed_at DESC
            LIMIT 3
            """,
            abha_id,
        )
        conflicts = await conn.fetch(
            """
            SELECT * FROM conflicts
            WHERE abha_id = $1 AND resolution IS NULL
            ORDER BY detected_at DESC
            """,
            abha_id,
        )
        allergies = await conn.fetch(
            """
            SELECT * FROM allergies
            WHERE abha_id = $1 AND status = 'active'
            ORDER BY ingested_at DESC
            """,
            abha_id,
        )
        return {
            "conditions": [dict(r) for r in conditions],
            "medications": [dict(r) for r in medications],
            "observations": [dict(r) for r in observations],
            "conflicts": [dict(r) for r in conflicts],
            "allergies": [dict(r) for r in allergies],
        }

    async def run(self, abha_id: str, plan: RetrievalPlan, exclusions: list[str]) -> RetrievedContext:
        start = time.perf_counter()
        logger.info("entry", agent="r2", intent=plan.intent, abha_id=abha_id)
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                top_facts: list[Fact] = []
                conditions: list[dict[str, Any]] = []
                medications: list[dict[str, Any]] = []
                observations: list[dict[str, Any]] = []
                allergies: list[dict[str, Any]] = []
                conflicts: list[dict[str, Any]] = []

                if plan.intent in {"general_briefing", "unsupported"}:
                    data = await self._fetch_general(conn, abha_id)
                    conditions, medications, observations, conflicts, allergies = (
                        data["conditions"], data["medications"], data["observations"], data["conflicts"], data["allergies"]
                    )
                elif plan.intent == "lab_trend":
                    loinc = str(plan.parameters.get("loinc_code", "")).strip()
                    rows = await conn.fetch(
                        """
                        SELECT * FROM observations
                        WHERE abha_id = $1 AND loinc_code = $2
                        ORDER BY observed_at ASC
                        """,
                        abha_id,
                        loinc,
                    )
                    observations = [dict(r) for r in rows]
                elif plan.intent == "medication_history":
                    rows = await conn.fetch(
                        """
                        SELECT * FROM medications
                        WHERE abha_id = $1
                        ORDER BY COALESCE(start_date, CURRENT_DATE) ASC
                        """,
                        abha_id,
                    )
                    medications = [dict(r) for r in rows]
                elif plan.intent == "allergy_check":
                    substance = str(plan.parameters.get("substance", "")).strip()
                    if substance:
                        rows = await conn.fetch(
                            """
                            SELECT * FROM allergies
                            WHERE abha_id = $1 AND (substance_name ILIKE $2 OR COALESCE(reaction, '') ILIKE $2)
                            ORDER BY ingested_at DESC
                            """,
                            abha_id,
                            f"%{substance}%",
                        )
                        allergies = [dict(r) for r in rows]
                        meds = await conn.fetch(
                            """
                            SELECT * FROM medications
                            WHERE abha_id = $1 AND display_name ILIKE $2
                            ORDER BY COALESCE(start_date, CURRENT_DATE) DESC
                            """,
                            abha_id,
                            f"%{substance}%",
                        )
                        medications = [dict(r) for r in meds]
                    else:
                        rows = await conn.fetch("SELECT * FROM allergies WHERE abha_id = $1 ORDER BY ingested_at DESC", abha_id)
                        allergies = [dict(r) for r in rows]
                elif plan.intent == "cohort_lookup":
                    rows = await conn.fetch(
                        """
                        SELECT display_name FROM conditions WHERE abha_id = $1 ORDER BY ingested_at DESC LIMIT 5
                        """,
                        abha_id,
                    )
                    conditions = [{"display_name": r["display_name"]} for r in rows]
                elif plan.intent == "interaction_check":
                    rows = await conn.fetch(
                        """
                        SELECT * FROM medications
                        WHERE abha_id = $1 AND (end_date IS NULL OR end_date >= CURRENT_DATE)
                        ORDER BY COALESCE(start_date, CURRENT_DATE) DESC
                        """,
                        abha_id,
                    )
                    medications = [dict(r) for r in rows]

                if "conditions" in exclusions:
                    conditions = []
                for row in observations + conditions + medications + allergies:
                    if "id" not in row:
                        continue
                    table = (
                        "observations" if row in observations else
                        "conditions" if row in conditions else
                        "medications" if row in medications else
                        "allergies"
                    )
                    source = self._to_source(table, row)
                    date = source.date if isinstance(source.date, datetime) else datetime.now(UTC)
                    top_facts.append(Fact(fact=self._fact_line(row, source), source=source, date=date, confidence=0.9))

                if "medications" in exclusions:
                    medications = []
                if "observations" in exclusions:
                    observations = []
                if "allergies" in exclusions:
                    allergies = []
                allowed_tables = {"conditions", "medications", "observations", "allergies"} - set(exclusions)
                top_facts = [fact for fact in top_facts if fact.source.table in allowed_tables]

                return RetrievedContext(
                    top_facts=top_facts,
                    conflicts=conflicts,
                    medications=medications,
                    observations=observations,
                    allergies=allergies,
                    conditions=conditions,
                )
        finally:
            logger.info("exit", agent="r2", latency_ms=int((time.perf_counter() - start) * 1000))
