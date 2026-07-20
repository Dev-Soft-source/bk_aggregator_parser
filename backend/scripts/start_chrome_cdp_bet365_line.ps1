# Start Google Chrome with remote debugging for Bet365 LINE (#/AO/).
# Uses port 9225 (live bet365 uses 9223) and a separate profile.

$ErrorActionPreference = "Continue"

$port = if ($env:BET365_LINE_CDP_PORT) { $env:BET365_LINE_CDP_PORT } else { "9225" }
$userData = Join-Path $env:LOCALAPPDATA "bet365-line-chrome-debug"
$cdpUrl = "http://127.0.0.1:$port/json/version"
$startUrl = if ($env:BET365_LINE_BROWSER_ENTRY_URL) {
    $env:BET365_LINE_BROWSER_ENTRY_URL
} else {
    # Open sports home (#/HO/) first; poller then moves to #/AO/.
    "https://www.bet365.com/#/HO/"
}
$lineUrl = if ($env:BET365_LINE_BROWSER_URL) {
    $env:BET365_LINE_BROWSER_URL
} else {
    "https://www.bet365.com/#/AO/"
}

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
    Write-Host "OK: Chrome CDP already on port $port (bet365-line profile)"
    Write-Host "Open $startUrl in THAT window (auth), then line hub: $lineUrl"
    Write-Host "  python main.py poll bet365-line"
    exit 0
}

$args = @(
    "--remote-debugging-port=$port",
    "--remote-debugging-address=127.0.0.1",
    "--user-data-dir=$userData",
    "--no-first-run",
    "--no-default-browser-check",
    "--start-maximized",
    "--new-window",
    $startUrl
)

Write-Host "Starting Chrome (bet365-line debug profile, port $port)..."
Write-Host "  profile: $userData"
Write-Host "  start:   $startUrl"
Write-Host "  hub:     $lineUrl"
Start-Process -FilePath $chrome -ArgumentList $args

$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    if (Test-CdpUp) {
        Write-Host ""
        Write-Host "OK: CDP ready at http://127.0.0.1:$port"
        Write-Host ""
        Write-Host "Wait for Cloudflare / sports home on $startUrl, then poll moves to $lineUrl"
        Write-Host "  cd backend"
        Write-Host "  python main.py poll bet365-line"
        exit 0
    }
}

Write-Error "Chrome started but CDP did not become ready on port $port"
