param(
    [Parameter(Mandatory = $false, Position = 0)]
    [ValidateSet('up', 'down', 'ps', 'logs')]
    [string]$Command = 'up',

    [Parameter(Mandatory = $false)]
    [switch]$Detached,

    [Parameter(Mandatory = $false)]
    [string]$ComposeFile = 'docker-compose.yml',

    [Parameter(Mandatory = $false)]
    [string]$FallbackComposeFile = 'docs/docker-compose-templates/compose.pgadmin-postgres.yml'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $env:DOCKER_HOST) {
    $env:DOCKER_HOST = 'tcp://192.168.1.239:2375'
}

function Resolve-ComposeFile {
    param(
        [string]$Primary,
        [string]$Fallback
    )

    if (-not (Test-Path -Path $Primary)) {
        throw "Primary compose file not found: $Primary"
    }

    $primaryContent = Get-Content -Path $Primary -Raw
    $dockerfileMatches = [regex]::Matches($primaryContent, 'dockerfile:\s*([^\r\n]+)')
    $missingDockerfiles = @()

    foreach ($match in $dockerfileMatches) {
        $dockerfilePath = $match.Groups[1].Value.Trim().Trim("'").Trim('"')
        if (-not [System.IO.Path]::IsPathRooted($dockerfilePath)) {
            $dockerfilePath = Join-Path (Get-Location) $dockerfilePath
        }
        if (-not (Test-Path -Path $dockerfilePath)) {
            $missingDockerfiles += $dockerfilePath
        }
    }

    if ($missingDockerfiles.Count -eq 0) {
        return $Primary
    }

    $missingList = $missingDockerfiles -join "`n- "

    if (-not (Test-Path -Path $Fallback)) {
        throw "Primary compose references missing Dockerfiles and fallback compose is missing.`nMissing Dockerfiles:`n- $missingList`nFallback compose: $Fallback"
    }

    Write-Warning "Primary compose references missing Dockerfiles. Falling back to: $Fallback`nMissing Dockerfiles:`n- $missingList"
    return $Fallback
}

$selectedCompose = Resolve-ComposeFile -Primary $ComposeFile -Fallback $FallbackComposeFile
Write-Host "Using DOCKER_HOST=$($env:DOCKER_HOST)"
Write-Host "Using compose file: $selectedCompose"

switch ($Command) {
    'up' {
        if ($Detached) {
            docker compose -f $selectedCompose up -d
        }
        else {
            docker compose -f $selectedCompose up
        }
    }
    'down' {
        docker compose -f $selectedCompose down
    }
    'ps' {
        docker compose -f $selectedCompose ps
    }
    'logs' {
        if ($Detached) {
            docker compose -f $selectedCompose logs --tail=200
        }
        else {
            docker compose -f $selectedCompose logs -f --tail=200
        }
    }
}
