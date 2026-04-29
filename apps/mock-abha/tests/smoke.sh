#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${MOCK_ABHA_URL:-http://localhost:8001}"

echo "[1/6] OTP init"
INIT_RESP=$(curl -sS -X POST "${BASE_URL}/abha/otp/init" \
  -H "Content-Type: application/json" \
  -d '{"mobile_or_aadhaar":"9876543210"}')
echo "$INIT_RESP"
TXN_ID=$(python -c "import json,sys; print(json.loads(sys.argv[1])['txn_id'])" "$INIT_RESP")

echo "[2/6] OTP verify"
VERIFY_RESP=$(curl -sS -X POST "${BASE_URL}/abha/otp/verify" \
  -H "Content-Type: application/json" \
  -d "{\"txn_id\":\"${TXN_ID}\",\"otp\":\"123456\"}")
echo "$VERIFY_RESP"
JWT=$(python -c "import json,sys; print(json.loads(sys.argv[1])['jwt'])" "$VERIFY_RESP")
ABHA_ID=$(python -c "import json,sys; print(json.loads(sys.argv[1])['abha_id'])" "$VERIFY_RESP")

echo "[3/6] Profile"
PROFILE_RESP=$(curl -sS -X POST "${BASE_URL}/abha/profile" \
  -H "Content-Type: application/json" \
  -d "{\"jwt\":\"${JWT}\"}")
echo "$PROFILE_RESP"

echo "[4/6] Consent request"
CONSENT_REQ_RESP=$(curl -sS -X POST "${BASE_URL}/hie/consent/request" \
  -H "Content-Type: application/json" \
  -d "{\"abha_id\":\"${ABHA_ID}\",\"requester_hpr_id\":\"HPR-001\",\"scope\":[\"conditions\",\"medications\"],\"purpose\":\"care\",\"expires_in\":3600}")
echo "$CONSENT_REQ_RESP"
CONSENT_REQUEST_ID=$(python -c "import json,sys; print(json.loads(sys.argv[1])['consent_request_id'])" "$CONSENT_REQ_RESP")

echo "[5/6] Consent grant"
CONSENT_GRANT_RESP=$(curl -sS -X POST "${BASE_URL}/hie/consent/grant" \
  -H "Content-Type: application/json" \
  -d "{\"consent_request_id\":\"${CONSENT_REQUEST_ID}\"}")
echo "$CONSENT_GRANT_RESP"
CONSENT_ID=$(python -c "import json,sys; print(json.loads(sys.argv[1])['consent_id'])" "$CONSENT_GRANT_RESP")

echo "[6/6] Consent fetch"
CONSENT_FETCH_RESP=$(curl -sS -X GET "${BASE_URL}/hie/consent/${CONSENT_ID}")
echo "$CONSENT_FETCH_RESP"

echo "Smoke test passed."
