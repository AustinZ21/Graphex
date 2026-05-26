# CGA Docker Desktop Bundle

This folder is the recommended local distribution for non-developer Docker Desktop usage.

## What It Does

- Builds the CGA API image directly from the checked-out repository.
- Starts CGA, FalkorDB, and Redis with one command.
- Stores the last active local ports in `tmp/cga-desktop-runtime.json` so the reopen launcher can find the correct URL.

## One-Click Windows Launchers

- `start-cga-desktop.cmd`: start the stack and open the Admin UI
- `open-cga-desktop.cmd`: reopen the Admin UI using the saved desktop port
- `status-cga-desktop.cmd`: show container state and the current URLs
- `stop-cga-desktop.cmd`: stop the stack
- `logs-cga-desktop.cmd`: follow the container logs

## Build A Portable Package

- Run `build-portable-bundle.cmd`.
- It creates `dist/CGA-Docker-Desktop` with a self-contained copy of the launcher, Docker build files, and a local `repos` folder.
- That generated folder is the one you can zip and hand to a non-developer user.

## Build A Versioned Release Zip

- Run `build-release-bundle.cmd`.
- It reads the current CGA app version and creates both:
	- `dist/releases/CGA-Docker-Desktop-<version>`
	- `dist/releases/CGA-Docker-Desktop-<version>.zip`
- That zip is the recommended release artifact to publish or send to another user.

## Default URLs

- Admin UI: `http://localhost:18001/admin`
- MCP SSE (`cga-mcp-server`): `http://localhost:18001/mcp/sse`
- FalkorDB Browser: `http://localhost:13001`

## First Run

1. Install Docker Desktop.
2. Open this folder in File Explorer.
3. Double-click `start-cga-desktop.cmd`.
4. Wait for the browser to open the Admin UI.

If `.env` does not exist yet, the launcher creates it from `.env.example` automatically.
The first launch takes longer because Docker Desktop builds the CGA API image from local source.

## Configuration

Edit `.env` in this folder when you want fixed credentials, fixed ports, or a different code mount.

Important settings:

- `CGA_REPOS_MOUNT`: host folder mounted into `/repos`
- `CGA_DESKTOP_API_PORT`: Admin and MCP host port
- `CGA_DESKTOP_FALKORDB_PORT`: FalkorDB host port
- `CGA_DESKTOP_BROWSER_PORT`: FalkorDB Browser host port
- `ADMIN_USERNAME` / `ADMIN_PASSWORD`: local login

When this bundle stays inside the CGA repository, the default `CGA_REPOS_MOUNT=../../` points back to the repository root. If you copy this folder somewhere else, change that path to the code folder you want indexed and also update `docker-compose.yml` build context paths.