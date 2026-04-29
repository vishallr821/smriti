# Smriti: AI-Agent-Powered Patient Memory Layer

A monorepo for Smriti, an AI-agent-powered patient memory layer that integrates with ABHA (Ayushman Bharat Health Account) and FHIR-compliant hospital systems to provide intelligent, privacy-preserving patient data abstraction and semantic search.

## Prerequisites

Before setting up Smriti, ensure you have the following installed:

- **Python 3.11+** - [Download](https://www.python.org/downloads/)
- **Node.js 20+** - [Download](https://nodejs.org/)
- **uv** - Ultra-fast Python package installer/resolver - [Install](https://github.com/astral-sh/uv#installation)
- **Docker & Docker Compose** - [Install](https://docs.docker.com/get-docker/)

## Repository Structure

```
smriti/
├── apps/
│   ├── smriti-api/           # FastAPI gateway + LangGraph
│   ├── mock-abha/            # Mock ABHA service
│   └── smriti-web/           # Next.js 15 clinician UI
├── packages/
│   └── shared-types/         # TypeScript types shared with frontend
├── scripts/
│   ├── generate_cohort.py    # Synthetic cohort generator
│   └── load_terminology.py   # Loads SNOMED/LOINC/ICD-10/RxNorm
├── docker/
│   └── hapi-fhir/            # MockHospital FHIR server config
├── docs/
│   └── SMRITI_PRD.md         # Product Requirements Document
└── [config files]            # .env.example, docker-compose.yml, etc.
```

## Initial Setup

### 1. Clone and Configure Environment

```bash
# Clone the repository (if applicable)
cd smriti

# Copy environment template and configure
cp .env.example .env
# Edit .env with your actual credentials:
# - SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_ANON_KEY
# - GROQ_API_KEY
# - MOCK_ABHA_SIGNING_KEY
# - SYSTEM_SALT
```

### 2. Install Dependencies

```bash
# Install all Python packages using uv
make setup

# Or manually for each app:
cd apps/smriti-api && uv sync
cd ../mock-abha && uv sync
cd ../..
```

### 3. Start FHIR Server

```bash
# Spin up HAPI FHIR server
make dev-fhir

# Or manually:
docker-compose up -d hapi-fhir
```

## Development

### Running Services

Start the API in one terminal:

```bash
make dev-api
# API will be available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

Start the mock ABHA service in another terminal:

```bash
make dev-mock-abha
# Service will be available at http://localhost:8001
```

Start the web UI (Phase 14):

```bash
make dev-web
# UI will be available at http://localhost:3000
```

## Running the demo

```bash
# Full deterministic prep (reset + seed + cache + dependency checks)
make demo-prep
```

One hour before presenting, run:

```bash
make demo-health
```

If any LLM/provider flakiness appears, set `DEMO_CACHE=true` in `.env`, restart `make dev-api`, and continue with the cached Priya briefing flow.

Day-of flow:

```bash
make dev-api
make dev-mock-abha
make dev-web
make demo-smoke
```

## Database setup

Smriti uses Supabase Cloud for its database. Create or select a Supabase project, then copy the database connection string from Project Settings > Database > Connection string.

Set `SUPABASE_URL` in `.env` to that Postgres connection string before running migrations locally. The service role key is still required for later API work, but the migration runner connects directly to Postgres.

Run the schema migrations with:

```bash
make db-migrate
```

The migration runner applies each `.sql` file in `apps/smriti-api/src/smriti/db/migrations/` once and records it in `_migrations`.

Seed terminology and synthetic cohort data after migrations:

```bash
make terminology-seed
make cohort-seed
```

Notes:
- On first run, `sentence-transformers` downloads `all-MiniLM-L6-v2` (~80MB) into `~/.cache/huggingface/`.
- Both seeders are idempotent and will skip work if data is already present.

### Database and Data

Load terminology and generate synthetic data:

```bash
# Load SNOMED/LOINC/ICD-10/RxNorm subsets
make terminology-seed

# Generate synthetic patient cohort
make cohort-seed
```

### Testing and Linting

```bash
# Run all tests
make test

# Run linters
make lint
```

## Available Commands

See `Makefile` for complete list. Quick reference:

| Command | Description |
|---------|-------------|
| `make setup` | Install dependencies for all Python apps |
| `make dev-api` | Run smriti-api dev server (port 8000) |
| `make dev-mock-abha` | Run mock-abha dev server (port 8001) |
| `make dev-web` | Run smriti-web dev server (port 3000) |
| `make dev-fhir` | Spin up HAPI FHIR server via Docker Compose |
| `make db-migrate` | Run database migrations |
| `make cohort-seed` | Generate synthetic patient cohort |
| `make terminology-seed` | Load SNOMED/LOINC/ICD-10/RxNorm subsets |
| `make test` | Run tests for all Python packages |
| `make lint` | Run linters (ruff, black, mypy) |

## API Endpoints

### Smriti API (Port 8000)

- `GET /health` - Health check
- Additional endpoints documented in [SMRITI_PRD.md](docs/SMRITI_PRD.md) Section 5

### Mock ABHA Service (Port 8001)

- `GET /health` - Health check
- Additional endpoints documented in [SMRITI_PRD.md](docs/SMRITI_PRD.md) Section 19

## Documentation

- [SMRITI_PRD.md](docs/SMRITI_PRD.md) - Complete Product Requirements Document

## Technologies

- **Backend**: FastAPI, uvicorn, Pydantic
- **LLM Orchestration**: LangGraph, LangChain
- **LLM Provider**: Groq (with fallback to Ollama)
- **Privacy**: Presidio (anonymization)
- **FHIR Support**: fhir.resources, hl7apy
- **Database**: Supabase (PostgreSQL)
- **Frontend**: Next.js 15, TypeScript
- **Container**: Docker, Docker Compose

## Environment Variables

See `.env.example` for all required environment variables:

- `SUPABASE_URL` - Supabase Postgres connection string
- `SUPABASE_SERVICE_ROLE_KEY` - Service role API key
- `SUPABASE_ANON_KEY` - Anonymous API key
- `GROQ_API_KEY` - Groq API key for LLM access
- `OLLAMA_BASE_URL` - Ollama server URL (default: http://localhost:11434)
- `MOCK_ABHA_URL` - Mock ABHA service URL
- `MOCK_ABHA_SIGNING_KEY` - Signing key for ABHA tokens
- `SYSTEM_SALT` - Salt for hashing operations
- `FIELD_ENCRYPTION_KEY` - Base64-encoded Fernet key for field-level encryption
- `SMRITI_API_PORT` - API port (default: 8000)
- `FHIR_HOSPITAL_URL` - FHIR server URL

## Troubleshooting

### uv command not found

Ensure uv is installed: `pip install uv` or follow [installation guide](https://github.com/astral-sh/uv#installation)

### Port already in use

Change the port in the respective `make` command or `.env`:
- API: `make dev-api` → edit `SMRITI_API_PORT`
- Mock ABHA: Modify `uvicorn` command
- Web: `make dev-web` → `npm run dev -- -p 3001`

## License

[Specify your license here]

## Contributing

[Contribution guidelines]
