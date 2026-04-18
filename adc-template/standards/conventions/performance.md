# Performance & Optimization
- **Algorithmic Limit (Big-O)**: Avoid nested loops that result in O(N²) for data processing. Utilize HashMaps or Set lookups to achieve O(N) where applicable.
- **Data Fetching Limitations**: Unbounded queries (`SELECT * FROM users`) are explicitly FORBIDDEN. Queries MUST be paginated (`LIMIT`).
- **Main Thread**: Blocking the main thread for over 50ms in frontend components is considered a violation.
