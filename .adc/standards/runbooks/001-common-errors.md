# Runbook: Common Errors and Self-Healing Strategies

When you encounter specific errors in CI/CD or local environment execution, apply the following remedies BEFORE modifying any source code:

## 1. JavaScript heap out of memory
**Symptom:** The build step fails with `FATAL ERROR: Ineffective mark-compacts near heap limit Allocation failed - JavaScript heap out of memory`.
**Remedy:** Try exporting `NODE_OPTIONS=--max_old_space_size=4096` before re-running the build. Do NOT change application code to fix this.

## 2. Docker container cannot mount local volume
**Symptom:** Permission denied when accessing a volume bind mount in Docker.
**Remedy:** Ensure your `.env` contains the correct host user mapping or run the init script `scripts/setup-permissions.sh` before running docker-compose.
