# Start Google Chrome with remote debugging for Betcity live WS tap.
# Uses port 9224 (Liga Stavok 9222, Bet365 9223) and a separate profile.
# Optional proxy: set BETCITY_PROXY=host:port (or http://host:port)

$ErrorActionPreference = "Continue"

$port = if ($env:BETCITY_CDP_PORT) { $env:BETCITY_CDP_PORT } else { "9224" }
$userData = Join-Path $env:LOCALAPPDATA "betcity-chrome-debug"
$cdpUrl = "http://127.0.0.1:$port/json/version"
$startUrl = if ($env:BETCITY_BROWSER_URL) { $env:BETCITY_BROWSER_URL } else { "https://betcity.ru/ru/live" }
$proxyRaw = if ($env:BETCITY_PROXY) { $env:BETCITY_PROXY.Trim() } else { "" }

function Test-CdpUp {
    try {
        $null = Invoke-WebRequest -Uri $cdpUrl -UseBasicParsing -TimeoutSec 2
        return $true
    } catch {
        return $false
    }
}

function Get-ChromeProxyServer([string]$raw) {
    if (-not $raw) { return $null }
    $value = $raw.Trim()
    if ($value -match '^[a-zA-Z][a-zA-Z0-9+.-]*://') {
        try {
            $uri = [Uri]$value
            if ($uri.IsDefaultPort) {
                return $uri.Host
            }
            return "$($uri.Host):$($uri.Port)"
        } catch {
            return $value
        }
    }
    return $value
}

$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    Write-Error "Google Chrome not found."
    exit 1
}

if (Test-CdpUp) {
    Write-Host "OK: Chrome CDP already on port $port (betcity profile)"
    Write-Host "Open $startUrl in THAT window."
    Write-Host "  python main.py poll betcity --browser"
    if ($proxyRaw) {
        Write-Host "Note: proxy is only applied when Chrome is started by this script."
        Write-Host "  Current BETCITY_PROXY=$proxyRaw"
    }
    exit 0
}

$chromeArgs = @(
    "--remote-debugging-port=$port",
    "--remote-debugging-address=127.0.0.1",
    "--user-data-dir=$userData",
    "--no-first-run",
    "--no-default-browser-check"
)

$proxyServer = Get-ChromeProxyServer $proxyRaw
if ($proxyServer) {
    $chromeArgs += "--proxy-server=$proxyServer"
    Write-Host "Proxy: $proxyServer"
}

$chromeArgs += $startUrl

Write-Host "Chrome: $chrome"
Write-Host "Profile: $userData"
Write-Host "CDP port: $port"
Write-Host "Starting Chrome (betcity debug profile)..."
Start-Process -FilePath $chrome -ArgumentList $chromeArgs

$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    if (Test-CdpUp) {
        Write-Host ""
        Write-Host "OK: CDP ready at http://127.0.0.1:$port"
        Write-Host ""
        Write-Host "Leave this Chrome window open on $startUrl. In another terminal:"
        Write-Host "  cd backend"
        Write-Host "  python main.py poll betcity --browser"
        exit 0
    }
}

Write-Host "FAILED: port $port not open after 45s." -ForegroundColor Red
Write-Host "Try ending all Chrome processes, then re-run this script."
exit 1
