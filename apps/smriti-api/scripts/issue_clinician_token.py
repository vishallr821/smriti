"""Issue a clinician JWT for local/demo use."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from jose import jwt

from smriti.config import settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Issue a clinician JWT signed by CLINICIAN_JWT_KEY")
    parser.add_argument("--hpr_id", required=True, help="Clinician HPR identifier")
    parser.add_argument("--provider_id", required=True, help="Provider identifier")
    parser.add_argument("--duration_hours", type=float, default=8.0, help="Token validity window in hours (default: 8)")
    parser.add_argument("--name", default="Dr. Arjun Mehta", help="Display name claim")
    parser.add_argument("--role", default="MD", help="Role claim")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if not settings.clinician_jwt_key:
        raise RuntimeError("CLINICIAN_JWT_KEY is required")
    if args.duration_hours <= 0:
        raise ValueError("--duration_hours must be > 0")

    now = datetime.now(UTC)
    exp = now + timedelta(hours=args.duration_hours)

    payload = {
        "hpr_id": args.hpr_id,
        "name": args.name,
        "role": args.role,
        "provider_id": args.provider_id,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }

    token = jwt.encode(payload, settings.clinician_jwt_key, algorithm="HS256")
    print(token)


if __name__ == "__main__":
    main()
