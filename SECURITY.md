# Security Policy

CGA is local-first developer infrastructure, but it can hold sensitive project
metadata, tokens, audit logs, and repository context. Please report security
issues responsibly.

## Reporting A Vulnerability

Do not open a public issue for an unpatched vulnerability. Use a private GitHub
Security Advisory when available, or contact the maintainers through the
repository owner's published contact path.

Please include:

- Affected version or commit.
- A clear description of the issue.
- Steps to reproduce, proof of concept, or logs when safe to share.
- Expected impact and any known mitigations.

Do not include real secrets, production tokens, private keys, or confidential
third-party data in the report.

## Supported Versions

Security fixes are prioritized for the current published release line and the
active development branch. Older local builds should be upgraded before exposing
CGA beyond localhost.

## Security Baselines

- Change default admin credentials and `JWT_SECRET_KEY` before any non-local
  deployment.
- Keep MCP access protected by project-scoped tokens.
- Do not commit `.env`, runtime databases, backups, deploy keys, or generated
  local artifacts.
- Run dependency and container vulnerability checks before public releases.
