# Frontend (Next.js + Tailwind)

Real-time table list of live matches, scores, odds, and betting status from PostgreSQL.

## Setup

```bash
cd frontend
cp .env.local.example .env.local
# Edit DATABASE_URL (same as backend) and SITE_NAME
npm install
```

## Run

**Terminal 1 — backend poller** (fills the database):

```bash
cd backend
python main.py poll
```

**Terminal 2 — frontend**:

```bash
cd frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The UI polls `/api/matches` every 5 seconds.

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/matches?place=live` | Live matches + stats |
| `GET /api/matches?place=line` | Pre-match |
| `GET /api/matches?place=all` | All places |

## Environment

| Variable | Default |
|----------|---------|
| `DATABASE_URL` | — (required) |
| `SITE_NAME` | `fonbet.com` |
| `NEXT_PUBLIC_POLL_INTERVAL_MS` | `5000` |
