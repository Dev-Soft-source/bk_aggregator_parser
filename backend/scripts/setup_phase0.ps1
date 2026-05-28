# Phase 0 setup (Windows PowerShell)
# Prerequisites: PostgreSQL running, backend/.env configured for booker_adapter

$ErrorActionPreference = "Stop"
$Backend = Split-Path -Parent $PSScriptRoot
Set-Location $Backend

Write-Host "=== Create database booker_adapter (if missing) ===" -ForegroundColor Cyan
psql -U postgres -d postgres -f scripts/create_database.sql 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Note: create_database may fail if DB already exists — continuing." -ForegroundColor Yellow
}

Write-Host "=== Phase 0 setup (schema + import + verify) ===" -ForegroundColor Cyan
python main.py setup
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== Adapter smoke test ===" -ForegroundColor Cyan
python main.py adapter fonbet/test.json
python -m unittest discover -s fonbet/tests -v

Write-Host ""
Write-Host "Done. Start stack:" -ForegroundColor Green
Write-Host "  python main.py poll"
Write-Host "  cd ../frontend; npm run dev"
