# Betcity live WebSocket

Bookmaker code: `betcity` · site: `betcity.ru`  
Package path: `backend/betcity_live/`

Live odds stream over:

```text
wss://sc.betcity.ru/?id=live&csn=<token>
```

## What works now

| Layer | Status |
|-------|--------|
| `listen` — dump raw WS frames | Yes (browser default for poll; `--direct` for Python WS) |
| CDP Chrome tap + proxy | Yes (port **9224**, auto-start on poll) |
| HTTP catalog (`ad.betcity.ru/d/on_air/events`) for names | Yes |
| Incremental state + mapper → `Change[]` | Yes (`Wm` P1/P2 → 921/923) |
| `poll` → PostgreSQL via `core.apply_changes` | Yes (always `betcity.ru`) |
| Alias cleanup (`betcity.` → `betcity.ru`) | Yes (on poll start) |
| Keep only current live matches + 1 snapshot | Yes (prunes finished events each poll) |

## Direct mode

No Chrome — Python connects to the WebSocket itself:

```powershell
cd backend
python main.py poll betcity --direct
python main.py listen betcity --direct --seconds 30 --save
```

## Browser mode (default for poll)

`python main.py poll betcity` opens CDP Chrome (port **9224**), loads the live page, then **keeps tapping** `sc.betcity.ru` frames while Chrome stays open.

```powershell
cd backend
python main.py poll betcity
```

With proxy:

```powershell
cd backend
$env:BETCITY_PROXY = "1.2.3.4:8080"
.\scripts\start_chrome_cdp_betcity.ps1   # optional; poll also auto-starts Chrome
python main.py poll betcity --proxy 1.2.3.4:8080
```

Leave the Chrome window open. Poll continues the socket tap automatically. If frames stop, press **F5** once on the live page.

```env
SITE_NAME=betcity.ru
BETCITY_WS_URL=wss://sc.betcity.ru/?id=live&csn=ooca9s
BETCITY_ORIGIN=https://betcity.ru
BETCITY_CATALOG_URL=https://ad.betcity.ru/d/on_air/events
BETCITY_BROWSER_CDP_URL=http://127.0.0.1:9224
BETCITY_BROWSER_URL=https://betcity.ru/ru/live
# BETCITY_USE_BROWSER=true
# BETCITY_PROXY=1.2.3.4:8080
# BETCITY_COOKIE=...
BETCITY_POLL_INTERVAL_SECONDS=3.5
BETCITY_ODDS_FACTOR_IDS=921,923
```

## Capture cookie (optional, direct mode)

Direct WS often works without a cookie. If you get 403:

1. Open [https://betcity.ru/](https://betcity.ru/) → DevTools → Network → WS
2. Copy Request URL (`csn=…`) and Cookie
3. Put them in `backend/.env` as `BETCITY_COOKIE`

## Frame shape (observed)

- `type=1` → `reply.sports` — championships / events / scores / timers (no team names)
- `type=2` → `reply.main` — markets; market `69` block `Wm` with `P1`/`P2`/`X` and `kf` odds
- HTTP catalog (`/d/on_air/events`) → `name_ht` / `name_at` / `name_ch` / `name_sp`
- Scores: prefer HTTP on-air catalog (`sc_ev` / `sc_ev_cmx`); WS sports deltas are often incomplete
- Betting state: main market `Wm` / P1·P2 `st` (`2`=open, `1`=locked) — not catalog `status_ev`

## Tests

```powershell
cd backend
python -m unittest discover -s betcity_live/tests -v
```

## Next improvements

1. Optionally merge prematch catalog (`/d/off/events`) for upcoming fixtures
2. Map more sports cleanly (tennis set scores vs football)
3. Authenticated proxy support via Chrome extension if needed
