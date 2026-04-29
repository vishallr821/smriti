from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from smriti.agents.consent_guard import ConsentGuard


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, providers: set[str], consents: list[dict]):
        self.providers = providers
        self.consents = consents

    async def fetchrow(self, query: str, *args):
        if "FROM providers" in query:
            provider_id = args[0]
            return {"provider_id": provider_id} if provider_id in self.providers else None
        return None

    async def fetch(self, query: str, *args):
        abha_id, now, actor_id = args
        rows = []
        for c in self.consents:
            if c["abha_id"] != abha_id:
                continue
            if c.get("revoked_at") is not None:
                continue
            expires_at = c.get("expires_at")
            if expires_at is not None and expires_at <= now:
                continue
            if c["grantee_class"] not in {"any_md", actor_id}:
                continue
            rows.append({"id": c["id"], "scope": c["scope"], "grantee_class": c["grantee_class"]})
        return rows

    def transaction(self):
        return _FakeTransaction()


class _FakeAcquire:
    def __init__(self, conn: _FakeConn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self.conn = conn

    def acquire(self):
        return _FakeAcquire(self.conn)


@pytest.mark.asyncio
async def test_patient_reading_own_data_allowed(monkeypatch):
    conn = _FakeConn(providers=set(), consents=[])
    monkeypatch.setattr("smriti.agents.consent_guard.get_pool", lambda: _async_value(_FakePool(conn)))
    decision = await ConsentGuard().check("ABHA-1", "patient", "ABHA-1", "read.timeline", ["conditions"])
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_random_clinician_no_consent_denied(monkeypatch):
    conn = _FakeConn(providers=set(), consents=[])
    monkeypatch.setattr("smriti.agents.consent_guard.get_pool", lambda: _async_value(_FakePool(conn)))
    decision = await ConsentGuard().check("HPR-9", "MD", "ABHA-1", "read.timeline", ["conditions"])
    assert decision.allowed is False


@pytest.mark.asyncio
async def test_matching_scope_grant_allowed(monkeypatch):
    conn = _FakeConn(
        providers=set(),
        consents=[
            {
                "id": uuid4(),
                "abha_id": "ABHA-1",
                "scope": ["conditions", "medications"],
                "grantee_class": "HPR-1",
                "expires_at": datetime.now(UTC) + timedelta(hours=1),
                "revoked_at": None,
            }
        ],
    )
    monkeypatch.setattr("smriti.agents.consent_guard.get_pool", lambda: _async_value(_FakePool(conn)))
    decision = await ConsentGuard().check("HPR-1", "MD", "ABHA-1", "read.timeline", ["conditions"])
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_partial_scope_grant_denied(monkeypatch):
    conn = _FakeConn(
        providers=set(),
        consents=[
            {
                "id": uuid4(),
                "abha_id": "ABHA-1",
                "scope": ["conditions"],
                "grantee_class": "any_md",
                "expires_at": datetime.now(UTC) + timedelta(hours=1),
                "revoked_at": None,
            }
        ],
    )
    monkeypatch.setattr("smriti.agents.consent_guard.get_pool", lambda: _async_value(_FakePool(conn)))
    decision = await ConsentGuard().check(
        "HPR-1", "MD", "ABHA-1", "read.timeline", ["conditions", "medications"]
    )
    assert decision.allowed is False


@pytest.mark.asyncio
async def test_expired_consent_denied(monkeypatch):
    conn = _FakeConn(
        providers=set(),
        consents=[
            {
                "id": uuid4(),
                "abha_id": "ABHA-1",
                "scope": ["conditions"],
                "grantee_class": "any_md",
                "expires_at": datetime.now(UTC) - timedelta(hours=1),
                "revoked_at": None,
            }
        ],
    )
    monkeypatch.setattr("smriti.agents.consent_guard.get_pool", lambda: _async_value(_FakePool(conn)))
    decision = await ConsentGuard().check("HPR-1", "MD", "ABHA-1", "read.timeline", ["conditions"])
    assert decision.allowed is False


@pytest.mark.asyncio
async def test_revoked_consent_denied(monkeypatch):
    conn = _FakeConn(
        providers=set(),
        consents=[
            {
                "id": uuid4(),
                "abha_id": "ABHA-1",
                "scope": ["conditions"],
                "grantee_class": "any_md",
                "expires_at": datetime.now(UTC) + timedelta(hours=1),
                "revoked_at": datetime.now(UTC),
            }
        ],
    )
    monkeypatch.setattr("smriti.agents.consent_guard.get_pool", lambda: _async_value(_FakePool(conn)))
    decision = await ConsentGuard().check("HPR-1", "MD", "ABHA-1", "read.timeline", ["conditions"])
    assert decision.allowed is False


@pytest.mark.asyncio
async def test_provider_write_allowed(monkeypatch):
    conn = _FakeConn(providers={"sentient_hms"}, consents=[])
    monkeypatch.setattr("smriti.agents.consent_guard.get_pool", lambda: _async_value(_FakePool(conn)))
    decision = await ConsentGuard().check(
        "sentient_hms", "provider", "ABHA-1", "write.condition", ["conditions"]
    )
    assert decision.allowed is True


async def _async_value(value):
    return value
