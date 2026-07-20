# Liga Stavok live

Self-contained live poller · site: `ligastavok.ru` · place: `live`  
Package: `backend/ligastavok_live/`

Line/prematch is a separate copy: [`ligastavok_line`](../ligastavok_line/).

## Poll

```powershell
cd backend
python main.py poll ligastavok-live
# alias: python main.py poll ligastavok
```

Browser page: `https://www.ligastavok.ru/live`.

Live imports prune `place=live` rows absent from each full HTTP snapshot
(`LIGASTAVOK_LIVE_PRUNE_ABSENT`, default on). WebSocket delta imports never prune.
