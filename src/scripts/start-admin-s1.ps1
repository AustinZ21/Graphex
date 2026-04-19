param(
    [Parameter(Mandatory = $false, Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'logs', 'status', 'url')]
    [string]$Command = 'start',

    [Parameter(Mandatory = $false)]
    [switch]$Detached = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

if (-not $env:DOCKER_HOST) {
    $env:DOCKER_HOST = 'tcp://192.168.1.239:2375'
}

Write-Host "Using DOCKER_HOST=$($env:DOCKER_HOST)"
Write-Host "Working directory: $repoRoot"

switch ($Command) {
    'start' {
        if ($Detached) {
            docker compose build api-dev
            docker compose up -d api-dev
        }
        else {
            docker compose build api-dev
            docker compose up api-dev
        }
        Write-Host "Admin URL: http://localhost:8001/admin"
    }
    'stop' {
        docker compose stop api-dev
    }
    'restart' {
        docker compose restart api-dev
        Write-Host "Admin URL: http://localhost:8001/admin"
    }
    'logs' {
        if ($Detached) {
            docker compose logs --tail=200 api-dev
        }
        else {
            docker compose logs -f --tail=200 api-dev
        }
    }
    'status' {
        docker compose ps api-dev
    }
    'url' {
        Write-Host "http://localhost:8001/admin"
    }
}
