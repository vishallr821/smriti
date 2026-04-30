"""Clinician-facing APIs (PRD 11.2)."""

from __future__ import annotations

import time
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from smriti.auth import ClinicianClaims, current_clinician
from smriti.db.connection import get_pool
from smriti.dependencies import requires_scope
from smriti.agents import AuditAgent, ConsentGuard
from smriti.agents.readers import run_reader_dag, run_reader_query
from smriti.agents.readers.r1_query_router import QueryRouterAgent
from smriti.agents.readers.dag import get_demo_cache_hit
from smriti.schemas.encounter import EncounterContext

router = APIRouter(prefix="/api/v1", tags=["clinician"])
logger = structlog.get_logger("clinician_routes")

TABLE_SCOPE_MAP = {
    "conditions": "conditions",
    "medications": "medications",
    "observations": "observations",
    "allergies": "allergies",
}


class BriefingRequest(BaseModel):
    abha_id: str
    encounter: EncounterContext


class QueryRequest(BaseModel):
    abha_id: str
    query: str = Field(min_length=1)


def _extract_evidence_ids(items: list[dict], limit: int = 5) -> list[str]:
    out: list[str] = []
    for item in items:
        value = item.get("id")
        if value is None:
            continue
        out.append(str(value))
        if len(out) >= limit:
            break
    return out


def _condition_lookup_answer(query: str, context: dict) -> dict:
    q = query.lower()
    conds = context.get("conditions", []) or []
    facts = context.get("top_facts", []) or []

    if "hypertension" in q or "htn" in q or "high blood pressure" in q:
        matches = [
            c for c in conds
            if "hypertension" in str(c.get("display_name", "")).lower()
            or str(c.get("snomed_code", "")).strip() == "38341003"
            or str(c.get("icd10_code", "")).strip().upper().startswith("I10")
        ]
        answer = "yes" if matches else "no"
        evidence = _extract_evidence_ids(matches if matches else conds)
        return {
            "direct_answer": answer,
            "question_type": "condition_lookup",
            "subject": "hypertension",
            "confidence": 0.9 if matches else 0.6,
            "evidence_ids": evidence,
            "rationale": "Detected from structured condition records." if matches else "No hypertension condition match found in current retrieval scope.",
            "supporting_facts": facts[:3],
        }

    return {
        "direct_answer": "unknown",
        "question_type": "general",
        "subject": None,
        "confidence": 0.5,
        "evidence_ids": _extract_evidence_ids(conds),
        "rationale": "No strict question template matched; returning retrieval context.",
        "supporting_facts": facts[:3],
    }


def _as_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc) or "forbidden")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    logger.exception("clinician_route_error", error=str(exc))
    return HTTPException(status_code=500, detail="internal_server_error")


@router.post("/clinician/auth")
async def clinician_auth(_: ClinicianClaims = Depends(current_clinician)):
    raise HTTPException(status_code=501, detail="Not implemented (Phase 6)")


@router.post("/clinician/briefing", dependencies=[Depends(requires_scope(["briefing"]))])
async def clinician_briefing(
    payload: BriefingRequest,
    response: Response,
    request: Request,
    clinician: ClinicianClaims = Depends(current_clinician),
):
    request.state.abha_id = payload.abha_id
    started = time.perf_counter()
    try:
        briefing = await run_reader_dag(payload.abha_id, payload.encounter, clinician)
    except Exception as exc:
        raise _as_http_error(exc) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Latency-Ms"] = str(latency_ms)
    if get_demo_cache_hit():
        response.headers["X-Demo-Cache"] = "true"
    return jsonable_encoder(briefing, by_alias=True)


@router.post("/clinician/query")
async def clinician_query(
    payload: QueryRequest,
    request: Request,
    clinician: ClinicianClaims = Depends(current_clinician),
):
    request.state.abha_id = payload.abha_id
    try:
        plan = await QueryRouterAgent().run(
            EncounterContext(chief_complaint=None, nl_query=payload.query, encounter_type="routine")
        )
        context = await run_reader_query(payload.abha_id, payload.query, clinician)
    except Exception as exc:
        raise _as_http_error(exc) from exc
    context_json = context.model_dump(mode="json")
    answer = _condition_lookup_answer(payload.query, context_json)
    return jsonable_encoder(
        {
            "intent": plan.intent,
            "parameters": plan.parameters,
            "query": payload.query,
            "direct_answer": answer["direct_answer"],
            "question_type": answer["question_type"],
            "subject": answer["subject"],
            "confidence": answer["confidence"],
            "evidence_ids": answer["evidence_ids"],
            "rationale": answer["rationale"],
            "supporting_facts": answer["supporting_facts"],
            "context": context_json,
        }
    )


@router.get("/clinician/source/{table}/{id}")
async def clinician_source(
    table: str,
    id: str,
    request: Request,
    clinician: ClinicianClaims = Depends(current_clinician),
):
    normalized_table = table.strip().lower()
    if normalized_table not in TABLE_SCOPE_MAP:
        raise HTTPException(status_code=400, detail="unsupported_source_table")

    try:
        record_id = UUID(id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_source_id") from exc

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT * FROM {normalized_table} WHERE id = $1::uuid",
            record_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="source_record_not_found")

    record = dict(row)
    abha_id = str(record.get("abha_id") or "")
    if not abha_id:
        raise HTTPException(status_code=404, detail="source_record_not_found")

    request.state.abha_id = abha_id
    request.state.required_scope = [TABLE_SCOPE_MAP[normalized_table]]

    decision = await ConsentGuard().check(
        actor_id=clinician.hpr_id,
        actor_role=clinician.role,
        abha_id=abha_id,
        action="read.source",
        scope=[TABLE_SCOPE_MAP[normalized_table]],
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)

    request.state.applicable_consent_id = decision.applicable_consent_id
    await AuditAgent().log(
        actor_id=clinician.hpr_id,
        actor_role=clinician.role,
        action="read.source",
        abha_id=abha_id,
        scope=[TABLE_SCOPE_MAP[normalized_table]],
        payload={"table": normalized_table, "id": str(record_id)},
        consent_id=str(decision.applicable_consent_id) if decision.applicable_consent_id else None,
    )
    return jsonable_encoder(record)
