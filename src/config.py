import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import logging

load_dotenv()


class Config:
    """
    Centralized configuration management for RIKI RPG Discord Bot.
    
    All configuration values loaded from environment variables with sensible defaults.
    Validates critical settings on startup to prevent runtime failures.
    
    Environment Variables:
        DISCORD_TOKEN: Bot authentication token (required)
        DISCORD_GUILD_ID: Optional guild ID for testing
        DATABASE_URL: PostgreSQL connection string (required)
        REDIS_URL: Redis connection string (optional)
        ENVIRONMENT: deployment environment (development/testing/production)
    
    Usage:
        >>> Config.DISCORD_TOKEN
        'your-bot-token'
        >>> Config.is_production()
        False
    """
    
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
    DISCORD_GUILD_ID: Optional[int] = int(os.getenv("DISCORD_GUILD_ID", 0)) or None
    COMMAND_PREFIX: str = os.getenv("COMMAND_PREFIX", "/")
    
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:password@localhost:5432/riki_rpg"
    )
    DATABASE_POOL_SIZE: int = int(os.getenv("DATABASE_POOL_SIZE", "50"))
    DATABASE_MAX_OVERFLOW: int = int(os.getenv("DATABASE_MAX_OVERFLOW", "50"))
    DATABASE_ECHO: bool = os.getenv("DATABASE_ECHO", "false").lower() == "true"
    DATABASE_POOL_RECYCLE: int = int(os.getenv("DATABASE_POOL_RECYCLE", "3600"))
    
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_PASSWORD: Optional[str] = os.getenv("REDIS_PASSWORD")
    REDIS_MAX_CONNECTIONS: int = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))
    REDIS_DECODE_RESPONSES: bool = True
    REDIS_SOCKET_TIMEOUT: int = int(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))
    REDIS_RETRY_ON_TIMEOUT: bool = True
    
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    LOGS_DIR: Path = BASE_DIR / "logs"
    DATA_DIR: Path = BASE_DIR / "data"
    
    BOT_NAME: str = "RIKI RPG"
    BOT_VERSION: str = "1.0.0"
    BOT_DESCRIPTION: str = "A Discord RPG featuring maidens, fusion, and strategic gameplay"
    
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_FAILOVER_TO_MEMORY: bool = True
    RATE_LIMIT_COOLDOWN_MESSAGE: str = "⏳ Please wait {remaining:.1f} seconds before using this command again."
    
    EMBED_COLOR_PRIMARY: int = 0x2c2d31
    EMBED_COLOR_SUCCESS: int = 0x2d5016
    EMBED_COLOR_ERROR: int = 0x8b0000
    EMBED_COLOR_WARNING: int = 0x8b6914
    EMBED_COLOR_INFO: int = 0x1e3a8a
    
    DEFAULT_STARTING_RIKIS: int = 1000
    DEFAULT_STARTING_GRACE: int = 5
    DEFAULT_STARTING_ENERGY: int = 100
    DEFAULT_STARTING_STAMINA: int = 50
    
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = 60
    CIRCUIT_BREAKER_EXPECTED_EXCEPTION: tuple = (Exception,)
    
    MAX_FUSION_COST: int = 10_000_000
    MAX_LEVEL_UPS_PER_TRANSACTION: int = 100
    
    @classmethod
    def validate(cls) -> None:
        """
        Validate critical configuration values on startup.
        
        Raises:
            ValueError: If required config values are missing in production
        """
        try:
            if not cls.DISCORD_TOKEN:
                raise ValueError("DISCORD_TOKEN environment variable is required")
            
            if not cls.DATABASE_URL:
                raise ValueError("DATABASE_URL environment variable is required")
            
            cls.LOGS_DIR.mkdir(exist_ok=True)
            cls.DATA_DIR.mkdir(exist_ok=True)
            
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"Config validation warning (safe for tests): {e}")
            if cls.ENVIRONMENT.lower() == "production":
                raise
    
    @classmethod
    def is_production(cls) -> bool:
        """Check if running in production environment."""
        return cls.ENVIRONMENT.lower() == "production"
    
    @classmethod
    def is_development(cls) -> bool:
        """Check if running in development environment."""
        return cls.ENVIRONMENT.lower() == "development"
    
    @classmethod
    def is_testing(cls) -> bool:
        """Check if running in testing environment."""
        return cls.ENVIRONMENT.lower() == "testing"


Config.validate()