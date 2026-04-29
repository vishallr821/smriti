from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from smriti.agents.readers.r3_cohort import CohortPanel, PrivacyParams
from smriti.agents.readers.r4_risk import RiskFlag
from smriti.agents.readers.r5_synthesis import SynthesisAgent
from smriti.schemas.encounter import EncounterContext, Fact, RetrievedContext, SourceRef


def _ctx() -> RetrievedContext:
    src1 = SourceRef(table="observations", id=uuid4(), provider="sentient_hms", date=datetime.now(UTC))
    src2 = SourceRef(table="conditions", id=uuid4(), provider="sentient_hms", date=datetime.now(UTC))
    facts = [
        Fact(fact="On 2024-09-10, HbA1c was 9.2% (high) at Sentient HMS.", source=src1, date=datetime.now(UTC), confidence=0.9),
        Fact(fact="Type 2 diabetes mellitus active.", source=src2, date=datetime.now(UTC), confidence=0.9),
    ]
    return RetrievedContext(
        top_facts=facts,
        conflicts=[],
        medications=[{"id": str(uuid4()), "display_name": "Metformin", "source_provider": "sentient_hms"}],
        observations=[],
        allergies=[],
        conditions=[{"id": str(uuid4()), "display_name": "Type 2 diabetes mellitus", "source_provider": "sentient_hms"}],
    )


def _panel() -> CohortPanel:
    return CohortPanel(n_total=20, buckets=[], privacy=PrivacyParams(), disclaimer="demo")


@pytest.mark.asyncio
async def test_synthesis_happy_path(monkeypatch):
    ctx = _ctx()
    encounter = EncounterContext(chief_complaint="T2DM follow-up", nl_query="show trend", encounter_type="routine")

    class _Router:
        async def call(self, **kwargs):
            from smriti.schemas.briefing import Briefing

            return Briefing(
                summary="Stable summary",
                top_facts=ctx.top_facts,
                conflicts=[],
                medication_timeline=ctx.medications,
                cohort_panel=_panel(),
                risk_flags=[],
                exclusions=[],
            )

    monkeypatch.setattr("smriti.agents.readers.r5_synthesis.get_router", lambda: _Router())
    briefing = await SynthesisAgent().run(encounter, ctx, [], _panel(), [], [])
    assert len(briefing.top_facts) >= 2
    assert all(f.source for f in briefing.top_facts)


@pytest.mark.asyncio
async def test_synthesis_citation_retry(monkeypatch):
    ctx = _ctx()
    encounter = EncounterContext(chief_complaint="T2DM follow-up", nl_query="show trend", encounter_type="routine")
    fake_src = SourceRef(table="observations", id=uuid4(), provider="x", date=datetime.now(UTC))

    class _Router:
        def __init__(self):
            self.calls = 0

        async def call(self, **kwargs):
            from smriti.schemas.briefing import Briefing

            self.calls += 1
            if self.calls == 1:
                return Briefing(
                    summary="bad source",
                    top_facts=[Fact(fact="x", source=fake_src, date=datetime.now(UTC), confidence=0.9)],
                    conflicts=[],
                    medication_timeline=[],
                    cohort_panel=_panel(),
                    risk_flags=[],
                    exclusions=[],
                )
            return Briefing(
                summary="good source",
                top_facts=ctx.top_facts,
                conflicts=[],
                medication_timeline=[],
                cohort_panel=_panel(),
                risk_flags=[],
                exclusions=[],
            )

    router = _Router()
    monkeypatch.setattr("smriti.agents.readers.r5_synthesis.get_router", lambda: router)
    briefing = await SynthesisAgent().run(encounter, ctx, [], _panel(), [], [])
    assert briefing.summary == "good source"
    assert router.calls == 2


@pytest.mark.asyncio
async def test_synthesis_two_failures_fallback(monkeypatch):
    ctx = _ctx()
    encounter = EncounterContext(chief_complaint="T2DM follow-up", nl_query="show trend", encounter_type="routine")
    fake_src = SourceRef(table="observations", id=uuid4(), provider="x", date=datetime.now(UTC))

    class _Router:
        async def call(self, **kwargs):
            from smriti.schemas.briefing import Briefing

            return Briefing(
                summary="bad source",
                top_facts=[Fact(fact="x", source=fake_src, date=datetime.now(UTC), confidence=0.9)],
                conflicts=[],
                medication_timeline=[],
                cohort_panel=_panel(),
                risk_flags=[],
                exclusions=[],
            )

    monkeypatch.setattr("smriti.agents.readers.r5_synthesis.get_router", lambda: _Router())
    briefing = await SynthesisAgent().run(encounter, ctx, [], _panel(), [], [])
    assert "[Template fallback mode.]" in briefing.disclaimers


@pytest.mark.asyncio
async def test_exclusion_respected(monkeypatch):
    ctx = _ctx()
    encounter = EncounterContext(chief_complaint="T2DM follow-up", nl_query="show trend", encounter_type="routine")

    class _Router:
        async def call(self, **kwargs):
            from smriti.schemas.briefing import Briefing

            return Briefing(
                summary="ok",
                top_facts=ctx.top_facts,
                conflicts=[],
                medication_timeline=ctx.medications,
                cohort_panel=_panel(),
                risk_flags=[],
                exclusions=[],
            )

    monkeypatch.setattr("smriti.agents.readers.r5_synthesis.get_router", lambda: _Router())
    briefing = await SynthesisAgent().run(encounter, ctx, [], _panel(), [], ["medications"])
    assert briefing.medication_timeline == []
    assert "medications" in briefing.exclusions


@pytest.mark.asyncio
async def test_conflict_and_latency(monkeypatch):
    ctx = _ctx()
    encounter = EncounterContext(chief_complaint="T2DM follow-up", nl_query="show trend", encounter_type="routine")
    conflicts = [{"conflict_type": "allergy_disagreement"}]

    class _Router:
        async def call(self, **kwargs):
            from smriti.schemas.briefing import Briefing

            return Briefing(
                summary="ok",
                top_facts=ctx.top_facts,
                conflicts=conflicts,
                medication_timeline=ctx.medications,
                cohort_panel=_panel(),
                risk_flags=[],
                exclusions=[],
            )

    monkeypatch.setattr("smriti.agents.readers.r5_synthesis.get_router", lambda: _Router())
    briefing = await SynthesisAgent().run(encounter, ctx, conflicts, _panel(), [], [])
    assert briefing.conflicts
    assert briefing.latency_ms is not None and briefing.latency_ms >= 0
