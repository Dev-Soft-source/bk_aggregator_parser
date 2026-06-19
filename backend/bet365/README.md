# Bet365 ZAP WebSocket

Bet365 live odds use a **proprietary ZAP protocol** on:

```text
wss://premws-pt1.365lpodds.com/zap/?uid=<random_digits>
```

Your example:

```text
wss://premws-pt1.365lpodds.com/zap/?uid=3528489557161243
```

The `uid` is required in the URL, but **not sufficient alone** — Qrator returns **HTTP 403** without a valid browser session (`pstk` cookie + handshake).

## Capture uid automatically (like Liga Stavok CDP)

Bet365 generates a **new random `uid`** when the browser opens the ZAP socket. You can capture it from Chrome instead of DevTools copy-paste.

### 1. Start CDP Chrome (port **9223** — separate from Liga Stavok 9222)

```powershell
cd backend
.\scripts\start_chrome_cdp_bet365.ps1
```

Wait for [bet365.com/#/HO/](https://www.bet365.com/#/HO/) to load (home / live hub).

### 2. Capture uid + cookie

```powershell
python main.py capture bet365 --env
```

Paste the printed lines into `backend/.env`:

```env
BET365_WS_UID=3528489557161243
BET365_COOKIE=pstk=...; aps03=...
BET365_BROWSER_CDP_URL=http://127.0.0.1:9223
BET365_BROWSER_URL=https://www.bet365.com/#/HO/
BET365_USE_BROWSER=true
```

### 3. Listen — browser tap (recommended)

No Python WebSocket, no cookie copy-paste. Taps frames from Chrome like Liga Stavok:

```powershell
python main.py listen bet365 --browser --seconds 30
```

**Parsed soccer 1X2 odds** (Fulltime Result, market `1777`):

```powershell
python main.py listen bet365 --browser --odds --seconds 15
python main.py listen bet365 --browser --odds --live-only --seconds 15
```

Offline replay from a saved ZAP body:

```powershell
python main.py listen bet365 --body bet365/sample_soccer_body.txt
```

Or with `.env` (`BET365_USE_BROWSER=true`):

```powershell
python main.py listen bet365 --seconds 30
python main.py listen bet365 --odds --seconds 15
```

Keep CDP Chrome open on `#/HO/`. On a **fresh debug profile** the cookie banner appears once — `capture` / `listen --browser` auto-clicks **Accept All**.

If the banner persists, click **Accept All** manually in the CDP window.

### 4. Listen — direct WebSocket (optional, often 403)

```powershell
python main.py listen bet365 --direct --uid 3528489557161243 --cookie "pstk=..."
```

### 5. Poll → PostgreSQL (every 3.5s)

Continuous import (same pattern as `poll ligastavok`):

```powershell
# .env: SITE_NAME=bet365.com, DATABASE_URL=..., BET365_BROWSER_CDP_URL=http://127.0.0.1:9223
python main.py poll bet365
python main.py poll bet365 --once --samples
python main.py poll bet365 --live-only --interval 10
```

Keeps CDP Chrome open, drains ZAP frames each tick, maps all sports/markets → PostgreSQL.

### Safe mode (default — lower bot risk)

`BET365_SAFE_MODE=true` (default) uses a **slower poll** and **no automatic page reloads**:

| Setting | Safe default | Aggressive (`BET365_SAFE_MODE=false`) |
|---------|--------------|----------------------------------------|
| Poll interval | **8s** | 3.5s |
| Auto reload loops | **off** | on |
| Recovery reload on stale feed | **off** (log + manual F5) | one reload |

Recommended workflow:

1. `.\scripts\start_chrome_cdp_bet365.ps1` — load bet365 live line manually.
2. `python main.py poll bet365` — passive WebSocket tap only.
3. If feed goes quiet, press **F5 once** in the CDP Chrome window (do not restart poll in a loop).

Optional overrides:

```env
BET365_SAFE_MODE=true
BET365_POLL_INTERVAL_SECONDS=10
BET365_BROWSER_AUTO_RELOAD=false
BET365_BROWSER_INITIAL_ATTACH=true   # one attach reload on first start
BET365_RECOVER_RELOAD=false          # never auto-reload on stale feed
BET365_STALE_POLLS_BEFORE_RECOVER=6
```

Env: `BET365_POLL_INTERVAL_SECONDS` overrides safe/standard default (falls back to `POLL_INTERVAL_SECONDS`).

### Cloudflare verification (entry → live hub)

1. Opens **`https://www.bet365.com/`** for Cloudflare auth.
2. After verification, navigates to **`https://www.bet365.com/#/HO/`** for the ZAP feed.

```env
BET365_BROWSER_ENTRY_URL=https://www.bet365.com/
BET365_BROWSER_URL=https://www.bet365.com/#/HO/
BET365_WAIT_FOR_CLOUDFLARE=true
BET365_CLOUDFLARE_AUTO_CLICK=true
BET365_CLOUDFLARE_AUTO_CLICK_DELAY_SECONDS=30
```

If Cloudflare reappears mid-poll, the adapter pauses again and prompts you.

---

## Manual capture (DevTools)

If you prefer DevTools:

1. Open [bet365.com/#/HO/](https://www.bet365.com/#/HO/) and log in / load the live line.
2. DevTools → **Network** → filter **WS**.
3. Find a connection to `premws-pt1.365lpodds.com/zap/`.
4. Copy:
   - **Request URL** (includes `uid=…`)
   - **Cookie** header (must contain `pstk=…`)

### 2. Put them in `backend/.env`

```env
BET365_WS_UID=3528489557161243
BET365_COOKIE=pstk=YOUR_SESSION; aps03=...; other=cookies
# Optional — if you have the full handshake token from DevTools frames:
# BET365_NST_TOKEN=part1.part2
```

### 3. Listen to the socket

```powershell
cd backend
pip install websockets
python main.py listen bet365 --seconds 30
```

Or directly:

```powershell
python -m bet365.listen --uid 3528489557161243 --cookie "pstk=..." --seconds 60 -o bet365/frames.json
```

## Protocol overview

| Piece | Value |
|-------|--------|
| Subprotocol | `zap-protocol-v1` |
| Compression | `permessage-deflate` |
| Handshake | `\x23\x03P\x01__time,S_<pstk>\x00` or with `D_<nst_token>` |
| Subscribe | `\x16\x00<TopicName>\x01` |
| Frame split | `\x08` (MESSAGE delimiter) |
| Load / delta | types `\x14` / `\x15` |

Default topics (in-play line):

```text
__host, CONFIG_1_3, LHInPlay_1_3, OVInPlay_1_3, Media_l1_Z3, XI_1_3, InPlay_1_3
```

A **second** socket to `wss://pshudws.365lpodds.com/zap/?uid=…` (aux) keeps the main connection stable longer — enabled by default (`BET365_USE_AUX_SOCKET=true`).

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `BET365_WS_URL` | `wss://premws-pt1.365lpodds.com/zap/` | Main WebSocket base |
| `BET365_WS_AUX_URL` | `wss://pshudws.365lpodds.com/zap/` | Aux heartbeat socket |
| `BET365_WS_UID` | random | `uid` query parameter |
| `BET365_COOKIE` | — | Full Cookie header from browser |
| `BET365_SESSION_ID` | — | `pstk` value (alternative to cookie) |
| `BET365_NST_TOKEN` | — | `part1.part2` for `D_` handshake field |
| `BET365_TOPICS` | see `config.py` | Comma-separated subscribe topics |
| `BET365_LISTEN_SECONDS` | `60` | Listen duration |
| `BET365_USE_AUX_SOCKET` | `true` | Open aux WebSocket |

## Module layout

```text
bet365/
  config.py      # URLs, env, headers
  protocol.py    # ZAP framing / handshake / subscribe
  session.py     # pstk from cookie or sports-configuration API
  ws_client.py   # async connect + stream
  listen.py      # CLI
```

## Next steps (not implemented yet)

- Poll loop → PostgreSQL (`SITE_NAME=bet365.com`)
- Frontend dashboard for bet365.com

## Implemented: ZAP → odds parser

| Module | Role |
|--------|------|
| `zap_parse.py` | Pipe/semicolon record parser, fractional odds |
| `state.py` | In-memory EV / MA / PA tree + delta updates |
| `mapper.py` | All sports/markets → `Change[]` |
| `odds_config.py` | Import mode, market names, esoccer filter |

**Default (`BET365_IMPORT_ALL=true`):** every sport and every priced market from the socket → PostgreSQL.

Env:

| Variable | Default | Purpose |
|----------|---------|---------|
| `BET365_IMPORT_ALL` | `true` | All sports + all markets (set `false` for soccer 1X2 only) |
| `BET365_SKIP_ESOCCER` | `true` | Drop virtual esoccer |
| `BET365_MAIN_MARKET_ID` | `1777` | Soccer fulltime (legacy / display priority) |
| `BET365_SAFE_MODE` | `true` | Slower poll, no auto reload loops |
| `BET365_POLL_INTERVAL_SECONDS` | `8` / `3.5` | Poll tick (8s safe, 3.5s standard) |
| `BET365_BROWSER_AUTO_RELOAD` | `false` / `true` | Reload page when uid missing |
| `BET365_RECOVER_RELOAD` | `false` / `true` | One reload after stale feed |

Primary win markets (`Fulltime Result`, `Match Winner`, …) map to factor ids **921/922/923** for the frontend. Other selections use bet365 PA `ID` as `factor_id`.

## Troubleshooting

### HTTP 403 on connect

- Refresh cookies from an **open** bet365.com tab.
- Ensure `pstk=` is in `BET365_COOKIE`.
- Try copying a **fresh** `uid` from the live WS URL in DevTools.

### Connect OK but no data

- Wait for handshake response (`\x08` frames).
- Check topics match your bet365 region/version (`InPlay_20_0` vs `InPlay_1_3` in DevTools subscribe frames).
- Enable aux socket (default on).

### NST token required

Some regions need `BET365_NST_TOKEN` (two-part token from bet365 JS). Without it, only the simple `S_<pstk>` handshake is sent — if the server closes immediately, capture the first **sent** frame from DevTools and replicate it in `.env`.
