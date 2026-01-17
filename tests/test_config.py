"""Tests for configuration module."""
import pytest
from pydantic import ValidationError

from src.config import Settings


def test_settings_default_values():
    """Test that settings have correct default values."""
    settings = Settings()

    assert settings.app_log_level == "info"
    assert settings.app_port == 8080
    assert settings.app_metrics_port == 9090
    assert settings.capture_window_start == "18:00"
    assert settings.capture_window_end == "08:00"
    assert settings.capture_window_timezone == "Europe/London"
    assert settings.digest_cron == "0 8 * * 1-5"
    assert settings.ollama_model == "llama3.1:8b"
    assert settings.ollama_temperature == 0.3
    assert settings.alert_retention_days == 30


def test_time_format_validation():
    """Test time format validation."""
    # Valid time formats
    Settings(capture_window_start="00:00", capture_window_end="23:59")
    Settings(capture_window_start="12:30", capture_window_end="18:45")

    # Invalid time formats
    with pytest.raises(ValidationError, match="Time must be in HH:MM format"):
        Settings(capture_window_start="25:00")

    with pytest.raises(ValidationError, match="Time must be in HH:MM format"):
        Settings(capture_window_end="12:60")

    with pytest.raises(ValidationError, match="Time must be in HH:MM format"):
        Settings(capture_window_start="not_a_time")


def test_temperature_validation():
    """Test temperature validation."""
    # Valid temperatures
    Settings(ollama_temperature=0.0)
    Settings(ollama_temperature=0.5)
    Settings(ollama_temperature=1.0)

    # Invalid temperatures
    with pytest.raises(ValidationError, match="Temperature must be between 0 and 1"):
        Settings(ollama_temperature=-0.1)

    with pytest.raises(ValidationError, match="Temperature must be between 0 and 1"):
        Settings(ollama_temperature=1.1)


def test_positive_int_validation():
    """Test positive integer validation."""
    # Valid values
    Settings(ollama_timeout_seconds=60)
    Settings(alert_retention_days=7)

    # Invalid values
    with pytest.raises(ValidationError, match="Value must be positive"):
        Settings(ollama_timeout_seconds=0)

    with pytest.raises(ValidationError, match="Value must be positive"):
        Settings(alert_retention_days=-1)


def test_k8s_namespace_list():
    """Test K8s namespace parsing."""
    # Empty namespaces
    settings = Settings(k8s_context_namespaces="")
    assert settings.k8s_namespace_list == []

    # Single namespace
    settings = Settings(k8s_context_namespaces="default")
    assert settings.k8s_namespace_list == ["default"]

    # Multiple namespaces
    settings = Settings(k8s_context_namespaces="default,kube-system,monitoring")
    assert settings.k8s_namespace_list == ["default", "kube-system", "monitoring"]

    # Namespaces with spaces
    settings = Settings(k8s_context_namespaces="default, kube-system , monitoring")
    assert settings.k8s_namespace_list == ["default", "kube-system", "monitoring"]
