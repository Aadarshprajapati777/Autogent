from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from ..config import settings

database_url = settings.database_url.replace(
    "postgresql://", "postgresql+psycopg://", 1
)
engine = create_async_engine(
    database_url, pool_pre_ping=True, pool_size=10, max_overflow=20
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
