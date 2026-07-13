
<<<<<<< HEAD
A bookmaker line parsing system for ingesting live sports data from bookmaker sites, normalizing it into a canonical model, and reviewing it in a web UI. The current focus is the **CORE layer** plus a **review frontend** — partner delivery (AMQP, multi-tenant HTTP API) is planned for a later phase.

The first supported bookmaker is **Fonbet** (`fonbet.com`). The architecture is designed so additional bookmakers can be added as separate adapter packages without changing core contracts.

## What it does

| Layer | Role |
|-------|------|
| **Parser adapters** | Fetch raw line data from bookmaker APIs and map packets to normalized `Change` events |
| **Core / persistence** | Store matches, scores, betting status, and odds in PostgreSQL (`booker_adapter`) |
| **Review frontend** | Next.js dashboard to browse live matches, scores, and odds in near real time |

**Current scope:** ingest **two odds per match** (main 2-way line; default Fonbet factors `921` home + `923` away). Full market trees and partner delivery are out of scope for this phase.

## Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│  Bookmaker sites (Fonbet, …)                                  │
└────────────────────────────┬─────────────────────────────────┘
                             │ public line API
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Adapter layer  (backend/fonbet/, backend/adapters/)          │
│  listLight snapshot → list deltas → Change[]                  │
└────────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  PostgreSQL  (booker_adapter)                                 │
│  sites · sports · matches · scores · odds_lines · …         │
└────────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Review frontend  (Next.js, frontend/)                       │
│  Polls /api/matches every few seconds                         │
└──────────────────────────────────────────────────────────────┘
```

**Target rule:** adapters emit `Change[]`; core owns all database writes. The live poll path still uses `fonbet/importer.py` today; a dedicated `backend/core/` ingestion package is on the roadmap (see [WORKFLOW.md](WORKFLOW.md)).

## Prerequisites

- **Python** 3.11+ (3.13 tested)
- **Node.js** 20+ and npm
- **PostgreSQL** 14+

## Quick start

### 1. Database

Create the `booker_adapter` database:

```powershell
psql -U postgres -d postgres -f backend/scripts/create_database.sql
```

Or run `CREATE DATABASE booker_adapter;` manually. Details: [docs/DATABASE.md](docs/DATABASE.md).

### 2. Backend

```powershell
cd backend
copy .env.example .env
# Edit DATABASE_URL and other settings in .env

pip install -r requirements.txt
python main.py setup
```

`setup` initializes the schema, imports sample data from `fonbet/test.json`, and verifies the database.

### 3. Frontend

```powershell
cd frontend
copy .env.local.example .env.local
# Use the same DATABASE_URL as backend

npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### 4. Live data (daily use)

Run in two terminals:

```powershell
# Terminal 1 — poll Fonbet live API → PostgreSQL
cd backend
python main.py poll fonbet
# also works: python main.py poll

# Terminal 2 — review UI
cd frontend
npm run dev
```

## Backend CLI

All commands run from `backend/`:

| Command | Description |
|---------|-------------|
| `python main.py setup` | Phase 0: schema + sample import + verification |
| `python main.py import <file.json>` | Import a Fonbet JSON packet (`--init-schema`, `--migrate` optional) |
| `python main.py poll fonbet` | Poll Fonbet live API and write to PostgreSQL |
| `python main.py adapter <file.json>` | Map packet to `Change[]` without touching the DB |
| `python main.py adapter --live --once` | Fetch one live packet and print changes |

Legacy shortcuts: `python main.py fonbet/test.json` (import), `python main.py --poll` (poll).

### Tests

```powershell
cd backend
python -m unittest discover -s fonbet/tests -v
```

### Adapter-only debug (no database)

```powershell
cd backend
python main.py adapter fonbet/test.json
python main.py adapter --live --once
```

Fonbet-specific API notes and module layout: [backend/fonbet/README.md](backend/fonbet/README.md).

## Frontend API

The Next.js app exposes read-only routes backed by PostgreSQL:

| Endpoint | Description |
|----------|-------------|
| `GET /api/matches?place=live` | Live matches with scores and odds |
| `GET /api/matches?place=line` | Pre-match |
| `GET /api/matches?place=all` | All places |

More detail: [frontend/README.md](frontend/README.md).

## Configuration

### Backend (`backend/.env`)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `SITE_NAME` | Bookmaker site label (default `fonbet.com`) |
| `FONBET_ODDS_FACTOR_IDS` | Two factor IDs to ingest (default `921,923`) |
| `FONBET_LIST_LIGHT_URL` | Fonbet snapshot endpoint |
| `FONBET_LIST_URL_BASE` | Fonbet delta endpoint base URL |
| `POLL_INTERVAL_SECONDS` | Poll loop interval |
| `RETAIN_SNAPSHOT_YEARS` | Audit snapshot retention |

### Frontend (`frontend/.env.local`)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Same database as backend |
| `SITE_NAME` | Site filter |
| `ODDS_FACTOR_IDS` | Factor IDs shown in the UI |
| `NEXT_PUBLIC_POLL_INTERVAL_MS` | UI refresh interval (default `5000`) |

Do not commit `.env` or `.env.local`.

## Project structure

```text
bk_aggregator_parser/
├── backend/
│   ├── main.py              # CLI entry point
│   ├── config.py            # DatabaseConfig
│   ├── db.py                # Connection, schema helpers
│   ├── schema.sql           # PostgreSQL DDL
│   ├── adapters/            # Shared Change DTOs and adapter protocol
│   ├── fonbet/              # Fonbet adapter, mapper, poll, importer
│   └── scripts/             # DB creation, Phase 0 setup
├── frontend/                # Next.js review UI
├── docs/
│   ├── DATABASE.md          # Database setup guide
│   └── REVIEW.md            # Project walkthrough
├── WORKFLOW.md              # Development phases and architecture target
├── TODO.md                  # Executable checklist
└── TZ_bookmaker_parsing_COMPLETE_EN.md   # Full client spec (reference)
```

## Documentation

| Document | Contents |
|----------|----------|
| [WORKFLOW.md](WORKFLOW.md) | Phases A–G, architecture target, quality gates |
| [TODO.md](TODO.md) | Step-by-step tasks and checklists |
| [docs/DATABASE.md](docs/DATABASE.md) | `booker_adapter` setup and schema overview |
| [docs/REVIEW.md](docs/REVIEW.md) | Codebase walkthrough before coding |
| [TZ_bookmaker_parsing_COMPLETE_EN.md](TZ_bookmaker_parsing_COMPLETE_EN.md) | Full technical specification (future phases) |
| [Appendix_A_sports_EN.md](Appendix_A_sports_EN.md) | 207 sports → `sr:sport:N` reference |
| [Appendix_C_markets_EN.md](Appendix_C_markets_EN.md) | Market definitions (incremental mapping) |

## Roadmap (this phase)

1. **Fonbet adapter** — stable `listLight` + delta streaming with tests
2. **Core ingestion** — single write path from `Change[]` to PostgreSQL
3. **URN / market mapping** — `payload_id` ↔ URN, subset of `market_id`
4. **Core read API** — dedicated HTTP API for the frontend
5. **Review UI** — site selector, match detail, mapping status
6. **Second bookmaker** (optional) — new folder under `backend/<bookmaker>/`

Out of scope until CORE is stable: RabbitMQ unified feed, partner HTTP API, arbitrage, admin panel, multi-tenant delivery. See [WORKFLOW.md](WORKFLOW.md) §5.

## License

Not specified in the repository. Add a license file if you intend to distribute this project.
=======
>>>>>>> 5f63ea7431d30b7820e899815f804b3ccdfa7cb2
