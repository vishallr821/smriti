"""Briefing response schema (PRD 11.4 aligned)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from smriti.agents.readers.r3_cohort import CohortPanel
from smriti.schemas.encounter import Fact


class Briefing(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: str(uuid4()), alias="briefing_id")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    summary: str
    top_facts: list[Fact] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    medication_timeline: list[dict[str, Any]] = Field(default_factory=list)
    cohort_panel: CohortPanel | None = None
    risk_flags: list[dict[str, Any]] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    disclaimers: str = (
        "Smriti surfaces existing records. It does not diagnose, treat, or replace clinical judgment. "
        "Verify all facts at their source."
    )
    latency_ms: int | None = None

    @field_validator("top_facts")
    @classmethod
    def _facts_must_have_source(cls, value: list[Fact]) -> list[Fact]:
        for idx, fact in enumerate(value):
            if fact.source is None:
                raise ValueError(f"top_facts[{idx}] missing source")
        return value

    @field_validator("summary")
    @classmethod
    def _summary_len(cls, value: str) -> str:
        if len(value) > 500:
            raise ValueError("summary exceeds 500 characters")
        return value
