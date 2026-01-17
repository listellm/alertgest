# Alertgest - Design Proposal

## Executive Summary

A fully self-contained Kubernetes-native service that captures AlertManager alerts during configurable overnight windows, aggregates them intelligently, enriches with cluster context, and delivers an LLM-generated summary with actionable recommendations via Microsoft Teams each morning. Uses Ollama for local LLM inference with no external API dependencies.

> **📋 Implementation Plan**: See [Implementation Plan](../../.claude/plans/happy-kindling-beacon.md) for milestone-based development roadmap (M0-M10).

---

## Problem Statement

Overnight alerts accumulate and auto-resolve, creating noise that masks genuine issues requiring attention. Engineers starting their day face alert fatigue and may miss patterns or recurring problems buried in resolved alerts.

---

## Solution Overview

```
┌─────────────────┐      webhook       ┌──────────────────────┐
│  AlertManager   │ ─────────────────► │  Alert Receiver API  │
└─────────────────┘                    └──────────┬───────────┘
                                                  │
                                                  ▼
                                       ┌──────────────────────┐
                                       │     PostgreSQL       │
                                       │   (Alert Storage)    │
                                       └──────────┬───────────┘
                                                  │
                    ┌─────────────────────────────┼─────────────────────────────┐
                    │                             │                             │
                    ▼                             ▼                             ▼
         ┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
         │  K8s API Client  │         │   Aggregation    │         │  Cron Scheduler  │
         │ (Context Enrich) │         │     Engine       │         │  (Digest Trigger)│
         └────────┬─────────┘         └────────┬─────────┘         └────────┬─────────┘
                  │                            │                            │
                  └─────────────────┬──────────┘                            │
                                    ▼                                       │
                          ┌──────────────────┐                              │
                          │     Ollama       │◄─────────────────────────────┘
                          │  (Local LLM)     │
                          └────────┬─────────┘
                                   │
                                   ▼
                          ┌──────────────────┐
                          │  Teams Webhook   │
                          │   (Delivery)     │
                          └──────────────────┘
```

---

## Components

### 1. Alert Receiver API

**Purpose:** HTTP endpoint receiving AlertManager webhook payloads.

**Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/alerts` | Receive AlertManager webhook |
| GET | `/health` | Liveness probe |
| GET | `/ready` | Readiness probe |
| GET | `/metrics` | Prometheus metrics |

**Behaviour:**
- Accepts AlertManager webhook format (array of alerts)
- Validates payload structure
- Checks if current time falls within configured capture window
- If within window: persists alerts to PostgreSQL
- If outside window: acknowledges but discards (or optionally still stores with flag)
- Returns 200 OK to AlertManager promptly (async processing)

**AlertManager Webhook Payload Structure:**
```json
{
  "version": "4",
  "groupKey": "{}:{alertname=\"HighMemoryUsage\"}",
  "status": "firing|resolved",
  "receiver": "overnight-digest",
  "groupLabels": {},
  "commonLabels": {},
  "commonAnnotations": {},
  "externalURL": "http://alertmanager:9093",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "HighMemoryUsage",
        "severity": "warning",
        "namespace": "production",
        "pod": "api-server-xyz",
        "team": "platform"
      },
      "annotations": {
        "summary": "Memory usage above 90%",
        "description": "Pod api-server-xyz memory at 94%",
        "runbook_url": "https://wiki.example.com/runbooks/high-memory"
      },
      "startsAt": "2024-01-15T02:30:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus:9090/graph?..."
    }
  ]
}
```

---

### 2. PostgreSQL Storage

**Purpose:** Durable storage for captured alerts with efficient querying for aggregation.

**Schema:**

```sql
-- Alerts table: stores individual alert instances
CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fingerprint VARCHAR(64) NOT NULL,  -- AlertManager fingerprint for dedup
    alertname VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL,  -- firing, resolved
    severity VARCHAR(50),
    namespace VARCHAR(255),
    labels JSONB NOT NULL,
    annotations JSONB NOT NULL,
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ends_at TIMESTAMP WITH TIME ZONE,
    received_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    capture_window_id UUID REFERENCES capture_windows(id),
    
    -- Indexes for common queries
    INDEX idx_alerts_window (capture_window_id),
    INDEX idx_alerts_alertname (alertname),
    INDEX idx_alerts_severity (severity),
    INDEX idx_alerts_received (received_at),
    INDEX idx_alerts_labels USING GIN (labels)
);

-- Capture windows: tracks overnight periods
CREATE TABLE capture_windows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
    window_end TIMESTAMP WITH TIME ZONE NOT NULL,
    digest_generated_at TIMESTAMP WITH TIME ZONE,
    digest_sent_at TIMESTAMP WITH TIME ZONE,
    alert_count INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active'  -- active, completed, digest_sent
);

-- Digests: stores generated summaries for audit/debugging
CREATE TABLE digests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    capture_window_id UUID REFERENCES capture_windows(id),
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    llm_model VARCHAR(100),
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    raw_prompt TEXT,
    raw_response TEXT,
    formatted_output TEXT,
    teams_message_id VARCHAR(255),
    delivery_status VARCHAR(20)  -- pending, sent, failed
);
```

**Retention Policy:**
- Alerts and digests retained for 30 days (configurable)
- Implemented via pg_cron or application-level scheduled job

---

### 3. Aggregation Engine

**Purpose:** Groups and summarises alerts to reduce volume before LLM processing.

**Aggregation Strategy:**

```
Raw Alerts (thousands)
        │
        ▼
┌───────────────────┐
│ Group by:         │
│ - alertname       │
│ - severity        │
│ - namespace       │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ For each group:   │
│ - Count total     │
│ - Count firing    │
│ - Count resolved  │
│ - First/last seen │
│ - Affected pods   │
│ - Sample labels   │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ Sort by:          │
│ 1. Severity       │
│ 2. Frequency      │
│ 3. Duration       │
└─────────┬─────────┘
          │
          ▼
Aggregated Summary (tens of groups)
```

**Aggregated Alert Group Structure:**
```json
{
  "alertname": "HighMemoryUsage",
  "severity": "warning",
  "namespace": "production",
  "total_occurrences": 47,
  "unique_pods_affected": 5,
  "firing_count": 3,
  "resolved_count": 44,
  "first_seen": "2024-01-15T02:30:00Z",
  "last_seen": "2024-01-15T07:45:00Z",
  "total_duration_minutes": 315,
  "flapping": true,  // resolved and re-fired multiple times
  "runbook_url": "https://wiki.example.com/runbooks/high-memory",
  "sample_affected_resources": ["api-server-abc", "api-server-def", "api-server-xyz"],
  "common_labels": {
    "team": "platform",
    "service": "api"
  }
}
```

---

### 4. Kubernetes Context Enrichment

**Purpose:** Query cluster state to provide LLM with operational context.

**Data Collected:**

| Context Type | K8s API | Information |
|--------------|---------|-------------|
| Recent Deployments | `apps/v1/deployments` | Deployments updated in last 24h, replica changes |
| Pod Restarts | `v1/pods` | Pods with restart count > 0, OOMKilled events |
| Failed Pods | `v1/pods` | Pods in CrashLoopBackOff, Error, ImagePullBackOff |
| Resource Pressure | `metrics.k8s.io/v1beta1` | Nodes/pods near CPU/memory limits |
| Recent Events | `v1/events` | Warning events in capture window |

**RBAC Requirements:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: alertgest-reader
rules:
  - apiGroups: [""]
    resources: ["pods", "events", "nodes"]
    verbs: ["get", "list"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets", "statefulsets", "daemonsets"]
    verbs: ["get", "list"]
  - apiGroups: ["metrics.k8s.io"]
    resources: ["pods", "nodes"]
    verbs: ["get", "list"]
```

**Context Output Structure:**
```json
{
  "collection_time": "2024-01-15T08:00:00Z",
  "recent_deployments": [
    {
      "name": "api-server",
      "namespace": "production",
      "updated_at": "2024-01-14T22:30:00Z",
      "replicas_change": "3 → 5",
      "image_change": "v1.2.3 → v1.2.4"
    }
  ],
  "problematic_pods": [
    {
      "name": "worker-abc",
      "namespace": "production", 
      "status": "CrashLoopBackOff",
      "restart_count": 15,
      "last_termination_reason": "OOMKilled"
    }
  ],
  "resource_pressure": {
    "high_memory_nodes": ["node-1", "node-3"],
    "high_cpu_pods": ["processor-xyz"]
  },
  "recent_warning_events": [
    {
      "reason": "FailedScheduling",
      "message": "Insufficient memory",
      "count": 12,
      "involved_object": "deployment/batch-processor"
    }
  ]
}
```

---

### 5. LLM Analysis (Ollama)

**Purpose:** Generate human-readable summary with actionable recommendations using locally-hosted LLM.

**Why Ollama:**
- Zero external API costs
- No API keys or cloud dependencies
- OpenAI-compatible API (easy integration)
- Simple deployment on K8s
- Runs on CPU (GPU optional for speed)
- Model flexibility - swap models without code changes

**Model Configuration:**
```yaml
llm:
  provider: ollama
  base_url: "http://ollama.alertgest.svc.cluster.local:11434"
  model: "llama3.1:8b"  # Recommended default
  fallback_model: "mistral:7b"
  max_tokens: 4096
  temperature: 0.3  # Lower for more consistent output
  timeout_seconds: 120  # LLM inference can take time on CPU
```

**Recommended Models (in order of preference):**

| Model | Size | RAM Required | Quality | Speed (CPU) |
|-------|------|--------------|---------|-------------|
| `llama3.1:8b` | 4.7GB | 8GB | Excellent | ~60s |
| `mistral:7b` | 4.1GB | 8GB | Very Good | ~45s |
| `qwen2.5:7b` | 4.4GB | 8GB | Very Good | ~50s |
| `phi3:medium` | 7.9GB | 12GB | Good | ~90s |
| `llama3.1:70b` | 40GB | 48GB+ | Best | GPU required |

**Note:** For CPU-only deployment, stick with 7B-8B parameter models. If you have GPU nodes available, larger models like `llama3.1:70b` provide significantly better analysis.

**Prompt Template:**
```
You are an SRE assistant analysing overnight alerts from a Kubernetes cluster. Your goal is to provide a concise, actionable morning briefing.

## Capture Window
From: {window_start}
To: {window_end}
Total alerts received: {total_alert_count}
Unique alert types: {unique_alertnames}

## Aggregated Alerts
{aggregated_alerts_json}

## Cluster Context
{k8s_context_json}

## Instructions
Analyse the alerts and cluster context to produce a morning briefing. Focus on:

1. **Critical Issues**: Any alerts that are still firing or indicate ongoing problems
2. **Patterns**: Recurring alerts, flapping alerts, correlated issues
3. **Root Cause Hints**: Connect alerts to cluster events (deployments, resource pressure, pod failures)
4. **Recommendations**: Specific actions to investigate or resolve, referencing runbooks where available

Format your response as follows:

### 🚨 Requires Immediate Attention
[List any critical/ongoing issues - or "None" if all clear]

### 📊 Overnight Summary  
[2-3 sentence overview of alert activity]

### 🔍 Key Patterns Identified
[Bullet points of notable patterns, correlations, or anomalies]

### 🔧 Recommended Actions
[Numbered list of specific investigation/remediation steps]

### 📋 Alert Breakdown by Severity
[Brief breakdown: X critical, Y warning, Z info]

Keep the response concise and actionable. Avoid restating raw data - provide insights.
```

**Token Management:**
- If aggregated data exceeds context limits, prioritise:
  1. Critical/high severity alerts
  2. Still-firing alerts
  3. High-frequency alerts
  4. Most recent alerts
- Log truncation events for observability

---

### 6. Teams Delivery

**Purpose:** Format and send digest via Microsoft Teams webhook.

**Adaptive Card Structure:**
```json
{
  "type": "message",
  "attachments": [
    {
      "contentType": "application/vnd.microsoft.card.adaptive",
      "content": {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
          {
            "type": "TextBlock",
            "size": "Large",
            "weight": "Bolder",
            "text": "🌅 Overnight Alertgest",
            "wrap": true
          },
          {
            "type": "TextBlock",
            "text": "{window_start} → {window_end}",
            "isSubtle": true,
            "spacing": "None"
          },
          {
            "type": "Container",
            "style": "attention",
            "items": [
              {
                "type": "TextBlock",
                "text": "🚨 Requires Immediate Attention",
                "weight": "Bolder"
              },
              {
                "type": "TextBlock",
                "text": "{critical_section}",
                "wrap": true
              }
            ],
            "isVisible": "{has_critical}"
          },
          {
            "type": "TextBlock",
            "text": "📊 Summary",
            "weight": "Bolder",
            "spacing": "Large"
          },
          {
            "type": "TextBlock",
            "text": "{summary_section}",
            "wrap": true
          },
          {
            "type": "ActionSet",
            "actions": [
              {
                "type": "Action.ToggleVisibility",
                "title": "Show Patterns",
                "targetElements": ["patterns-section"]
              },
              {
                "type": "Action.ToggleVisibility", 
                "title": "Show Recommendations",
                "targetElements": ["recommendations-section"]
              }
            ]
          },
          {
            "type": "Container",
            "id": "patterns-section",
            "isVisible": false,
            "items": [
              {
                "type": "TextBlock",
                "text": "🔍 Patterns Identified",
                "weight": "Bolder"
              },
              {
                "type": "TextBlock",
                "text": "{patterns_section}",
                "wrap": true
              }
            ]
          },
          {
            "type": "Container",
            "id": "recommendations-section",
            "isVisible": false,
            "items": [
              {
                "type": "TextBlock",
                "text": "🔧 Recommended Actions",
                "weight": "Bolder"
              },
              {
                "type": "TextBlock",
                "text": "{recommendations_section}",
                "wrap": true
              }
            ]
          }
        ]
      }
    }
  ]
}
```

**Delivery Handling:**
- Retry with exponential backoff (3 attempts)
- Log delivery failures to digest table
- Emit metric on success/failure

---

### 7. Scheduler

**Purpose:** Trigger digest generation at configured time.

**Implementation:** Kubernetes CronJob or in-application scheduler (e.g., APScheduler for Python, node-cron for Node.js).

**Recommendation:** Use in-application scheduler for:
- Simpler deployment (single pod)
- Shared database connection
- Easier coordination with capture window

**Configuration:**
```yaml
schedule:
  capture_window:
    start: "18:00"      # 6 PM local
    end: "08:00"        # 8 AM local
    timezone: "Europe/London"
  digest_generation:
    cron: "0 8 * * 1-5"  # 8 AM weekdays
    timezone: "Europe/London"
```

---

## Configuration

**Environment Variables / ConfigMap:**

```yaml
# Application Config
APP_LOG_LEVEL: "info"
APP_PORT: "8080"
APP_METRICS_PORT: "9090"

# Database
DATABASE_URL: "postgresql://user:pass@postgres:5432/alertgest"
DATABASE_POOL_SIZE: "10"

# Capture Window
CAPTURE_WINDOW_START: "18:00"
CAPTURE_WINDOW_END: "08:00"
CAPTURE_WINDOW_TIMEZONE: "Europe/London"

# Digest Schedule
DIGEST_CRON: "0 8 * * 1-5"
DIGEST_TIMEZONE: "Europe/London"

# Ollama LLM
OLLAMA_BASE_URL: "http://ollama.alertgest.svc.cluster.local:11434"
OLLAMA_MODEL: "llama3.1:8b"
OLLAMA_FALLBACK_MODEL: "mistral:7b"
OLLAMA_MAX_TOKENS: "4096"
OLLAMA_TEMPERATURE: "0.3"
OLLAMA_TIMEOUT_SECONDS: "120"

# Teams
TEAMS_WEBHOOK_URL: "${TEAMS_WEBHOOK_URL}"  # From secret

# Kubernetes Context
K8S_CONTEXT_ENABLED: "true"
K8S_CONTEXT_NAMESPACES: ""  # Empty = all namespaces
K8S_METRICS_SERVER_ENABLED: "true"

# Retention
ALERT_RETENTION_DAYS: "30"
```

**Secrets:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: alertgest-secrets
type: Opaque
stringData:
  TEAMS_WEBHOOK_URL: "https://outlook.office.com/webhook/..."
  DATABASE_PASSWORD: "..."
```

---

## Kubernetes Manifests

### Namespace
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: alertgest
  labels:
    app.kubernetes.io/name: alertgest
```

### Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alertgest
  namespace: alertgest
spec:
  replicas: 1  # Single replica - leader election not required
  selector:
    matchLabels:
      app: alertgest
  template:
    metadata:
      labels:
        app: alertgest
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9090"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: alertgest
      containers:
        - name: alertgest
          image: alertgest:latest
          ports:
            - name: http
              containerPort: 8080
            - name: metrics
              containerPort: 9090
          envFrom:
            - configMapRef:
                name: alertgest-config
            - secretRef:
                name: alertgest-secrets
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /ready
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
```

### Service
```yaml
apiVersion: v1
kind: Service
metadata:
  name: alertgest
  namespace: alertgest
spec:
  selector:
    app: alertgest
  ports:
    - name: http
      port: 80
      targetPort: 8080
    - name: metrics
      port: 9090
      targetPort: 9090
```

### ServiceAccount & RBAC
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: alertgest
  namespace: alertgest
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: alertgest-reader
rules:
  - apiGroups: [""]
    resources: ["pods", "events", "nodes"]
    verbs: ["get", "list"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets", "statefulsets", "daemonsets"]
    verbs: ["get", "list"]
  - apiGroups: ["metrics.k8s.io"]
    resources: ["pods", "nodes"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: alertgest-reader
subjects:
  - kind: ServiceAccount
    name: alertgest
    namespace: alertgest
roleRef:
  kind: ClusterRole
  name: alertgest-reader
  apiGroup: rbac.authorization.k8s.io
```

### Ollama Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
  namespace: alertgest
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ollama
  template:
    metadata:
      labels:
        app: ollama
    spec:
      containers:
        - name: ollama
          image: ollama/ollama:latest
          ports:
            - name: http
              containerPort: 11434
          env:
            - name: OLLAMA_HOST
              value: "0.0.0.0"
          volumeMounts:
            - name: ollama-data
              mountPath: /root/.ollama
          resources:
            requests:
              memory: "8Gi"
              cpu: "2000m"
            limits:
              memory: "12Gi"
              cpu: "4000m"
          # Uncomment below for GPU support (NVIDIA)
          # resources:
          #   limits:
          #     nvidia.com/gpu: 1
          livenessProbe:
            httpGet:
              path: /
              port: http
            initialDelaySeconds: 30
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /
              port: http
            initialDelaySeconds: 10
            periodSeconds: 10
      volumes:
        - name: ollama-data
          persistentVolumeClaim:
            claimName: ollama-data
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ollama-data
  namespace: alertgest
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 20Gi  # Enough for multiple models
---
apiVersion: v1
kind: Service
metadata:
  name: ollama
  namespace: alertgest
spec:
  selector:
    app: ollama
  ports:
    - name: http
      port: 11434
      targetPort: 11434
```

### Ollama Model Init Job
```yaml
# Run once after deployment to pull the required model
apiVersion: batch/v1
kind: Job
metadata:
  name: ollama-model-pull
  namespace: alertgest
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: model-pull
          image: curlimages/curl:latest
          command:
            - /bin/sh
            - -c
            - |
              echo "Waiting for Ollama to be ready..."
              until curl -s http://ollama.alertgest.svc.cluster.local:11434/api/tags; do
                sleep 5
              done
              echo "Pulling llama3.1:8b model..."
              curl -X POST http://ollama.alertgest.svc.cluster.local:11434/api/pull \
                -d '{"name": "llama3.1:8b"}' \
                --max-time 1800
              echo "Pulling mistral:7b fallback model..."
              curl -X POST http://ollama.alertgest.svc.cluster.local:11434/api/pull \
                -d '{"name": "mistral:7b"}' \
                --max-time 1800
              echo "Models pulled successfully"
  backoffLimit: 3
```

### PostgreSQL (Simple StatefulSet)
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: alertgest
spec:
  serviceName: postgres
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
        - name: postgres
          image: postgres:16-alpine
          ports:
            - containerPort: 5432
          env:
            - name: POSTGRES_DB
              value: alertgest
            - name: POSTGRES_USER
              value: alertgest
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: alertgest-secrets
                  key: DATABASE_PASSWORD
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: alertgest
spec:
  selector:
    app: postgres
  ports:
    - port: 5432
  clusterIP: None
```

### ServiceMonitor (for Prometheus Operator)
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: alertgest
  namespace: alertgest
spec:
  selector:
    matchLabels:
      app: alertgest
  endpoints:
    - port: metrics
      interval: 30s
```

---

## AlertManager Configuration

Add to AlertManager config to send alerts to the digest service:

```yaml
receivers:
  - name: 'overnight-digest'
    webhook_configs:
      - url: 'http://alertgest.alertgest.svc.cluster.local/api/v1/alerts'
        send_resolved: true

route:
  receiver: 'default'
  routes:
    # Send all alerts to overnight digest (in addition to other receivers)
    - receiver: 'overnight-digest'
      continue: true  # Important: allows alerts to continue to other receivers
      matchers: []    # Match all alerts
```

---

## Observability

### Prometheus Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `alertgest_alerts_received_total` | Counter | `alertname`, `severity`, `status` | Total alerts received |
| `alertgest_alerts_stored_total` | Counter | `alertname`, `severity` | Alerts stored (within window) |
| `alertgest_alerts_discarded_total` | Counter | `reason` | Alerts discarded (outside window, invalid) |
| `alertgest_capture_window_active` | Gauge | | 1 if currently in capture window |
| `alertgest_digest_generation_duration_seconds` | Histogram | | Time to generate digest |
| `alertgest_llm_request_duration_seconds` | Histogram | `model` | Ollama API latency |
| `alertgest_llm_tokens_total` | Counter | `model`, `type` | Tokens used (prompt/completion) |
| `alertgest_teams_delivery_total` | Counter | `status` | Teams webhook delivery attempts |
| `alertgest_k8s_context_collection_duration_seconds` | Histogram | | K8s API query time |

### Logging

Structured JSON logging with fields:
- `timestamp`
- `level`
- `message`
- `component` (receiver, aggregator, llm, teams, scheduler)
- `trace_id` (for request correlation)
- `alert_count`, `window_id`, `digest_id` (where applicable)

---

## Technology Stack Recommendation

| Component | Recommendation | Rationale |
|-----------|----------------|-----------|
| Language | Python 3.11+ | Rich ecosystem for data processing, familiar |
| Web Framework | FastAPI | Async support, automatic OpenAPI docs, Pydantic validation |
| Database | PostgreSQL 16 | JSONB support, reliable, good tooling |
| ORM | SQLAlchemy 2.0 + asyncpg | Async support, type hints |
| Scheduler | APScheduler | In-process, timezone-aware, persistent job store |
| K8s Client | kubernetes-client/python | Official client, well-maintained |
| LLM Client | httpx / aiohttp | Ollama uses OpenAI-compatible REST API |
| Metrics | prometheus-client | Standard Python Prometheus library |
| Container | Python 3.11-slim | Small image size |

---

## Project Structure

```
alertgest/
├── src/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entrypoint
│   ├── config.py               # Pydantic settings
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py           # API endpoints
│   │   └── schemas.py          # Pydantic models for API
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py           # SQLAlchemy models
│   │   ├── session.py          # Database session management
│   │   └── migrations/         # Alembic migrations
│   ├── services/
│   │   ├── __init__.py
│   │   ├── alert_receiver.py   # Alert ingestion logic
│   │   ├── aggregator.py       # Alert aggregation
│   │   ├── k8s_context.py      # Kubernetes API client
│   │   ├── llm_client.py       # Ollama integration
│   │   ├── teams_sender.py     # Teams webhook
│   │   └── digest_generator.py # Orchestrates digest creation
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── jobs.py             # Scheduled tasks
│   └── metrics/
│       ├── __init__.py
│       └── prometheus.py       # Metric definitions
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api/
│   ├── test_services/
│   └── fixtures/
├── k8s/
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── serviceaccount.yaml
│   ├── postgres.yaml
│   ├── ollama.yaml
│   └── servicemonitor.yaml
├── Dockerfile
├── docker-compose.yaml         # Local development
├── pyproject.toml
├── alembic.ini
└── README.md
```

---

## Development & Deployment

### Local Development

```bash
# Start dependencies
docker-compose up -d postgres

# Run migrations
alembic upgrade head

# Start application
uvicorn src.main:app --reload

# Test webhook
curl -X POST http://localhost:8080/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/sample_alerts.json
```

### Build & Deploy

```bash
# Build image
docker build -t alertgest:latest .

# Apply K8s manifests
kubectl apply -f k8s/

# Verify
kubectl -n alertgest get pods
kubectl -n alertgest logs -f deployment/alertgest
```

---

## Future Enhancements

1. **Multi-team support**: Route different digests to different Teams channels based on alert labels
2. **Feedback loop**: Allow engineers to rate digest usefulness, fine-tune prompts
3. **Historical analysis**: "Compare to last week" context in digests
4. **Alert suppression rules**: Learn which alerts are consistently noise
5. **Slack/Discord/Email**: Additional delivery channels
6. **Web UI**: Dashboard showing historical digests and alert trends
7. **On-demand generation**: API endpoint to trigger immediate digest

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Alert capture reliability | 99.9% of alerts received are stored |
| Digest delivery reliability | 99% of scheduled digests delivered |
| Time to digest | < 120 seconds from trigger to Teams message (CPU inference) |
| LLM inference time | < 90 seconds for 8B model on CPU |
| Engineer satisfaction | Qualitative feedback after 2 weeks |

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM produces unhelpful summaries | Low value | Iterate on prompts, try different models, collect feedback |
| High alert volume exceeds context | Truncated analysis | Aggressive aggregation, prioritisation |
| Ollama pod OOM/crashes | Delayed digest | Resource limits, health checks, restart policy |
| Slow CPU inference | Delayed digest | Ensure adequate CPU allocation, consider GPU node |
| Teams webhook failures | Missed digest | Retry logic, fallback notification method |
| Database growth | Storage costs | Retention policy, periodic cleanup |
| Model download time | Slow initial setup | Init job handles this, PVC persists models |

---

## Appendix: Sample LLM Output

```markdown
### 🚨 Requires Immediate Attention

**HighMemoryUsage** - 3 pods in `production` namespace still firing:
- `api-server-abc`, `api-server-def`, `api-server-ghi`
- Memory at 92-96%, started 02:30 UTC
- ⚠️ Correlates with deployment of api-server v1.2.4 at 22:30 UTC yesterday

### 📊 Overnight Summary

Captured 847 alerts across 12 unique alert types. 94% resolved automatically. 
The cluster experienced elevated memory pressure following the api-server 
deployment, with cascading effects on dependent services.

### 🔍 Key Patterns Identified

- **Deployment correlation**: 78% of HighMemoryUsage alerts started within 
  2 hours of api-server v1.2.4 rollout
- **Flapping**: `PodCrashLooping` for `worker-processor` fired/resolved 23 
  times (investigate restart loop)
- **Resource pressure**: Nodes `node-1` and `node-3` hit 85%+ memory, 
  triggering pod evictions

### 🔧 Recommended Actions

1. **Immediate**: Investigate api-server memory regression in v1.2.4 
   - Check for memory leaks, increased allocation
   - Consider rollback if critical
   - [Runbook: High Memory](https://wiki.example.com/runbooks/high-memory)

2. **Today**: Review worker-processor crash loop
   - 15 restarts overnight, OOMKilled
   - May need memory limit increase

3. **This week**: Capacity review for nodes 1 & 3
   - Consistently near limits during peak overnight processing

### 📋 Alert Breakdown by Severity

- 🔴 Critical: 3 (all HighMemoryUsage, still firing)
- 🟠 Warning: 156 (89% resolved)
- 🔵 Info: 688 (100% resolved)
```
