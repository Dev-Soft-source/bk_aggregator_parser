# 1xBet line HTTP

Bookmaker code: `lxbet-line` · site: `1xbet.com` · place: `line`  
Package path: `backend/lxbet_line/`

Each `Get1x2_VZip` response is hard-capped (~50 events). To cover the full site catalog the poller:

1. `GetSportsShortZip` — sport list + counts  
2. Per sport: `Get1x2_VZip?sports={id}&count=50`  
3. If a sport is truncated vs catalog count: `GetChampsZip` + per-champ `Get1x2_VZip?champs={id}`  
4. Optional `top=true` list, then merge by event id  

Default poll interval is **20s** (full catalog is many HTTP calls).

## Poll

```powershell
cd backend
python main.py poll lxbet-line
python main.py poll lxbet-line --once --samples
```

## Env

```env
# LXBET_LINE_EVENTS_URL=https://1xlite-55157.pro/service-api/LineFeed/Get1x2_VZip
# LXBET_LINE_SPORTS_URL=https://1xlite-55157.pro/service-api/LineFeed/GetSportsShortZip
# LXBET_LINE_CHAMPS_URL=https://1xlite-55157.pro/service-api/LineFeed/GetChampsZip
# LXBET_LINE_SPORT_COUNT=50
# LXBET_LINE_FETCH_ALL_SPORTS=true
# LXBET_LINE_FETCH_TOP=true
# LXBET_LINE_MAX_WORKERS=1
# LXBET_LINE_REQUEST_PAUSE_SECONDS=1.0
# LXBET_LINE_HTTP_TIMEOUT=60
# LXBET_LINE_ONLY_SPORT_IDS=1,2,3,4,5,6,10,16,40
# LXBET_LINE_PRUNE_COVERAGE_MIN=0.9
# LXBET_LINE_PRUNE_PAST_HOURS=48
# LXBET_LINE_POLL_INTERVAL_SECONDS=90
# LXBET_LINE_LNG=en
# LXBET_LINE_MODE=4
# LXBET_LINE_COUNTRY=179
# LXBET_ODDS_FACTOR_IDS=921,922,923
```

| ID | Sport |
|----|--------|
| 1 | Football |
| 2 | Ice Hockey |
| 3 | Basketball |
| 4 | Tennis |
| 5 | Baseball |
| 6 | Volleyball |
| 10 | Table Tennis |
| 16 | Badminton |
| 40 | Esports |

Set `LXBET_LINE_ONLY_SPORT_IDS=` empty to fetch every catalog sport.  
Set `LXBET_LINE_FETCH_ALL_SPORTS=false` to fall back to a single capped list.

To reduce `HTTPSConnectionPool` / SSL drops: keep `LXBET_LINE_MAX_WORKERS=1` and raise `LXBET_LINE_REQUEST_PAUSE_SECONDS` (e.g. `1.0`). Cycles get slower but stabler.

## Mapping

| Source | DB |
|--------|-----|
| `O1` / `O2` / `S` | fixture (`place=line`) |
| `E[]` `G=1` `T=1/2/3` | odds **921** / **922** / **923** (Football, Tennis, …) |
| `E[]` `G=2766` `T=3653/3654/3655` | Basketball 1X2 |
| `E[]` `G=101` `T=401/402` | Basketball 2-way moneyline |

Events without main home+away odds (921+923) are skipped — no fixture/blocked row is stored.

## Retention

- Each poll **upserts** current fixtures/odds (recent data is kept and refreshed).
- Absent-match prune runs only when fetch coverage ≥ `LXBET_LINE_PRUNE_COVERAGE_MIN` (default 90%), so timeouts mid-catalog do not wipe the DB.
- Line matches with kickoff older than `LXBET_LINE_PRUNE_PAST_HOURS` (default 48) are removed.
