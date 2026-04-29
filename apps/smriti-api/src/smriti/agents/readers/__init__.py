"""Reader agents exports with lazy imports to avoid import cycles."""

from __future__ import annotations

from typing import Any

__all__ = [
    "CohortAgent",
    "CohortBucket",
    "CohortPanel",
    "ContextRetrievalAgent",
    "PatientProfile",
    "PrivacyParams",
    "QueryRouterAgent",
    "RiskAgent",
    "RiskFlag",
    "SynthesisAgent",
    "run_reader_dag",
    "run_reader_query",
]


async def run_reader_dag(*args: Any, **kwargs: Any):
    from .dag import run_reader_dag as _run_reader_dag

    return await _run_reader_dag(*args, **kwargs)


async def run_reader_query(*args: Any, **kwargs: Any):
    from .dag import run_reader_query as _run_reader_query

    return await _run_reader_query(*args, **kwargs)


def __getattr__(name: str):
    if name in {"CohortAgent", "CohortBucket", "CohortPanel", "PatientProfile", "PrivacyParams"}:
        from . import r3_cohort

        return getattr(r3_cohort, name)
    if name in {"RiskAgent", "RiskFlag"}:
        from . import r4_risk

        return getattr(r4_risk, name)
    if name == "QueryRouterAgent":
        from .r1_query_router import QueryRouterAgent

        return QueryRouterAgent
    if name == "ContextRetrievalAgent":
        from .r2_context_retrieval import ContextRetrievalAgent

        return ContextRetrievalAgent
    if name == "SynthesisAgent":
        from .r5_synthesis import SynthesisAgent

        return SynthesisAgent
    raise AttributeError(name)
