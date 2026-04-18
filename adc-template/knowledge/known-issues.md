# Technical Debt & No-Touch Zones
- `src/legacy-billing/`: **DO NOT TOUCH**. This is a fragile legacy sub-system. Only modify if explicitly instructed by human to fix a critical P0 bug.
- The `AuthService` class currently has tight coupling with the Redis cache. Do not attempt to refactor this class without explicit permission.
