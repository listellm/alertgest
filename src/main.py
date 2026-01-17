"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import settings
from src.db.session import close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    print(f"Starting Alertgest on port {settings.app_port}")
    print(f"Database URL: {settings.database_url}")
    print(f"Log level: {settings.app_log_level}")

    yield

    # Shutdown
    print("Shutting down Alertgest...")
    await close_db()


app = FastAPI(
    title="Alertgest",
    description="Kubernetes-native overnight alert digest service",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Liveness probe endpoint."""
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    """Readiness probe endpoint."""
    # TODO: Add database connectivity check
    return {"status": "ready"}
