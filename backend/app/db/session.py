from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

sync_engine = create_engine(
    settings.database_url_sync,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)
async_engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

SyncSession = sessionmaker(bind=sync_engine)
AsyncSession = async_sessionmaker(bind=async_engine, expire_on_commit=False)
