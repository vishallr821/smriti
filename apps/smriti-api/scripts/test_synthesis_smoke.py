from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from smriti.agents.readers import CohortAgent, ContextRetrievalAgent, QueryRouterAgent, RiskAgent, SynthesisAgent
from smriti.agents.readers.r3_cohort import PatientProfile
from smriti.schemas.encounter import EncounterContext, Fact, RetrievalPlan, RetrievedContext, SourceRef


async def main() -> None:
    abha_id = "ABHA-1"
    encounter = EncounterContext(
        chief_complaint="Routine T2DM follow-up, HbA1c 9.2",
        nl_query="show me the HbA1c trend and major risks",
        encounter_type="routine",
    )

    try:
        plan = await QueryRouterAgent().run(encounter)
    except Exception:
        plan = RetrievalPlan(intent="general_briefing", parameters={})
    if plan.intent == "unsupported":
        plan = RetrievalPlan(intent="general_briefing", parameters={})

    r2 = ContextRetrievalAgent()
    try:
        retrieved = await r2.run(abha_id, plan, exclusions=[])
    except Exception:
        src = SourceRef(table="observations", id="00000000-0000-0000-0000-000000000001", provider="sentient_hms", date=datetime.now(UTC))
        retrieved = RetrievedContext(
            top_facts=[Fact(fact="On 2024-09-10, HbA1c was 9.2% (high) at Sentient HMS.", source=src, date=datetime.now(UTC), confidence=0.9)],
            conflicts=[],
            medications=[{"id": "00000000-0000-0000-0000-000000000011", "display_name": "Metformin", "source_provider": "sentient_hms"}],
            observations=[{"id": "00000000-0000-0000-0000-000000000001", "display_name": "HbA1c"}],
            allergies=[],
            conditions=[{"id": "00000000-0000-0000-0000-000000000021", "display_name": "Type 2 diabetes mellitus", "snomed_code": "44054006"}],
        )

    profile = PatientProfile(
        age=47,
        sex="F",
        conditions=[str(c.get("snomed_code", "44054006")) for c in retrieved.conditions] or ["44054006"],
        current_medications=[str(m.get("display_name", "")) for m in retrieved.medications],
        key_labs={"hba1c": 9.2},
    )
    try:
        cohort = await CohortAgent().run(profile)
    except Exception:
        from smriti.agents.readers.r3_cohort import CohortPanel, PrivacyParams

        cohort = CohortPanel(n_total=0, buckets=[], privacy=PrivacyParams(), disclaimer="Cohort unavailable in smoke fallback.")

    meds_with_sources = []
    for m in retrieved.medications:
        meds_with_sources.append({**m, "source": None})
    risks = await RiskAgent().run(abha_id, meds_with_sources)

    briefing = await SynthesisAgent().run(
        encounter=encounter,
        retrieved_context=retrieved,
        conflicts=retrieved.conflicts,
        cohort_panel=cohort,
        risk_flags=risks,
        exclusions=[],
    )

    print(json.dumps(briefing.model_dump(mode="json"), indent=2, ensure_ascii=False))

    cache_path = Path(".cache/llm/demo_briefing.json")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(briefing.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved: {cache_path}")


if __name__ == "__main__":
    asyncio.run(main())
