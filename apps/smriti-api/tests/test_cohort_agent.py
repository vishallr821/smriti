from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from smriti.agents.readers.r3_cohort import CohortAgent, CohortPanel, PatientProfile


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, query, *args):
        if "FROM cohort_patients" in query:
            return self.rows
        return []


def _rows():
    rows = []
    for _ in range(14):
        rows.append(
            {
                "treatments": [{"rxnorm": "6809", "dose": "500mg BID"}],
                "outcomes": {"hba1c_3mo_change": -0.7},
            }
        )
    for _ in range(13):
        rows.append(
            {
                "treatments": [{"rxnorm": "6809", "dose": "500mg BID"}, {"rxnorm": "1991302", "dose": "0.5mg weekly"}],
                "outcomes": {"hba1c_3mo_change": -1.4},
            }
        )
    for _ in range(11):
        rows.append(
            {
                "treatments": [{"rxnorm": "6809", "dose": "500mg BID"}, {"rxnorm": "1545653", "dose": "10mg daily"}],
                "outcomes": {"hba1c_3mo_change": -1.1},
            }
        )
    for _ in range(9):
        rows.append(
            {
                "treatments": [{"rxnorm": "6809", "dose": "500mg BID"}, {"rxnorm": "274783", "dose": "10U HS"}],
                "outcomes": {"hba1c_3mo_change": -1.6},
            }
        )
    return rows


async def _pool_value(conn):
    return _Pool(conn)


class _Embed:
    def __call__(self, text):
        return [0.01] * 384


@pytest.mark.asyncio
async def test_priya_profile_buckets_and_k_floor(monkeypatch):
    conn = _Conn(_rows())
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.get_pool", lambda: _pool_value(conn))
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.embed_profile", lambda _text: __import__("numpy").array([0.01] * 384))
    profile = PatientProfile(
        age=47,
        sex="F",
        conditions=["44054006", "38341003"],
        current_medications=["metformin 500mg BID"],
        key_labs={"hba1c": 9.2},
    )
    panel = await CohortAgent().run(profile)
    regimen_names = {b.regimen for b in panel.buckets}
    assert "6809" in next(iter(regimen_names))
    assert all(b.n >= 10 for b in panel.buckets)
    assert panel.n_total >= 30


@pytest.mark.asyncio
async def test_means_near_effect_sizes_with_noise(monkeypatch):
    conn = _Conn(_rows())
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.get_pool", lambda: _pool_value(conn))
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.embed_profile", lambda _text: __import__("numpy").array([0.01] * 384))
    profile = PatientProfile(age=47, sex="F", conditions=["44054006"], current_medications=["metformin"], key_labs={})
    panel = await CohortAgent().run(profile)
    means = sorted([b.mean_with_dp for b in panel.buckets])
    assert any(abs(m - (-0.7)) <= 0.5 for m in means)
    assert any(abs(m - (-1.4)) <= 0.5 for m in means)


@pytest.mark.asyncio
async def test_out_of_cohort_profile_returns_empty(monkeypatch):
    conn = _Conn(_rows())
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.get_pool", lambda: _pool_value(conn))
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.embed_profile", lambda _text: __import__("numpy").array([0.01] * 384))
    profile = PatientProfile(age=80, sex="M", conditions=["ALZ"], current_medications=[], key_labs={})
    panel = await CohortAgent().run(profile)
    assert panel.n_total == 0
    assert panel.buckets == []


@pytest.mark.asyncio
async def test_noise_differs_across_runs(monkeypatch):
    conn = _Conn(_rows())
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.get_pool", lambda: _pool_value(conn))
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.embed_profile", lambda _text: __import__("numpy").array([0.01] * 384))
    profile = PatientProfile(age=47, sex="F", conditions=["44054006"], current_medications=["metformin"], key_labs={})
    p1 = await CohortAgent().run(profile)
    p2 = await CohortAgent().run(profile)
    map1 = {b.regimen: b.mean_with_dp for b in p1.buckets}
    map2 = {b.regimen: b.mean_with_dp for b in p2.buckets}
    assert any(map1[k] != map2[k] for k in map1.keys() & map2.keys())


@pytest.mark.asyncio
async def test_schema_validation(monkeypatch):
    conn = _Conn(_rows())
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.get_pool", lambda: _pool_value(conn))
    monkeypatch.setattr("smriti.agents.readers.r3_cohort.embed_profile", lambda _text: __import__("numpy").array([0.01] * 384))
    profile = PatientProfile(age=47, sex="F", conditions=["44054006"], current_medications=["metformin"], key_labs={})
    panel = await CohortAgent().run(profile)
    validated = CohortPanel.model_validate(panel.model_dump())
    assert validated.n_total >= 0
