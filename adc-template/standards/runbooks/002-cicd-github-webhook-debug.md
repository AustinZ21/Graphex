# Runbook: Full CI/CD Setup + Debug Playbook (GitHub + Webhook Deploy)

## 1. Objective
Use this runbook to ensure:
- Push to target branch triggers deployment automatically.
- Deployment pipeline is observable and auditable.
- Failures can be isolated quickly (target: within 10 minutes).

## 2. Required Baseline Inputs
Define before setup:
- GitHub repository URL and owner/name.
- Deployment webhook endpoint (`DEPLOY_WEBHOOK_URL`).
- Deployment branch (production default: `main`).
- Trigger mode:
  - webhook-driven auto deploy (preferred)
  - manual trigger fallback
- Environment policy:
  - `main -> production`
  - `dev/* -> non-prod/staging`

## 3. Required Secrets and Environment Variables
Store in secure runtime configuration and never commit to Git:
- `GITHUB_URL`
- `GITHUB_TOKEN` (permission to manage repo hooks)
- `GITHUB_WEBHOOK_SECRET`
- `DEPLOY_WEBHOOK_URL`

## 3.1 Preflight Gate (Mandatory Order)
Before any webhook configuration steps:
1. Confirm admin token exists: `GITHUB_TOKEN`.
2. Confirm deployment target exists: `DEPLOY_WEBHOOK_URL`.
3. Confirm CI/CD mode is enabled: `CICD=enabled` (legacy `CICD_Enabled=true` accepted).
4. Validate token and endpoint health before proceeding:
  - Validate GitHub token with `GET /user`.
  - Validate deployment webhook endpoint reachability.
5. Only if all checks pass, continue with branch alignment and webhook setup.

## 4. Canonical Trigger Flow
Expected deployment chain:
1. Developer pushes to target branch.
2. GitHub emits push event.
3. GitHub webhook calls deployment webhook endpoint.
4. Deployment platform queues deployment.
5. Deployment platform pulls target branch commit.
6. Build and startup run.
7. Health checks pass.
8. Deployment is considered successful.

## 5. One-Time Setup Procedure
Execute once per app:
1. Ensure deployment target is configured to accept webhook-triggered deployments.
2. Ensure deployment target branch equals deployment branch.
3. In GitHub repo, create webhook:
   - event: push only
  - URL: deployment webhook endpoint
   - content type: `json`
  - secret: same value as `WEBHOOK_SECRET`
4. Run webhook test delivery from GitHub and require HTTP 2xx.
5. Confirm deployment appears in deployment history/queue.
6. Run one manual deployment trigger as fallback validation.

## 6. Common Root Causes (Priority Order)
1. Deployment branch does not match pushed branch.
2. Webhook secret mismatch between GitHub and deployment target.
3. Wrong webhook URL/path.
4. GitHub -> deployment target network/TLS/firewall issue.
5. Tokens exist in local `.env` but no setup process actually uses them.
6. Webhook disabled or filtered by wrong branch.

## 7. Fast Debug Sequence (Follow In Order)
### Step A: Verify Git state
- Confirm latest commit exists on remote target branch.
- Confirm push branch matches deployment branch policy.

### Step B: Verify deployment target config
- Target is reachable and active.
- Deployment branch equals target branch.

### Step C: Verify GitHub webhook config
- `active = true`
- events = push only
- `branch_filter` matches target branch
- webhook URL and secret are correct

### Step D: Verify event delivery
- Run "Test Delivery" in GitHub.
- Require HTTP 2xx.
- If not 2xx, inspect response body and fix URL/secret/network.

### Step E: Verify deployment queue
- A new deployment record appears.
- Commit SHA matches pushed SHA.
- Locate failure stage: pull/build/runtime/health-check.

### Step F: Fallback manual deploy test
- Trigger deployment manually from your deployment platform.
- If manual deploy works but webhook deploy does not: issue is webhook path/config.
- If manual deploy also fails: issue is app config, build runtime, or health checks.

## 8. Security Concerns and Required Mitigations
- Do not use broad admin tokens unless absolutely required; prefer scoped service tokens.
- Never print secrets in logs or terminal output.
- Rotate `GITHUB_TOKEN` and `WEBHOOK_SECRET` on schedule and after exposure risk.
- Restrict webhook to push event and production branch filter.
- Ensure webhook endpoint uses HTTPS with valid TLS.
- Keep `.env` and CI secret stores access-limited by least privilege.
- Maintain immutable deployment and webhook delivery audit logs.
- Verify rollback path before production go-live.

## 9. Production Readiness Gate
Before go-live:
1. Push a test commit to deployment branch.
2. Confirm auto-deploy triggers without manual action.
3. Confirm deployed commit SHA matches pushed SHA.
4. Confirm health checks pass.
5. Confirm rollback path has been tested.
6. Document branch policy, webhook URL, and secret ownership in operations docs.
