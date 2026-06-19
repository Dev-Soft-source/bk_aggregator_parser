# Liga Stavok adapter

Bookmaker code: `ligastavok` (Liga Stavok, TZ Table 6.1).

Ingests live line data from Liga Stavok, maps packets to normalized `Change[]`, and writes to PostgreSQL through `backend/core/apply_changes.py` — same schema and frontend as Fonbet.

## API

| Source | Endpoint | Role |
|--------|----------|------|
| HTTP snapshot | `POST …/rest/events/v8/eventsList` | Full live line; paginated with `skip` / `limit` |
| WebSocket (optional) | `wss://lds-api-sites.ligastavok.ru/ws` | JSON-RPC `subscribe` → `/notifications/v3/eventUpdated` patches |

The site no longer uses the old `GET …/line/v3/events` endpoint. All HTTP traffic goes through **Qrator** — session cookies or browser headers are required.

Configure URLs and poll interval via `backend/.env` (`LIGASTAVOK_*` variables below). All Liga Stavok code lives under `backend/ligastavok/`.

## Data flow

```text
Playwright (optional) ──► fresh Qrator cookies each poll
         │
capture.curl (headers/body) ──► HTTP POST eventsList (paginated)
                                    │
                                    ▼
                           LigastavokAdapter
                           mapper → Change[]
                                    │
                                    ▼
                           core/apply_changes.py
                                    │
                                    ▼
                           PostgreSQL (SITE_NAME=ligastavok.ru)
                                    │
                                    ▼
                           frontend /api/matches (every 3.5s)
```

**Production path:** `python main.py poll ligastavok --browser` — refreshes cookies via Chromium, polls every **3.5 seconds**, imports to DB.

WebSocket patches are supported for adapter debugging only; they are **not** merged into the poll loop yet.

## Playwright / Chrome cookie refresh

Qrator cookies copied from DevTools expire in seconds when replayed by Python. A **Playwright-launched** browser is usually **blocked** (banner: *"being controlled by automated test software"*, page *«Доступ заблокирован системой защиты»*).

**Use CDP: attach to your normal Chrome** (recommended).

### Install

```powershell
cd backend
pip install playwright
playwright install chromium
```

### CDP — attach to your Chrome (recommended)

1. Close all Chrome windows.

2. Start Chrome with remote debugging (PowerShell):

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$env:LOCALAPPDATA\liga-chrome-debug"
```

3. In **that** Chrome window, open [ligastavok.ru](https://www.ligastavok.ru) and wait until the live line loads (no block page).

4. In `backend/.env`:

```env
LIGASTAVOK_USE_PLAYWRIGHT=true
LIGASTAVOK_BROWSER_CDP_URL=http://127.0.0.1:9222
```

5. Poll (reads cookies from your open Chrome; does not show the automation banner):

```powershell
python main.py poll ligastavok --browser --curl capture.curl
```

Keep Chrome running while the poller works.

### Playwright profile (often blocked by Qrator)

```env
LIGASTAVOK_USE_PLAYWRIGHT=true
LIGASTAVOK_BROWSER_HEADLESS=false
LIGASTAVOK_BROWSER_PROFILE_DIR=.liga_browser_profile
```

If you see the Qrator block page, switch to **CDP** above.

### Enable (quick)

```env
LIGASTAVOK_USE_PLAYWRIGHT=true
LIGASTAVOK_BROWSER_HEADLESS=true
LIGASTAVOK_BROWSER_URL=https://www.ligastavok.ru
```

Or pass the flag:

```powershell
python main.py poll ligastavok --browser --curl capture.curl
```

`capture.curl` is still used for **URL, POST body, and headers** — Playwright only replaces the `Cookie` header.

| Variable | Default | Purpose |
|----------|---------|---------|
| `LIGASTAVOK_USE_PLAYWRIGHT` | `false` | Enable browser cookie refresh |
| `LIGASTAVOK_BROWSER_HEADLESS` | `true` | Headless Chromium (`false` = visible window, easier to debug) |
| `LIGASTAVOK_BROWSER_URL` | `https://www.ligastavok.ru` | Page that triggers `eventsList` |
| `LIGASTAVOK_BROWSER_TIMEOUT_SECONDS` | `60` | Wait for API / Qrator challenge |
| `LIGASTAVOK_BROWSER_REFRESH_RANGE` | `15-25` | Random refresh every N polls (N ∈ 15..25) |
| `LIGASTAVOK_BROWSER_REFRESH_EVERY` | — | Fixed refresh every N polls (overrides range if set alone) |
| `LIGASTAVOK_BROWSER_CDP_URL` | — | Attach to Chrome on port 9222 (recommended) |
| `LIGASTAVOK_BROWSER_CHANNEL` | — | `chrome` for installed Google Chrome |
| `LIGASTAVOK_BROWSER_PROFILE_DIR` | — | Playwright profile (often Qrator-blocked) |

On **403**, the adapter refreshes cookies once and retries automatically when Playwright is enabled.

## Packet → Change mapping

| Change type | Liga Stavok source |
|-------------|-------------------|
| `fixture` | `team1` / `team2`, `gameTitle`, `categoryTitle`, `tournamentTitle`, `ns`, `gameTs` |
| `score` | `scores.total`, `matchTime`, `status` |
| `betting_status` | `hasUnlocked`, `corrupted`, market `locked` |
| `odds` | `markets` type `WIN2` + outcomes `_1`, `_2` (`facId`, `value`) |

Response envelope:

```json
{
  "result": { "data": [ /* events */ ], "total": 984, "ts": 1780067434909 },
  "httpCode": 200
}
```

## Two-odds scope

Default: main 2-way line (`WIN2`), outcomes `_1` (home) and `_2` (away). Draw (`x`) is skipped.

Liga Stavok uses its own `facId` values. On DB import, odds are normalized to factor IDs **921** (home) and **923** (away) so the existing frontend works unchanged.

```env
LIGASTAVOK_MAIN_MARKET_TYPE=WIN2
LIGASTAVOK_OUTCOME_KEYS=_1,_2
```

Frontend:

```env
ODDS_FACTOR_IDS=921,923
```

## Quick start (poll → DB → UI)

### 1. Backend `.env`

```env
SITE_NAME=ligastavok.ru
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/booker_adapter
LIGASTAVOK_CURL_FILE=capture.curl
LIGASTAVOK_LIVE_ALL_SPORTS=true
LIGASTAVOK_POLL_INTERVAL_SECONDS=1.5
```

### 2. Capture session from browser

1. Open [ligastavok.ru](https://www.ligastavok.ru/) → **Live**.
2. DevTools → **Network** → filter `eventsList`.
3. Right-click the `POST …/events/v8/eventsList` request → **Copy → Copy as cURL**.
4. Save to `backend/capture.curl`.

The file must include:

- `--data-raw '{...}'` (request body), and
- `-b '…'` cookies **or** a `Cookie:` header (recommended; cookies expire in minutes).

Both **bash** and **Windows cmd** cURL formats (`^"` escapes) are supported.

Alternatively, paste cookies into `.env`:

```env
LIGASTAVOK_COOKIE=qrator_jsid2=...; cfidsgib-w-ligastavok=...
```

### 3. Run poller

**With Playwright (recommended for 24/7 poll):**

```powershell
cd backend
python main.py poll ligastavok --browser --curl capture.curl
```

**Manual cookies only (expires quickly):**

```powershell
python main.py poll ligastavok --curl capture.curl
```

One cycle for testing:

```powershell
python main.py poll ligastavok --once --curl capture.curl
```

Expected output:

```text
[1] snapshot ts=… fixtures=159 … db_matches=159 db_odds=80
  imported snapshot_id=8584 matches=159 odds=80
```

### 4. Frontend

```powershell
cd frontend
# .env.local: DATABASE_URL, SITE_NAME=ligastavok.ru, ODDS_FACTOR_IDS=921,923
npm run dev
```

Dashboard polls `/api/matches` every **3500 ms** (`NEXT_PUBLIC_POLL_INTERVAL_MS=3500`).

Run poller and frontend in two terminals for live review.

## CLI reference

All commands run from `backend/`:

| Command | Description |
|---------|-------------|
| `python main.py poll ligastavok --browser` | Poll with Playwright cookie refresh |
| `python main.py poll ligastavok --once` | Single poll cycle |
| `python main.py poll ligastavok -o ligastavok/ligastavok.json` | Poll + optional JSON backup each tick |
| `python main.py fetch ligastavok --curl capture.curl -o ligastavok/ligastavok.json` | One-shot HTTP fetch to file |
| `python main.py adapter ligastavok [file.json]` | Map snapshot to `Change[]` (no DB) |
| `python main.py adapter ligastavok --live --once` | WebSocket patches (needs cookies) |

Useful flags:

| Flag | Purpose |
|------|---------|
| `--curl capture.curl` | DevTools cURL file (overrides `LIGASTAVOK_CURL_FILE`) |
| `--interval 3.5` | Poll interval in seconds |
| `--live-all` / `--no-live-all` | All live sports vs single `gameId` from curl body |
| `--site-name ligastavok.ru` | DB site label (default: `SITE_NAME` env) |

### Live-all sports mode

When `LIGASTAVOK_LIVE_ALL_SPORTS=true` (default), the adapter:

- strips `gameId` from the POST body,
- sets `ns: live`,
- paginates with `skip` until `total` is reached (`LIGASTAVOK_SNAPSHOT_MAX_PAGES=0` = no page cap).

This mirrors Fonbet `place=live` across all sports.

Single sport only:

```powershell
python main.py fetch ligastavok --curl capture.curl --no-live-all -o ligastavok/mma.json
```

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `LIGASTAVOK_SNAPSHOT_URL` | `…/events/v8/eventsList` | HTTP snapshot endpoint |
| `LIGASTAVOK_CURL_FILE` | — | Path to DevTools cURL export |
| `LIGASTAVOK_COOKIE` | — | Session cookies (fallback if curl has no `-b`) |
| `LIGASTAVOK_SNAPSHOT_BODY` | — | POST JSON body if missing from curl |
| `LIGASTAVOK_POLL_INTERVAL_SECONDS` | `1.5` | Poll loop interval |
| `LIGASTAVOK_LIVE_ALL_SPORTS` | `true` | All live sports + pagination |
| `LIGASTAVOK_SNAPSHOT_LIMIT` | `160` | Page size (higher = fewer HTTP calls) |
| `LIGASTAVOK_SNAPSHOT_PARALLEL` | `true` | Fetch extra pages in parallel |
| `LIGASTAVOK_SNAPSHOT_PARALLEL_WORKERS` | `6` | Parallel HTTP workers |
| `LIGASTAVOK_JSON_PRETTY` | `false` | Compact JSON (much faster writes) |
| `LIGASTAVOK_PROFILE` | `false` | Log fetch/cycle timings |
| `LIGASTAVOK_SNAPSHOT_MAX_PAGES` | `0` | Max pages (`0` = fetch all) |
| `LIGASTAVOK_MAIN_MARKET_TYPE` | `WIN2` | Main market filter |
| `LIGASTAVOK_OUTCOME_KEYS` | `_1,_2` | Outcome keys to ingest |
| `LIGASTAVOK_WS_URL` | `wss://…/ws` | WebSocket URL (adapter debug) |
| `LIGASTAVOK_USE_PLAYWRIGHT` | `false` | Playwright cookie refresh |
| `LIGASTAVOK_BROWSER_HEADLESS` | `true` | Headless browser |
| `LIGASTAVOK_BROWSER_URL` | `…/` | Page loaded for cookies |
| `LIGASTAVOK_BROWSER_TIMEOUT_SECONDS` | `60` | Browser wait timeout |
| `LIGASTAVOK_BROWSER_REFRESH_RANGE` | `15-25` | Random N polls between refreshes |
| `LIGASTAVOK_BROWSER_REFRESH_EVERY` | — | Fixed N polls (optional) |
| `SITE_NAME` | `ligastavok.ru` | Bookmaker label in PostgreSQL |

See `backend/.env.example` for the full list.

## Performance

Typical ~1s cycle breakdown:

| Step | Before | After (defaults) |
|------|--------|------------------|
| HTTP (3× sequential pages @80) | ~900ms | ~350ms (1 page @160 or parallel) |
| JSON write (35k lines indented) | ~300–800ms | ~50ms (compact) |
| DB import | ~100–200ms | same |

**Already enabled in defaults:**

```env
LIGASTAVOK_SNAPSHOT_LIMIT=160
LIGASTAVOK_SNAPSHOT_PARALLEL=true
LIGASTAVOK_SNAPSHOT_PARALLEL_WORKERS=6
# compact JSON (default)
LIGASTAVOK_JSON_PRETTY=false
```

**Measure timings:**

```env
LIGASTAVOK_PROFILE=true
```

Shows `fetch_snapshot: N page(s) in Xms` and `cycle: Xms` per poll.

**Further tuning:**

- `LIGASTAVOK_SNAPSHOT_LIMIT=200` — single HTTP call if total events &lt; 200
- `--no-json` — skip file write if you only need DB + frontend
- Keep CDP Chrome open — cookie read is instant (no page reload between refreshes)

## Troubleshooting

### Block page: «Доступ заблокирован системой защиты»

Qrator detected **automation** (Playwright). Do **not** use `LIGASTAVOK_BROWSER_PROFILE_DIR` for this site.

Use **CDP** with your real Chrome (see above), or refresh `capture.curl` manually from DevTools.

### 403 Forbidden — session expired

Cookies (`qrator_jsid2`, `cfidsgib-w-ligastavok`, …) expire quickly.

1. Refresh [ligastavok.ru](https://www.ligastavok.ru/) in the browser.
2. Copy a fresh `eventsList` request as cURL → overwrite `backend/capture.curl`.
3. Confirm `-b '…'` or `LIGASTAVOK_COOKIE` is set.
4. Test: `python main.py poll ligastavok --once --curl capture.curl`

### `Could not find URL in curl file`

Chrome on Windows exports cmd-style cURL (`^"` escapes). The parser handles this — if you still see this error, re-copy the request or use **Copy as cURL (bash)**.

### Empty frontend

- Poller running? `python main.py poll ligastavok --curl capture.curl`
- `SITE_NAME=ligastavok.ru` in both `backend/.env` and `frontend/.env.local`?
- Frontend dev server restarted after env change?

### 502 / 503 during pagination

Transient server errors are retried; partial pages are merged when possible. The next poll tick refreshes the full snapshot.

## Module layout

```text
ligastavok/
  adapter.py         # LigastavokAdapter — poll, WS, health
  mapper.py          # snapshot → Change[]
  api.py             # HTTP client, cURL parser, pagination
  poll.py            # Poll loop → PostgreSQL
  browser_session.py # Playwright Qrator cookie refresh
  fetch_snapshot.py  # One-shot fetch CLI
  run_adapter.py     # Adapter CLI (no DB)
  snapshot_body.py   # Live-all POST body builder
  config.py          # LigastavokApiConfig
  odds_config.py     # 2-odds filter
  patch.py           # JSON Patch applier (WS)
  ws.py              # WebSocket client
  ligastavok.json    # Sample snapshot
  tests/

core/
  apply_changes.py   # Change[] → PostgreSQL (shared with future adapters)
```

### WebSocket 403 Forbidden

Qrator **blocks Python WebSocket handshakes** even when HTTP cookies work. With `--browser` / CDP, the poller **does not open its own WebSocket** — it reads frames from Chrome's connection on `https://www.ligastavok.ru`.

Fix:

1. CDP Chrome on **https://www.ligastavok.ru** (line loaded).
2. Restart poll: `python main.py poll ligastavok --browser --curl capture.curl`
3. Look for:
   - `Listening for browser WebSocket frames`
   - `Browser WebSocket connected: wss://…`
   - `(ws)` imports in poll log

On first run the poller may reload the live page once so Playwright can attach (connections opened before attach are invisible).

Without `--browser`, set `LIGASTAVOK_WS_ENABLED=false` — scores/timers still update via HTTP + client-side timer tick, but slower.

## WebSocket (live scores & timers)

The HTTP `eventsList` snapshot often repeats the same `matchTime`/score for many polls while odds change. With `--browser`, the poll loop **taps Chrome's WebSocket** for live patches between HTTP fetches.

1. HTTP snapshot → bootstrap `events_by_id`
2. WebSocket subscribe (same cookies as HTTP)
3. JSON Patch updates → re-map to `Change[]` → PostgreSQL
4. Frontend ticks minute clocks locally between refreshes (`timer_seconds` + `timer_updated_at`)

Debug adapter-only (no DB):

```powershell
python main.py adapter ligastavok ligastavok/ligastavok.json --live --once --max-events 10
```

Requires valid session cookies in `capture.curl` or `LIGASTAVOK_COOKIE`.

## Tests

```powershell
cd backend
python -m unittest discover -s ligastavok/tests -v
```

Covers mapper, cURL parser (bash + Windows cmd), snapshot body builder, and API helpers.
