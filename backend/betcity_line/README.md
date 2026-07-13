# Betcity line (prematch) HTTP

Bookmaker code: `betcity-line` · site: `betcity.ru` · place: `line`  
Package path: `backend/betcity_line/`

Prematch odds over HTTP (Fonbet-shaped poll):

```text
GET https://ad.betcity.ru/d/off/events?rev=6&add=dep_events&ver=82&csn=<token>
```

Cursor: response `reply.ntime` → next request adds `&md={ntime}`. Interval: **10 seconds**.

## Poll

```powershell
cd backend
python main.py poll betcity-line
python main.py poll betcity_line   # alias
python main.py poll betcity-line --once --samples
```

`poll betcity` remains the **live** WebSocket package (`betcity_live/`).

## Env

```env
# BETCITY_LINE_URL=https://ad.betcity.ru/d/off/events
# BETCITY_LINE_REV=6
# BETCITY_LINE_VER=82
# BETCITY_LINE_CSN=ooca9s
# BETCITY_LINE_POLL_INTERVAL_SECONDS=10
# BETCITY_LINE_HTTP_TIMEOUT=90
# BETCITY_LINE_CONNECT_TIMEOUT=20
```

On network timeouts the poller keeps the last `md` cursor and backs off instead of immediately re-fetching the full snapshot. After several consecutive failures it resets to a snapshot.

Site is always written as **`betcity.ru`**; rows are distinguished from live by `place=line`.

## Mapping

| Source | DB |
|--------|-----|
| `name_ht` / `name_at` / `date_ev` | fixture (`place=line`) |
| `ev.main["69"].blocks.Wm` `P1`/`P2` `kf` | odds factors **921** / **923** |
| Wm outcome/block `st` (`2` open, `1` locked) | betting status |

Outright-only `YNm` markets without Wm are skipped for odds.

## Retention

On each **full snapshot** (no `md`), absent `place=line` matches for `betcity.ru` are pruned and only the current snapshot is kept. Deltas update in place without pruning.
