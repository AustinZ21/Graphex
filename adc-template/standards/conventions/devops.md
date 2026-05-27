# DevOps Workflow Policy

## Branching and Check-In Rules
- **No Direct Check-In to `main`**: Direct commits or direct pushes to the `main` branch are forbidden.
- **Required Development Branch**: All code check-ins MUST be performed on a dedicated development branch named `dev/<scope>` (or `dev/<scope>-<ticket>`).
- **Merge Path**: Changes MUST be merged into `main` only through a reviewed Pull Request.
- **Pre-Merge Gates**: Required CI checks and policy checklist validation MUST pass before merge.
- **Hotfix Exception**: Emergency hotfixes may use `hotfix/<scope>` branches, but direct commits to `main` are still forbidden.

## Deploy Key Handling Policy
- **Documentation Location**: The active public deploy key MUST be recorded in `docs/deploy_key.md`.
- **Preferred Source**: Reuse an existing approved public deploy key when available.
- **Fallback Generation**: If no approved deploy key exists, generate a new SSH key pair without passphrase and record the public key in `docs/deploy_key.md`.
- **No Private Key in Repo**: Private keys MUST NEVER be committed to the repository.
- **Rotation Update**: When deploy keys rotate, `docs/deploy_key.md` MUST be updated in the same change set.

## ContextGraph Integration Policy
- **Authoritative Onboarding URL**: Integration with ContextGraph MUST use the CGA Admin UI at `http://localhost:18001/admin` as the local setup surface for project registration and token creation.
- **Mandatory Registration**: All ADC-compliant projects MUST be registered in CGA before feature work begins unless CGA is temporarily unavailable and the exception is documented.
- **Automatic MCP Installation**: Project bootstrap SHOULD automatically install or refresh the paired `cga-mcp-server` profile in `.adc/contextgraph-edge-agent/mcp/mcp-servers.json` using environment-variable backed credentials.
- **No Unreviewed Deviation**: Agents and developers MUST NOT use alternate ContextGraph onboarding flows unless explicitly approved in the same PR description.
- **Traceability Requirement**: Any PR that introduces or changes ContextGraph integration MUST include a short "ContextGraph integration notes" section describing what step(s) from the onboarding URL were applied.
- **MCP Alignment**: If ContextGraph integration adds or changes external service endpoints or credentials, `mcp-servers.json` MUST be updated in the same change set.

## ContextGraph Edge Agent and ContextGraph MCP Use Policy
- **Responsibility Split**: `contextgraph-edge-agent/` is for local orchestration artifacts (task queues, scratchpad notes, MCP wiring). ContextGraph MCP is for programmatic integration/retrieval against ContextGraph services.
- **CGA MCP Server Profile Baseline**: ADC templates MUST ship a `cga-mcp-server` entry in `.adc/contextgraph-edge-agent/mcp/mcp-servers.json` so downstream repositories auto-inherit CGA MCP Server wiring.
- **Runtime Neutrality**: MCP wiring MUST be language-agnostic by default. Do not require a Node-specific local entrypoint unless that repository explicitly ships and maintains one.
- **Execution Policy**: ContextGraph MCP MUST NOT be used to replace local compile, lint, unit test, or integration test execution. Build/test must run through project-native tooling.
- **Authority Policy**: Outputs from ContextGraph Edge Agent scratchpad/tasks are operational context, not product truth. Canonical product rules remain in constitution/convention/planning files.
- **Network Policy**: Local ContextGraph services are expected on localhost endpoints; upstream ContextGraph access MUST use the configured upstream URL and approved credentials only.
- **Default MCP Endpoint**: Local dev MCP clients SHOULD use `http://localhost:18001/mcp/sse` unless the CGA deployment explicitly advertises a different MCP SSE endpoint.
- **Secret Policy**: Tokens and project identifiers (`CONTEXTGRAPH_MCP_TOKEN`, `CONTEXTGRAPH_EDGE_AGENT_TOKEN`, `CONTEXTGRAPH_PROJECT_ID`) MUST be injected via environment variables and never committed to repository files.
- **Change Policy**: Any PR changing ContextGraph integration behavior MUST update both `bootstrap.md` and `mcp-servers.json`, and include validation notes.

## CGA Progress Reporting and Indexing Policy
- **Automatic Progress Reporting**: Projects SHOULD emit periodic progress reports to CGA through the project work briefing API or `workassist_record_activity` MCP tool for service starts, template generation, feature milestones, validation runs, and releases.
- **Change Indexing**: After meaningful source, documentation, configuration, or test changes, agents SHOULD run `index_repo_changes(repo_path)` through `cga-mcp-server` so CGA indexes modified content.
- **Periodic Indexing**: Long-running projects SHOULD schedule periodic incremental indexing even when no single task explicitly requests it, so CGA remains current.
- **Failure Handling**: If CGA reporting or indexing fails, continue local build/test validation, record the failure in `.adc/contextgraph-edge-agent/scratchpad/session.md`, and retry when CGA is reachable.

## CI/CD Policy (GitHub + Webhook Deploy)

### Conditional Initialization Rule
- If `.env` includes `CICD=enabled` (or legacy `CICD_Enabled=true`), `GITHUB_TOKEN`, and `DEPLOY_WEBHOOK_URL`, the automation workflow MUST ask the user to confirm initialization before making CI/CD changes.
- Confirmation text MUST clearly state target repo, deployment webhook endpoint, deployment branch, and whether deployment test trigger is enabled.

### Baseline Inputs
- Git provider and repository URL MUST be defined using GitHub.
- ADC source distribution and checkins MUST target `git@github.com:nascousa/ADC.git`; future ADC changes MUST NOT check in to `nasco_microsoft`.
- Deployment target MUST include a reachable deployment webhook endpoint.
- Production deployment branch is `main` unless explicitly overridden.
- Branch policy: `main -> production`, `dev/* -> staging/non-prod`.

### Trigger and Fallback Model
- Preferred mode is **Webhook-driven auto deploy** on push events for target branch.
- Fallback mode is manual deployment trigger from deployment platform tooling.
- Canonical trigger chain: push -> GitHub push event -> webhook delivery -> deployment queue -> build/startup -> health check pass.

### Secret and Security Controls
- Required environment variables: `GITHUB_URL`, `GITHUB_TOKEN`, `DEPLOY_WEBHOOK_URL`.
- Recommended variable: `WEBHOOK_SECRET` for explicit secret ownership and rotation.
- Admin tokens MUST NOT be logged, echoed, or written to tracked files.
- Tokens MUST use least privilege and be scoped to repo-hook management (GitHub) and deployment operations for your target platform.
- CI/CD setup jobs MUST fail closed if webhook secret synchronization fails.
- Webhook events MUST be restricted to push events and branch-filtered to target branch.
- CI/CD setup output MUST provide an auditable summary without exposing sensitive values.

### Required Validation Sequence
- Validate GitHub token with `GET /user`.
- Validate deployment webhook endpoint reachability.
- Ensure deployment target branch equals configured deployment branch.
- Create or update GitHub webhook with push-only events and matching secret.
- Execute webhook test delivery and require HTTP 2xx.
- Verify deployment appears in deployment queue and commit SHA matches pushed SHA.

## Docker Compose Health Check Policy
- Every service in every `docker-compose.yml` / `docker-compose.yaml` file MUST include the following health check block (unless a stricter service-specific endpoint is explicitly approved):

```yaml
healthcheck:
	test:
		- CMD
		- curl
		- '-f'
		- 'http://localhost:8000/health'
	interval: 30s
	timeout: 10s
	retries: 3
	start_period: 40s
```


