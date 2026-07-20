# Bet365 line (prematch)

Bookmaker code: `bet365-line` · site: `bet365.com` · place: `line`  
Package path: `backend/bet365_line/`

Same ZAP + CDP approach as `backend/bet365/` (live `#/HO/`), but opens the
**prematch / Asian Odds hub**:

`https://www.bet365.com/#/AO/`

All fixtures are stored with `place=line`. Absent line matches are pruned each
poll when the export set is non-empty.

## Poll

```powershell
cd backend
# Separate Chrome for line (port 9225):
powershell -File scripts/start_chrome_cdp_bet365_line.ps1

python main.py poll bet365-line
python main.py poll bet365-line --once --samples
```

Use a **separate CDP Chrome** from live (9223) so both can run in parallel.

## Env

```env
SITE_NAME=bet365.com
BET365_LINE_BROWSER_CDP_URL=http://127.0.0.1:9225
BET365_LINE_BROWSER_URL=https://www.bet365.com/#/AO/
BET365_LINE_BROWSER_ENTRY_URL=https://www.bet365.com/
BET365_LINE_SAFE_MODE=true
BET365_LINE_POLL_INTERVAL_SECONDS=15
# Shared with live where useful:
# BET365_COOKIE_BANNER_AUTO_CLICK=true
# BET365_WAIT_FOR_CLOUDFLARE=true
# BET365_IMPORT_ALL=true
```

## Bootstrap

1. Open sports home / AO shell for auth
2. Rotate **all sports** `#/AS/B{n}/` (Soccer, Tennis, Basketball, …) so ZAP
   loads each book — bet365 only streams the **visible** sport
3. Accumulate EV / MA / PA across sports → `place=line`

Configure sports with:

```env
BET365_LINE_SPORT_IDS=1,13,18,16,91,78,17,12,8,9,14,15,3,36,83
BET365_LINE_INITIAL_LOAD_SECONDS=90
```

Default includes football **and** the other common line sports. Keep the CDP
Chrome tab open while polling.

```env
BET365_LINE_BROWSER_ENTRY_URL=https://www.bet365.com/#/HO/
BET365_LINE_BROWSER_URL=https://www.bet365.com/#/AO/
```

## Geo / first screen

A **fresh** line Chrome profile often opens the US splash
(`bet365.com/usa` → “Where do you want to play?”). That page has **no ZAP feed**.

Opening `#/HO/` first (same as live) usually reaches the sports book; the poller
then switches to `#/AO/`. Do not click US state buttons.

**Keep live Chrome (port 9223) open** on the international sports site while
starting line — the line poller **automatically copies bet365 cookies** from
live Chrome so `#/AO/` does not bounce to `/usa`.

```env
BET365_LINE_COOKIE_IMPORT_CDP_URL=http://127.0.0.1:9223
```




| Source | DB |
|--------|-----|
| EV / MA / PA from ZAP on `#/AO/` | fixtures + odds (`place=line`) |
| Scores / timers | only when present (usually empty prematch) |

## Retention

`prune_absent` for `place=line` keeps only fixtures exported in the current tick.
