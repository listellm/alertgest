#!/usr/bin/env python3
"""Alert generator that pushes test metrics to Prometheus Pushgateway."""
import time
import random
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

registry = CollectorRegistry()
memory_gauge = Gauge('test_memory_usage_percent', 'Test memory usage percentage', registry=registry)
restart_gauge = Gauge('test_pod_restarts', 'Test pod restart count', registry=registry)
rapidfire_gauge = Gauge('test_rapid_fire', 'Rapid fire test metric', registry=registry)

PUSHGATEWAY_URL = 'pushgateway:9091'


def generate_alerts():
    """Generate various alert patterns."""
    patterns = {
        'steady_high': lambda: 95,  # Constant high memory - will fire TestHighMemory
        'spike': lambda: random.choice([50, 50, 50, 95]),  # Occasional spikes
        'flapping': lambda: random.choice([85, 95]),  # Flapping around threshold
        'normal': lambda: random.randint(50, 80),  # Normal range
    }

    # Randomly select pattern
    pattern = random.choice(list(patterns.keys()))

    # Set metric values
    memory_gauge.set(patterns[pattern]())
    restart_gauge.set(random.randint(0, 10))  # Sometimes > 5 to fire TestCrashLooping
    rapidfire_gauge.set(random.randint(0, 1))  # Randomly fire TestMultipleFiring

    # Push to gateway
    try:
        push_to_gateway(PUSHGATEWAY_URL, job='test-alerts', registry=registry)
        print(f"✓ Pushed metrics using pattern: {pattern} (memory: {memory_gauge._value.get():.1f}%, restarts: {restart_gauge._value.get():.0f})")
    except Exception as e:
        print(f"✗ Error pushing metrics: {e}")


if __name__ == '__main__':
    print("Starting alert generator...")
    print(f"Pushing metrics to {PUSHGATEWAY_URL} every 30 seconds")
    print("Patterns: steady_high, spike, flapping, normal")
    print("-" * 80)

    while True:
        generate_alerts()
        time.sleep(30)  # Push every 30 seconds
