param([switch]$Production, [ValidateRange(1, 65535)][int]$FrontendPort = 5173)
# Keep Python options out of PowerShell's common-parameter binding (e.g. --db).
$ServiceArguments = $args
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Push-Location -LiteralPath (Join-Path $project 'frontend')
try {
    if (-not (Test-Path -LiteralPath 'node_modules/.bin/vite.cmd')) {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci exited with code $LASTEXITCODE; see output above." }
    }
    if ($Production) {
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build exited with code $LASTEXITCODE; see output above." }
    }
} finally { Pop-Location }
$frontend = $null
$exitCode = 1
$previousApiUrl = $env:AGENT_PLATFORM_API_URL
Push-Location -LiteralPath (Join-Path $project 'backend')
try {
    # Resolve the same default/CLI port as the backend, including --port=NNNN.
    $port = python -c "import argparse; from agent_platform.settings.platform import read_settings; p = argparse.ArgumentParser(add_help=False); p.add_argument('--port', type=int, default=read_settings()['service']['port']); print(p.parse_known_args()[0].port)" @ServiceArguments
    if ($LASTEXITCODE -ne 0) { throw "Resolving backend port exited with code $LASTEXITCODE; see output above." }
    $apiUrl = "http://127.0.0.1:$port"
    $listener = Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $_.LocalPort -eq [int]$port } | Select-Object -First 1
    if ($null -ne $listener) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction Stop
        if ($null -eq $owner -or $owner.CommandLine -notmatch '\s-m\s+agent_platform\s+serve(?:\s|$)') {
            throw "Port $port is owned by PID $($listener.OwningProcess), not an agent_platform serve process. Restart aborted."
        }
        $oldBackend = Get-Process -Id $listener.OwningProcess -ErrorAction Stop
        $session = Invoke-RestMethod -Uri "$apiUrl/api/session" -TimeoutSec 10
        if (-not $session.can_shutdown -or -not $session.token) {
            throw "Service at $apiUrl did not provide a shutdown-capable session. Restart aborted."
        }
        Write-Host "Stopping existing workbench at $apiUrl; waiting for backend cleanup..."
        $body = @{ action = 'shutdown'; token = $session.token } | ConvertTo-Json -Compress
        $result = Invoke-RestMethod -Uri "$apiUrl/api/action" -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 10
        if (-not $result.ok) { throw "Shutdown at $apiUrl was not acknowledged: $($result | ConvertTo-Json -Depth 10 -Compress)" }
        # The backend owns the configurable drain deadline and timeout action.
        # Wait for actual exit; a separate launcher deadline must not override it.
        Wait-Process -InputObject $oldBackend -ErrorAction Stop
        # The previous launcher stops its Vite in finally after Python exits.
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        do {
            $frontendListening = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
                Where-Object { $_.Port -eq $FrontendPort }
            if (-not $frontendListening) { break }
            Start-Sleep -Milliseconds 200
        } while ([DateTime]::UtcNow -lt $deadline)
        if ($frontendListening) {
            throw "Previous frontend still occupies port $FrontendPort after backend shutdown. Restart aborted; no new backend started."
        }
        Write-Host 'Previous workbench stopped. Starting frontend and backend...'
    }
    if (-not $Production) {
        $env:AGENT_PLATFORM_API_URL = $apiUrl
        $vite = Join-Path $project 'frontend/node_modules/vite/bin/vite.js'
        # Share this interactive console so Vite diagnostics remain visible.
        $frontend = Start-Process -FilePath (Get-Command node.exe -ErrorAction Stop).Source -ArgumentList @("`"$vite`"", '--port', "$FrontendPort") -WorkingDirectory (Join-Path $project 'frontend') -NoNewWindow -PassThru
        Start-Sleep -Milliseconds 1000
        if ($frontend.HasExited) { throw "Vite exited with code $($frontend.ExitCode); see output above." }
        Write-Host "Workbench (hot reload): http://127.0.0.1:$FrontendPort"
        Write-Host 'Use the workbench Stop service action or Ctrl+C to stop.'
    }
    python -m agent_platform serve @ServiceArguments
    $exitCode = $LASTEXITCODE
} finally {
    if ($null -ne $frontend -and -not $frontend.HasExited) {
        try { Stop-Process -Id $frontend.Id -ErrorAction Stop }
        catch {
            Write-Error -ErrorRecord $_ -ErrorAction Continue
            if ($exitCode -eq 0) { $exitCode = 1 }
        }
    }
    $env:AGENT_PLATFORM_API_URL = $previousApiUrl
    Pop-Location
}
exit $exitCode
