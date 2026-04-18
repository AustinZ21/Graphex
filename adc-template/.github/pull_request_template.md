## Summary

Describe what changed and why.

## Validation

- [ ] Unit/E2E tests pass locally
- [ ] New dependencies were checked for CVEs/CVSS threshold policy
- [ ] This change was developed on `dev/*` (or `hotfix/*`) branch and not committed directly to `main`
- [ ] `docs/deploy_key.md` is updated with the current public deploy key when deploy credentials changed
- [ ] Mermaid diagrams were updated if architecture/data-flow/schema changed
- [ ] Docker CPU/Memory limits are configured via env variables when applicable

## Policy Checklist

- [ ] JWT/token entropy policy applied (algorithm, key strength, claims, TTL, rotation)
- [ ] Data policy applied for pgvector/sqlite-vec/graph usage and index/query constraints
