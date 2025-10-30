from typing import Optional, Any
from contextlib import asynccontextmanager
import json
import redis.asyncio as redis
from redis.asyncio.lock import Lock
from datetime import datetime
import asyncio

from src.config import Config
from src.services.logger import get_logger

logger = get_logger(__name__)


class CircuitBreaker:
    """
    Circuit breaker pattern for Redis connection resilience.
    
    Prevents cascade failures by temporarily disabling Redis after repeated failures.
    Automatically attempts reconnection after recovery timeout.
    
    States:
        - closed: Normal operation, all calls allowed
        - open: Failures exceeded threshold, calls blocked
        - half-open: Testing if service recovered
    
    Args:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds before attempting reconnection
    """
    
    def __init__(self, failure_threshold: int, recovery_timeout: int):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"
    
    def call_succeeded(self):
        """Record successful call and reset failure counter."""
        self.failure_count = 0
        self.state = "closed"
    
    def call_failed(self):
        """Record failed call and potentially open circuit."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
    
    def can_attempt(self) -> bool:
        """
        Check if calls should be allowed.
        
        Returns:
            True if calls allowed, False if circuit is open
        """
        if self.state == "closed":
            return True
        
        if self.state == "open":
            if self.last_failure_time:
                time_since_failure = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if time_since_failure >= self.recovery_timeout:
                    self.state = "half-open"
                    logger.info("Circuit breaker entering half-open state (will attempt reconnect)")
                    return True
            return False
        
        return True


class RedisService:
    """
    Centralized Redis cache management with graceful degradation.
    
    Provides caching, distributed locking, and rate limiting with automatic
    failover to database when Redis is unavailable.
    
    Features:
        - Circuit breaker pattern for resilience
        - Automatic reconnection attempts
        - JSON serialization/deserialization
        - Distributed locks for concurrency control
        - TTL support for cache expiration
    
    Usage:
        >>> await RedisService.initialize()
        >>> await RedisService.set("player:123", {"rikis": 1000}, ttl=300)
        >>> data = await RedisService.get("player:123")
        >>> async with RedisService.acquire_lock("fusion:123"):
        ...     # Critical section
    
    Graceful Degradation:
        When Redis is unavailable, operations return None/False rather than
        raising exceptions, allowing application to continue with database fallback.
    """
    
    _client: redis.Redis = None
    _circuit_breaker: CircuitBreaker = None
    
    @classmethod
    async def initialize(cls) -> None:
        """
        Initialize Redis client with connection pooling.
        
        Raises:
            Exception: If Redis connection cannot be established
        """
        if cls._client is not None:
            logger.warning("RedisService already initialized")
            return
        
        try:
            cls._client = redis.from_url(
                Config.REDIS_URL,
                password=Config.REDIS_PASSWORD,
                max_connections=Config.REDIS_MAX_CONNECTIONS,
                decode_responses=Config.REDIS_DECODE_RESPONSES,
                socket_connect_timeout=Config.REDIS_SOCKET_TIMEOUT,
                socket_keepalive=True,
                retry_on_timeout=Config.REDIS_RETRY_ON_TIMEOUT,
            )
            
            cls._circuit_breaker = CircuitBreaker(
                failure_threshold=Config.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                recovery_timeout=Config.CIRCUIT_BREAKER_RECOVERY_TIMEOUT
            )
            
            await cls._client.ping()
            logger.info("RedisService initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize RedisService: {e}")
            raise
    
    @classmethod
    async def shutdown(cls) -> None:
        """Close Redis connection and cleanup resources."""
        if cls._client is None:
            return
        
        try:
            await cls._client.close()
            cls._client = None
            logger.info("RedisService shutdown successfully")
            
        except Exception as e:
            logger.error(f"Error during RedisService shutdown: {e}")
    
    @classmethod
    async def health_check(cls) -> bool:
        """
        Verify Redis connectivity.
        
        Returns:
            True if Redis is accessible, False otherwise
        """
        try:
            if cls._client is None:
                return False
            await cls._client.ping()
            return True
        except Exception:
            return False
    
    @classmethod
    async def _attempt_reconnect(cls) -> bool:
        """
        Attempt to reconnect to Redis after circuit breaker opens.
        
        Returns:
            True if reconnection successful, False otherwise
        """
        try:
            if cls._client is None:
                await cls.initialize()
            else:
                await cls._client.ping()
            
            cls._circuit_breaker.call_succeeded()
            logger.info("Redis reconnection successful, circuit breaker closed")
            return True
            
        except Exception as e:
            cls._circuit_breaker.call_failed()
            logger.error(f"Redis reconnection failed: {e}")
            return False
    
    @classmethod
    async def get(cls, key: str) -> Optional[Any]:
        """
        Get value from Redis cache.
        
        Automatically deserializes JSON values. Returns None if key not found
        or Redis unavailable (graceful degradation).
        
        Args:
            key: Cache key
        
        Returns:
            Cached value (deserialized if JSON) or None
        """
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            if cls._circuit_breaker.state == "half-open":
                await cls._attempt_reconnect()
            else:
                logger.warning("RedisService unavailable, circuit breaker open")
            return None
        
        try:
            value = await cls._client.get(key)
            cls._circuit_breaker.call_succeeded()
            
            if value is None:
                return None
            
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
                
        except Exception as e:
            cls._circuit_breaker.call_failed()
            logger.error(f"Redis GET error for key {key}: {e}")
            return None
    
    @classmethod
    async def set(cls, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Set value in Redis cache with optional TTL.
        
        Automatically serializes dicts/lists to JSON.
        
        Args:
            key: Cache key
            value: Value to cache (will be JSON-serialized if dict/list)
            ttl: Time-to-live in seconds (None = no expiration)
        
        Returns:
            True if successful, False if Redis unavailable
        """
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            if cls._circuit_breaker.state == "half-open":
                await cls._attempt_reconnect()
            else:
                logger.warning("RedisService unavailable, circuit breaker open")
            return False
        
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            
            if ttl:
                await cls._client.setex(key, ttl, value)
            else:
                await cls._client.set(key, value)
            
            cls._circuit_breaker.call_succeeded()
            return True
            
        except Exception as e:
            cls._circuit_breaker.call_failed()
            logger.error(f"Redis SET error for key {key}: {e}")
            return False
    
    @classmethod
    async def delete(cls, key: str) -> bool:
        """Delete key from Redis cache."""
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            return False
        
        try:
            await cls._client.delete(key)
            cls._circuit_breaker.call_succeeded()
            return True
            
        except Exception as e:
            cls._circuit_breaker.call_failed()
            logger.error(f"Redis DELETE error for key {key}: {e}")
            return False
    
    @classmethod
    async def exists(cls, key: str) -> bool:
        """Check if key exists in Redis cache."""
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            return False
        
        try:
            result = await cls._client.exists(key)
            cls._circuit_breaker.call_succeeded()
            return result > 0
        except Exception as e:
            cls._circuit_breaker.call_failed()
            logger.error(f"Redis EXISTS error for key {key}: {e}")
            return False
    
    @classmethod
    async def increment(cls, key: str, amount: int = 1) -> Optional[int]:
        """
        Atomically increment integer value in Redis.
        
        Args:
            key: Cache key
            amount: Amount to increment by
        
        Returns:
            New value after increment, or None if Redis unavailable
        """
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            return None
        
        try:
            result = await cls._client.incrby(key, amount)
            cls._circuit_breaker.call_succeeded()
            return result
        except Exception as e:
            cls._circuit_breaker.call_failed()
            logger.error(f"Redis INCR error for key {key}: {e}")
            return None
    
    @classmethod
    async def expire(cls, key: str, ttl: int) -> bool:
        """Set TTL on existing key."""
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            return False
        
        try:
            await cls._client.expire(key, ttl)
            cls._circuit_breaker.call_succeeded()
            return True
        except Exception as e:
            cls._circuit_breaker.call_failed()
            logger.error(f"Redis EXPIRE error for key {key}: {e}")
            return False
    
    @classmethod
    @asynccontextmanager
    async def acquire_lock(cls, lock_name: str, timeout: int = 5, blocking_timeout: int = 3):
        """
        Acquire distributed lock for critical sections (RIKI LAW Article I.3).
        
        Prevents race conditions in concurrent operations like fusion, trading,
        or button double-clicks.
        
        Args:
            lock_name: Unique identifier for the lock
            timeout: Lock expiration time (seconds)
            blocking_timeout: Max time to wait for lock (seconds)
        
        Yields:
            Lock object
        
        Raises:
            RuntimeError: If Redis unavailable (circuit breaker open)
            TimeoutError: If lock cannot be acquired within blocking_timeout
        
        Example:
            >>> async with RedisService.acquire_lock(f"fusion:{player_id}"):
            ...     # Critical section - only one coroutine can execute this
            ...     await perform_fusion(player_id)
        """
        if cls._client is None or not cls._circuit_breaker.can_attempt():
            if cls._circuit_breaker.state == "half-open":
                await cls._attempt_reconnect()
            
            if not cls._circuit_breaker.can_attempt():
                raise RuntimeError(f"Redis unavailable, circuit breaker open. Cannot acquire lock: {lock_name}")
        
        lock = Lock(cls._client, lock_name, timeout=timeout, blocking_timeout=blocking_timeout)
        
        try:
            acquired = await lock.acquire(blocking=True, blocking_timeout=blocking_timeout)
            cls._circuit_breaker.call_succeeded()
            
            if not acquired:
                raise TimeoutError(f"Failed to acquire lock: {lock_name}")
            
            yield lock
            
        except Exception as e:
            cls._circuit_breaker.call_failed()
            logger.error(f"Redis LOCK error for {lock_name}: {e}")
            raise
        finally:
            try:
                await lock.release()
            except Exception as e:
                logger.error(f"Error releasing lock {lock_name}: {e}")