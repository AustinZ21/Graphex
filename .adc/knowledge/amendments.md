# Constitutional Amendments
*All changes to the rules inside the `.adc` directory MUST be proposed via PR with the `[AMENDMENT]` prefix. It MUST NOT be modified autonomously without human ratification.*

- **2026-03-13**: Digital Constitution initial ratification. V1.0.0 created.
- **2026-03-23**: Added ContextGraph integration policy in `standards/conventions/devops.md` to require onboarding via `http://localhost:8000/getstarted` and enforce PR traceability/MCP alignment.
- **2026-04-18**: Added `cg-edge-mcp-server` as the ADC baseline MCP plugin profile so downstream ADC projects auto-inherit ContextGraph Edge MCP Server wiring and guidance.
- **2026-04-18**: Updated CG Edge MCP baseline to endpoint-first, language-agnostic wiring so repositories are not forced to provide a local Node entrypoint.
- **2026-04-18**: Added default token generation policy: unless explicitly overridden by target system requirements, tokens MUST use cryptographically random 35-character values restricted to `A-Za-z0-9`.


