"""Template fallback for synthesis failures."""

from __future__ import annotations

from typing import Any

from smriti.schemas.briefing import Briefing
from smriti.schemas.encounter import EncounterContext, RetrievedContext


class TemplateBriefingFallback:
    def run(
        self,
        encounter: EncounterContext,
        retrieved_context: RetrievedContext,
        conflicts: list[dict[str, Any]],
        cohort_panel: Any,
        risk_flags: list[Any],
        exclusions: list[str],
    ) -> Briefing:
        top_conditions = [c.get("display_name", "condition") for c in retrieved_context.conditions[:3]]
        cond_text = ", ".join(top_conditions) if top_conditions else "limited condition data"
        meds_n = len(retrieved_context.medications if "medications" not in exclusions else [])
        summary = (
            f"Patient with {cond_text}, on {meds_n} active medications. "
            f"{len(conflicts)} unresolved conflicts."
        )
        return Briefing(
            summary=summary[:500],
            top_facts=retrieved_context.top_facts,
            conflicts=conflicts,
            medication_timeline=[] if "medications" in exclusions else retrieved_context.medications,
            cohort_panel=cohort_panel,
            risk_flags=risk_flags,
            exclusions=exclusions,
            disclaimers=(
                "Smriti surfaces existing records. It does not diagnose, treat, or replace clinical judgment. "
                "Verify all facts at their source. [Template fallback mode.]"
            ),
        )
