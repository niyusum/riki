from typing import AsyncGenerator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine
)
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy import text
import asyncio

from src.config import Config
from src.services.logger import get_logger

logger = get_logger(__name__)


class DatabaseService:
    """
    Centralized database connection and session management.
    
    Provides async context managers for transactional and non-transactional
    database access. Handles connection pooling, health checks, and initialization.
    
    Architecture:
        - Single async engine with connection pooling
        - Session factory for creating isolated sessions
        - Automatic transaction management via context managers
        - Retry logic on initialization failure
    
    Usage:
        # Transaction (auto-commit on success)
        >>> async with DatabaseService.get_transaction() as session:
        ...     player = await session.get(Player, discord_id, with_for_update=True)
        ...     player.rikis += 1000
        
        # Read-only (no auto-commit)
        >>> async with DatabaseService.get_session() as session:
        ...     result = await session.execute(select(Player))
    
    Thread Safety:
        All methods are async-safe. Each session is isolated per coroutine.
    """
    
    _engine: AsyncEngine = None
    _session_factory: async_sessionmaker = None
    _health_check_query: str = "SELECT 1"
    
    @classmethod
    async def initialize(cls, max_retries: int = 3, retry_delay: int = 5) -> None:
        """
        Initialize database engine and session factory.
        
        Args:
            max_retries: Number of connection attempts before failing
            retry_delay: Seconds to wait between retry attempts
        
        Raises:
            Exception: If initialization fails after all retries
        """
        if cls._engine is not None:
            logger.warning("DatabaseService already initialized")
            return
        
        for attempt in range(1, max_retries + 1):
            try:
                pool_class = NullPool if Config.is_testing() else QueuePool
                
                cls._engine = create_async_engine(
                    Config.DATABASE_URL,
                    echo=Config.DATABASE_ECHO,
                    poolclass=pool_class,
                    pool_size=Config.DATABASE_POOL_SIZE if pool_class == QueuePool else None,
                    max_overflow=Config.DATABASE_MAX_OVERFLOW if pool_class == QueuePool else None,
                    pool_pre_ping=True,
                    pool_recycle=Config.DATABASE_POOL_RECYCLE,
                )
                
                cls._session_factory = async_sessionmaker(
                    cls._engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autocommit=False,
                    autoflush=False,
                )
                
                await cls.health_check()
                logger.info(f"DatabaseService initialized successfully on attempt {attempt}")
                return
                
            except Exception as e:
                logger.error(f"Failed to initialize DatabaseService (attempt {attempt}/{max_retries}): {e}")
                
                if attempt < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.critical("DatabaseService initialization failed after all retries")
                    raise
    
    @classmethod
    async def shutdown(cls) -> None:
        """Close all database connections and dispose of engine."""
        if cls._engine is None:
            return
        
        try:
            await cls._engine.dispose()
            cls._engine = None
            cls._session_factory = None
            logger.info("DatabaseService shutdown successfully")
            
        except Exception as e:
            logger.error(f"Error during DatabaseService shutdown: {e}")
    
    @classmethod
    async def health_check(cls) -> bool:
        """
        Verify database connectivity with a simple query.
        
        Returns:
            True if database is accessible, False otherwise
        """
        try:
            async with cls._engine.connect() as conn:
                await conn.execute(text(cls._health_check_query))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
    
    @classmethod
    @asynccontextmanager
    async def get_session(cls) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session without automatic commit.
        
        Use for read-only queries or when manual transaction control is needed.
        Session is automatically closed on context exit.
        
        Yields:
            AsyncSession instance
        
        Raises:
            RuntimeError: If DatabaseService not initialized
        """
        if cls._session_factory is None:
            raise RuntimeError("DatabaseService not initialized")
        
        async with cls._session_factory() as session:
            try:
                yield session
            except Exception as e:
                await session.rollback()
                logger.error(f"Database session error: {e}")
                raise
            finally:
                await session.close()
    
    @classmethod
    @asynccontextmanager
    async def get_transaction(cls) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session with automatic commit on success.
        
        Use for all write operations (RIKI LAW Article I.6).
        Transaction automatically commits on clean exit, rolls back on exception.
        
        Yields:
            AsyncSession instance
        
        Raises:
            RuntimeError: If DatabaseService not initialized
        
        Example:
            >>> async with DatabaseService.get_transaction() as session:
            ...     player = await session.get(Player, discord_id, with_for_update=True)
            ...     player.rikis += 1000
            ...     # Auto-commits here
        """
        if cls._session_factory is None:
            raise RuntimeError("DatabaseService not initialized")
        
        async with cls._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"Transaction rolled back: {e}")
                raise
            finally:
                await session.close()
    
    @classmethod
    async def create_tables(cls) -> None:
        """
        Create all database tables from SQLModel definitions.
        
        Idempotent - safe to call multiple times.
        
        Raises:
            RuntimeError: If DatabaseService not initialized
        """
        from sqlmodel import SQLModel
        from src.database.models import (
            Player, Maiden, MaidenBase, GameConfig,
            DailyQuest, LeaderboardSnapshot, TransactionLog
        )
        
        if cls._engine is None:
            raise RuntimeError("DatabaseService not initialized")
        
        try:
            async with cls._engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
            logger.info("Database tables created successfully")
            
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            raise
    
    @classmethod
    async def drop_tables(cls) -> None:
        """
        Drop all database tables.
        
        DESTRUCTIVE OPERATION - Only allowed in non-production environments.
        
        Raises:
            RuntimeError: If called in production environment
        """
        from sqlmodel import SQLModel
        
        if cls._engine is None:
            raise RuntimeError("DatabaseService not initialized")
        
        if Config.is_production():
            raise RuntimeError("Cannot drop tables in production environment")
        
        try:
            async with cls._engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.drop_all)
            logger.warning("Database tables dropped")
            
        except Exception as e:
            logger.error(f"Failed to drop tables: {e}")
            raise