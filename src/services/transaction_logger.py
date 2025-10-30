from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.transaction_log import TransactionLog
from src.services.logger import get_logger

logger = get_logger(__name__)


class TransactionLogger:
    """
    Centralized audit logging for all game transactions (RIKI LAW Article I.2).
    
    Records every significant player action for debugging, support tickets,
    anti-cheat, and compliance. All logs stored in database for long-term retention.
    
    Transaction Types:
        - resource_change_* (rikis, grace, energy, etc.)
        - maiden_* (acquired, fused, consumed)
        - fusion_attempt
        - summon_attempt
        - prayer_performed
        - level_up
        - quest_completed
    
    Usage:
        >>> async with DatabaseService.get_transaction() as session:
        ...     await TransactionLogger.log_transaction(
        ...         session=session,
        ...         player_id=123,
        ...         transaction_type="fusion_attempt",
        ...         details={"tier": 3, "success": True},
        ...         context="command:/fuse"
        ...     )
    """
    
    @staticmethod
    async def log_transaction(
        session: AsyncSession,
        player_id: int,
        transaction_type: str,
        details: Dict[str, Any],
        context: Optional[str] = None
    ) -> None:
        """
        Log a transaction to the database.
        
        Args:
            session: Database session (must be part of active transaction)
            player_id: Discord ID of the player
            transaction_type: Type of transaction (fusion_attempt, resource_change, etc.)
            details: Structured data about the transaction
            context: Where the transaction originated (command name, event, etc.)
        """
        try:
            log_entry = TransactionLog(
                player_id=player_id,
                transaction_type=transaction_type,
                details=details,
                context=context or "unknown",
                timestamp=datetime.utcnow()
            )
            
            session.add(log_entry)
            
            logger.info(
                f"TRANSACTION: player={player_id} type={transaction_type} "
                f"details={details} context={context}"
            )
            
        except Exception as e:
            logger.error(f"Failed to log transaction: {e}")
    
    @staticmethod
    async def log_resource_change(
        session: AsyncSession,
        player_id: int,
        resource_type: str,
        old_value: int,
        new_value: int,
        reason: str,
        context: Optional[str] = None
    ) -> None:
        """
        Log a resource change (rikis, grace, energy, stamina, etc.).
        
        Args:
            session: Database session
            player_id: Discord ID
            resource_type: Type of resource (rikis, grace, energy, etc.)
            old_value: Value before change
            new_value: Value after change
            reason: Why the change occurred
            context: Command/event that triggered the change
        """
        delta = new_value - old_value
        
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type=f"resource_change_{resource_type}",
            details={
                "resource": resource_type,
                "old_value": old_value,
                "new_value": new_value,
                "delta": delta,
                "reason": reason
            },
            context=context
        )
    
    @staticmethod
    async def log_maiden_change(
        session: AsyncSession,
        player_id: int,
        action: str,
        maiden_id: int,
        maiden_name: str,
        tier: int,
        quantity_change: int,
        context: Optional[str] = None
    ) -> None:
        """
        Log maiden acquisition, fusion, or consumption.
        
        Args:
            session: Database session
            player_id: Discord ID
            action: Action type (acquired, fused, consumed)
            maiden_id: Database ID of the maiden
            maiden_name: Name of the maiden
            tier: Current tier
            quantity_change: Change in quantity (positive = gained, negative = lost)
            context: Command/event that triggered the change
        """
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type=f"maiden_{action}",
            details={
                "maiden_id": maiden_id,
                "maiden_name": maiden_name,
                "tier": tier,
                "quantity_change": quantity_change,
                "action": action
            },
            context=context
        )
    
    @staticmethod
    async def log_fusion_attempt(
        session: AsyncSession,
        player_id: int,
        success: bool,
        tier: int,
        cost: int,
        result_tier: Optional[int] = None,
        context: Optional[str] = None
    ) -> None:
        """
        Log fusion attempt with outcome.
        
        Args:
            session: Database session
            player_id: Discord ID
            success: Whether fusion succeeded
            tier: Input maiden tier
            cost: Rikis cost
            result_tier: Output maiden tier (if successful)
            context: Command that triggered fusion
        """
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type="fusion_attempt",
            details={
                "success": success,
                "input_tier": tier,
                "result_tier": result_tier,
                "cost": cost,
                "outcome": "success" if success else "failure"
            },
            context=context
        )
    
    @staticmethod
    async def flush(session: AsyncSession) -> None:
        """
        Flush pending transaction logs to database.
        
        Normally not needed as logs are added to session during transaction.
        """
        try:
            await session.flush()
            logger.debug("Transaction logs flushed to database")
        except Exception as e:
            logger.error(f"Failed to flush transaction logs: {e}")
            raise