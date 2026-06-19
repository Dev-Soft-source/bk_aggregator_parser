# Start Google Chrome with remote debugging for Bet365 ZAP capture.
# Uses port 9223 (Liga Stavok uses 9222) and a separate profile.

$ErrorActionPreference = "Continue"

$port = if ($env:BET365_CDP_PORT) { $env:BET365_CDP_PORT } else { "9223" }
$userData = Join-Path $env:LOCALAPPDATA "bet365-chrome-debug"
$cdpUrl = "http://127.0.0.1:$port/json/version"
$startUrl = if ($env:BET365_BROWSER_ENTRY_URL) { $env:BET365_BROWSER_ENTRY_URL } else { "https://www.bet365.com/" }
$liveUrl = if ($env:BET365_BROWSER_URL) { $env:BET365_BROWSER_URL } else { "https://www.bet365.com/#/HO/" }

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
    Write-Error "Google Chrome not found."
}

if (Test-CdpUp) {
    Write-Host "OK: Chrome CDP already on port $port (bet365 profile)"
    Write-Host "Open $startUrl in THAT window (auth), then live hub: $liveUrl"
    Write-Host "  python main.py capture bet365 --env"
    exit 0
}

$args = @(
    "--remote-debugging-port=$port",
    "--remote-debugging-address=127.0.0.1",
    "--user-data-dir=$userData",
    "--no-first-run",
    "--no-default-browser-check",
    $startUrl
)

Write-Host "Starting Chrome (bet365 debug profile, port $port)..."
Start-Process -FilePath $chrome -ArgumentList $args

$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    if (Test-CdpUp) {
        Write-Host ""
        Write-Host "OK: CDP ready at http://127.0.0.1:$port"
        Write-Host ""
        Write-Host "Wait for Cloudflare auth on $startUrl, then poll opens $liveUrl"
        Write-Host "  cd backend"
        Write-Host "  python main.py capture bet365 --env"
        exit 0
    }
}

Write-Host "FAILED: port $port not open after 45s." -ForegroundColor Red
exit 1
