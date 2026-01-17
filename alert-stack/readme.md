# Alert Stack - Test Infrastructure

Basic Prometheus and AlertManager stack for testing alert generation, routing, and webhook delivery.

## Components

| Component | Purpose | Port | UI |
|-----------|---------|------|-----|
| **Prometheus** | Metric collection & alert evaluation | 9090 | http://localhost:9090 |
| **AlertManager** | Alert routing, grouping, deduplication | 9093 | http://localhost:9093 |
| **Pushgateway** | Receives metrics from alert generator | 9091 | http://localhost:9091 |
| **Alert Generator** | Pushes test metrics to trigger alerts | - | - |
| **Webhook Receiver** | Mock endpoint logging alert webhooks | 8080 | http://localhost:8080 |

## Quick Start

### 1. Start the Stack

```bash
cd alert-stack
docker compose up -d
```

### 2. Verify Services

```bash
# Check all services are running
docker compose ps

# Check service health
curl http://localhost:9090/-/healthy  # Prometheus
curl http://localhost:9093/-/healthy  # AlertManager
curl http://localhost:8080/health     # Webhook receiver
```

### 3. View Alert Flow

**Prometheus UI:**
```bash
open http://localhost:9090/alerts
```
- Shows defined alert rules
- Displays firing/pending alerts
- View alert details and labels

**AlertManager UI:**
```bash
open http://localhost:9093/#/alerts
```
- Shows active alerts from Prometheus
- Displays alert grouping
- Manage silences

**Webhook Logs:**
```bash
docker compose logs -f webhook-receiver
```
- Real-time webhook payloads
- Alert status (firing/resolved)
- Complete alert details

## Test Alerts

The stack includes three test alerts:

### TestHighMemory
- **Trigger:** `test_memory_usage_percent > 90`
- **Duration:** Fires after 1 minute
- **Severity:** Warning
- **Namespace:** production

### TestCrashLooping
- **Trigger:** `test_pod_restarts > 5`
- **Duration:** Fires after 30 seconds
- **Severity:** Critical
- **Namespace:** production

### TestMultipleFiring
- **Trigger:** `test_rapid_fire > 0`
- **Duration:** Immediate
- **Severity:** Info
- **Namespace:** staging

## Alert Generator Patterns

The alert generator randomly selects from these patterns:

- **steady_high** (95%) - Continuous high memory, fires TestHighMemory
- **spike** (50/50/50/95%) - Occasional memory spikes
- **flapping** (85/95%) - Memory hovering around threshold
- **normal** (50-80%) - Normal range, no alerts

Metrics are pushed every 30 seconds.

## Inspecting Alerts

### View Current Metrics

```bash
# Pushgateway metrics
curl http://localhost:9091/metrics | grep test_

# Example output:
# test_memory_usage_percent 95.0
# test_pod_restarts 7.0
# test_rapid_fire 1.0
```

### View Firing Alerts in Prometheus

```bash
# Query active alerts
curl -s http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | {alert: .labels.alertname, state: .state}'
```

### View AlertManager Webhook Payload

The webhook receiver logs the complete payload. Example:

```json
{
  "version": "4",
  "groupKey": "{}:{alertname=\"TestHighMemory\"}",
  "status": "firing",
  "receiver": "test-webhook",
  "groupLabels": {
    "alertname": "TestHighMemory"
  },
  "commonLabels": {
    "alertname": "TestHighMemory",
    "namespace": "production",
    "severity": "warning",
    "team": "platform"
  },
  "commonAnnotations": {
    "description": "Test alert: Memory at 95%",
    "runbook_url": "https://wiki.example.com/runbooks/high-memory",
    "summary": "Memory usage above 90%"
  },
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "TestHighMemory",
        "namespace": "production",
        "severity": "warning",
        "team": "platform"
      },
      "annotations": {
        "description": "Test alert: Memory at 95%",
        "runbook_url": "https://wiki.example.com/runbooks/high-memory",
        "summary": "Memory usage above 90%"
      },
      "startsAt": "2024-01-17T12:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus:9090/graph?..."
    }
  ]
}
```

## Customising Alerts

### Add New Alert Rules

Edit `prometheus/alerts.yml`:

```yaml
- alert: MyCustomAlert
  expr: my_metric > threshold
  for: 2m
  labels:
    severity: warning
    team: myteam
  annotations:
    summary: "My custom alert"
    description: "Value: {{ $value }}"
```

Reload Prometheus configuration:

```bash
curl -X POST http://localhost:9090/-/reload
```

### Modify AlertManager Routing

Edit `alertmanager/alertmanager.yml` to change:
- Grouping strategy (`group_by`)
- Timing (`group_wait`, `group_interval`, `repeat_interval`)
- Webhook URL

Restart AlertManager:

```bash
docker compose restart alertmanager
```

## Troubleshooting

### Alerts Not Firing

```bash
# Check metrics are being pushed
curl http://localhost:9091/metrics | grep test_

# Check Prometheus is scraping pushgateway
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'

# Check alert rules are loaded
curl http://localhost:9090/api/v1/rules | jq '.data.groups[].rules[] | {alert: .name, state: .state}'
```

### Webhooks Not Received

```bash
# Check AlertManager is routing to webhook
docker compose logs alertmanager | grep webhook

# Check webhook receiver is accessible
docker compose exec prometheus curl http://webhook-receiver:8080/health

# Verify AlertManager configuration
docker compose exec alertmanager amtool config show
```

### View Container Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f prometheus
docker compose logs -f alertmanager
docker compose logs -f alert-generator
docker compose logs -f webhook-receiver
```

## Stopping the Stack

```bash
# Stop all services
docker compose down

# Stop and remove volumes
docker compose down -v
```

## Next Steps

Once the alert stack is validated, you can:
1. Replace `webhook-receiver` with Alertgest API
2. Update AlertManager webhook URL to `http://alertgest:8080/api/v1/alerts`
3. Verify alerts are captured and stored during capture windows
4. Test alert aggregation and LLM digest generation

## Architecture

```
Alert Generator (Python)
    ↓ (pushes metrics every 30s)
Pushgateway
    ↓ (scraped by Prometheus)
Prometheus (evaluates rules every 15s)
    ↓ (sends alerts)
AlertManager (groups and routes)
    ↓ (webhook POST)
Webhook Receiver (logs payload)
```

## References

- [Prometheus Alerting](https://prometheus.io/docs/alerting/latest/overview/)
- [AlertManager Configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [Pushgateway](https://github.com/prometheus/pushgateway)
- [AlertManager Webhook Format](https://prometheus.io/docs/alerting/latest/configuration/#webhook_config)
