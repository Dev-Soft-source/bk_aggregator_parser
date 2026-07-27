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
| `eventBlocks` | `ChangeType.BETTING_STATUS` (override). Missing → default `unblocked` for every fixture |
| `customFactors` | `ChangeType.ODDS` |

## Fonbet-specific notes

- `sportId` on an event is the **league segment id**, not the root sport id.
- `factor_id` (`f`) is numeric; UOF `market_id` mapping is a core concern (Appendix C).
- Delta packets (`fromVersion` > 0) may omit sports in `events[]`; scores still update via `liveEventInfos`.
- Pass `known_match_ids` when consuming deltas so odds/scores apply to matches already in core/DB.
- `place=notActive` without `willBeLive` = left live board (finished for prune); with `willBeLive` = upcoming linger (not persisted until `live`).
- Suspended selections use `v=0` — importer/mapper **skip** those rows so last odds stay.
- Soft-finished lingerers (football FT blocked @90', esports at match length) are deleted even while Fonbet still sends `place=live`.
- Poll refreshes with `listLight` every `FONBET_SNAPSHOT_EVERY` ticks (default 20) so matches that left the feed are pruned.
- Prematch `place=line` rows with `start_time` already past are deleted each poll (`FONBET_LINE_PAST_GRACE_HOURS`, default `0`).
- Lifecycle helpers: `fonbet/lifecycle.py`. Audit: `docs/acceptance/fonbet_audit.md`.

## Usage

```powershell
cd backend

# Phase 0 setup (DB + schema + sample import)
python main.py setup

# Import JSON file
python main.py import fonbet/test.json --init-schema

# Poll live API → PostgreSQL
python main.py poll fonbet

# Adapter (map packet, no DB)
python main.py adapter fonbet/test.json
python main.py adapter --live --once

# Shortcuts
python main.py fonbet/test.json          # same as import
python main.py --poll                    # same as poll (legacy)
```

## Retention

Live poll keeps **current live data only**:

- On each full `listLight` snapshot, `place=live` matches no longer in the active live set are deleted
- Finished / `notActive` rows are not written; prior live rows are pruned
- Import snapshots collapse to the latest one (no historical pile-up)

## Module layout

```
fonbet/
  api.py              # HTTP listLight / list
  adapter.py          # FonbetAdapter — poll + health
  mapper.py           # packet → Change DTOs
  importer.py         # PostgreSQL import
  lifecycle.py        # place/finish/suspend helpers (Track B2)
  poll.py             # poll loop
  parsers.py          # country/league/match parsing
  sports_reference.py # Appendix A mapping (pre-B3)
  odds_config.py      # main-line factor ids (921/922/923)
  config.py           # FonbetApiConfig
  test.json           # sample delta packet
  tests/
```

Acceptance docs: `docs/acceptance/fonbet_audit.md`, `fonbet_lifecycle.md`.
