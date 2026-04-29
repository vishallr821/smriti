"""R4 risk stub agent with demo interaction table."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from smriti.schemas.encounter import SourceRef


class RiskFlag(BaseModel):
    type: str
    severity: Literal["info", "warn", "alert"]
    description: str
    source_records: list[SourceRef] = Field(default_factory=list)


INTERACTION_TABLE: dict[tuple[str, str], tuple[str, str]] = {
    ("atorvastatin", "clarithromycin"): ("alert", "Potential severe interaction: atorvastatin + clarithromycin."),
    ("metformin", "iv_contrast"): ("warn", "Consider holding metformin before contrast procedure."),
    ("warfarin", "aspirin"): ("alert", "Increased bleeding risk with warfarin + aspirin."),
    ("metoprolol", "verapamil"): ("warn", "May increase bradycardia risk: metoprolol + verapamil."),
}


class RiskAgent:
    async def run(self, abha_id: str, current_medications: list) -> list[RiskFlag]:
        meds: list[tuple[str, SourceRef | None]] = []
        for item in current_medications:
            name = str(item.get("display_name", "")).strip().lower()
            source = item.get("source")
            meds.append((name, source))

        flags: list[RiskFlag] = []
        for i in range(len(meds)):
            for j in range(i + 1, len(meds)):
                a_name, a_source = meds[i]
                b_name, b_source = meds[j]
                if not a_name or not b_name:
                    continue
                key = (a_name, b_name)
                rev = (b_name, a_name)
                if key in INTERACTION_TABLE:
                    sev, desc = INTERACTION_TABLE[key]
                elif rev in INTERACTION_TABLE:
                    sev, desc = INTERACTION_TABLE[rev]
                else:
                    continue
                sources = [s for s in [a_source, b_source] if isinstance(s, SourceRef)]
                flags.append(
                    RiskFlag(
                        type="drug_interaction",
                        severity=sev,  # type: ignore[arg-type]
                        description=desc,
                        source_records=sources,
                    )
                )
        return flags
