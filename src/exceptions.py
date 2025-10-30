from typing import Optional, Any, Dict


class RIKIException(Exception):
    """
    Base exception for all RIKI RPG errors.
    
    Provides structured error information with details for logging and user display.
    All custom exceptions should inherit from this base class.
    
    Args:
        message: Human-readable error message
        details: Additional structured data about the error
    
    Example:
        >>> raise RIKIException("Something went wrong", {"context": "fusion"})
    """
    
    def __init__(self, message: str, details: Optional[Any] = None):
        self.message = message
        self.details = details
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/serialization."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details
        }


class InsufficientResourcesError(RIKIException):
    """
    Raised when player lacks required resources for an action.
    
    Args:
        resource: Name of the resource (rikis, grace, energy, etc.)
        required: Amount needed
        current: Amount player has
    
    Example:
        >>> raise InsufficientResourcesError("rikis", 5000, 1000)
    """
    
    def __init__(self, resource: str, required: int, current: int):
        self.resource = resource
        self.required = required
        self.current = current
        message = f"Insufficient {resource}: need {required:,}, have {current:,}"
        super().__init__(message, {"resource": resource, "required": required, "current": current})


class MaidenNotFoundError(RIKIException):
    """
    Raised when a maiden cannot be found in player's collection.
    
    Args:
        maiden_id: Database ID of the maiden
        maiden_name: Name of the maiden
    """
    
    def __init__(self, maiden_id: Optional[int] = None, maiden_name: Optional[str] = None):
        self.maiden_id = maiden_id
        self.maiden_name = maiden_name
        message = f"Maiden not found: {maiden_name or f'ID {maiden_id}'}"
        super().__init__(message, {"maiden_id": maiden_id, "maiden_name": maiden_name})


class PlayerNotFoundError(RIKIException):
    """
    Raised when a player cannot be found in database.
    
    Args:
        discord_id: Discord user ID
    """
    
    def __init__(self, discord_id: int):
        self.discord_id = discord_id
        message = f"Player not found: {discord_id}"
        super().__init__(message, {"discord_id": discord_id})


class ValidationError(RIKIException):
    """
    Raised when user input fails validation.
    
    Args:
        field: Name of the field that failed validation
        message: Description of why validation failed
    """
    
    def __init__(self, field: str, message: str):
        self.field = field
        error_message = f"Validation error for {field}: {message}"
        super().__init__(error_message, {"field": field, "message": message})


class FusionError(RIKIException):
    """
    Raised when fusion operation fails for business logic reasons.
    
    Args:
        reason: Description of why fusion failed
    """
    
    def __init__(self, reason: str):
        message = f"Fusion failed: {reason}"
        super().__init__(message, {"reason": reason})


class CooldownError(RIKIException):
    """
    Raised when action is on cooldown.
    
    Args:
        action: Name of the action on cooldown
        remaining_seconds: Time remaining until action available
    """
    
    def __init__(self, action: str, remaining_seconds: float):
        self.action = action
        self.remaining_seconds = remaining_seconds
        message = f"{action} is on cooldown: {remaining_seconds:.1f}s remaining"
        super().__init__(message, {"action": action, "remaining": remaining_seconds})


class ConfigurationError(RIKIException):
    """
    Raised when configuration is invalid or missing.
    
    Args:
        config_key: The configuration key that has issues
        message: Description of the configuration problem
    """
    
    def __init__(self, config_key: str, message: str):
        self.config_key = config_key
        error_message = f"Configuration error for {config_key}: {message}"
        super().__init__(error_message, {"config_key": config_key, "message": message})


class DatabaseError(RIKIException):
    """
    Raised when database operations fail.
    
    Args:
        operation: Description of the operation that failed
        original_error: The underlying exception
    """
    
    def __init__(self, operation: str, original_error: Exception):
        self.operation = operation
        self.original_error = original_error
        message = f"Database error during {operation}: {str(original_error)}"
        super().__init__(message, {"operation": operation, "error": str(original_error)})


class RateLimitError(RIKIException):
    """
    Raised when command rate limit is exceeded.
    
    Args:
        command: Name of the rate-limited command
        retry_after: Seconds until command can be used again
    """
    
    def __init__(self, command: str, retry_after: float):
        self.command = command
        self.retry_after = retry_after
        message = f"Rate limit exceeded for {command}: retry after {retry_after:.1f}s"
        super().__init__(message, {"command": command, "retry_after": retry_after})