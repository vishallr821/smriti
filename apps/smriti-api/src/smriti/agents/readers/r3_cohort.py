"""R3 Cohort Agent: privacy-preserving cohort aggregation panel."""

from __future__ import annotations

import json
import math
import time
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from smriti.config import settings
from smriti.db.connection import get_pool

from .r3_helpers import build_profile_text, embed_profile, laplace_noise, regimen_key_from_treatments

logger = structlog.get_logger("r3_cohort")


class PatientProfile(BaseModel):
    age: int
    sex: str
    conditions: list[str]
    current_medications: list[str] = Field(default_factory=list)
    key_labs: dict[str, float] = Field(default_factory=dict)


class PrivacyParams(BaseModel):
    k_anonymity: int = 10
    epsilon: float = 1.0
    mechanism: Literal["laplace"] = "laplace"


class CohortBucket(BaseModel):
    regimen: str
    regimen_codes: list[str]
    n: int
    outcome_metric: str
    mean_with_dp: float
    ci_low: float
    ci_high: float
    raw_mean: float | None = None


class CohortPanel(BaseModel):
    n_total: int
    buckets: list[CohortBucket]
    privacy: PrivacyParams
    disclaimer: str


class CohortAgent:
    async def run(self, profile: PatientProfile) -> CohortPanel:
        start = time.perf_counter()
        logger.info("entry", agent="r3")
        try:
            if "44054006" not in profile.conditions:
                return CohortPanel(
                    n_total=0,
                    buckets=[],
                    privacy=PrivacyParams(),
                    disclaimer="Cohort unavailable: profile is outside the T2DM-focused cohort.",
                )

            profile_text = build_profile_text(profile)
            vec = embed_profile(profile_text)
            vec_literal = "[" + ",".join(f"{float(v):.8f}" for v in vec.tolist()) + "]"

            pool = await get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT treatments, outcomes
                    FROM cohort_patients
                    ORDER BY profile_vector <=> $1::vector
                    LIMIT 50
                    """,
                    vec_literal,
                )

            buckets_raw: dict[str, dict] = {}
            for row in rows:
                treatments_raw = row.get("treatments") or []
                outcomes_raw = row.get("outcomes") or {}
                if isinstance(treatments_raw, str):
                    try:
                        treatments_raw = json.loads(treatments_raw)
                    except Exception:
                        treatments_raw = []
                if isinstance(outcomes_raw, str):
                    try:
                        outcomes_raw = json.loads(outcomes_raw)
                    except Exception:
                        outcomes_raw = {}
                treatments = treatments_raw if isinstance(treatments_raw, list) else []
                outcomes = outcomes_raw if isinstance(outcomes_raw, dict) else {}
                regimen_key = regimen_key_from_treatments(treatments)
                if regimen_key not in buckets_raw:
                    buckets_raw[regimen_key] = {
                        "codes": sorted(str(t.get("rxnorm")) for t in treatments if t.get("rxnorm")),
                        "values": [],
                    }
                if "hba1c_3mo_change" in outcomes:
                    buckets_raw[regimen_key]["values"].append(float(outcomes["hba1c_3mo_change"]))

            panel_buckets: list[CohortBucket] = []
            for regimen_key, payload in buckets_raw.items():
                values = payload["values"]
                n = len(values)
                if n < 10:
                    continue
                raw_mean = sum(values) / n
                variance = sum((v - raw_mean) ** 2 for v in values) / n if n > 0 else 0.0
                std = math.sqrt(variance)
                sensitivity = 5.0 / n
                mean_with_dp = raw_mean + laplace_noise(sensitivity=sensitivity, epsilon=1.0)
                ci_width = 1.96 * std / math.sqrt(n) if n > 0 else 0.0
                bucket = CohortBucket(
                    regimen=regimen_key,
                    regimen_codes=payload["codes"],
                    n=n,
                    outcome_metric="hba1c_3mo_change",
                    mean_with_dp=round(mean_with_dp, 1),
                    ci_low=round(mean_with_dp - ci_width, 1),
                    ci_high=round(mean_with_dp + ci_width, 1),
                    raw_mean=round(raw_mean, 1) if settings.debug_dp else None,
                )
                panel_buckets.append(bucket)

            panel_buckets.sort(key=lambda b: b.n, reverse=True)
            n_total = sum(b.n for b in panel_buckets)
            if n_total == 0:
                return CohortPanel(
                    n_total=0,
                    buckets=[],
                    privacy=PrivacyParams(),
                    disclaimer="Cohort built from de-identified records linked to this memory layer. Privacy: k≥10, ε=1.0. [Hackathon: synthetic cohort.] Insufficient data for k-anonymous buckets.",
                )

            return CohortPanel(
                n_total=n_total,
                buckets=panel_buckets,
                privacy=PrivacyParams(),
                disclaimer="Cohort built from de-identified records linked to this memory layer. Privacy: k≥10, ε=1.0. [Hackathon: synthetic cohort.]",
            )
        finally:
            logger.info("exit", agent="r3", latency_ms=int((time.perf_counter() - start) * 1000))
