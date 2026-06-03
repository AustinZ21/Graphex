# CGA Runtime Operations

This guide keeps operational details out of the README while preserving the setup and maintenance notes needed by users and maintainers.

## Supported Local Runtimes

### Docker Desktop Bundle

The Docker Desktop bundle is the recommended local distribution for non-developer Windows usage.

- Entry folder: `deploy/docker-desktop`
- Admin UI: `http://localhost:18001/admin`
- MCP SSE: `http://localhost:18001/mcp/sse`
- FalkorDB Browser: `http://localhost:13001`

One-click launchers:

- `start-cga-desktop.cmd`: starts containers and opens the Admin UI.
- `open-cga-desktop.cmd`: reopens the Admin UI using the last saved desktop port.
- `stop-cga-desktop.cmd`: stops the desktop stack.
- `logs-cga-desktop.cmd`: tails desktop stack logs for support and debugging.

### Repository-Root Desktop Stack

Use this when developing from the repository but wanting the desktop-style port layout and runtime isolation.

```powershell
Copy-Item .env.example .env
./src/scripts/start-desktop.ps1 start
```

Useful commands:

```powershell
./src/scripts/start-desktop.ps1 status
./src/scripts/start-desktop.ps1 logs
./src/scripts/start-desktop.ps1 stop
./src/scripts/start-desktop.ps1 open
```

Set `CGA_DESKTOP_API_PORT`, `CGA_DESKTOP_FALKORDB_PORT`, or `CGA_DESKTOP_BROWSER_PORT` in `.env` or in the shell when fixed custom desktop ports are needed.

### Dev Compose Profile

Use this for source development and container rebuilds.

```powershell
Copy-Item .env.example .env
docker compose --profile dev up --build
```

Default URLs:

- Admin UI: `http://localhost:8001/admin`
- MCP discovery: `http://localhost:8001/mcp`
- FalkorDB Browser: `http://localhost:13000`

## Default Runtime Shape

For CGA local development, the default supported single-machine runtime is:

- Backend and Admin UI are served together by the single CGA API container.
- FastAPI serves `/admin` and the static frontend.
- FalkorDB stores graph data.
- PostgreSQL stores users, projects, tokens, audit logs, and work activity metadata.
- Redis supports runtime services.
- A backup sidecar snapshots runtime data when enabled by the active compose profile.

Legacy dev-profile helper commands remain available:

```powershell
./src/scripts/start-admin-s1.ps1 start
./src/scripts/start-admin-s1.ps1 status
./src/scripts/start-admin-s1.ps1 logs
./src/scripts/start-admin-s1.ps1 stop
```

## Work Briefing Aggregation

CGA includes a built-in work activity domain adapted from WorkAssist so cross-project progress can roll up into one admin surface.

- Admin UI: `http://localhost:18001/admin/briefing` in desktop mode.
- Admin summary API: `/api/admin/work-briefing`
- Admin activity list API: `/api/admin/work-briefing/activities`
- Project-scoped ingest API: `POST /api/project/work-briefing/activity`
- Project-scoped summary APIs: `GET /api/project/work-briefing`, `GET /api/project/work-briefing/activities`
- MCP tools: `workassist_record_activity`, `workassist_list_recent_activity`, `workassist_get_activity_briefing`

The Admin briefing dashboard includes copyable PowerShell, Python, and JSON request templates for project-scoped activity publishing. The Report tab can connect a Microsoft account with device-code login so generated WSR payloads can enrich stored PBI/PR references with Azure DevOps ticket details.

Recorded activity is stored in the local PostgreSQL auth database under the `work_activities` table, keeping project progress local-first alongside project and audit metadata.

## Admin Schedule Automation

CGA includes an admin-only Schedule surface for recurring automation jobs.

- Admin UI: `http://localhost:18001/admin/schedule` in desktop mode.
- Admin schedule API: `/api/admin/schedules`
- Supported task types: BrowserAgent command POSTs, BrowserAgent page-test workflows, agent activation HTTP calls, and generic HTTP POST jobs.
- BrowserAgent page tests can target a page URL, text assertions, console capture, metrics, screenshots, and optional DOM snapshots.
- Each task stores an 8-character task ID, cadence, runner URL, project binding, agent ID, JSON payload, last run status, next run time, and recent execution history.

A lightweight background worker runs due enabled tasks, carries the opened BrowserAgent tab ID through each page-test step, retries text assertions while the page settles, and records each result in `scheduled_task_runs`.

When scheduled tasks execute inside `cga-desktop-api`, `localhost:<port>` points to the container. Host-side BrowserAgent or workflow targets should use `host.docker.internal:<port>` and the target service must be listening on the host.

## Runtime Persistence And Backup

- CGA runtime state lives in PostgreSQL for users, projects, tokens, audit logs, and work activity records.
- FalkorDB stores repository graph data.
- Runtime UI configuration is persisted in `data/runtime-config.json` by default, or in `CGA_RUNTIME_CONFIG_PATH` when set.
- The Admin UI's System Settings / Indexing panel stores the default repos folder used when project indexing resolves a project without an explicit Repository Path.
- A backup sidecar dumps PostgreSQL with `pg_dump --format=plain | gzip` and FalkorDB runtime data into `data/backups/<stack>/` every hour by default.
- Override backup destination with `CGA_BACKUP_DIR` and the schedule with `CGA_BACKUP_INTERVAL_SECONDS` / `CGA_BACKUP_KEEP_COUNT`.
- Latest snapshots are written as `auth-latest.sql.gz` and `falkordb-latest.tgz` under the stack-specific backup folder.
- Restoring an auth snapshot uses `psql --single-transaction` and takes a pre-restore safety snapshot first.

The Admin UI's System Settings / Backup panel reads and writes the same folder, so manual Back Up Now, restore, and delete actions are visible to both the UI and sidecar.

## Desktop Bundle Packaging

Recommended non-technical distribution files live under `deploy/docker-desktop`.

Build a zip-ready self-contained package:

```powershell
Set-Location .\deploy\docker-desktop
./build-portable-bundle.ps1
```

Build a versioned release folder and zip archive:

```powershell
Set-Location .\deploy\docker-desktop
./build-release-bundle.ps1
```

The release builder produces `cga-desktop-api-image.tar` inside the release folder. The launcher loads that image automatically, so first startup does not need to build the CGA API image from source. Developers can still force the fallback build path with:

```powershell
./start-desktop.ps1 start -BuildFromSource
```

The Docker Desktop package intentionally uses `18001`, `16381`, and `13001` so it does not collide with the dev profile defaults. The launcher also saves the last active desktop ports under `tmp/cga-desktop-runtime.json` so reopening from a fresh shell still targets the correct local URL.

The release zip intentionally does not include local projects, private repositories, PostgreSQL data, FalkorDB graph indexes, Redis state, backups, or sample/demo project data. First run creates a fresh runtime, creates the configured admin account, and waits for you to add and index repositories.

Default local credentials come from the active launcher's `.env.example`. Change `JWT_SECRET_KEY`, `ADMIN_USERNAME`, and `ADMIN_PASSWORD` before exposing the service beyond localhost.