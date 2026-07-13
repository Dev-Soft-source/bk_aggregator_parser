# 1xBet live HTTP

Bookmaker code: `lxbet-live` · site: `1xbet.com` · place: `live`  
Package path: `backend/lxbet_live/`

**Default:** same strategy as `lxbet_line` — collect the **full live catalog in one cycle**:

1. `GetSportsShortZip`
2. Per sport `Get1x2_VZip?sports={id}&count=50`
3. If truncated: `GetChampsZip` + per-champ events
4. Optional `top=true`, merge by event id

One cycle takes longer than Fonbet’s 3.5s (many HTTP calls). Interval waits **after** the cycle finishes.

For a fast capped list only: `LXBET_LIVE_FETCH_ALL_SPORTS=false`.

## Poll

```powershell
cd backend
python main.py poll lxbet-live
python main.py poll lxbet-live --once --samples
```

## Env

```env
# LXBET_LIVE_EVENTS_URL=https://1xlite-55157.pro/service-api/LiveFeed/Get1x2_VZip
# LXBET_LIVE_SPORTS_URL=https://1xlite-55157.pro/service-api/LiveFeed/GetSportsShortZip
# LXBET_LIVE_CHAMPS_URL=https://1xlite-55157.pro/service-api/LiveFeed/GetChampsZip
# LXBET_LIVE_SPORT_COUNT=50
# LXBET_LIVE_FETCH_ALL_SPORTS=true
# LXBET_LIVE_FETCH_TOP=true
# LXBET_LIVE_MAX_WORKERS=1
# LXBET_LIVE_REQUEST_PAUSE_SECONDS=0.5
# LXBET_LIVE_HTTP_TIMEOUT=60
# LXBET_LIVE_ONLY_SPORT_IDS=
# LXBET_LIVE_SKIP_SPORT_IDS=314,176
# LXBET_LIVE_PRUNE_COVERAGE_MIN=0.9
# LXBET_LIVE_POLL_INTERVAL_SECONDS=10
# LXBET_LIVE_GR=1197
# LXBET_LIVE_LNG=en
# LXBET_LIVE_MODE=4
# LXBET_LIVE_COUNTRY=179
```

## Mapping

| Source | DB |
|--------|-----|
| `O1` / `O2` / `S` | fixture (`place=live`) |
| `SC.FS` / `SC.SLS` / `SC.CPS` / `SC.TS` | score + live timer |
| `E[]` `G=1` `T=1/2/3` | odds **921** / **922** / **923** |
| `E[]` `G=2766` / `G=101` | Basketball 1X2 / moneyline |

Events without main home+away odds are skipped.

## Retention

Absent `place=live` prune runs when fetch coverage ≥ `LXBET_LIVE_PRUNE_COVERAGE_MIN`.
