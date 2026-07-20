A bookmaker line parsing system that ingests live and pre-match sports data from bookmaker sites, normalizes it into a canonical model in PostgreSQL, and reviews it in a web UI.

Supported bookmakers (each as its own adapter package under `backend/`):

| Bookmaker | Live | Line (prematch) | Site name |
|-----------|------|-----------------|-----------|
| **Fonbet** | `python main.py poll fonbet` | same poll (`place` from packet) | `fonbet.com` |
| **Liga Stavok** | `python main.py poll ligastavok-live` | `python main.py poll ligastavok-line` | `ligastavok.ru` |
| **Bet365** | `python main.py poll bet365` | `python main.py poll bet365-line` | `bet365.com` |
| **Betcity** | `python main.py poll betcity-live` | `python main.py poll betcity-line` | `betcity.ru` |
| **1xBet** | `python main.py poll lxbet-live` | `python main.py poll lxbet-line` | `1xbet.com` |

Partner delivery (AMQP, multi-tenant HTTP API) is planned for a later phase — see [docs/WORKFLOW.md](docs/WORKFLOW.md).

## What it does

| Layer | Role |
|-------|------|
| **Parser adapters** | Fetch raw line data (HTTP / WebSocket / browser CDP) and map packets to normalized `Change` events |
| **Core / persistence** | Store matches, scores, betting status, and odds in PostgreSQL (`booker_adapter`) |
| **Review frontend** | Next.js dashboard — filter by site and place (`live` / `line`), scores, odds, betting state |

**Odds scope:** ingest main line outcomes (typically factors `921` / `922` / `923` for 1 / X / 2). Full market trees and partner delivery are out of scope for this phase.

### Betting status (Fonbet)

- Every fixture gets a `betting_status` row: `eventBlocks` overrides when present, otherwise default **`unblocked`**.
- Odds-only delta packets also write status, so line matches do not show `—` in the UI after odds updates.
- UI shows `Unblocked` / `Blocked` / `Partial`, or `—` when no status row exists yet.

## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│  Bookmaker sites (Fonbet, Liga Stavok, Bet365, Betcity, 1xBet)   │
└───────────────────────────────┬─────────────────────────────────┘
                                │ HTTP / WS / CDP+ZAP
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Adapter packages  (backend/<bookmaker>/)                         │
│  snapshot / deltas / sockets → Change[] or direct DB import     │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PostgreSQL  (booker_adapter)                                     │
│  sites · sports · matches · match_scores · odds_lines ·           │
│  betting_status · …                                               │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Review frontend  (Next.js, frontend/)                           │
│  Polls /api/matches · site selector · place=live|line|all         │
└─────────────────────────────────────────────────────────────────┘
```

**Target rule:** adapters emit `Change[]`; core owns DB writes. Fonbet’s live poll path still uses `fonbet/importer.py` today; a shared `backend/core/` write path is on the roadmap.

## Prerequisites

- **Python** 3.11+ (3.13 tested)
- **Node.js** 20+ and npm
- **PostgreSQL** 14+
- **Chrome with CDP** for Bet365 / Liga Stavok / Betcity browser-assisted sessions (see adapter READMEs)

## Quick start

### 1. Database

```sql
CREATE DATABASE booker_adapter;
```

Details: [docs/DATABASE.md](docs/DATABASE.md). Schema is applied by `python main.py setup` (or `--init-schema` / `--migrate` on import/poll).

### 2. Backend

```powershell
cd backend
copy .env.example .env
# Edit DATABASE_URL, SITE_NAME, and bookmaker-specific settings

pip install -r requirements.txt
python main.py setup
```

`setup` initializes the schema, imports sample Fonbet data from `fonbet/test.json`, and verifies the database.

### 3. Frontend

```powershell
cd frontend
copy .env.local.example .env.local
# Same DATABASE_URL as backend; SITE_NAME filters the default site

npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Use the site selector for Fonbet, Liga Stavok, Bet365, Betcity, or 1xBet.

### 4. Live data (daily use)

Run a poller for each bookmaker you care about, plus the UI:

```powershell
# Terminal 1 — example: Fonbet
cd backend
python main.py poll fonbet

# Terminal 2 — review UI
cd frontend
npm run dev
```

Other pollers (separate terminals / hosts as needed):

```powershell
python main.py poll ligastavok-live
python main.py poll ligastavok-line
python main.py poll bet365          # Chrome CDP port 9223
python main.py poll bet365-line     # Chrome CDP port 9225
python main.py poll betcity-live    # Chrome CDP (default); alias: betcity
python main.py poll betcity-line
python main.py poll lxbet-live
python main.py poll lxbet-line
```

Bet365 CDP helpers:

```powershell
cd backend
.\scripts\start_chrome_cdp_bet365.ps1       # live → 9223
.\scripts\start_chrome_cdp_bet365_line.ps1  # line → 9225
```

## Backend CLI

All commands run from `backend/`:

| Command | Description |
|---------|-------------|
| `python main.py setup` | Phase 0: schema + sample import + verification |
| `python main.py import <file.json>` | Import a Fonbet JSON packet |
| `python main.py poll <bookmaker>` | Poll and write to PostgreSQL (see table above) |
| `python main.py adapter <file.json>` | Map Fonbet packet to `Change[]` (no DB) |
| `python main.py adapter ligastavok …` | Liga Stavok adapter debug |
| `python main.py fetch ligastavok` | Download Liga Stavok snapshot JSON |
| `python main.py listen bet365 \| betcity` | Stream WebSocket frames (debug) |
| `python main.py capture bet365` | Capture Bet365 `uid` + cookie from CDP Chrome |

Legacy shortcuts: `python main.py fonbet/test.json` (import), `python main.py --poll` (Fonbet poll).

### Tests

```powershell
cd backend
python -m unittest discover -s fonbet/tests -v
python -m unittest discover -s bet365/tests -v
# other adapters ship tests under backend/<adapter>/tests/
```

### Adapter docs

| Package | README |
|---------|--------|
| Fonbet | [backend/fonbet/README.md](backend/fonbet/README.md) |
| Liga Stavok live | [backend/ligastavok_live/README.md](backend/ligastavok_live/README.md) |
| Liga Stavok line | [backend/ligastavok_line/README.md](backend/ligastavok_line/README.md) |
| Bet365 live | [backend/bet365/README.md](backend/bet365/README.md) |
| Bet365 line | [backend/bet365_line/README.md](backend/bet365_line/README.md) |
| Betcity live | [backend/betcity_live/README.md](backend/betcity_live/README.md) |
| Betcity line | [backend/betcity_line/README.md](backend/betcity_line/README.md) |
| 1xBet live | [backend/lxbet_live/README.md](backend/lxbet_live/README.md) |
| 1xBet line | [backend/lxbet_line/README.md](backend/lxbet_line/README.md) |

## Frontend API

| Endpoint | Description |
|----------|-------------|
| `GET /api/matches?place=live` | Live matches with scores and odds |
| `GET /api/matches?place=line` | Pre-match |
| `GET /api/matches?place=all` | All places |
| `GET /api/matches?site=fonbet.com` | Filter by site (`all` for every site) |

More detail: [frontend/README.md](frontend/README.md).

## Configuration

### Backend (`backend/.env`)

Copy from [backend/.env.example](backend/.env.example). Common variables:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `SITE_NAME` | Default site label for imports (`fonbet.com`, `bet365.com`, …) |
| `FONBET_ODDS_FACTOR_IDS` | Factor IDs to ingest (default `921,922,923`) |
| `FONBET_LIST_LIGHT_URL` / `FONBET_LIST_URL_BASE` | Fonbet snapshot / delta endpoints |
| `POLL_INTERVAL_SECONDS` | Default poll interval (Fonbet) |
| `RETAIN_SNAPSHOT_YEARS` | Audit snapshot retention |

Bookmaker-specific blocks (Bet365 CDP, Liga Stavok cookies, Betcity WS, 1xBet URLs, etc.) are documented in `.env.example` and each adapter README.

### Frontend (`frontend/.env.local`)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Same database as backend |
| `SITE_NAME` | Default site filter |
| `ODDS_FACTOR_IDS` | Factor IDs shown in the UI (`921,922,923`) |
| `NEXT_PUBLIC_POLL_INTERVAL_MS` | UI refresh interval |

Do not commit `.env` or `.env.local`.

## Project structure

```text
bk_aggregator_parser/
├── backend/
│   ├── main.py                 # CLI entry point
│   ├── config.py / db.py       # DB config and helpers
│   ├── schema.sql              # PostgreSQL DDL
│   ├── adapters/               # Shared Change DTOs
│   ├── core/                   # Shared apply_changes helpers
│   ├── fonbet/                 # Fonbet HTTP poll + importer
│   ├── ligastavok_live/        # Liga Stavok live (self-contained)
│   ├── ligastavok_line/        # Liga Stavok prematch (self-contained)
│   ├── bet365/                 # Bet365 live ZAP + CDP
│   ├── bet365_line/            # Bet365 prematch (#/AO/, #/AS/)
│   ├── betcity_live/           # Betcity live WS
│   ├── betcity_line/           # Betcity prematch HTTP
│   ├── lxbet_live/ / lxbet_line/
│   └── scripts/                # CDP Chrome launchers, Phase 0 setup
├── frontend/                   # Next.js review UI
└── docs/                       # Specs, workflow, DB guide
```

## Documentation

| Document | Contents |
|----------|----------|
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Phases, architecture target, quality gates |
| [docs/TODO.md](docs/TODO.md) | Step-by-step tasks |
| [docs/DATABASE.md](docs/DATABASE.md) | `booker_adapter` setup and schema overview |
| [docs/REVIEW.md](docs/REVIEW.md) | Codebase walkthrough |
| [docs/TZ_bookmaker_parsing_COMPLETE_EN.md](docs/TZ_bookmaker_parsing_COMPLETE_EN.md) | Full technical specification |
| [docs/Appendix_A_sports_EN.md](docs/Appendix_A_sports_EN.md) | Sports → `sr:sport:N` reference |
| [docs/Appendix_C_markets_EN.md](docs/Appendix_C_markets_EN.md) | Market definitions |

## Roadmap (this phase)

1. Stable multi-bookmaker pollers with tests
2. Shared core ingestion from `Change[]` for all adapters
3. URN / market mapping (`payload_id` ↔ URN, Appendix C subset)
4. Dedicated core read API for the frontend
5. Review UI polish (detail views, mapping status)

Out of scope until CORE is stable: RabbitMQ unified feed, partner HTTP API, arbitrage, admin panel, multi-tenant delivery. See [docs/WORKFLOW.md](docs/WORKFLOW.md).

## License

Not specified in the repository. Add a license file if you intend to distribute this project.
