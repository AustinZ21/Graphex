# Security & Vulnerability Management
- **Inviolable Rule**: Do NOT introduce dependencies with a CVSS score >= 7.0.
- **Input Sanitization**: All external inputs MUST run through the Zod validation middleware before reaching controllers.
- **Secret Management**: NEVER hardcode API keys. All keys MUST be retrieved at runtime via `aws-secrets-manager`.

## Token Security Policy (JWT and Opaque Tokens)
- **Approved JWT Algorithms**: Use `RS256` or `ES256` for multi-service and third-party trust boundaries. `HS256` is allowed only for internal-only services with strong secret management.
- **JWT Signing Key Strength**: HMAC signing keys MUST be at least 256 bits (32 random bytes). RSA keys MUST be at least 2048 bits.
- **JWT Claim Requirements**: Every JWT MUST include `iss`, `sub`, `aud`, `exp`, `iat`, and `jti`.
- **JWT Lifetime Limits**: Access tokens MUST expire in 15 minutes or less. Refresh tokens MUST be rotated on every use and revoked on suspected compromise.
- **Forbidden JWT Practices**: `alg=none`, static/non-random `jti`, or long-lived bearer tokens without revocation capability are strictly forbidden.

## Token Entropy and Generation Requirements
- **CSPRNG Requirement**: All tokens MUST be generated using a cryptographically secure random generator.
- **Minimum Entropy**: Opaque tokens (session IDs, API keys, refresh tokens, password reset tokens, email verification tokens) MUST provide at least 128 bits of entropy. 192 bits or higher is recommended for long-lived tokens.
- **Encoding Guidance**: If base64url is used, token length MUST preserve required entropy (for example, at least 22 base64url chars for 128-bit entropy, at least 43 chars for 256-bit entropy).
- **Single-Use and Expiry**: Password reset and one-time verification tokens MUST be single-use and MUST expire quickly.
- **Storage and Logging**: Raw tokens MUST NOT be stored in plaintext where avoidable and MUST NEVER be written to logs.

## Common Security Strategies
- **Least Privilege Access**: Grant users, services, and CI jobs only the minimum permissions required, and review privileges regularly.
- **Defense in Depth**: Apply layered controls across application, infrastructure, and network boundaries so one control failure does not expose critical assets.
- **Secure by Default Configuration**: Default new services to deny-all network posture, strict auth requirements, and disabled debug/admin surfaces.
- **Strong Authentication and Authorization**: Enforce strong identity verification, short-lived credentials, and explicit authorization checks on every protected action.
- **Encryption in Transit and at Rest**: Require TLS for all external and internal service communication and encrypt sensitive persisted data with managed keys.
- **Input Validation and Output Encoding**: Validate all untrusted input against strict schemas and encode output contexts to prevent injection vulnerabilities.
- **Dependency and Supply Chain Security**: Pin dependencies, run vulnerability scans in CI, verify package integrity, and remove unused packages.
- **Secret Lifecycle Management**: Store secrets in dedicated secret managers, rotate on schedule, and revoke immediately on exposure suspicion.
- **Secure Logging and Monitoring**: Use structured logs without sensitive payloads, alert on anomalous auth/access patterns, and preserve audit trails.
- **Patch and Vulnerability Management**: Apply security updates quickly, track temporary exceptions with expiry, and require owner accountability.
- **Incident Response Readiness**: Maintain runbooks for detection, containment, recovery, and post-incident review with assigned responders.
- **Backup and Recovery Validation**: Protect backups with encryption and test restore procedures regularly to ensure recovery objectives are achievable.

## Version, Update, and Patch Security Strategies
- **Security-First Versioning**: Treat security fixes as highest-priority releases and publish versioned patch notes with risk and remediation context.
- **Patch Cadence Policy**: Apply routine dependency and base-image updates on a fixed schedule, with emergency out-of-band patches for critical vulnerabilities.
- **Risk-Based Prioritization**: Prioritize updates by exploitability and asset exposure, not only by CVSS score.
- **Time-Bounded Exceptions**: Any temporary vulnerability exception MUST include owner, justification, and explicit expiry date enforced in CI.
- **Canary and Rollback Safety**: Roll out sensitive security updates in stages and maintain tested rollback paths for failed deployments.
- **Compatibility and Regression Gates**: Security-related upgrades MUST pass automated tests, policy checks, and smoke validation before merge.
- **Provenance and Integrity Verification**: Verify package source integrity and prefer trusted registries and signed artifacts when available.
- **SBOM and Inventory Tracking**: Maintain current dependency inventory (including transitive packages) to accelerate impact analysis during advisories.
- **End-of-Life Component Policy**: Replace unsupported runtimes, frameworks, and libraries on a defined timeline; do not defer EOL remediation indefinitely.
- **Post-Patch Verification**: After applying critical patches, validate control effectiveness with targeted checks and document evidence in reports.
