"""Build deterministic demo briefing cache files for Priya."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np

from smriti.agents.readers import run_reader_dag
from smriti.agents.writers.dag import run_writer_dag
from smriti.agents.writers.w3_normalization import NormalizationAgent
from smriti.schemas.clinical import NormalizedClinicalEntity
from smriti.schemas.encounter import EncounterContext

from _demo_common import (
    PRIYA_ABHA,
    apollo_bundle,
    clinician_claims,
    ensure_priya_patient,
    sentient_bundle,
    set_priya_consent,
    source_record,
)

CACHE_DIR = Path(".cache/llm")
PRIYA_CACHE = CACHE_DIR / "demo_briefing_priya.json"
PRIYA_NO_MEDS_CACHE = CACHE_DIR / "demo_briefing_priya_no_meds.json"


_original_normalization_run = NormalizationAgent.run


async def _demo_normalization_run(self: NormalizationAgent, entities):
    """Deterministic, LLM-free normalization for demo data preparation."""
    out: list[NormalizedClinicalEntity] = []
    for entity in entities:
        candidates = await self._top_candidates(entity)
        if candidates:
            out.append(self._apply_code(entity, str(candidates[0]["code"]), str(candidates[0]["system"])))
        else:
            out.append(NormalizedClinicalEntity.model_validate(entity.model_dump() | {"confidence": 0.4}))
    return out


async def _run_flow(include_medications: bool) -> dict:
    await ensure_priya_patient()
    await run_writer_dag(source_record("sentient_hms", sentient_bundle()), PRIYA_ABHA)
    await run_writer_dag(source_record("mock_apollo", apollo_bundle()), PRIYA_ABHA)
    await set_priya_consent(include_medications=include_medications)

    np.random.seed(42)
    briefing = await run_reader_dag(
        PRIYA_ABHA,
        EncounterContext(chief_complaint="T2DM follow-up", encounter_type="routine"),
        clinician_claims(),
    )
    return briefing.model_dump(mode="json", by_alias=True)


async def main() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    NormalizationAgent.run = _demo_normalization_run

    try:
        full = await _run_flow(include_medications=True)
        PRIYA_CACHE.write_text(json.dumps(full, indent=2, sort_keys=True), encoding="utf-8")

        no_meds = await _run_flow(include_medications=False)
        PRIYA_NO_MEDS_CACHE.write_text(json.dumps(no_meds, indent=2, sort_keys=True), encoding="utf-8")
    finally:
        NormalizationAgent.run = _original_normalization_run

    print(f"cached: {PRIYA_CACHE}")
    print(f"cached: {PRIYA_NO_MEDS_CACHE}")


if __name__ == "__main__":
    asyncio.run(main())
