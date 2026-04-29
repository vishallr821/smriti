# Smriti Demo Runbook (One Page)

## Pre-demo checklist (T-60 min)
- Run `make demo-prep`
- Run `make demo-health` and confirm all checks are green
- Issue clinician token if needed: `cd apps/smriti-api && uv run python scripts/issue_clinician_token.py --hpr_id HPR-DR-001 --provider_id sentient_hms`
- Confirm routes open:
  - `http://localhost:3000/clinician/12-3456-7890-1234`
  - `http://localhost:3000/embed/clinician?abha_id=12-3456-7890-1234&jwt=<token>`
- Keep one terminal open on API logs (`make dev-api`) and one on web (`make dev-web`)

## 5-minute script (PRD §20)
1. 0:00-0:30 (Slide 1)
- Click: title slide
- Say: Priya has fragmented care across hospitals and no shared memory

2. 0:30-1:30 (Patient view)
- Click: patient app, conflict alert, consent tab
- Say: Smriti surfaces cross-hospital conflict and gives patient consent control

3. 1:30-3:30 (Clinician in Sentient HMS)
- Click: Sentient HMS -> Smriti Memory tab -> enter encounter -> Generate briefing
- Say: in under five seconds we get conflict, cited top facts, timeline, and cohort panel
- Click: a citation chip and show raw source record

4. 3:30-4:30 (Privacy moment)
- Click: patient app -> toggle medications off -> return to clinician view -> regenerate
- Say: medication timeline is withheld, cohort panel constrained, exclusions explicit

5. 4:30-5:00 (Architecture + ask)
- Click: architecture slide
- Say: Sentient HMS + Smriti is provider intelligence + patient intelligence, ABDM-ready

## Backup switch (if unstable)
- Set `DEMO_CACHE=true` in `.env`
- Restart API (`make dev-api`)
- Cached Priya briefing will serve on failures with live-looking timestamps

## Recovery procedures
- Groq down
- Action: keep `DEMO_CACHE=true`; continue clinician flow; citations and structure still render

- Wi-Fi out
- Action: run local only (`localhost` URLs), avoid cloud-only steps, continue with prepared data

- Sentient HMS embed broken
- Action: switch to standalone clinician route (`/clinician/12-3456-7890-1234`) and state that embed fallback is shared-component mode

## Final go/no-go checks (T-5 min)
- `make demo-health` all green
- briefing latency <8s and query <3s from `make demo-smoke`
- conflict + citation click-through verified once
