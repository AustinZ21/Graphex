param(
    [Parameter(Mandatory = $false)]
    [string]$OutputFolder = (Join-Path $PSScriptRoot 'dist\CGA-Docker-Desktop')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$portableRoot = $OutputFolder

if (Test-Path $portableRoot) {
    Remove-Item -Path $portableRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $portableRoot | Out-Null
New-Item -ItemType Directory -Path (Join-Path $portableRoot 'repos') | Out-Null

$filesToCopy = @(
    @{ Source = Join-Path $repoRoot 'Dockerfile.dev'; Target = Join-Path $portableRoot 'Dockerfile.dev' },
    @{ Source = Join-Path $repoRoot 'docker-entrypoint.sh'; Target = Join-Path $portableRoot 'docker-entrypoint.sh' },
    @{ Source = Join-Path $repoRoot 'requirements.txt'; Target = Join-Path $portableRoot 'requirements.txt' },
    @{ Source = Join-Path $PSScriptRoot 'start-desktop.ps1'; Target = Join-Path $portableRoot 'start-desktop.ps1' },
    @{ Source = Join-Path $PSScriptRoot 'start-cga-desktop.cmd'; Target = Join-Path $portableRoot 'start-cga-desktop.cmd' },
    @{ Source = Join-Path $PSScriptRoot 'open-cga-desktop.cmd'; Target = Join-Path $portableRoot 'open-cga-desktop.cmd' },
    @{ Source = Join-Path $PSScriptRoot 'status-cga-desktop.cmd'; Target = Join-Path $portableRoot 'status-cga-desktop.cmd' },
    @{ Source = Join-Path $PSScriptRoot 'logs-cga-desktop.cmd'; Target = Join-Path $portableRoot 'logs-cga-desktop.cmd' },
    @{ Source = Join-Path $PSScriptRoot 'stop-cga-desktop.cmd'; Target = Join-Path $portableRoot 'stop-cga-desktop.cmd' }
)

foreach ($item in $filesToCopy) {
    Copy-Item -Path $item.Source -Destination $item.Target -Force
}

Copy-Item -Path (Join-Path $repoRoot 'src') -Destination (Join-Path $portableRoot 'src') -Recurse -Force

$portableCompose = @"
name: cga-desktop-portable

services:
  cga:
    build:
      context: .
      dockerfile: Dockerfile.dev
    image: cga-desktop-portable-cga:local
    restart: unless-stopped
    ports:
      - "{CGA_DESKTOP_API_PORT:-18001}:8000"
    env_file:
      - path: .env
        required: false
    environment:
      - FALKORDB_HOST=falkordb
      - FALKORDB_PORT=6379
      - FALKORDB_URL=falkor://falkordb:6379
      - FALKORDB_URL_HOST=redis://localhost:{CGA_DESKTOP_FALKORDB_PORT:-16381}
      - FALKORDB_BROWSER_URL=http://falkordb:3000
      - FALKORDB_BROWSER_PUBLIC_URL=http://localhost:{CGA_DESKTOP_BROWSER_PORT:-13001}
      - QUEUE_REDIS_URL=redis://redis:6379/1
      - CACHE_REDIS_URL=redis://redis:6379/2
      - AUTH_DB_PATH=/app/data/auth.db
      - JWT_SECRET_KEY={JWT_SECRET_KEY:-change-me-at-least-32-chars!!!!!}
      - ADMIN_USERNAME={ADMIN_USERNAME:-admin}
      - ADMIN_PASSWORD={ADMIN_PASSWORD:-changeme}
      - GITHUB_OAUTH_CALLBACK_URL={GITHUB_OAUTH_CALLBACK_URL:-http://localhost:{CGA_DESKTOP_API_PORT:-18001}/api/auth/github/callback}
      - PYTHONPATH=/app/src
      - MCP_ACCESS_TOKEN={MCP_ACCESS_TOKEN:-}
    volumes:
      - auth_db_data:/app/data
      - "{CGA_REPOS_MOUNT:-./repos}:/repos:ro"
    depends_on:
      falkordb:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  falkordb:
    image: falkordb/falkordb:latest
    restart: unless-stopped
    ports:
      - "{CGA_DESKTOP_FALKORDB_PORT:-16381}:6379"
      - "{CGA_DESKTOP_BROWSER_PORT:-13001}:3000"
    volumes:
      - falkordb_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 20s

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3

volumes:
  auth_db_data:
  falkordb_data:
  redis_data:
"@

$portableCompose = $portableCompose.Replace([char]0x7f, '$')
Set-Content -Path (Join-Path $portableRoot 'docker-compose.yml') -Value $portableCompose -Encoding UTF8

$portableEnv = @"
# CGA portable Docker Desktop bundle settings
CGA_DESKTOP_API_PORT=18001
CGA_DESKTOP_FALKORDB_PORT=16381
CGA_DESKTOP_BROWSER_PORT=13001

# Drop repositories you want to index into the local ./repos folder,
# or point this at another host folder.
CGA_REPOS_MOUNT=./repos

JWT_SECRET_KEY=change-me-at-least-32-chars!!!!!
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme

MCP_ACCESS_TOKEN=
GITHUB_OAUTH_CLIENT_ID=
GITHUB_OAUTH_CLIENT_SECRET=
GITHUB_OAUTH_CALLBACK_URL=http://localhost:18001/api/auth/github/callback
"@
Set-Content -Path (Join-Path $portableRoot '.env.example') -Value $portableEnv -Encoding UTF8

$portableDockerIgnore = @"
.env
.env.*
!.env.example
repos
tmp
*.log
Thumbs.db
.DS_Store
"@
Set-Content -Path (Join-Path $portableRoot '.dockerignore') -Value $portableDockerIgnore -Encoding UTF8

$portableReadme = @"
# CGA Portable Docker Desktop Package

This folder is a self-contained CGA package for Docker Desktop.

## Use

1. Copy repository folders you want to analyze into `repos`.
2. Double-click `start-cga-desktop.cmd`.
3. Open `http://localhost:18001/admin` if the browser does not open automatically.

## Included Launchers

- `start-cga-desktop.cmd`
- `open-cga-desktop.cmd`
- `status-cga-desktop.cmd`
- `logs-cga-desktop.cmd`
- `stop-cga-desktop.cmd`

## Notes

- The first startup builds the local CGA image from the packaged source files.
- Edit `.env` if you want different ports, credentials, or a different `CGA_REPOS_MOUNT` path.
- The default repo drop location is the local `repos` folder beside this README.
- The packaged `.dockerignore` excludes `repos` so added user repositories do not bloat the Docker build context.
"@
Set-Content -Path (Join-Path $portableRoot 'README.md') -Value $portableReadme -Encoding UTF8

New-Item -ItemType File -Path (Join-Path $portableRoot 'repos\.gitkeep') -Force | Out-Null
Set-Content -Path (Join-Path $portableRoot 'repos\README.txt') -Value "Drop repositories to index in this folder, or edit .env and point CGA_REPOS_MOUNT at another host folder." -Encoding UTF8

Write-Host "Portable bundle created at: $portableRoot"