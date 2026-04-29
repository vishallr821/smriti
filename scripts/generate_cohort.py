"""Generate and seed synthetic cohort_patients data."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter, defaultdict
from urllib.parse import urlparse

import asyncpg
import numpy as np
from sentence_transformers import SentenceTransformer

# scripts/generate_cohort.py
# Run once before the hackathon

CONDITIONS = [
    ("44054006", "Type 2 diabetes mellitus", 0.5),
    ("38341003", "Essential hypertension", 0.4),
    ("13644009", "Hypercholesterolemia", 0.3),
    ("53741008", "Coronary arteriosclerosis", 0.15),
]

REGIMENS = {
    "metformin_only": [{"rxnorm": "6809", "dose": "500mg BID"}],
    "metformin_glp1": [
        {"rxnorm": "6809", "dose": "500mg BID"},
        {"rxnorm": "1991302", "dose": "0.5mg weekly"},
    ],
    "metformin_sglt2": [
        {"rxnorm": "6809", "dose": "500mg BID"},
        {"rxnorm": "1545653", "dose": "10mg daily"},
    ],
    "insulin_basal_metformin": [
        {"rxnorm": "6809", "dose": "500mg BID"},
        {"rxnorm": "274783", "dose": "10U HS"},
    ],
}

# Realistic effect sizes from published evidence
EFFECT_SIZES = {
    "metformin_only": {"hba1c_3mo_change_mean": -0.7, "sd": 0.3},
    "metformin_glp1": {"hba1c_3mo_change_mean": -1.4, "sd": 0.2},
    "metformin_sglt2": {"hba1c_3mo_change_mean": -1.1, "sd": 0.3},
    "insulin_basal_metformin": {"hba1c_3mo_change_mean": -1.6, "sd": 0.4},
}

REGIMEN_TEXT = {
    "metformin_only": "on metformin 500mg BID",
    "metformin_glp1": "on metformin BID and GLP-1 weekly",
    "metformin_sglt2": "on metformin BID and SGLT2 inhibitor daily",
    "insulin_basal_metformin": "on metformin BID and basal insulin HS",
    "none": "not on a diabetes regimen",
}


def _is_pooler_dsn(dsn: str) -> bool:
    parsed = urlparse(dsn)
    host = (parsed.hostname or "").lower()
    return "pooler.supabase.com" in host or parsed.port == 6543


def _resolve_dsn() -> str:
    dsn = os.getenv("SUPABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("SUPABASE_URL is required")
    if not dsn.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("SUPABASE_URL must be a Postgres connection string")
    return dsn


def _build_profile_text(age: int, sex: str, bmi: float, conditions: list[str], regimen: str) -> str:
    lead = f"{age}{sex}, BMI {int(round(bmi))}"

    cond_bits: list[str] = []
    if "44054006" in conditions:
        cond_bits.append("T2DM with HbA1c 8.9")
    if "38341003" in conditions:
        cond_bits.append("hypertensive")
    if "13644009" in conditions:
        cond_bits.append("hypercholesterolemia")
    if "53741008" in conditions:
        cond_bits.append("coronary artery disease")

    cond_text = ", ".join(cond_bits) if cond_bits else "no major chronic condition"
    return f"{lead}, {cond_text}, {REGIMEN_TEXT[regimen]} and atorvastatin 20mg daily"


def _sample_conditions(rng: np.random.Generator) -> list[tuple[str, str]]:
    k = int(rng.integers(1, 4))
    probs = np.array([item[2] for item in CONDITIONS], dtype=np.float64)
    probs = probs / probs.sum()
    chosen_idx = rng.choice(len(CONDITIONS), size=k, replace=False, p=probs)
    return [(CONDITIONS[i][0], CONDITIONS[i][1]) for i in chosen_idx]


def _vector_literal(vector: np.ndarray) -> str:
    values = ",".join(f"{float(v):.8f}" for v in vector.tolist())
    return f"[{values}]"


async def generate_cohort() -> None:
    np.random.seed(42)
    rng = np.random.default_rng(42)

    dsn = _resolve_dsn()
    connect_kwargs: dict[str, object] = {"dsn": dsn}
    if _is_pooler_dsn(dsn):
        connect_kwargs["statement_cache_size"] = 0

    model = SentenceTransformer("all-MiniLM-L6-v2")

    connection = await asyncpg.connect(**connect_kwargs)
    try:
        existing_count = await connection.fetchval("SELECT COUNT(*) FROM cohort_patients")
        assert isinstance(existing_count, int)
        if existing_count >= 200:
            print("already seeded")
        else:
            records: list[dict[str, object]] = []
            for _ in range(200):
                age = int(rng.integers(35, 71))
                sex = str(rng.choice(["F", "M"], p=[0.6, 0.4]))
                bmi = float(np.clip(rng.normal(28.0, 4.0), 18.0, 45.0))

                sampled_conditions = _sample_conditions(rng)
                condition_codes = [code for code, _ in sampled_conditions]

                regimen = "none"
                treatments: list[dict[str, object]] = []
                hba1c_change = 0.0
                if "44054006" in condition_codes:
                    regimen = str(rng.choice(list(REGIMENS.keys())))
                    effect = EFFECT_SIZES[regimen]
                    hba1c_change = float(
                        rng.normal(effect["hba1c_3mo_change_mean"], effect["sd"])
                    )
                    for med in REGIMENS[regimen]:
                        treatments.append(
                            {
                                "rxnorm": med["rxnorm"],
                                "start_offset_days": int(rng.integers(-365, -30)),
                                "dose": med["dose"],
                            }
                        )

                bp_base = 0.52 + (0.08 if regimen in {"metformin_glp1", "metformin_sglt2"} else 0.0)
                bp_base -= 0.10 if "38341003" in condition_codes else 0.0
                bp_base -= 0.07 if bmi >= 33 else 0.0
                bp_control = int(rng.random() < np.clip(bp_base, 0.15, 0.90))

                readmit_base = 0.12
                readmit_base += 0.08 if "53741008" in condition_codes else 0.0
                readmit_base += 0.05 if "44054006" in condition_codes else 0.0
                readmit_base -= 0.03 if regimen in {"metformin_glp1", "metformin_sglt2"} else 0.0
                readmit_90d = int(rng.random() < np.clip(readmit_base, 0.03, 0.45))

                profile_text = _build_profile_text(age, sex, bmi, condition_codes, regimen)
                records.append(
                    {
                        "age": age,
                        "sex": sex,
                        "conditions": condition_codes,
                        "treatments": treatments,
                        "outcomes": {
                            "regimen": regimen,
                            "hba1c_3mo_change": round(hba1c_change, 3),
                            "bp_control": bp_control,
                            "readmit_90d": readmit_90d,
                        },
                        "profile_text": profile_text,
                    }
                )

            vectors = model.encode([str(r["profile_text"]) for r in records], show_progress_bar=False)
            for rec, vec in zip(records, vectors):
                rec["profile_vector"] = np.asarray(vec, dtype=np.float32)

            async with connection.transaction():
                for rec in records:
                    await connection.execute(
                        """
                        INSERT INTO cohort_patients
                        (age, sex, conditions, treatments, outcomes, profile_text, profile_vector)
                        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6, $7::vector)
                        """,
                        rec["age"],
                        rec["sex"],
                        json.dumps(rec["conditions"]),
                        json.dumps(rec["treatments"]),
                        json.dumps(rec["outcomes"]),
                        rec["profile_text"],
                        _vector_literal(rec["profile_vector"]),
                    )

        null_vector_count = await connection.fetchval(
            "SELECT COUNT(*) FROM cohort_patients WHERE profile_vector IS NULL"
        )
        assert isinstance(null_vector_count, int)
        if null_vector_count > 0:
            raise RuntimeError("profile_vector validation failed: null vectors found")

        rows = await connection.fetch(
            """
            SELECT outcomes->>'regimen' AS regimen,
                   AVG((outcomes->>'hba1c_3mo_change')::numeric) AS mean_hba1c_change,
                   COUNT(*) AS n
            FROM cohort_patients
            GROUP BY outcomes->>'regimen'
            ORDER BY n DESC
            """
        )

        regimen_dist: Counter[str] = Counter()
        hba1c_summary: dict[str, float] = {}
        for row in rows:
            regimen = str(row["regimen"])
            regimen_dist[regimen] = int(row["n"])
            hba1c_summary[regimen] = float(row["mean_hba1c_change"])

        total = await connection.fetchval("SELECT COUNT(*) FROM cohort_patients")
        print(f"cohort_patients total rows: {int(total)}")
        print("distribution by regimen:")
        for regimen, count in regimen_dist.items():
            print(f"  {regimen}: {count}")
        print("mean hba1c_3mo_change per regimen:")
        for regimen, mean_val in hba1c_summary.items():
            print(f"  {regimen}: {mean_val:.3f}")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(generate_cohort())
