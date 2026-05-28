# Database setup — `booker_adapter`

PostgreSQL database for adapter + CORE development and the review frontend.

---

## 1. Create database

**psql (recommended):**

```powershell
psql -U postgres -d postgres -f backend/scripts/create_database.sql
```

**Or manually:**

```sql
CREATE DATABASE booker_adapter;
```

On Windows, if locale options in the script fail, use only `CREATE DATABASE booker_adapter;`.

---

## 2. Environment variables

**`backend/.env`** (copy from `backend/.env.example`):

```env
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/booker_adapter
SITE_NAME=fonbet.com
POLL_INTERVAL_SECONDS=3.5
RETAIN_SNAPSHOT_YEARS=1
```

**`frontend/.env.local`** (copy from `frontend/.env.local.example`):

```env
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/booker_adapter
SITE_NAME=fonbet.com
NEXT_PUBLIC_POLL_INTERVAL_MS=5000
```

| Setting | Value |
|---------|--------|
| Database name | `booker_adapter` |
| Code default | `backend/config.py` → `DB_NAME=booker_adapter` |

---

## 3. Apply schema

```powershell
cd backend
pip install -r requirements.txt
python main.py setup
```

Creates database (if missing), tables, and imports sample data. Or manually:

```powershell
python main.py import fonbet/test.json --init-schema --migrate
```

Creates tables including:

| Table | Purpose |
|-------|---------|
| `sites` | Bookmaker domains (`fonbet.com`, …) |
| `sport_reference` | Appendix A sports (207) |
| `sports` | Per-site sport catalog |
| `countries`, `leagues` | Geography / competition |
| `matches` | Level-1 events |
| `match_scores` | Live scores, timer |
| `betting_status` | Block/suspend state |
| `odds_lines` | Factor prices |
| `import_snapshots` | Poll audit |

---

## 4. Verify

```powershell
psql -U postgres -d booker_adapter -c "\dt"
psql -U postgres -d booker_adapter -c "SELECT id, name FROM sites;"
psql -U postgres -d booker_adapter -c "SELECT COUNT(*) FROM matches;"
```

---

## 5. Migrate from `bk_aggregator` (optional)

If you used the old database name:

```powershell
pg_dump -U postgres -d bk_aggregator -F c -f bk_aggregator.dump
pg_restore -U postgres -d booker_adapter --no-owner bk_aggregator.dump
```

Or start fresh on `booker_adapter` and re-run `main.py poll`.

---

## 6. Maintenance

```sql
-- Prune old audit snapshots (example: before 2026)
DELETE FROM import_snapshots WHERE year < 2026;

-- Prune old matches (optional)
DELETE FROM matches WHERE event_year < 2026;
```

Retention is also controlled by `RETAIN_SNAPSHOT_YEARS` in `.env` during poll.

---

See also: [TODO.md](../TODO.md), [WORKFLOW.md](../WORKFLOW.md).
