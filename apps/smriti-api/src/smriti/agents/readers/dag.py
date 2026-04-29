"""LangGraph reader DAG (R1-R5 + consent/audit)."""

from __future__ import annotations

import hashlib
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, TypedDict
from uuid import UUID, uuid4

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from smriti.agents import AuditAgent, ConsentGuard
from smriti.auth import ClinicianClaims
from smriti.config import settings
from smriti.db.connection import get_pool
from smriti.llm.cache import get_demo_cached_briefing
from smriti.llm.exceptions import LLMRouterError
from smriti.schemas.briefing import Briefing
from smriti.schemas.encounter import EncounterContext, RetrievedContext, RetrievalPlan, SourceRef

from .r1_query_router import QueryRouterAgent
from .r2_context_retrieval import ContextRetrievalAgent
from .r3_cohort import CohortAgent, CohortPanel, PatientProfile, PrivacyParams
from .r4_risk import RiskAgent
from .r5_synthesis import SynthesisAgent

logger = structlog.get_logger("reader_dag")
_demo_cache_hit_ctx: ContextVar[bool] = ContextVar("reader_demo_cache_hit", default=False)

READ_SCOPE_ORDER = ["conditions", "medications", "observations", "allergies"]
COHORT_REQUIRED_SCOPES = {"conditions", "medications", "observations"}


class ReaderState(TypedDict, total=False):
    encounter: EncounterContext
    abha_id: str
    exclusions: list[str]
    plan: RetrievalPlan
    retrieved_context: RetrievedContext
    cohort_panel: CohortPanel
    risk_flags: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    briefing: Briefing


@dataclass(slots=True)
class ReaderAccess:
    scope: list[str]
    exclusions: list[str]
    consent_id: str | None


def get_demo_cache_hit() -> bool:
    return bool(_demo_cache_hit_ctx.get())


def _briefing_hash(briefing_id: str) -> str:
    return hashlib.sha256(briefing_id.encode("utf-8")).hexdigest()


def _empty_cohort_panel(reason: str) -> CohortPanel:
    return CohortPanel(
        n_total=0,
        buckets=[],
        privacy=PrivacyParams(),
        disclaimer=reason,
    )


def _safe_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.now(UTC)


def _safe_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _calculate_age(dob: date | None) -> int:
    if dob is None:
        return 0
    today = datetime.now(UTC).date()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


async def _resolve_exclusions(abha_id: str, clinician_claims: ClinicianClaims) -> list[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT scope
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
            datetime.now(UTC),
            clinician_claims.hpr_id,
        )

    allowed = {
        str(item)
        for row in rows
        for item in (row["scope"] or [])
        if str(item) in READ_SCOPE_ORDER
    }
    return [scope for scope in READ_SCOPE_ORDER if scope not in allowed]


async def authorize_clinician_read(
    abha_id: str,
    clinician_claims: ClinicianClaims,
    action: str,
    requested_scope: list[str] | None = None,
) -> ReaderAccess:
    if requested_scope is None:
        exclusions = await _resolve_exclusions(abha_id, clinician_claims)
        requested_scope = [scope for scope in READ_SCOPE_ORDER if scope not in exclusions]
    else:
        requested_scope = [scope for scope in requested_scope if scope in READ_SCOPE_ORDER]
        exclusions = [scope for scope in READ_SCOPE_ORDER if scope not in requested_scope]

    if not requested_scope:
        raise PermissionError("consent_missing_or_scope_insufficient")

    decision = await ConsentGuard().check(
        actor_id=clinician_claims.hpr_id,
        actor_role=clinician_claims.role,
        abha_id=abha_id,
        action=action,
        scope=requested_scope,
    )
    if not decision.allowed:
        raise PermissionError(decision.reason)

    return ReaderAccess(
        scope=requested_scope,
        exclusions=exclusions,
        consent_id=str(decision.applicable_consent_id) if decision.applicable_consent_id else None,
    )


async def _build_patient_profile(abha_id: str, retrieved_context: RetrievedContext) -> PatientProfile:
    pool = await get_pool()
    async with pool.acquire() as conn:
        patient_row = await conn.fetchrow(
            """
            SELECT dob, sex
            FROM patients
            WHERE abha_id = $1
            """,
            abha_id,
        )

    conditions = [
        str(item.get("snomed_code"))
        for item in retrieved_context.conditions
        if item.get("snomed_code")
    ]
    medications = [
        str(item.get("display_name"))
        for item in retrieved_context.medications
        if item.get("display_name")
    ]

    key_labs: dict[str, float] = {}
    for item in retrieved_context.observations:
        if str(item.get("loinc_code", "")).strip() != "4548-4":
            continue
        value = item.get("value_numeric")
        try:
            key_labs["hba1c"] = float(value)
            break
        except (TypeError, ValueError):
            continue

    dob = patient_row["dob"] if patient_row and patient_row["dob"] else None
    sex = str(patient_row["sex"]) if patient_row and patient_row["sex"] else "O"
    return PatientProfile(
        age=_calculate_age(dob),
        sex=sex,
        conditions=conditions,
        current_medications=medications,
        key_labs=key_labs,
    )


async def _r1_router(state: ReaderState) -> dict[str, Any]:
    plan = await QueryRouterAgent().run(state["encounter"])
    return {"plan": plan}


async def _r2_context(state: ReaderState) -> dict[str, Any]:
    retrieved_context = await ContextRetrievalAgent().run(
        state["abha_id"],
        state["plan"],
        exclusions=state.get("exclusions", []),
    )
    return {
        "retrieved_context": retrieved_context,
        "conflicts": retrieved_context.conflicts,
    }


async def _r3_cohort(state: ReaderState) -> dict[str, Any]:
    exclusions = set(state.get("exclusions", []))
    if exclusions & COHORT_REQUIRED_SCOPES:
        return {
            "cohort_panel": _empty_cohort_panel(
                "Cohort unavailable because one or more consented data categories required for profile matching were withheld."
            )
        }

    profile = await _build_patient_profile(state["abha_id"], state["retrieved_context"])
    panel = await CohortAgent().run(profile)
    return {"cohort_panel": panel}


async def _r4_risk(state: ReaderState) -> dict[str, Any]:
    medication_rows: list[dict[str, Any]] = []
    for item in state["retrieved_context"].medications:
        source_id = _safe_uuid(item.get("id"))
        med_row = dict(item)
        if source_id is not None:
            med_row["source"] = SourceRef(
                table="medications",
                id=source_id,
                provider=str(item.get("source_provider", "unknown")),
                date=_safe_datetime(item.get("start_date") or item.get("ingested_at")),
            )
        medication_rows.append(med_row)

    flags = await RiskAgent().run(state["abha_id"], medication_rows)
    return {"risk_flags": [flag.model_dump(mode="json") for flag in flags]}


async def _r5_synthesis(state: ReaderState) -> dict[str, Any]:
    briefing = await SynthesisAgent().run(
        encounter=state["encounter"],
        retrieved_context=state["retrieved_context"],
        conflicts=state.get("conflicts", []),
        cohort_panel=state.get("cohort_panel"),
        risk_flags=state.get("risk_flags", []),
        exclusions=state.get("exclusions", []),
    )
    return {"briefing": briefing}


def _build_graph():
    graph = StateGraph(ReaderState)
    graph.add_node("r1_router", _r1_router)
    graph.add_node("r2_context", _r2_context)
    graph.add_node("r3_cohort", _r3_cohort)
    graph.add_node("r4_risk", _r4_risk)
    graph.add_node("r5_synthesis", _r5_synthesis)

    graph.set_entry_point("r1_router")
    graph.add_edge("r1_router", "r2_context")
    graph.add_edge("r2_context", "r3_cohort")
    graph.add_edge("r2_context", "r4_risk")
    graph.add_edge("r2_context", "r5_synthesis")
    graph.add_edge("r3_cohort", "r5_synthesis")
    graph.add_edge("r4_risk", "r5_synthesis")
    graph.add_edge("r5_synthesis", END)
    return graph.compile(checkpointer=MemorySaver())


_compiled = _build_graph()


async def _audit_reader_attempt(
    *,
    clinician_claims: ClinicianClaims,
    action: str,
    abha_id: str,
    scope: list[str],
    consent_id: str | None,
    encounter: EncounterContext | None = None,
    plan: RetrievalPlan | None = None,
    result_payload: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    payload: dict[str, Any] = {
        "status": "succeeded" if error is None else "failed",
        "scope": scope,
    }
    if encounter is not None:
        payload["encounter"] = encounter.model_dump(mode="json")
    if plan is not None:
        payload["plan"] = plan.model_dump(mode="json")
    if result_payload:
        payload.update(result_payload)
    if error is not None:
        payload["error"] = {"type": type(error).__name__, "detail": str(error)}

    payload_hash = None
    if result_payload and result_payload.get("briefing_id"):
        payload_hash = _briefing_hash(str(result_payload["briefing_id"]))

    await AuditAgent().log(
        actor_id=clinician_claims.hpr_id,
        actor_role=clinician_claims.role,
        action=action,
        abha_id=abha_id,
        scope=scope,
        payload=payload,
        payload_hash=payload_hash,
        consent_id=consent_id,
    )


async def run_reader_dag(
    abha_id: str,
    encounter: EncounterContext,
    clinician_claims: ClinicianClaims,
) -> Briefing:
    start = time.perf_counter()
    _demo_cache_hit_ctx.set(False)
    logger.info("entry", workflow="reader_dag", abha_id=abha_id)

    access: ReaderAccess | None = None
    plan: RetrievalPlan | None = None
    briefing: Briefing | None = None
    error: Exception | None = None
    try:
        access = await authorize_clinician_read(abha_id, clinician_claims, action="read.briefing")

        cached = get_demo_cached_briefing(abha_id, encounter, access.exclusions)
        if cached is not None:
            _demo_cache_hit_ctx.set(True)
            briefing = cached
            logger.warning(
                "DEMO CACHE HIT",
                abha_id=abha_id,
                reason="precomputed_priya_briefing",
                exclusions=access.exclusions,
            )
            return briefing

        initial_state: ReaderState = {
            "encounter": encounter,
            "abha_id": abha_id,
            "exclusions": access.exclusions,
        }
        try:
            out = await _compiled.ainvoke(
                initial_state,
                config={"configurable": {"thread_id": f"reader:{abha_id}:{uuid4()}"}},
            )
        except LLMRouterError:
            if settings.demo_cache:
                cached_after_error = get_demo_cached_briefing(abha_id, encounter, access.exclusions)
                if cached_after_error is not None:
                    _demo_cache_hit_ctx.set(True)
                    briefing = cached_after_error
                    logger.warning(
                        "DEMO CACHE HIT",
                        abha_id=abha_id,
                        reason="llm_router_error_fallback",
                        exclusions=access.exclusions,
                    )
                    return briefing
            raise
        plan = out.get("plan")
        briefing = out["briefing"]
        return briefing
    except Exception as exc:
        error = exc
        raise
    finally:
        scope = access.scope if access is not None else list(READ_SCOPE_ORDER)
        consent_id = access.consent_id if access is not None else None
        result_payload = {"briefing_id": briefing.id} if briefing is not None else None
        try:
            await _audit_reader_attempt(
                clinician_claims=clinician_claims,
                action="read.briefing",
                abha_id=abha_id,
                scope=scope,
                consent_id=consent_id,
                encounter=encounter,
                plan=plan,
                result_payload=result_payload,
                error=error,
            )
        finally:
            logger.info(
                "exit",
                workflow="reader_dag",
                abha_id=abha_id,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )


async def run_reader_query(
    abha_id: str,
    query: str,
    clinician_claims: ClinicianClaims,
) -> RetrievedContext:
    access: ReaderAccess | None = None
    plan: RetrievalPlan | None = None
    context: RetrievedContext | None = None
    error: Exception | None = None
    encounter = EncounterContext(chief_complaint=None, nl_query=query, encounter_type="routine")
    try:
        access = await authorize_clinician_read(abha_id, clinician_claims, action="read.query")
        plan = await QueryRouterAgent().run(encounter)
        context = await ContextRetrievalAgent().run(abha_id, plan, exclusions=access.exclusions)
        return context
    except Exception as exc:
        error = exc
        raise
    finally:
        scope = access.scope if access is not None else list(READ_SCOPE_ORDER)
        consent_id = access.consent_id if access is not None else None
        counts = None
        if context is not None:
            counts = {
                "counts": {
                    "top_facts": len(context.top_facts),
                    "conditions": len(context.conditions),
                    "medications": len(context.medications),
                    "observations": len(context.observations),
                    "allergies": len(context.allergies),
                    "conflicts": len(context.conflicts),
                }
            }
        await _audit_reader_attempt(
            clinician_claims=clinician_claims,
            action="read.query",
            abha_id=abha_id,
            scope=scope,
            consent_id=consent_id,
            encounter=encounter,
            plan=plan,
            result_payload=counts,
            error=error,
        )
