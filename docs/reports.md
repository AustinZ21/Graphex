# Project Update Report

Date: 2026-03-26
Repository: ADC

## Scope
This report captures the latest repository structure and convention updates requested during the current session.

## Completed Changes
1. Renamed ADC workspace folder from `agent-workspace` to `cga-relay` under the template.
2. Added ContextGraph integration requirements:
   - ContextGraph project registration endpoint
   - CGA-Relay integration guidance
   - CGA MCP Server integration guidance
3. Standardized build output location to `src/dist`.
4. Added and standardized runtime log location at `src/log`.
5. Renamed source utility scripts folder from `src/scripts` to `src/script` and aligned documentation references.
6. Added terminology glossary file with workflow and platform terms, including CPMD.

## Current Repository Structure
- Source code package: `src/backend/`
- Test suite: `src/tests/`
- Operational scripts: `src/scripts/`
- Runtime logs directory: `src/logs/`
- Public/project documentation: `docs/`
- ADC template source: `adc-template/`

## Workflow Term
- CPMD: checkin, push, merge, deploy.

## Notes
- Changes above were applied to repository files and conventions so future generated templates align with the same structure.

## Security Exception Register
- ID: `CVE-2026-4539`
- Package: `pygments` (`2.19.2`)
- Scope: Temporary CI ignore in `pip-audit` only.
- Expiry: `2026-04-15` (hard-fail enforced in CI after this date).
- Owner: Repository maintainers.
- Required action: remove ignore and upgrade to a fixed version as soon as upstream publishes a patched release.


