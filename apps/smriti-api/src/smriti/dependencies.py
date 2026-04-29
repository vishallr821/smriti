"""FastAPI dependencies for consent and audit cross-cutting concerns."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from fastapi import Depends, HTTPException, Request

from smriti.agents import AuditAgent, ConsentGuard


def requires_scope(scope: list[str]) -> Callable[[Request], None]:
    """Return dependency that marks and enforces required scope."""

    required_scope = [s.strip() for s in scope if s and s.strip()]

    async def _dependency(request: Request) -> None:
        request.state.required_scope = required_scope
        if required_scope == ["briefing"]:
            return
        actor_id = getattr(request.state, "actor_id", "")
        actor_role = getattr(request.state, "actor_role", "")
        abha_id = getattr(request.state, "abha_id", "")
        action = getattr(request.state, "action", request.url.path)
        if not actor_id or not actor_role or not abha_id:
            raise HTTPException(status_code=403, detail="insufficient_context_for_consent")
        decision = await ConsentGuard().check(
            actor_id=actor_id,
            actor_role=actor_role,
            abha_id=abha_id,
            action=action,
            scope=required_scope,
        )
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.reason)
        request.state.applicable_consent_id = decision.applicable_consent_id

    setattr(_dependency, "__smriti_required_scope__", required_scope)
    return _dependency


def audit_action(action: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that appends audit event after successful route execution."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            response = await func(*args, **kwargs)
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            if request is not None:
                await AuditAgent().log(
                    actor_id=getattr(request.state, "actor_id", "unknown"),
                    actor_role=getattr(request.state, "actor_role", "unknown"),
                    action=action,
                    abha_id=getattr(request.state, "abha_id", None),
                    scope=getattr(request.state, "required_scope", None),
                    payload={"path": str(request.url.path), "method": request.method},
                    consent_id=(
                        str(getattr(request.state, "applicable_consent_id", ""))
                        if getattr(request.state, "applicable_consent_id", None)
                        else None
                    ),
                )
            return response

        return wrapper

    return decorator
