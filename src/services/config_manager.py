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
            "shards_per_failure_min": 1,
            "shards_per_failure_max": 12,
            "shards_for_redemption": 100,
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
            "grace_per_prayer": 1,
            "max_charges": 5,
            "regen_minutes": 5,
            "class_bonuses": {
                "destroyer": 1.0,
                "adapter": 1.0,
                "invoker": 1.2
            }
        },
        "gacha_rates": {
            "tier_unlock_levels": {
                "tier_1": 1,
                "tier_2": 1,
                "tier_3": 1,
                "tier_4": 10,
                "tier_5": 20,
                "tier_6": 30,
                "tier_7": 30,
                "tier_8": 40,
                "tier_9": 40,
                "tier_10": 40,
                "tier_11": 45,
                "tier_12": 50
            },
            "rate_distribution": {
            "decay_factor": 0.75,
            "highest_tier_base": 22.0
        }
        },
        "pity_system": {
            "summons_for_pity": 25,
            "pity_type": "new_maiden_or_next_bracket"
        },
        "summon_costs": {
            "grace_per_summon": 5,
            "x5_multiplier": 5,
            "x10_multiplier": 10,
            "x10_premium_only": True
        },
        "event_modifiers": {
            "fusion_rate_boost": 0.0,
            "xp_boost": 0.0,
            "rikis_boost": 0.0,
            "shard_boost": 0.0
        },
        "daily_rewards": {
            "base_rikis": 500,
            "base_grace": 3,
            "base_gems": 1,
            "base_xp": 100,
            "completion_bonus_rikis": 500,
            "completion_bonus_grace": 2,
            "completion_bonus_gems": 1,
            "completion_bonus_xp": 200,
            "streak_multiplier": 0.1
        },
        "daily_quests": {
            "prayer_required": 1,
            "summon_required": 1,
            "fusion_required": 1,
            "energy_required": 10,
            "stamina_required": 5
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
        },
        "resource_system": {
            "grace_max_cap": 999999,
            "rikis_max_cap": None,  # No cap for rikis
            "riki_gems_max_cap": None,  # No cap for gems
            "modifier_stacking": "multiplicative",
            "passive_income_enabled": False,  # Future feature
            "audit_retention_days": 90
        },
        "modifier_rules": {
            "stack_method": "multiplicative",
            "max_bonus_cap": 300,  # 300% maximum bonus
            "min_penalty_cap": 10  # 10% minimum (90% penalty max)
        },
        "exploration_system": {
            "progress_rates": {
                "sector_1": 7.0,
                "sector_2": 4.5,
                "sector_3": 3.5,
                "sector_4": 2.5,
                "sector_5": 2.0,
                "sector_6": 1.5,
                "sector_7": 1.0,
            },
            "miniboss_progress_multiplier": 0.5,
            "energy_costs": {
                "sector_1_base": 5,
                "sector_2_base": 8,
                "sector_3_base": 12,
                "sector_4_base": 17,
                "sector_5_base": 23,
                "sector_6_base": 30,
                "sector_7_base": 38,
                "sublevel_increment": 1,
                "boss_multiplier": 1.5
            },
            "riki_rewards": {
                "sector_1_min": 50,
                "sector_1_max": 100,
                "sector_scaling": 1.5,
            },
            "xp_rewards": {
                "sector_1_min": 10,
                "sector_1_max": 30,
                "sector_scaling": 1.5,
            },
            "encounter_rates": {
                "sector_1": 8.0,
                "sector_2": 10.0,
                "sector_3": 12.0,
                "sector_4": 12.0,
                "sector_5": 15.0,
                "sector_6": 15.0,
                "sector_7": 18.0,
            },
            "capture_rates": {
                "common": 60.0,
                "uncommon": 45.0,
                "rare": 30.0,
                "epic": 15.0,
                "legendary": 8.0,
                "mythic": 3.0,
            },
            "capture_level_modifier": 2.0,
            "guaranteed_purification_costs": {
                "common": 50,
                "uncommon": 100,
                "rare": 200,
                "epic": 500,
                "legendary": 1500,
                "mythic": 5000,
            },
            "unlock_requirement": 100.0,
        },
        
        # MINIBOSS SYSTEM
        "miniboss_system": {
            "hp_base": {
                "uncommon": 2000,
                "rare": 5000,
                "epic": 15000,
                "legendary": 50000,
                "mythic": 150000,
            },
            "hp_sector_multiplier": 0.5,
            "hp_sublevel_multiplier": 0.1,
            "sector_avg_rarity": {
                "sector_1": "uncommon",
                "sector_2": "rare",
                "sector_3": "rare",
                "sector_4": "epic",
                "sector_5": "epic",
                "sector_6": "legendary",
                "sector_7": "legendary",
            },
            "rarity_tier_increase": [1, 2],
            "reward_base_rikis": 500,
            "reward_base_xp": 100,
            "reward_sector_multiplier": 1.0,
            "boss_sublevel_bonus": 2.0,
            "boss_rewards": {
                "prayer_charges": 1,
                "fusion_catalyst": 1,
            },
            "egg_rarity_upgrade": True,
        },
        
        # ASCENSION SYSTEM
        "ascension_system": {
            "base_stamina_cost": 5,
            "stamina_increase_per_10_levels": 1,
            "enemy_hp_base": 1000,
            "enemy_hp_growth_rate": 1.12,
            "attack_multipliers": {
                "x1": 1,
                "x5": 5,
                "x20": 20,
            },
            "x20_attack_crit_bonus": 0.2,
            "x20_attack_gem_cost": 10,
            "reward_base_rikis": 50,
            "reward_base_xp": 20,
            "reward_growth_rate": 1.1,
            "bonus_intervals": {
                "egg_every_n_floors": 5,
                "prayer_charge_every_n_floors": 10,
                "fusion_catalyst_every_n_floors": 25,
            },
            "milestones": {
                50: {
                    "title": "Tower Climber",
                    "rikis": 10000,
                    "gems": 50,
                },
                100: {
                    "title": "Sky Breaker",
                    "rikis": 50000,
                    "gems": 100,
                    "mythic_egg": True,
                },
                150: {
                    "title": "Heaven Piercer",
                    "rikis": 100000,
                    "gems": 200,
                },
                200: {
                    "title": "Divine Ascendant",
                    "rikis": 250000,
                    "gems": 500,
                },
            },
            "egg_rarity_floors": {
                "common": [1, 10],
                "uncommon": [11, 25],
                "rare": [26, 50],
                "epic": [51, 100],
                "legendary": [101, 200],
                "mythic": [201, 999999],
            }
        }
    }
    
    @classmethod
    async def initialize(cls, session: AsyncSession) -> None:
        """
        Initialize ConfigManager by loading all config from database.
        
        Loads all GameConfig rows from database and populates in-memory cache.
        Falls back to hardcoded defaults if database is empty.
        Starts background refresh task for periodic cache updates.
        
        Args:
            session: Database session
        
        Raises:
            Exception: If database connection fails
        
        Example:
            >>> async with DatabaseService.get_session() as session:
            ...     await ConfigManager.initialize(session)
        """
        try:
            result = await session.execute(select(GameConfig))
            configs = result.scalars().all()
            
            if configs:
                for config in configs:
                    cls._cache[config.config_key] = config.config_value
                    cls._cache_timestamps[config.config_key] = datetime.utcnow()
                logger.info(f"ConfigManager initialized with {len(configs)} config entries")
            else:
                cls._cache = cls._defaults.copy()
                logger.info("ConfigManager initialized with default config (database empty)")
            
            cls._initialized = True
            
            if cls._refresh_task is None:
                cls._refresh_task = asyncio.create_task(cls._background_refresh())
                logger.info("ConfigManager background refresh task started")
            
        except Exception as e:
            logger.error(f"Failed to initialize ConfigManager: {e}")
            cls._cache = cls._defaults.copy()
            cls._initialized = True
            raise
    
    @classmethod
    async def _background_refresh(cls) -> None:
        """Background task to refresh cache periodically."""
        while True:
            try:
                await asyncio.sleep(cls._cache_ttl)
                from src.services.database_service import DatabaseService
                
                async with DatabaseService.get_session() as session:
                    result = await session.execute(select(GameConfig))
                    configs = result.scalars().all()
                    
                    for config in configs:
                        cls._cache[config.config_key] = config.config_value
                        cls._cache_timestamps[config.config_key] = datetime.utcnow()
                    
                    logger.debug(f"ConfigManager cache refreshed ({len(configs)} entries)")
                    
            except asyncio.CancelledError:
                logger.info("ConfigManager background refresh cancelled")
                break
            except Exception as e:
                logger.error(f"ConfigManager background refresh error: {e}")
    
    @classmethod
    async def shutdown(cls) -> None:
        """Stop background refresh task and cleanup."""
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
    async def set(
        cls,
        session: AsyncSession,
        key: str,
        value: Any,
        modified_by: str = "system"
    ) -> None:
        """
        Set configuration value in database and update cache.
        
        Updates both database and in-memory cache.
        Supports dot notation for nested values.
        
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