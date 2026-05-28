# Fonbet adapter

Bookmaker code: `fonbet` (TZ Table 6.1).

## API

| Endpoint | Role |
|----------|------|
| `listLight?place=live&scopeMarket=1600` | Full live snapshot; sets `packetVersion` |
| `list?version={packetVersion}&scopeMarket=1600` | Delta updates only |

Configure URLs via `backend/.env` (`FONBET_LIST_LIGHT_URL`, `FONBET_LIST_URL_BASE`, `POLL_INTERVAL_SECONDS`). All Fonbet code lives under `backend/fonbet/`.

## Packet fields

| Field | Adapter mapping |
|-------|-----------------|
| `sports` (kind=sport) | `SportRef` |
| `sports` (kind=segment) | `TournamentRef` + country parse |
| `events` (level=1) | `EventRef` / `ChangeType.FIXTURE` |
| `eventMiscs` | `ChangeType.SCORE` |
| `liveEventInfos` | `ChangeType.SCORE` (timer, subscores) |
| `eventBlocks` | `ChangeType.BETTING_STATUS` |
| `customFactors` | `ChangeType.ODDS` |

## Fonbet-specific notes

- `sportId` on an event is the **league segment id**, not the root sport id.
- `factor_id` (`f`) is numeric; UOF `market_id` mapping is a core concern (Appendix C).
- Delta packets (`fromVersion` > 0) may omit sports in `events[]`; scores still update via `liveEventInfos`.
- Pass `known_match_ids` when consuming deltas so odds/scores apply to matches already in core/DB.

## Usage

```powershell
cd backend

# Phase 0 setup (DB + schema + sample import)
python main.py setup

# Import JSON file
python main.py import fonbet/test.json --init-schema

# Poll live API → PostgreSQL
python main.py poll

# Adapter (map packet, no DB)
python main.py adapter fonbet/test.json
python main.py adapter --live --once

# Shortcuts
python main.py fonbet/test.json          # same as import
python main.py --poll                    # same as poll (legacy)
```

## Module layout

```
fonbet/
  api.py              # HTTP listLight / list
  adapter.py          # FonbetAdapter — poll + health
  mapper.py           # packet → Change DTOs
  importer.py         # PostgreSQL import
  poll.py             # poll loop
  parsers.py          # country/league/match parsing
  sports_reference.py # Appendix A mapping
  config.py           # FonbetApiConfig
  test.json           # sample delta packet
  Appendix_A_sports_EN.md
```
