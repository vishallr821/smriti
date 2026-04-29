"""W3 normalization agent."""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

from smriti.db.connection import get_pool
from smriti.llm.router import get_router
from smriti.schemas.clinical import NormalizedClinicalEntity, RawClinicalEntity
from smriti.security import InjectionGuard

logger = structlog.get_logger("w3_norm")


class _NormalizationChoice(BaseModel):
    code: str | None = None
    system: str | None = None


ENTITY_SYSTEMS = {
    "condition": ["snomed", "icd10"],
    "medication": ["rxnorm"],
    "observation": ["loinc"],
    "allergy": ["snomed"],
}


class NormalizationAgent:
    def __init__(self) -> None:
        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
        self.guard = InjectionGuard()

    def _vector_literal(self, vector: list[float]) -> str:
        return "[" + ",".join(f"{float(v):.8f}" for v in vector) + "]"

    async def _top_candidates(self, entity: RawClinicalEntity) -> list[dict[str, Any]]:
        systems = ENTITY_SYSTEMS[entity.entity_type]
        emb_raw = self.embedder.encode([entity.display_name], show_progress_bar=False)[0]
        emb = emb_raw.tolist() if hasattr(emb_raw, "tolist") else list(emb_raw)
        vec = self._vector_literal(emb)
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT system, code, display_name, 1 - (embedding <=> $1::vector) AS score
                FROM terminology_index
                WHERE system = ANY($2::text[])
                ORDER BY embedding <=> $1::vector
                LIMIT 5
                """,
                vec,
                systems,
            )
        return [dict(r) for r in rows]

    def _apply_code(self, entity: RawClinicalEntity, code: str | None, system: str | None) -> NormalizedClinicalEntity:
        update: dict[str, Any] = {}
        if code and system == "snomed":
            update["snomed_code"] = code
        elif code and system == "icd10":
            update["icd10_code"] = code
        elif code and system == "rxnorm":
            update["rxnorm_code"] = code
        elif code and system == "loinc":
            update["loinc_code"] = code
        return NormalizedClinicalEntity.model_validate(entity.model_dump() | update)

    async def run(self, entities: list[RawClinicalEntity]) -> list[NormalizedClinicalEntity]:
        start = time.perf_counter()
        logger.info("entry", agent="w3", entity_count=len(entities))
        try:
            out: list[NormalizedClinicalEntity] = []
            for entity in entities:
                candidates = await self._top_candidates(entity)
                if candidates and float(candidates[0].get("score", 0.0)) >= 0.85:
                    out.append(self._apply_code(entity, str(candidates[0]["code"]), str(candidates[0]["system"])))
                    continue

                wrapped = self.guard.wrap_data(json.dumps(entity.model_dump()), "entity")
                response = await get_router().call(
                    role="normalization",
                    prompt=(
                        "Pick best matching code from candidates.\n"
                        f"candidates={json.dumps(candidates)}\n"
                        f"{wrapped}\n"
                        "Return {code, system}."
                    ),
                    schema=_NormalizationChoice,
                )
                code = response.code
                system = response.system
                valid_codes = {str(c["code"]) for c in candidates}
                if code is None or code not in valid_codes:
                    out.append(NormalizedClinicalEntity.model_validate(entity.model_dump() | {"confidence": 0.4}))
                    continue
                out.append(self._apply_code(entity, code, system))
            return out
        finally:
            logger.info("exit", agent="w3", latency_ms=int((time.perf_counter() - start) * 1000))
