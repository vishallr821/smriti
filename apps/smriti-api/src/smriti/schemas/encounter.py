"""Schemas for reader pipeline encounter planning and retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class EncounterContext(BaseModel):
    chief_complaint: str | None = None
    nl_query: str | None = None
    encounter_type: Literal["routine", "urgent", "emergency"] = "routine"


Intent = Literal[
    "general_briefing",
    "lab_trend",
    "medication_history",
    "allergy_check",
    "cohort_lookup",
    "interaction_check",
    "unsupported",
]


class RetrievalPlan(BaseModel):
    intent: Intent
    parameters: dict[str, Any] = Field(default_factory=dict)


class SourceRef(BaseModel):
    table: str
    id: UUID
    provider: str
    date: datetime


class Fact(BaseModel):
    fact: str
    source: SourceRef
    date: datetime
    confidence: float


class RetrievedContext(BaseModel):
    top_facts: list[Fact] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    medications: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    allergies: list[dict[str, Any]] = Field(default_factory=list)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
