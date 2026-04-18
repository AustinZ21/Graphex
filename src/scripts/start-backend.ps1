param(
    [Parameter(Mandatory = $false)]
    [string]$BindHost = '127.0.0.1',

    [Parameter(Mandatory = $false)]
    [int]$PreferredPort = 8000,

    [Parameter(Mandatory = $false)]
    [int]$PortSearchCount = 50,

    [Parameter(Mandatory = $false)]
    [string]$FalkorHost = 'localhost',

    [Parameter(Mandatory = $false)]
    [string]$FalkorPort = '16379',

    [Parameter(Mandatory = $false)]
    [string]$QueueRedisUrl = 'redis://localhost:6380/1',

    [Parameter(Mandatory = $false)]
    [string]$CacheRedisUrl = 'redis://localhost:6380',

    [Parameter(Mandatory = $false)]
    [switch]$PrintOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-PortAvailable {
    param(
        [string]$BindHost,
        [int]$Port
    )

    $listener = $null
    try {
        $ip = [System.Net.IPAddress]::Parse($BindHost)
        $listener = [System.Net.Sockets.TcpListener]::new($ip, $Port)
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
}

function Resolve-FreePort {
    param(
        [string]$BindHost,
        [int]$StartPort,
        [int]$Count
    )

    for ($i = 0; $i -lt $Count; $i++) {
        $candidate = $StartPort + $i
        if (Test-PortAvailable -BindHost $BindHost -Port $candidate) {
            return $candidate
        }
    }

    throw "No free port found from $StartPort to $($StartPort + $Count - 1) on host $BindHost"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Push-Location $repoRoot
try {
    $selectedPort = Resolve-FreePort -BindHost $BindHost -StartPort $PreferredPort -Count $PortSearchCount

    if ($env:PYTHONPATH) {
        if (-not ($env:PYTHONPATH -split ';' | Where-Object { $_ -eq 'src' })) {
            $env:PYTHONPATH = "src;$($env:PYTHONPATH)"
        }
    }
    else {
        $env:PYTHONPATH = 'src'
    }

    $env:FALKORDB_HOST = $FalkorHost
    $env:FALKORDB_PORT = $FalkorPort
    $env:QUEUE_REDIS_URL = $QueueRedisUrl
    $env:CACHE_REDIS_URL = $CacheRedisUrl

    Write-Host "ContextGraph backend launch settings:"
    Write-Host "- host: $BindHost"
    Write-Host "- port: $selectedPort"
    Write-Host "- mcp root: http://$($BindHost):$($selectedPort)/mcp"

    if ($PrintOnly) {
        return
    }

    python -m uvicorn backend.main:app --host $BindHost --port $selectedPort
}
finally {
    Pop-Location
}
