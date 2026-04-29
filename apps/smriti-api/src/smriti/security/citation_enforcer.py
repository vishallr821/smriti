"""Ensure every synthesized fact is source-backed and traceable."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True)
class SourceRef:
    table: str
    id: UUID
    provider: str


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    violations: list[str]


class CitationEnforcer:
    def validate(self, briefing: dict, available_sources: list[SourceRef]) -> ValidationResult:
        allowed = {(s.table, str(s.id)) for s in available_sources}
        violations: list[str] = []
        facts = briefing.get("top_facts", [])

        for idx, fact in enumerate(facts):
            source = fact.get("source")
            if source is None:
                violations.append(f"top_facts[{idx}] missing source")
                continue
            table = source.get("table")
            source_id = str(source.get("id")) if source.get("id") is not None else None
            if not table or not source_id:
                violations.append(f"top_facts[{idx}] source incomplete")
                continue
            if (table, source_id) not in allowed:
                violations.append(f"top_facts[{idx}] source not found in available_sources")

        return ValidationResult(valid=len(violations) == 0, violations=violations)
