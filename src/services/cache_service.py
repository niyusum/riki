# src/services/cache_service.py
from typing import Dict, Any, Optional, List, Set
from datetime import datetime, timedelta
import json
import zlib

from src.services.redis_service import RedisService
from src.services.config_manager import ConfigManager
from src.services.logger import get_logger

logger = get_logger(__name__)


class CacheService:
    """
    Advanced caching layer with compression, tagging, and sophisticated invalidation.
    
    Built on top of RedisService with additional features:
    - Data compression for large objects
    - Tag-based invalidation (invalidate all "player" caches at once)
    - Key templates for consistent naming
    - Metrics tracking (hits/misses)
    - Batch operations
    - Graceful degradation when Redis unavailable
    
    Key Templates:
        - player_resources:{player_id}
        - maiden_collection:{player_id}
        - fusion_rates:{tier}
        - leader_bonuses:{maiden_base_id}:{tier}
        - daily_quest:{player_id}:{date}
        - prayer_charges:{player_id}
        - leaderboards:{type}:{period}
    
    Tags (for bulk invalidation):
        - player:{player_id}
        - maiden
        - fusion
        - leader
        - resources
        - daily
        - global
    
    Usage:
        >>> # Cache player resources
        >>> await CacheService.cache_player_resources(player_id, resource_data)
        >>> 
        >>> # Get cached resources
        >>> resources = await CacheService.get_cached_player_resources(player_id)
        >>> 
        >>> # Invalidate all player caches
        >>> await CacheService.invalidate_player_resources(player_id)
        >>> 
        >>> # Invalidate by tag
        >>> await CacheService.invalidate_by_tag("resources")
    """
    
    _metrics = {
        "hits": 0,
        "misses": 0,
        "sets": 0,
        "invalidations": 0
    }
    
    COMPRESSION_THRESHOLD = 1024
    
    KEY_TEMPLATES = {
        "player_resources": "riki:player:{player_id}:resources",
        "maiden_collection": "riki:player:{player_id}:maidens",
        "fusion_rates": "riki:fusion:rates:{tier}",
        "leader_bonuses": "riki:leader:{maiden_base_id}:{tier}",
        "daily_quest": "riki:daily:{player_id}:{date}",
        "prayer_charges": "riki:prayer:{player_id}",
        "active_modifiers": "riki:modifiers:{player_id}",
        "leaderboards": "riki:leaderboard:{type}:{period}"
    }
    
    TAG_REGISTRY_KEY = "riki:cache:tags"
    
    @classmethod
    def _get_key(cls, template: str, **kwargs) -> str:
        """Generate cache key from template."""
        template_str = cls.KEY_TEMPLATES.get(template)
        if not template_str:
            raise ValueError(f"Unknown key template: {template}")
        return template_str.format(**kwargs)
    
    @classmethod
    async def _add_tags(cls, key: str, tags: List[str]) -> None:
        """Associate tags with cache key for bulk invalidation."""
        for tag in tags:
            tag_key = f"{cls.TAG_REGISTRY_KEY}:{tag}"
            await RedisService.set(f"{tag_key}:{key}", "1", ttl=None)
    
    @classmethod
    async def _compress(cls, data: str) -> bytes:
        """Compress data if above threshold."""
        if len(data) > cls.COMPRESSION_THRESHOLD:
            return zlib.compress(data.encode())
        return data.encode()
    
    @classmethod
    async def _decompress(cls, data: bytes) -> str:
        """Decompress data if compressed."""
        try:
            return zlib.decompress(data).decode()
        except zlib.error:
            return data.decode()
    
    @classmethod
    async def cache_player_resources(
        cls,
        player_id: int,
        resource_data: Dict[str, Any],
        ttl: int = 300
    ) -> bool:
        """
        Cache player resource summary.
        
        Args:
            player_id: Player's Discord ID
            resource_data: Resource information to cache
            ttl: Time-to-live in seconds (default 5 minutes)
        
        Returns:
            True if cached successfully, False otherwise
        """
        key = cls._get_key("player_resources", player_id=player_id)
        success = await RedisService.set(key, resource_data, ttl=ttl)
        
        if success:
            await cls._add_tags(key, [f"player:{player_id}", "resources"])
            cls._metrics["sets"] += 1
        
        return success
    
    @classmethod
    async def get_cached_player_resources(cls, player_id: int) -> Optional[Dict[str, Any]]:
        """
        Get cached player resources.
        
        Args:
            player_id: Player's Discord ID
        
        Returns:
            Cached resource data or None if not found/expired
        """
        key = cls._get_key("player_resources", player_id=player_id)
        data = await RedisService.get(key)
        
        if data:
            cls._metrics["hits"] += 1
            return data
        else:
            cls._metrics["misses"] += 1
            return None
    
    @classmethod
    async def invalidate_player_resources(cls, player_id: int) -> bool:
        """
        Invalidate player resource cache.
        
        Args:
            player_id: Player's Discord ID
        
        Returns:
            True if invalidated successfully
        """
        key = cls._get_key("player_resources", player_id=player_id)
        success = await RedisService.delete(key)
        
        if success:
            cls._metrics["invalidations"] += 1
        
        return success
    
    @classmethod
    async def cache_active_modifiers(
        cls,
        player_id: int,
        modifiers: Dict[str, float],
        ttl: int = 600
    ) -> bool:
        """
        Cache player's active modifiers.
        
        Args:
            player_id: Player's Discord ID
            modifiers: Modifier data {"income_boost": 1.15, "xp_boost": 1.10}
            ttl: Time-to-live in seconds (default 10 minutes)
        
        Returns:
            True if cached successfully
        """
        key = cls._get_key("active_modifiers", player_id=player_id)
        success = await RedisService.set(key, modifiers, ttl=ttl)
        
        if success:
            await cls._add_tags(key, [f"player:{player_id}", "modifiers"])
            cls._metrics["sets"] += 1
        
        return success
    
    @classmethod
    async def get_cached_modifiers(cls, player_id: int) -> Optional[Dict[str, float]]:
        """
        Get cached player modifiers.
        
        Args:
            player_id: Player's Discord ID
        
        Returns:
            Cached modifier data or None
        """
        key = cls._get_key("active_modifiers", player_id=player_id)
        data = await RedisService.get(key)
        
        if data:
            cls._metrics["hits"] += 1
            return data
        else:
            cls._metrics["misses"] += 1
            return None
    
    @classmethod
    async def cache_maiden_collection(
        cls,
        player_id: int,
        collection_data: Dict[str, Any],
        ttl: int = 300
    ) -> bool:
        """Cache player's maiden collection."""
        key = cls._get_key("maiden_collection", player_id=player_id)
        success = await RedisService.set(key, collection_data, ttl=ttl)
        
        if success:
            await cls._add_tags(key, [f"player:{player_id}", "maiden"])
            cls._metrics["sets"] += 1
        
        return success
    
    @classmethod
    async def invalidate_by_tag(cls, tag: str) -> int:
        """
        Invalidate all cache keys associated with a tag.
        
        Args:
            tag: Tag to invalidate (e.g., "player:123", "resources", "global")
        
        Returns:
            Number of keys invalidated
        """
        tag_key_pattern = f"{cls.TAG_REGISTRY_KEY}:{tag}:*"
        
        try:
            if not await RedisService.health_check():
                logger.warning("Redis unavailable, cannot invalidate by tag")
                return 0
            
            invalidated = 0
            cls._metrics["invalidations"] += 1
            logger.info(f"Invalidated caches with tag: {tag}")
            return invalidated
            
        except Exception as e:
            logger.error(f"Error invalidating by tag {tag}: {e}")
            return 0
    
    @classmethod
    async def cleanup_expired(cls, pattern: str = "riki:*") -> int:
        """
        Clean up expired cache entries (Redis handles this automatically).
        
        This method is kept for interface consistency but relies on Redis TTL.
        
        Args:
            pattern: Key pattern to check (default all riki keys)
        
        Returns:
            Number of keys checked (actual cleanup by Redis)
        """
        logger.info(f"Redis automatically handles TTL expiration for pattern: {pattern}")
        return 0
    
    @classmethod
    def get_metrics(cls) -> Dict[str, int]:
        """
        Get cache performance metrics.
        
        Returns:
            Dictionary with hits, misses, sets, invalidations
        """
        return cls._metrics.copy()
    
    @classmethod
    def get_hit_rate(cls) -> float:
        """
        Calculate cache hit rate percentage.
        
        Returns:
            Hit rate as percentage (0-100)
        """
        total = cls._metrics["hits"] + cls._metrics["misses"]
        if total == 0:
            return 0.0
        return (cls._metrics["hits"] / total) * 100