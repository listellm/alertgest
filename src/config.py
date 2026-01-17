"""Application configuration using Pydantic Settings."""
from typing import Optional
from pydantic import Field, field_validator, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application configuration
    app_log_level: str = Field(default="info", description="Logging level")
    app_port: int = Field(default=8080, description="HTTP server port")
    app_metrics_port: int = Field(default=9090, description="Prometheus metrics port")

    # Database configuration
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://alertgest:alertgest@localhost:5432/alertgest",
        description="PostgreSQL connection URL"
    )
    database_pool_size: int = Field(default=10, description="Database connection pool size")

    # Capture window configuration
    capture_window_start: str = Field(default="18:00", description="Capture window start time (HH:MM)")
    capture_window_end: str = Field(default="08:00", description="Capture window end time (HH:MM)")
    capture_window_timezone: str = Field(default="Europe/London", description="Timezone for capture window")

    # Digest schedule configuration
    digest_cron: str = Field(default="0 8 * * 1-5", description="Cron expression for digest generation")
    digest_timezone: str = Field(default="Europe/London", description="Timezone for digest generation")

    # Ollama LLM configuration
    ollama_base_url: str = Field(
        default="http://ollama.alertgest.svc.cluster.local:11434",
        description="Ollama API base URL"
    )
    ollama_model: str = Field(default="llama3.1:8b", description="Primary Ollama model")
    ollama_fallback_model: str = Field(default="mistral:7b", description="Fallback Ollama model")
    ollama_max_tokens: int = Field(default=4096, description="Maximum tokens for LLM generation")
    ollama_temperature: float = Field(default=0.3, description="LLM temperature")
    ollama_timeout_seconds: int = Field(default=120, description="Ollama API timeout in seconds")

    # Microsoft Teams configuration
    teams_webhook_url: Optional[str] = Field(default=None, description="Microsoft Teams webhook URL")

    # Kubernetes context configuration
    k8s_context_enabled: bool = Field(default=True, description="Enable Kubernetes context collection")
    k8s_context_namespaces: str = Field(
        default="",
        description="Comma-separated namespaces to monitor (empty = all)"
    )
    k8s_metrics_server_enabled: bool = Field(default=True, description="Enable metrics server queries")

    # Retention configuration
    alert_retention_days: int = Field(default=30, description="Alert retention period in days")

    @field_validator("capture_window_start", "capture_window_end")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        """Validate time is in HH:MM format."""
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError(f"Time must be in HH:MM format, got: {v}")

        try:
            hour, minute = int(parts[0]), int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError(f"Invalid time: {v}")
        except ValueError as e:
            raise ValueError(f"Time must be in HH:MM format with valid hours (0-23) and minutes (0-59): {v}") from e

        return v

    @field_validator("ollama_temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """Validate temperature is between 0 and 1."""
        if not 0 <= v <= 1:
            raise ValueError(f"Temperature must be between 0 and 1, got: {v}")
        return v

    @field_validator("ollama_timeout_seconds", "alert_retention_days")
    @classmethod
    def validate_positive_int(cls, v: int) -> int:
        """Validate value is positive."""
        if v <= 0:
            raise ValueError(f"Value must be positive, got: {v}")
        return v

    @property
    def k8s_namespace_list(self) -> list[str]:
        """Parse comma-separated namespaces into list."""
        if not self.k8s_context_namespaces:
            return []
        return [ns.strip() for ns in self.k8s_context_namespaces.split(",") if ns.strip()]


# Global settings instance
settings = Settings()
