#!/usr/bin/env python3
"""Mock webhook receiver for AlertManager alerts."""
from fastapi import FastAPI, Request
import json
from datetime import datetime, timezone

app = FastAPI(title="Alert Webhook Receiver")


@app.post("/alerts")
async def receive_alerts(request: Request):
    """Receive and log AlertManager webhook payloads."""
    payload = await request.json()

    timestamp = datetime.now(timezone.utc).isoformat()
    alert_count = len(payload.get('alerts', []))

    print(f"\n{'='*80}")
    print(f"[{timestamp}] Received AlertManager Webhook")
    print(f"{'='*80}")
    print(f"Status: {payload.get('status', 'unknown')}")
    print(f"Receiver: {payload.get('receiver', 'unknown')}")
    print(f"Alerts: {alert_count}")
    print(f"\n{json.dumps(payload, indent=2)}")
    print(f"{'='*80}\n")

    return {"status": "received", "alert_count": alert_count}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Alert Webhook Receiver",
        "endpoints": {
            "webhook": "POST /alerts",
            "health": "GET /health"
        }
    }


if __name__ == "__main__":
    import uvicorn
    print("Starting webhook receiver on http://0.0.0.0:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
