"""Application middleware definitions."""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .agents import ConsentGuard
from .auth import verify_clinician_jwt, verify_patient_jwt
from .logging_config import request_id_ctx_var


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign and propagate per-request IDs."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        request_id_ctx_var.set(request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply simple per-IP request limits via slowapi."""

    def __init__(self, app):
        super().__init__(app)
        self.limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

    async def dispatch(self, request: Request, call_next):
        try:
            self.limiter._check_request_limit(request, endpoint_func=None, in_middleware=True)
        except RateLimitExceeded as exc:
            return JSONResponse(status_code=429, content={"detail": str(exc)})
        return await call_next(request)


class ConsentMiddleware(BaseHTTPMiddleware):
    """C1 consent gate middleware."""

    @staticmethod
    def _extract_required_scope(request: Request) -> list[str] | None:
        route = request.scope.get("route")
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            return None
        for dep in getattr(dependant, "dependencies", []):
            call = getattr(dep, "call", None)
            scope = getattr(call, "__smriti_required_scope__", None)
            if scope:
                return list(scope)
        return None

    @staticmethod
    def _extract_bearer_token(request: Request) -> str | None:
        authz = request.headers.get("Authorization", "").strip()
        if not authz:
            return None
        parts = authz.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
            return None
        return parts[1].strip()

    def _resolve_actor(self, request: Request) -> tuple[str, str] | None:
        actor_id = getattr(request.state, "actor_id", None)
        actor_role = getattr(request.state, "actor_role", None)
        if actor_id and actor_role:
            return str(actor_id), str(actor_role)

        token = self._extract_bearer_token(request)
        if not token:
            return None

        try:
            patient_claims = verify_patient_jwt(token)
            request.state.actor_id = patient_claims.abha_id
            request.state.actor_role = "patient"
            request.state.abha_id = patient_claims.abha_id
            return patient_claims.abha_id, "patient"
        except Exception:
            pass

        try:
            clinician_claims = verify_clinician_jwt(token)
            request.state.actor_id = clinician_claims.hpr_id
            request.state.actor_role = clinician_claims.role
            request.state.provider_id = clinician_claims.provider_id
            return clinician_claims.hpr_id, clinician_claims.role
        except Exception:
            return None

    async def dispatch(self, request: Request, call_next):
        required_scope = self._extract_required_scope(request)
        if required_scope:
            request.state.required_scope = required_scope
            if required_scope == ["briefing"]:
                return await call_next(request)
            actor = self._resolve_actor(request)
            if actor is None:
                return JSONResponse(status_code=403, content={"detail": "missing_or_invalid_actor_token"})

            actor_id, actor_role = actor
            abha_id = (
                getattr(request.state, "abha_id", None)
                or request.path_params.get("abha_id")
                or request.query_params.get("abha_id")
                or request.headers.get("X-ABHA-ID")
            )
            if not abha_id:
                return JSONResponse(status_code=403, content={"detail": "missing_abha_id_for_consent"})

            action = request.headers.get("X-Smriti-Action", f"{request.method.lower()}.{request.url.path}")
            request.state.action = action
            decision = await ConsentGuard().check(
                actor_id=actor_id,
                actor_role=actor_role,
                abha_id=str(abha_id),
                action=action,
                scope=required_scope,
            )
            if not decision.allowed:
                return JSONResponse(status_code=403, content={"detail": decision.reason})
            request.state.applicable_consent_id = decision.applicable_consent_id

        return await call_next(request)
