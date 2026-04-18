# Docker Compose Templates

This folder provides reusable Docker Compose templates for common setups.

## Persistence Rule

All stateful services in templates must use persistent named volumes.

- Datastores and queues (PostgreSQL, MySQL, MongoDB, Redis, Kafka, RabbitMQ, MinIO, etc.) must mount named volumes for data directories.
- Services that manage internal application state (for example Appsmith stacks/data) must persist state with named volumes.
- Templates intended to be stateless-only (for example test runners) should clearly stay stateless and must not claim persistence.

## Available Templates

1. `compose.web-postgres-redis.yml`
- Python/Node web app + PostgreSQL + Redis.

2. `compose.fastapi-nginx-postgres-redis.yml`
- FastAPI backend + Nginx gateway + PostgreSQL + Redis.

3. `compose.node-mongo.yml`
- Node.js app + MongoDB.

4. `compose.worker-rabbitmq.yml`
- API + background worker + RabbitMQ + Redis.

5. `compose.monitoring-prometheus-grafana.yml`
- Prometheus + Grafana + Node Exporter monitoring stack.

6. `compose.traefik-whoami.yml`
- Traefik reverse proxy routing example.

7. `compose.mysql-phpmyadmin.yml`
- MySQL + phpMyAdmin database stack.

8. `compose.elasticsearch-kibana.yml`
- Elasticsearch + Kibana search and analytics stack.

9. `compose.minio.yml`
- S3-compatible MinIO object storage.

10. `compose.kafka-kraft-ui.yml`
- Kafka (KRaft mode) + Kafka UI.

11. `compose.wordpress-mysql.yml`
- WordPress + MySQL CMS stack.

12. `compose.flask-postgres-redis.yml`
- Flask app + PostgreSQL + Redis.

13. `compose.flask-celery-rabbitmq.yml`
- Flask API + Celery worker + RabbitMQ + Redis.

14. `compose.flask-nginx-postgres.yml`
- Flask backend + Nginx gateway + PostgreSQL.

15. `compose.fastapi-postgres-redis.yml`
- FastAPI API + PostgreSQL + Redis.

16. `compose.fastapi-celery-rabbitmq.yml`
- FastAPI API + Celery worker + RabbitMQ + Redis + Flower.

17. `compose.fastapi-traefik-postgres.yml`
- FastAPI behind Traefik + PostgreSQL.

18. `compose.fastapi-mongodb.yml`
- FastAPI API + MongoDB.

19. `compose.react-vite-nginx.yml`
- React (Vite build) served as static SPA.

20. `compose.react-vite-node-postgres-redis.yml`
- React frontend + Node API + PostgreSQL + Redis.

21. `compose.react-traefik.yml`
- React SPA behind Traefik router.

22. `compose.react-dev-hot-reload.yml`
- React development server with bind mount and hot reload.

23. `compose.vue-vite-nginx.yml`
- Vue (Vite build) served as static SPA.

24. `compose.node-express-postgres-redis.yml`
- Node.js Express API + PostgreSQL + Redis.

25. `compose.express-mongodb.yml`
- Express API + MongoDB.

26. `compose.vue-node-express-fullstack.yml`
- Vue frontend + Express API + PostgreSQL + Redis.

27. `compose.adminer-mysql.yml`
- Adminer + MySQL admin panel stack.

28. `compose.pgadmin-postgres.yml`
- pgAdmin + PostgreSQL admin panel stack.

29. `compose.strapi-postgres.yml`
- Strapi admin/CMS + PostgreSQL.

30. `compose.metabase-postgres.yml`
- Metabase admin/BI panel + PostgreSQL.

31. `compose.nextjs-standalone.yml`
- Next.js standalone app template.

32. `compose.nestjs-postgres-redis.yml`
- NestJS API + PostgreSQL + Redis.

33. `compose.graphql-apollo-postgres.yml`
- Apollo GraphQL server + PostgreSQL.

34. `compose.mailhog-smtp-testing.yml`
- Local SMTP testing with MailHog.

35. `compose.playwright-e2e.yml`
- End-to-end test runner with Playwright.

36. `compose.pytest-coverage.yml`
- Pytest runner with coverage reports (XML and HTML).

37. `compose.jest-coverage.yml`
- Jest runner with coverage output.

38. `compose.sonarqube-postgres.yml`
- SonarQube quality gate server with PostgreSQL.

39. `compose.cypress-e2e.yml`
- End-to-end test runner with Cypress.

40. `compose.k6-load-testing.yml`
- Performance/load testing with k6.

41. `compose.allure-report.yml`
- Allure test report service.

42. `compose.react-echarts-nginx.yml`
- React ECharts dashboard served as static SPA.

43. `compose.react-d3-nginx.yml`
- React D3.js dashboard served as static SPA.

44. `compose.react-echarts-d3-dev.yml`
- React development template with ECharts + D3 and hot reload.

45. `compose.dashboard-react-fastapi-postgres-redis.yml`
- Full-stack dashboard: React frontend + FastAPI + PostgreSQL + Redis.

46. `compose.dashboard-realtime-websocket.yml`
- Real-time dashboard with WebSocket gateway + API + PostgreSQL + Redis.

47. `compose.grafana-loki-promtail.yml`
- Log dashboard stack with Grafana + Loki + Promtail.

48. `compose.superset-postgres-redis.yml`
- BI dashboard stack with Apache Superset + PostgreSQL + Redis.

49. `compose.n8n-postgres-redis.yml`
- Workflow automation with n8n + PostgreSQL + Redis.

50. `compose.node-red-mosquitto.yml`
- Node-RED automation flows + Mosquitto MQTT broker.

51. `compose.redis-sentinel.yml`
- Redis high availability with Sentinel.

52. `compose.rabbitmq-management.yml`
- RabbitMQ messaging queue with management UI.

53. `compose.nats-jetstream.yml`
- NATS messaging with JetStream persistence.

54. `compose.keycloak-postgres.yml`
- IAM/authentication with Keycloak + PostgreSQL.

55. `compose.vault-dev.yml`
- Secret management with HashiCorp Vault (dev mode).

56. `compose.authelia-redis.yml`
- Authentication gateway with Authelia + Redis.

57. `compose.nginx-modsecurity-waf.yml`
- WAF protection with Nginx + ModSecurity CRS.

58. `compose.clamav-antivirus.yml`
- Antivirus service template with ClamAV.

59. `compose.localstack-aws.yml`
- Local AWS service emulator for cloud-native development.

60. `compose.otel-jaeger-prometheus.yml`
- OpenTelemetry collector + Jaeger + Prometheus observability stack.

61. `compose.flyway-postgres-migrations.yml`
- Database migrations workflow with Flyway + PostgreSQL.

62. `compose.unleash-postgres.yml`
- Feature flag platform with Unleash + PostgreSQL.

63. `compose.temporal-postgres.yml`
- Durable workflow orchestration with Temporal + PostgreSQL.

64. `compose.appsmith-mongodb-redis.yml`
- Internal app builder platform with Appsmith + MongoDB + Redis.

65. `compose.appsmith-pgvector-redis.yml`
- Appsmith with pgvector-enabled PostgreSQL + Redis for AI/vector workloads.

66. `compose.refine-antdesign-fastapi-pgvector-redis.yml`
- React + TypeScript (Vite) with Ant Design + Refine frontend, FastAPI backend, pgvector PostgreSQL, and Redis.

67. `compose.vuestic-admin-fastapi-pgvector-redis.yml`
- Vuestic Admin frontend + FastAPI backend + pgvector PostgreSQL + Redis.

## Usage

Copy the template you want and adjust image names, env vars, domains, and volumes.

```powershell
Copy-Item docs/docker-compose-templates/compose.web-postgres-redis.yml docker-compose.yml
```

Then run:

```powershell
docker compose up -d
```
