# Liga Stavok line (prematch)

Self-contained prematch poller · site: `ligastavok.ru` · place: `line`  
Package: `backend/ligastavok_line/`

Live is a separate copy: [`ligastavok_live`](../ligastavok_live/).

## Poll

```powershell
cd backend
python main.py poll ligastavok-line
python main.py poll ligastavok-line --once
```

## Env

```env
LIGASTAVOK_LINE_POLL_INTERVAL_SECONDS=10
LIGASTAVOK_LINE_BROWSER_URL=https://www.ligastavok.ru/prematch
# LIGASTAVOK_LINE_BROWSER_CDP_URL=http://127.0.0.1:9222
# Drop place=line rows missing from the latest full HTTP snapshot (default: on)
# LIGASTAVOK_LINE_PRUNE_ABSENT=true
# LIGASTAVOK_LINE_PRUNE_MIN_FIXTURES=1
```

Browser page: `https://www.ligastavok.ru/prematch` (never `/live`).

Line imports prune `place=line` rows absent from each full prematch HTTP snapshot.
