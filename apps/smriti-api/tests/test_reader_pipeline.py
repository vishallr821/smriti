from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from smriti.agents.readers import ContextRetrievalAgent, QueryRouterAgent
from smriti.schemas.encounter import EncounterContext, RetrievalPlan


@pytest.mark.asyncio
async def test_r1_hba1c_trend_intent(monkeypatch):
    class _Resp:
        intent = "lab_trend"
        parameters = {"loinc_code": "4548-4"}

    class _Router:
        async def call(self, **_kwargs):
            return _Resp()

    monkeypatch.setattr("smriti.agents.readers.r1_query_router.get_router", lambda: _Router())
    plan = await QueryRouterAgent().run(
        EncounterContext(chief_complaint=None, nl_query="show me the HbA1c trend", encounter_type="routine")
    )
    assert plan.intent == "lab_trend"
    assert plan.parameters.get("loinc_code") == "4548-4"


@pytest.mark.asyncio
async def test_r1_medication_history_intent(monkeypatch):
    class _Resp:
        intent = "medication_history"
        parameters = {}

    class _Router:
        async def call(self, **_kwargs):
            return _Resp()

    monkeypatch.setattr("smriti.agents.readers.r1_query_router.get_router", lambda: _Router())
    plan = await QueryRouterAgent().run(
        EncounterContext(chief_complaint=None, nl_query="is she on metformin", encounter_type="routine")
    )
    assert plan.intent == "medication_history"


@pytest.mark.asyncio
async def test_r1_unsupported(monkeypatch):
    class _Resp:
        intent = "unsupported"
        parameters = {}

    class _Router:
        async def call(self, **_kwargs):
            return _Resp()

    monkeypatch.setattr("smriti.agents.readers.r1_query_router.get_router", lambda: _Router())
    plan = await QueryRouterAgent().run(
        EncounterContext(chief_complaint=None, nl_query="tell me a joke", encounter_type="routine")
    )
    assert plan.intent == "unsupported"


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _Conn:
    def __init__(self):
        self.now = datetime.now(UTC)
        self.conditions = [
            {"id": uuid4(), "abha_id": "ABHA-1", "display_name": "Type 2 diabetes mellitus", "status": "active", "source_provider": "sentient_hms", "ingested_at": self.now},
            {"id": uuid4(), "abha_id": "ABHA-1", "display_name": "Essential hypertension", "status": "active", "source_provider": "sentient_hms", "ingested_at": self.now},
            {"id": uuid4(), "abha_id": "ABHA-1", "display_name": "Hypercholesterolemia", "status": "active", "source_provider": "sentient_hms", "ingested_at": self.now},
            {"id": uuid4(), "abha_id": "ABHA-1", "display_name": "CAD", "status": "active", "source_provider": "mock_apollo", "ingested_at": self.now},
            {"id": uuid4(), "abha_id": "ABHA-1", "display_name": "Hypothyroidism", "status": "active", "source_provider": "sentient_hms", "ingested_at": self.now},
        ]
        self.medications = [
            {"id": uuid4(), "abha_id": "ABHA-1", "display_name": "Metformin", "source_provider": "sentient_hms", "start_date": None, "end_date": None, "ingested_at": self.now},
        ]
        self.observations = [
            {"id": uuid4(), "abha_id": "ABHA-1", "display_name": "Hemoglobin A1c/Hemoglobin.total in Blood", "loinc_code": "4548-4", "value_numeric": 9.2, "unit": "%", "abnormal_flag": "H", "source_provider": "sentient_hms", "observed_at": self.now, "ingested_at": self.now},
            {"id": uuid4(), "abha_id": "ABHA-1", "display_name": "Hemoglobin A1c/Hemoglobin.total in Blood", "loinc_code": "4548-4", "value_numeric": 8.7, "unit": "%", "abnormal_flag": "H", "source_provider": "sentient_hms", "observed_at": self.now, "ingested_at": self.now},
        ]
        self.conflicts = [{"id": uuid4(), "abha_id": "ABHA-1", "resolution": None, "source_provider": "sentient_hms", "detected_at": self.now}]
        self.allergies = [{"id": uuid4(), "abha_id": "ABHA-1", "substance_name": "Penicillin", "status": "active", "source_provider": "mock_apollo", "ingested_at": self.now}]

    async def fetch(self, query, *args):
        if "FROM conditions" in query:
            return self.conditions
        if "FROM medications" in query:
            return self.medications
        if "FROM observations" in query:
            if "loinc_code = $2" in query:
                return [r for r in self.observations if r["loinc_code"] == args[1]]
            return self.observations
        if "FROM conflicts" in query:
            return self.conflicts
        if "FROM allergies" in query:
            return self.allergies
        return []


async def _pool_value(conn):
    return _Pool(conn)


@pytest.mark.asyncio
async def test_r2_general_briefing(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr("smriti.agents.readers.r2_context_retrieval.get_pool", lambda: _pool_value(conn))
    out = await ContextRetrievalAgent().run("ABHA-1", RetrievalPlan(intent="general_briefing", parameters={}), exclusions=[])
    assert len(out.conditions) == 5
    assert len(out.medications) >= 1
    assert len(out.observations) >= 1
    assert all(f.source.table for f in out.top_facts)


@pytest.mark.asyncio
async def test_r2_exclusions_medications(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr("smriti.agents.readers.r2_context_retrieval.get_pool", lambda: _pool_value(conn))
    out = await ContextRetrievalAgent().run("ABHA-1", RetrievalPlan(intent="general_briefing", parameters={}), exclusions=["medications"])
    assert out.medications == []


@pytest.mark.asyncio
async def test_r2_lab_trend(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr("smriti.agents.readers.r2_context_retrieval.get_pool", lambda: _pool_value(conn))
    out = await ContextRetrievalAgent().run("ABHA-1", RetrievalPlan(intent="lab_trend", parameters={"loinc_code": "4548-4"}), exclusions=[])
    assert len(out.observations) == 2
