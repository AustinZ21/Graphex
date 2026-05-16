# Publishing CGA (ContextGraphAdmin)

This guide covers the public GitHub release path for CGA, aka ContextGraphAdmin: source code, Docker images, and a one-file runtime compose download.

## Release Channels

- Source download: GitHub automatically provides zip/tarball downloads for every release tag.
- Runtime bundle: the release workflow attaches `cga-<version>.tar.gz`, `docker-compose.release.yml`, and `SHA256SUMS.txt`.
- Container image: tag pushes publish the API/runtime image to GitHub Container Registry:
  - `ghcr.io/nascousa/cga-api:<tag>`

## Maintainer Preflight

Before the first public release:

1. Confirm the MIT license in `LICENSE` is still the intended public license.
2. Confirm `.env`, `.deploy-keys/`, `data/`, `tmp/`, logs, local databases, and private keys are not tracked.
3. Update `README.md` version and date.
4. Run local validation from the repository root:

```bash
docker compose --profile dev config
docker compose --profile dev up --build
```

Then open `http://localhost:8001/admin` and `http://localhost:8001/mcp`.

## Tag Release Flow

Use Semantic Versioning tags. Example for `1.29.85`:

```bash
git status --short
git checkout main
git pull origin main
git tag -a v1.29.85 -m "CGA v1.29.85"
git push origin v1.29.85
```

Pushing the tag runs `.github/workflows/release.yml`, which builds and publishes GHCR images and creates a GitHub Release.

## User Install From Source

```bash
git clone https://github.com/nascousa/cga.git
cd cga
cp .env.example .env
docker compose --profile dev up --build
```

Open:
- Admin UI: `http://localhost:8001/admin`
- MCP discovery: `http://localhost:8001/mcp`
- FalkorDB Browser: `http://localhost:13000`

## User Install From Release Images

Download `docker-compose.release.yml` and `.env.example`, then run:

```bash
cp .env.example .env
docker compose -f docker-compose.release.yml up -d
```

Open:
- Admin UI: `http://localhost:8000/admin`
- MCP discovery: `http://localhost:8000/mcp`
- FalkorDB Browser: `http://localhost:13000`

Pin a specific release image by setting `CGA_VERSION` in `.env`:

```bash
CGA_VERSION=v1.29.85
```

## GitHub Repository Settings

Recommended settings for a public launch:

- Repository name: `cga` under `nascousa`.
- Repository visibility: Public.
- Actions permissions: allow GitHub Actions to create releases and write packages.
- Packages: after first GHCR publish, make packages public if GitHub does not inherit repository visibility automatically.
- Pages: keep the existing docs workflow enabled if you want README/docs published as a static site.
- About section: set description, topics, and website URL.

Suggested topics: `mcp`, `ai-agents`, `code-indexing`, `graph-database`, `falkordb`, `developer-tools`.

If GitHub returns `Public repositories are not permitted for Enterprise Managed Organizations`, the repository cannot be made public under that organization. Use a public-capable organization/account or ask the enterprise administrator to enable public repositories before tagging the public release.

## Security Notes

- Never commit real `.env` files, tokens, OAuth secrets, private keys, SQLite auth databases, or deployment keys.
- Change `JWT_SECRET_KEY`, `ADMIN_USERNAME`, and `ADMIN_PASSWORD` before exposing the service beyond localhost.
- For public deployments, put the API behind TLS and restrict MCP access with project-scoped tokens.