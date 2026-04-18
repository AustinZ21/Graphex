# Test-Driven Development (TDD)
- **TDD Enforcement**: You MUST write the failing tests in the `tests/` directory **FIRST**, and ONLY write the business implementation in `src/` after tests are written.
- **MockDB**: Use `src/utils/mockFactory.ts` instead of hitting the live PostgreSQL database instance for unit tests.
- **LOC Coverage (Line of Code Coverage) Definition**: `LOC Coverage = (Executed Coverable Lines / Total Coverable Lines) * 100`.
- **Coverable Lines Scope**: Count executable lines only; exclude blank lines, comments, generated files, and non-executable declarations.

## Common Test and Software Quality Strategies
- **Risk-Based Test Pyramid**: Prioritize many unit tests, targeted integration tests, and a small number of end-to-end smoke tests.
- **Optional VS Code Integrated Browser**: During manual verification or UI-focused test debugging, you MAY use the VS Code built-in Integrated Browser when needed.
- **Branch Coverage Focus**: Measure branch coverage in addition to line coverage for critical logic and decision paths.
- **Critical-Path Coverage Targets**: Apply stricter coverage expectations for security-sensitive and business-critical modules.
- **Changed-Code Accountability**: New or modified behavior MUST include corresponding tests in the same change set.
- **Regression Safeguards**: Preserve tests for previously fixed defects to prevent recurrence.
- **Deterministic Test Design**: Avoid flaky tests by controlling time, randomness, and external dependencies.
- **Contract and Boundary Testing**: Verify request/response contracts and failure handling at system boundaries.
- **Golden/Snapshot Validation**: For template-driven outputs, use golden or snapshot tests to detect unintended drift.
- **Security Test Coverage**: Include tests for auth, input validation, secret handling, and fail-closed behavior.
- **Mutation Testing for Core Rules**: Periodically apply mutation testing to critical modules to assess assertion quality.

## Coverage Governance
- **Minimum Baseline**: Maintain at least 80% line coverage for the repository unless an approved exception exists.
- **No Silent Gaps**: Untested critical-path code is treated as incomplete work.
- **Evidence in Reports**: Record notable coverage changes and test strategy updates in project reports.
