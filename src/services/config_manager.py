from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
import asyncio

from src.database.models.game_config import GameConfig
from src.services.logger import get_logger

logger = get_logger(__name__)


class ConfigManager:
    """
    Dynamic game configuration management with database backing and caching.
    
    Provides hierarchical config access using dot notation (e.g., 'fusion_costs.base').
    Values cached in-memory with TTL and automatically refreshed from database.
    Enables balance changes without code deployment (RIKI LAW Article I.4).
    
    Features:
        - Database-backed for live updates
        - In-memory cache with configurable TTL
        - Automatic background refresh task
        - Graceful fallback to hardcoded defaults
        - Hierarchical config paths with dot notation
    
    Usage:
        >>> await ConfigManager.initialize(session)
        >>> cost = ConfigManager.get("fusion_costs.base", 1000)
        >>> await ConfigManager.set(session, "fusion_costs.base", 1500, "admin")
    
    Thread Safety:
        Class is thread-safe for reads. Writes require session lock.
    """
    
    _cache: Dict[str, Any] = {}
    _cache_timestamps: Dict[str, datetime] = {}
    _initialized: bool = False
    _cache_ttl: int = 300
    _refresh_task: Optional[asyncio.Task] = None
    
    _defaults: Dict[str, Any] = {
        "fusion_rates": {
            "1": 70, "2": 65, "3": 60, "4": 55, "5": 50, "6": 45,
            "7": 40, "8": 35, "9": 30, "10": 25, "11": 20
        },
        "fusion_costs": {
            "base": 1000,
            "multiplier": 2.5,
            "max_cost": 10_000_000
        },
        "shard_system": {
            "shards_per_failure": 1,
            "shards_for_redemption": 10,
            "enabled": True
        },
        "energy_system": {
            "base_max": 100,
            "regen_minutes": 5,
            "per_level_increase": 10,
            "overcap_bonus": 0.10
        },
        "stamina_system": {
            "base_max": 50,
            "regen_minutes": 10,
            "per_level_increase": 5,
            "overcap_bonus": 0.10
        },
        "xp_curve": {
            "type": "polynomial",
            "base": 50,
            "exponent": 2.2
        },
        "level_milestones": {
            "minor_interval": 5,
            "major_interval": 10,
            "minor_rewards": {
                "rikis_multiplier": 100,
                "grace": 5,
                "gems_divisor": 10
            },
            "major_rewards": {
                "rikis_multiplier": 500,
                "grace": 10,
                "gems": 5,
                "max_energy_increase": 10,
                "max_stamina_increase": 5
            }
        },
        "prayer_system": {
            "grace_per_prayer": 5,
            "max_charges": 5,
            "regen_minutes": 5,
            "class_bonuses": {
                "destroyer": 1.0,
                "adapter": 1.0,
                "invoker": 1.2
            }
        },
        "gacha_rates": {
            "tier_1": 40.0,
            "tier_2": 30.0,
            "tier_3": 15.0,
            "tier_4": 8.0,
            "tier_5": 4.0,
            "tier_6": 2.0,
            "tier_7": 0.7,
            "tier_8": 0.2,
            "tier_9": 0.08,
            "tier_10": 0.02,
            "pity_counter": 90,
            "pity_tier": 7
        },
        "event_modifiers": {
            "fusion_rate_boost": 0.0,
            "xp_boost": 0.0,
            "rikis_boost": 0.0,
            "shard_boost": 0.0
        },
        "quest_rewards": {
            "base_rikis": 500,
            "base_grace": 3,
            "base_gems": 1,
            "completion_bonus_rikis": 500,
            "completion_bonus_grace": 2,
            "completion_bonus_gems": 1,
            "streak_multiplier": 0.1
        },
        "element_combinations": {
            "infernal|infernal": "infernal",
            "infernal|abyssal": "umbral",
            "infernal|tempest": "radiant",
            "infernal|earth": "tempest",
            "infernal|radiant": "earth",
            "infernal|umbral": "abyssal",
            "abyssal|abyssal": "abyssal",
            "abyssal|tempest": "earth",
            "abyssal|earth": "umbral",
            "abyssal|radiant": "tempest",
            "abyssal|umbral": "infernal",
            "tempest|tempest": "tempest",
            "tempest|earth": "radiant",
            "tempest|radiant": "umbral",
            "tempest|umbral": "abyssal",
            "earth|earth": "earth",
            "earth|radiant": "abyssal",
            "earth|umbral": "tempest",
            "radiant|radiant": "radiant",
            "radiant|umbral": "infernal",
            "umbral|umbral": "umbral",
        }
    }
    
    @classmethod
    async def initialize(cls, session: AsyncSession) -> None:
        """
        Initialize ConfigManager by loading all config from database.
        
        Args:
            session: Database session for loading config
        """
        try:
            result = await session.execute(select(GameConfig))
            configs = result.scalars().all()
            
            for config in configs:
                cls._cache[config.config_key] = config.config_value
                cls._cache_timestamps[config.config_key] = datetime.utcnow()
            
            cls._initialized = True
            logger.info(f"ConfigManager initialized with {len(cls._cache)} entries from database")
            
        except Exception as e:
            logger.warning(f"Failed to initialize ConfigManager from database: {e}")
            logger.warning("Using hardcoded defaults")
            cls._cache = cls._defaults.copy()
            cls._initialized = True
    
    @classmethod
    async def start_refresh_task(cls, session_factory) -> None:
        """
        Start background task to periodically refresh config from database.
        
        Args:
            session_factory: Callable that returns async session context manager
        """
        if cls._refresh_task is not None:
            logger.warning("Refresh task already running")
            return
        
        async def refresh_loop():
            while True:
                try:
                    await asyncio.sleep(cls._cache_ttl - 30)
                    
                    async with session_factory() as session:
                        result = await session.execute(select(GameConfig))
                        configs = result.scalars().all()
                        
                        for config in configs:
                            cls._cache[config.config_key] = config.config_value
                            cls._cache_timestamps[config.config_key] = datetime.utcnow()
                        
                        logger.debug(f"ConfigManager cache refreshed with {len(configs)} entries")
                        
                except asyncio.CancelledError:
                    logger.info("ConfigManager refresh task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in ConfigManager refresh task: {e}")
                    await asyncio.sleep(60)
        
        cls._refresh_task = asyncio.create_task(refresh_loop())
        logger.info("ConfigManager refresh task started")
    
    @classmethod
    async def stop_refresh_task(cls) -> None:
        """Stop background refresh task."""
        if cls._refresh_task is not None:
            cls._refresh_task.cancel()
            try:
                await cls._refresh_task
            except asyncio.CancelledError:
                pass
            cls._refresh_task = None
            logger.info("ConfigManager refresh task stopped")
    
    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """
        Get configuration value by hierarchical key.
        
        Supports dot notation for nested values (e.g., 'fusion_costs.base').
        Falls back to hardcoded defaults if key not in cache.
        
        Args:
            key: Configuration key (dot-separated for nested values)
            default: Default value if key not found
        
        Returns:
            Configuration value or default
        
        Example:
            >>> ConfigManager.get("fusion_costs.base", 1000)
            1000
            >>> ConfigManager.get("fusion_rates.3")
            60
        """
        if not cls._initialized:
            logger.warning("ConfigManager not initialized, using defaults")
            cls._cache = cls._defaults.copy()
            cls._initialized = True
        
        if key in cls._cache_timestamps:
            age = (datetime.utcnow() - cls._cache_timestamps[key]).total_seconds()
            if age > cls._cache_ttl:
                cls._cache.pop(key, None)
                cls._cache_timestamps.pop(key, None)
        
        keys = key.split(".")
        value = cls._cache
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    value = cls._get_from_defaults(key)
                    return value if value is not None else default
            else:
                value = cls._get_from_defaults(key)
                return value if value is not None else default
        
        return value if value is not None else default
    
    @classmethod
    def _get_from_defaults(cls, key: str) -> Any:
        """Navigate hardcoded defaults using dot notation."""
        keys = key.split(".")
        value = cls._defaults
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return None
            else:
                return None
        
        return value
    
    @classmethod
    def _set_nested_value(cls, data: Dict, keys: list, value: Any) -> Dict:
        """Set value in nested dictionary structure."""
        if len(keys) == 1:
            data[keys[0]] = value
            return data
        
        if keys[0] not in data:
            data[keys[0]] = {}
        
        data[keys[0]] = cls._set_nested_value(data[keys[0]], keys[1:], value)
        return data
    
    @classmethod
    async def set(cls, session: AsyncSession, key: str, value: Any, modified_by: str = "system") -> None:
        """
        Update configuration value in database and cache.
        
        Args:
            session: Database session
            key: Configuration key (dot-separated for nested values)
            value: New value
            modified_by: Username/system making the change
        
        Raises:
            Exception: If database update fails
        
        Example:
            >>> await ConfigManager.set(session, "fusion_costs.base", 1500, "admin")
        """
        try:
            keys = key.split(".")
            top_level_key = keys[0]
            
            result = await session.execute(
                select(GameConfig).where(GameConfig.config_key == top_level_key)
            )
            config = result.scalar_one_or_none()
            
            if len(keys) > 1:
                if config:
                    config_data = config.config_value.copy()
                else:
                    config_data = {}
                
                config_data = cls._set_nested_value(config_data, keys[1:], value)
                final_value = config_data
            else:
                final_value = value
            
            if config:
                config.config_value = final_value
                config.modified_by = modified_by
                config.last_modified = datetime.utcnow()
            else:
                config = GameConfig(
                    config_key=top_level_key,
                    config_value=final_value,
                    modified_by=modified_by
                )
                session.add(config)
            
            await session.commit()
            
            if top_level_key in cls._cache:
                cls._cache[top_level_key] = final_value
            else:
                cls._cache = {}
                result = await session.execute(select(GameConfig))
                configs = result.scalars().all()
                for cfg in configs:
                    cls._cache[cfg.config_key] = cfg.config_value
            
            cls._cache_timestamps[top_level_key] = datetime.utcnow()
            logger.info(f"ConfigManager updated: {key} by {modified_by}")
            
        except Exception as e:
            logger.error(f"Failed to update config {key}: {e}")
            await session.rollback()
            raise
    
    @classmethod
    def clear_cache(cls) -> None:
        """Clear in-memory cache and reset initialization state."""
        cls._cache.clear()
        cls._cache_timestamps.clear()
        cls._initialized = False
        logger.info("ConfigManager cache cleared")