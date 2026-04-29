from __future__ import annotations

from datetime import UTC, datetime

import pytest

from smriti.agents.audit import AuditAgent, verify_chain


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self):
        self.rows: list[dict] = []

    def transaction(self):
        return _FakeTransaction()

    async def fetchrow(self, query: str, *args):
        if "ORDER BY id DESC" in query:
            if not self.rows:
                return None
            return {"this_hash": self.rows[-1]["this_hash"]}
        return None

    async def fetch(self, query: str, *args):
        return list(self.rows)

    async def execute(self, query: str, *args):
        self.rows.append(
            {
                "id": len(self.rows) + 1,
                "abha_id": args[0],
                "actor_id": args[1],
                "actor_role": args[2],
                "action": args[3],
                "scope": args[4],
                "consent_id": args[5],
                "payload_hash": args[6],
                "prev_hash": args[7],
                "this_hash": args[8],
                "created_at": datetime.fromisoformat(args[9]).astimezone(UTC),
            }
        )


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
async def test_sequential_logs_maintain_hash_chain(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr("smriti.agents.audit.get_pool", lambda: _async_value(_FakePool(conn)))
    agent = AuditAgent()
    await agent.log("HPR-1", "MD", "read.briefing", abha_id="ABHA-1", payload={"i": 1})
    await agent.log("HPR-1", "MD", "read.briefing", abha_id="ABHA-1", payload={"i": 2})
    await agent.log("HPR-1", "MD", "read.briefing", abha_id="ABHA-1", payload={"i": 3})

    assert conn.rows[1]["prev_hash"] == conn.rows[0]["this_hash"]
    assert conn.rows[2]["prev_hash"] == conn.rows[1]["this_hash"]
    assert await verify_chain() is True


@pytest.mark.asyncio
async def test_tampering_middle_row_breaks_chain(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr("smriti.agents.audit.get_pool", lambda: _async_value(_FakePool(conn)))
    agent = AuditAgent()
    await agent.log("HPR-1", "MD", "read.briefing", abha_id="ABHA-1", payload={"i": 1})
    await agent.log("HPR-1", "MD", "read.briefing", abha_id="ABHA-1", payload={"i": 2})
    await agent.log("HPR-1", "MD", "read.briefing", abha_id="ABHA-1", payload={"i": 3})

    conn.rows[1]["payload_hash"] = "tampered"
    assert await verify_chain() is False


async def _async_value(value):
    return value
