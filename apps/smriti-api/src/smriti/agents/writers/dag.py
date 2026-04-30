"""LangGraph writer DAG (W1-W5 + persist)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, StateGraph
from sentence_transformers import SentenceTransformer
from pydantic import BaseModel, Field

from smriti.agents import AuditAgent, ConsentGuard
from smriti.agents.writers import (
    EpisodeLinkerAgent,
    IngestionAgent,
    IngestionError,
    NormalizationAgent,
    PIIRedactionAgent,
    ReconciliationAgent,
)
from smriti.db.connection import get_pool
from smriti.schemas.clinical import NormalizedClinicalEntity, RawClinicalEntity, SourceRecord

logger = structlog.get_logger("writer_dag")


class WriterResult(BaseModel):
    inserted: int = 0
    merged: int = 0
    conflicts: int = 0
    quarantined: bool = False


class WriterState(TypedDict, total=False):
    source_record: SourceRecord
    abha_id: str
    actor_id: str
    actor_role: str
    required_scope: list[str]
    entities: list[RawClinicalEntity]
    sanitized: Any
    normalized: list[NormalizedClinicalEntity]
    reconciled: Any
    episode_links: list[dict[str, Any]]
    errors: list[str]
    quarantined: bool
    result: WriterResult


_embedder: SentenceTransformer | None = None


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def _vec_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in vector) + "]"


async def _check_consent(state: WriterState) -> WriterState:
    decision = await ConsentGuard().check(
        actor_id=state["actor_id"],
        actor_role=state["actor_role"],
        abha_id=state["abha_id"],
        action="write.ingest",
        scope=state.get("required_scope", ["conditions", "medications", "observations", "allergies"]),
    )
    if not decision.allowed:
        raise PermissionError(f"consent_denied: {decision.reason}")
    return state


async def _w1(state: WriterState) -> WriterState:
    await _check_consent(state)
    state["entities"] = await IngestionAgent().run(state["source_record"])
    return state


async def _w2(state: WriterState) -> WriterState:
    raw_text = state["source_record"].payload.get("raw_text")
    sanitized = await PIIRedactionAgent().run(state["entities"], raw_text=raw_text, abha_id=state["abha_id"])
    state["sanitized"] = sanitized
    state["entities"] = sanitized.sanitized_entities
    state["quarantined"] = bool(sanitized.injection_detected and (raw_text is not None))
    return state


async def _w3(state: WriterState) -> WriterState:
    state["normalized"] = await NormalizationAgent().run(state["entities"])
    return state


async def _w4(state: WriterState) -> WriterState:
    state["reconciled"] = await ReconciliationAgent().run(state["abha_id"], state["normalized"])
    return state


async def _w5(state: WriterState) -> WriterState:
    state["episode_links"] = await EpisodeLinkerAgent().run(state["abha_id"], state["reconciled"].inserts)
    return state


async def _persist(state: WriterState) -> WriterState:
    if state.get("quarantined"):
        state["result"] = WriterResult(quarantined=True)
        return state
    pool = await get_pool()
    inserted = 0
    merged = len(state["reconciled"].merges)
    conflicts = len(state["reconciled"].conflicts)
    embeddings_model: SentenceTransformer | None = None
    enable_chunk_indexing = _chunk_indexing_enabled()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for conflict in state["reconciled"].conflicts:
                await conn.execute(
                    """
                    INSERT INTO conflicts (abha_id, conflict_type, severity, source_a, source_b, detected_at)
                    VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6)
                    """,
                    state["abha_id"],
                    conflict["conflict_type"],
                    conflict["severity"],
                    json.dumps(conflict["source_a"]),
                    json.dumps(conflict["source_b"]),
                    datetime.now(UTC),
                )

            for item in state["reconciled"].inserts:
                entity = NormalizedClinicalEntity.model_validate(item["entity"])
                row_id = None
                if entity.entity_type == "condition":
                    row_id = await conn.fetchval(
                        """
                        INSERT INTO conditions (abha_id, source_provider, source_record_id, snomed_code, icd10_code, display_name, status, ingested_at, confidence, raw_value)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id
                        """,
                        state["abha_id"], entity.source_provider, entity.source_record_id, entity.snomed_code, entity.icd10_code,
                        entity.display_name, entity.attributes.get("status"), datetime.now(UTC), entity.confidence, entity.raw_value
                    )
                elif entity.entity_type == "medication":
                    row_id = await conn.fetchval(
                        """
                        INSERT INTO medications (abha_id, source_provider, source_record_id, rxnorm_code, display_name, dose, start_date, end_date, ingested_at, raw_value)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id
                        """,
                        state["abha_id"], entity.source_provider, entity.source_record_id, entity.rxnorm_code, entity.display_name,
                        entity.attributes.get("dose"), entity.attributes.get("start_date"), entity.attributes.get("end_date"),
                        datetime.now(UTC), entity.raw_value
                    )
                elif entity.entity_type == "observation":
                    row_id = await conn.fetchval(
                        """
                        INSERT INTO observations (abha_id, source_provider, source_record_id, loinc_code, display_name, value_text, observed_at, ingested_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id
                        """,
                        state["abha_id"], entity.source_provider, entity.source_record_id, entity.loinc_code, entity.display_name,
                        entity.raw_value, datetime.now(UTC), datetime.now(UTC)
                    )
                elif entity.entity_type == "allergy":
                    row_id = await conn.fetchval(
                        """
                        INSERT INTO allergies (abha_id, source_provider, source_record_id, substance_code, substance_name, status, ingested_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id
                        """,
                        state["abha_id"], entity.source_provider, entity.source_record_id, entity.snomed_code, entity.display_name,
                        entity.attributes.get("status", "active"), datetime.now(UTC)
                    )
                if row_id is None:
                    continue
                inserted += 1
                if enable_chunk_indexing:
                    try:
                        if embeddings_model is None:
                            embeddings_model = _get_embedder()
                        vec_raw = embeddings_model.encode([entity.raw_value], show_progress_bar=False)[0]
                        vec = vec_raw.tolist() if hasattr(vec_raw, "tolist") else list(vec_raw)
                        source_table = {
                            "condition": "conditions",
                            "medication": "medications",
                            "observation": "observations",
                            "allergy": "allergies",
                        }[entity.entity_type]
                        await conn.execute(
                            """
                            INSERT INTO record_chunks (abha_id, source_table, source_id, chunk_text, chunk_vector, created_at)
                            VALUES ($1,$2,$3,$4,$5::vector,$6)
                            """,
                            state["abha_id"],
                            source_table,
                            row_id,
                            entity.raw_value,
                            _vec_literal(vec),
                            datetime.now(UTC),
                        )
                    except Exception as exc:  # pragma: no cover - demo guard
                        logger.warning("chunk_indexing_skipped", abha_id=state["abha_id"], error=str(exc))

    await AuditAgent().log(
        actor_id=state["actor_id"],
        actor_role=state["actor_role"],
        action="write.ingest.persist",
        abha_id=state["abha_id"],
        scope=state.get("required_scope", []),
        payload={"inserted": inserted, "merged": merged, "conflicts": conflicts},
    )
    state["result"] = WriterResult(inserted=inserted, merged=merged, conflicts=conflicts, quarantined=False)
    return state


async def _quarantine(state: WriterState) -> WriterState:
    state["result"] = WriterResult(quarantined=True)
    return state


def _route_after_w2(state: WriterState) -> str:
    return "quarantine" if state.get("quarantined") else "w3_normalization"


def _build_graph():
    graph = StateGraph(WriterState)
    graph.add_node("w1_ingestion", _w1)
    graph.add_node("w2_pii", _w2)
    graph.add_node("w3_normalization", _w3)
    graph.add_node("w4_reconciliation", _w4)
    graph.add_node("w5_episode", _w5)
    graph.add_node("persist", _persist)
    graph.add_node("quarantine", _quarantine)

    graph.set_entry_point("w1_ingestion")
    graph.add_edge("w1_ingestion", "w2_pii")
    graph.add_conditional_edges("w2_pii", _route_after_w2, {"quarantine": "quarantine", "w3_normalization": "w3_normalization"})
    graph.add_edge("w3_normalization", "w4_reconciliation")
    graph.add_edge("w4_reconciliation", "w5_episode")
    graph.add_edge("w5_episode", "persist")
    graph.add_edge("persist", END)
    graph.add_edge("quarantine", END)
    return graph.compile()


_compiled = _build_graph()


def _chunk_indexing_enabled() -> bool:
    # Demo-safe default is OFF to avoid local native/runtime crashes while encoding embeddings.
    return os.getenv("SMRITI_ENABLE_CHUNK_INDEXING", "").strip().lower() in {"1", "true", "yes", "on"}


async def run_writer_dag(source_record: SourceRecord, abha_id: str, actor_id: str | None = None, actor_role: str = "provider") -> WriterResult:
    start = time.perf_counter()
    logger.info("entry", workflow="writer_dag", provider=source_record.provider_id)
    try:
        state: WriterState = {
            "source_record": source_record,
            "abha_id": abha_id,
            "actor_id": actor_id or source_record.provider_id,
            "actor_role": actor_role,
            "required_scope": ["conditions", "medications", "observations", "allergies"],
            "errors": [],
        }
        out = await _compiled.ainvoke(state)
        return out.get("result", WriterResult(quarantined=True))
    except IngestionError:
        return WriterResult(quarantined=True)
    finally:
        logger.info("exit", workflow="writer_dag", latency_ms=int((time.perf_counter() - start) * 1000))
