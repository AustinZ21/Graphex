# Telemetry & Logging
- **Structured Logs**: Standard `console.log()` is FORBIDDEN in the backend. All logs MUST be structured JSON including `event_id`, `timestamp`, and `user_id`.
- **Custom Metrics**: When processing core transactions, autonomously add metrics (e.g., `orders_processed_total`).
- **Distributed Tracing**: Propagate OpenTelemetry logic for all inter-service `.fetch()` calls.
