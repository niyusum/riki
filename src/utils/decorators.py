from typing import Callable
from functools import wraps
import discord

from src.services.redis_service import RedisService
from src.exceptions import RateLimitError
from src.services.logger import get_logger

logger = get_logger(__name__)


def ratelimit(uses: int, per_seconds: int, command_name: str):
    """
    Rate limit decorator for Discord commands (RIKI LAW).
    
    Prevents command spam by limiting uses within time window.
    Uses Redis for distributed rate limiting, falls back to allowing command if Redis unavailable.
    
    Args:
        uses: Number of uses allowed per time window
        per_seconds: Time window in seconds
        command_name: Name of the command (for logging and key generation)
    
    Returns:
        Decorator function
    
    Raises:
        RateLimitError: If user exceeds rate limit
    
    Example:
        >>> @commands.slash_command(name="fuse")
        >>> @ratelimit(uses=5, per_seconds=60, command_name="fuse")
        >>> async def fuse(self, inter: discord.Interaction):
        ...     # Can only be used 5 times per minute
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, inter: discord.Interaction, *args, **kwargs):
            key = f"ratelimit:{command_name}:{inter.user.id}"
            
            try:
                current = await RedisService.get(key)
                
                if current and int(current) >= uses:
                    ttl = await RedisService._client.ttl(key)
                    raise RateLimitError(
                        command=command_name,
                        retry_after=float(ttl) if ttl > 0 else per_seconds
                    )
                
                if current:
                    await RedisService.increment(key)
                else:
                    await RedisService.set(key, 1, ttl=per_seconds)
                
                return await func(self, inter, *args, **kwargs)
                
            except RateLimitError:
                raise
            except Exception as e:
                logger.error(f"Rate limit check failed for {command_name}: {e}")
                return await func(self, inter, *args, **kwargs)
        
        return wrapper
    return decorator