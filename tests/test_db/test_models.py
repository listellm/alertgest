"""Tests for database models."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from src.db.models import Alert, CaptureWindow, Digest


@pytest.mark.asyncio
async def test_create_capture_window(test_db_session):
    """Test creating a capture window."""
    window = CaptureWindow(
        window_start=datetime(2024, 1, 15, 18, 0, tzinfo=timezone.utc),
        window_end=datetime(2024, 1, 16, 8, 0, tzinfo=timezone.utc),
        status="active",
    )

    test_db_session.add(window)
    await test_db_session.commit()

    result = await test_db_session.execute(select(CaptureWindow))
    windows = result.scalars().all()

    assert len(windows) == 1
    assert windows[0].status == "active"
    assert windows[0].alert_count == 0


@pytest.mark.asyncio
async def test_create_alert(test_db_session):
    """Test creating an alert."""
    window = CaptureWindow(
        window_start=datetime(2024, 1, 15, 18, 0, tzinfo=timezone.utc),
        window_end=datetime(2024, 1, 16, 8, 0, tzinfo=timezone.utc),
    )
    test_db_session.add(window)
    await test_db_session.flush()

    alert = Alert(
        fingerprint="abc123",
        alertname="HighMemoryUsage",
        status="firing",
        severity="warning",
        namespace="production",
        labels={"team": "platform", "service": "api"},
        annotations={"summary": "Memory usage high"},
        starts_at=datetime(2024, 1, 15, 20, 0, tzinfo=timezone.utc),
        capture_window_id=window.id,
    )

    test_db_session.add(alert)
    await test_db_session.commit()

    result = await test_db_session.execute(select(Alert))
    alerts = result.scalars().all()

    assert len(alerts) == 1
    assert alerts[0].alertname == "HighMemoryUsage"
    assert alerts[0].severity == "warning"
    assert alerts[0].labels["team"] == "platform"


@pytest.mark.asyncio
async def test_create_digest(test_db_session):
    """Test creating a digest."""
    window = CaptureWindow(
        window_start=datetime(2024, 1, 15, 18, 0, tzinfo=timezone.utc),
        window_end=datetime(2024, 1, 16, 8, 0, tzinfo=timezone.utc),
    )
    test_db_session.add(window)
    await test_db_session.flush()

    digest = Digest(
        capture_window_id=window.id,
        llm_model="llama3.1:8b",
        prompt_tokens=1000,
        completion_tokens=500,
        raw_prompt="Test prompt",
        raw_response="Test response",
        formatted_output="Formatted output",
        delivery_status="pending",
    )

    test_db_session.add(digest)
    await test_db_session.commit()

    result = await test_db_session.execute(select(Digest))
    digests = result.scalars().all()

    assert len(digests) == 1
    assert digests[0].llm_model == "llama3.1:8b"
    assert digests[0].prompt_tokens == 1000
    assert digests[0].delivery_status == "pending"


@pytest.mark.asyncio
async def test_capture_window_alert_relationship(test_db_session):
    """Test relationship between capture window and alerts."""
    window = CaptureWindow(
        window_start=datetime(2024, 1, 15, 18, 0, tzinfo=timezone.utc),
        window_end=datetime(2024, 1, 16, 8, 0, tzinfo=timezone.utc),
    )
    test_db_session.add(window)
    await test_db_session.flush()

    alert1 = Alert(
        fingerprint="abc123",
        alertname="HighMemoryUsage",
        status="firing",
        labels={},
        annotations={},
        starts_at=datetime(2024, 1, 15, 20, 0, tzinfo=timezone.utc),
        capture_window_id=window.id,
    )

    alert2 = Alert(
        fingerprint="def456",
        alertname="PodCrashLooping",
        status="resolved",
        labels={},
        annotations={},
        starts_at=datetime(2024, 1, 15, 21, 0, tzinfo=timezone.utc),
        capture_window_id=window.id,
    )

    test_db_session.add_all([alert1, alert2])
    await test_db_session.commit()

    result = await test_db_session.execute(
        select(CaptureWindow).where(CaptureWindow.id == window.id)
    )
    fetched_window = result.scalar_one()

    # Access relationship
    assert len(fetched_window.alerts) == 2
    assert {a.alertname for a in fetched_window.alerts} == {"HighMemoryUsage", "PodCrashLooping"}
