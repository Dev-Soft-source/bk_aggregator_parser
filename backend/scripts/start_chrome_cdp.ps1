# Start Google Chrome with remote debugging for Liga Stavok poll (CDP).
# If poll fails with ECONNREFUSED :9222, run this script FIRST in a separate terminal.

$ErrorActionPreference = "Continue"

$port = if ($env:LIGASTAVOK_CDP_PORT) { $env:LIGASTAVOK_CDP_PORT } else { "9222" }
$userData = Join-Path $env:LOCALAPPDATA "liga-chrome-debug"
$cdpUrl = "http://127.0.0.1:$port/json/version"

function Test-CdpUp {
    try {
        $null = Invoke-WebRequest -Uri $cdpUrl -UseBasicParsing -TimeoutSec 2
        return $true
    } catch {
        return $false
    }
}

$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    Write-Error "Google Chrome not found. Install Chrome from https://www.google.com/chrome/"
}

if (Test-CdpUp) {
    Write-Host "OK: Chrome CDP already on port $port"
    Write-Host "Open https://www.ligastavok.ru in THAT Chrome window (separate profile: liga-chrome-debug)."
    Write-Host "Then: python main.py poll ligastavok --browser --curl capture.curl"
    exit 0
}

# Separate profile = separate process (works even if normal Chrome is open)
$args = @(
    "--remote-debugging-port=$port",
    "--remote-debugging-address=127.0.0.1",
    "--user-data-dir=$userData",
    "--no-first-run",
    "--no-default-browser-check",
    "https://www.ligastavok.ru"
)

Write-Host "Chrome: $chrome"
Write-Host "Profile: $userData"
Write-Host "CDP port: $port"
Write-Host ""
Write-Host "Starting Chrome (new window with debug profile)..."

Start-Process -FilePath $chrome -ArgumentList $args

$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    if (Test-CdpUp) {
        $ver = Invoke-WebRequest -Uri $cdpUrl -UseBasicParsing -TimeoutSec 5
        Write-Host ""
        Write-Host "OK: CDP ready at http://127.0.0.1:$port"
        Write-Host $ver.Content
        Write-Host ""
        Write-Host "Leave this Chrome window open. In another terminal:"
        Write-Host "  cd backend"
        Write-Host "  python main.py poll ligastavok --browser --curl capture.curl"
        exit 0
    }
}

Write-Host ""
Write-Host "FAILED: port $port still not open after 45s." -ForegroundColor Red
Write-Host ""
Write-Host "Try:"
Write-Host "  1) Task Manager -> end ALL 'Google Chrome' processes"
Write-Host "  2) Run this script again"
Write-Host "  3) Or set LIGASTAVOK_BROWSER_CDP_URL empty and refresh capture.curl from DevTools"
Write-Host ""
Write-Host "Test in browser: http://127.0.0.1:$port/json/version  (must show JSON)"
exit 1