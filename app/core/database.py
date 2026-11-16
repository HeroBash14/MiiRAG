from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Base class untuk seluruh SQLAlchemy ORM models."""


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency untuk menyediakan async database session per request."""
    async with AsyncSessionLocal() as session:
        yield session


async def check_db_health() -> bool:
    """Memastikan koneksi database dan ekstensi pgvector tersedia."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        )
        return result.scalar_one_or_none() == 1
