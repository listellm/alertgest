"""Database session management with async support."""
from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, Pool

from src.config import settings

# Global engine instance
_engine: Optional[object] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine(pool_class: Optional[type[Pool]] = None):
    """Get or create the database engine."""
    global _engine

    if _engine is None:
        _engine = create_async_engine(
            str(settings.database_url),
            echo=settings.app_log_level.lower() == "debug",
            pool_size=settings.database_pool_size,
            max_overflow=10,
            pool_pre_ping=True,
            poolclass=pool_class,
        )

    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the session factory."""
    global _session_factory

    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting database sessions."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db():
    """Close database connections gracefully."""
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
