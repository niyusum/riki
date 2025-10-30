from typing import Dict, Any, Optional
from datetime import datetime
from sqlmodel import Field, SQLModel, Column, BigInteger, select
from sqlalchemy import Index
import json

from src.services.logger import get_logger

logger = get_logger(__name__)


class Transaction(SQLModel, table=True):
    """
    Audit log for all resource changes and player actions.
    
    Tracks every rikis change, summon, fusion, and other significant
    player actions for debugging, analytics, and potential rollbacks.
    
    Attributes:
        player_id: Discord ID of player
        transaction_type: Type of action (summon, fusion, daily_claim, etc.)
        rikis_change: Amount of rikis gained/spent (negative for spending)
        timestamp: When action occurred
        details: JSON field with additional context
    
    Indexes:
        - player_id (for player history queries)
        - timestamp (for time-range queries)
        - transaction_type (for analytics)
    """
    
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_player_id", "player_id"),
        Index("ix_transactions_timestamp", "timestamp"),
        Index("ix_transactions_type", "transaction_type"),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True)
    )
    transaction_type: str = Field(max_length=50, nullable=False, index=True)
    rikis_change: int = Field(default=0, sa_column=Column(BigInteger))
    timestamp: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    details: Optional[str] = Field(default=None)


class TransactionService:
    """
    Service for logging all player transactions and resource changes.
    
    Every action that changes player resources or state should be logged
    through this service for audit trails, analytics, and debugging.
    
    Usage:
        >>> await TransactionService.log(
        ...     session=session,
        ...     player_id=123456789,
        ...     transaction_type="summon",
        ...     rikis_change=-100,
        ...     details={"maiden_base_id": 5, "tier": 3}
        ... )
    """
    
    @staticmethod
    async def log(
        session,
        player_id: int,
        transaction_type: str,
        rikis_change: int = 0,
        details: Optional[Dict[str, Any]] = None
    ) -> Transaction:
        """
        Log a transaction to the database.
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            transaction_type: Type of transaction (summon, fusion, daily_claim, etc.)
            rikis_change: Amount of rikis changed (negative for spending)
            details: Additional context as dictionary (will be JSON serialized)
        
        Returns:
            Created Transaction object
        
        Example:
            >>> await TransactionService.log(
            ...     session=session,
            ...     player_id=123456789,
            ...     transaction_type="fusion",
            ...     rikis_change=-5000,
            ...     details={
            ...         "maiden_base_id": 10,
            ...         "from_tier": 3,
            ...         "to_tier": 4,
            ...         "success": True
            ...     }
            ... )
        """
        details_json = None
        if details:
            try:
                details_json = json.dumps(details)
            except (TypeError, ValueError) as e:
                logger.error(f"Failed to serialize transaction details: {e}")
                details_json = json.dumps({"error": "serialization_failed"})
        
        transaction = Transaction(
            player_id=player_id,
            transaction_type=transaction_type,
            rikis_change=rikis_change,
            details=details_json
        )
        
        session.add(transaction)
        
        logger.debug(
            f"Transaction logged: {transaction_type} for player {player_id} "
            f"(rikis_change: {rikis_change})"
        )
        
        return transaction
    
    @staticmethod
    async def get_player_history(
        session,
        player_id: int,
        limit: int = 50,
        transaction_type: Optional[str] = None
    ) -> list[Transaction]:
        """
        Get transaction history for a player.
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            limit: Maximum number of transactions to return
            transaction_type: Optional filter by transaction type
        
        Returns:
            List of Transaction objects, newest first
        
        Example:
            >>> history = await TransactionService.get_player_history(
            ...     session=session,
            ...     player_id=123456789,
            ...     limit=20,
            ...     transaction_type="summon"
            ... )
        """
        stmt = select(Transaction).where(Transaction.player_id == player_id)
        
        if transaction_type:
            stmt = stmt.where(Transaction.transaction_type == transaction_type)
        
        stmt = stmt.order_by(Transaction.timestamp.desc()).limit(limit)
        
        result = await session.exec(stmt)
        return result.all()
    
    @staticmethod
    async def get_total_spent(
        session,
        player_id: int,
        transaction_type: Optional[str] = None
    ) -> int:
        """
        Calculate total rikis spent by player.
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            transaction_type: Optional filter by transaction type
        
        Returns:
            Total rikis spent (positive number)
        
        Example:
            >>> total = await TransactionService.get_total_spent(
            ...     session=session,
            ...     player_id=123456789,
            ...     transaction_type="summon"
            ... )
            >>> print(f"Spent {total} rikis on summons")
        """
        from sqlalchemy import func
        
        stmt = select(func.sum(Transaction.rikis_change)).where(
            Transaction.player_id == player_id,
            Transaction.rikis_change < 0
        )
        
        if transaction_type:
            stmt = stmt.where(Transaction.transaction_type == transaction_type)
        
        result = await session.exec(stmt)
        total = result.one_or_none()
        
        return abs(total) if total else 0
    
    @staticmethod
    async def get_total_earned(
        session,
        player_id: int,
        transaction_type: Optional[str] = None
    ) -> int:
        """
        Calculate total rikis earned by player.
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            transaction_type: Optional filter by transaction type
        
        Returns:
            Total rikis earned
        
        Example:
            >>> total = await TransactionService.get_total_earned(
            ...     session=session,
            ...     player_id=123456789,
            ...     transaction_type="daily_claim"
            ... )
            >>> print(f"Earned {total} rikis from dailies")
        """
        from sqlalchemy import func
        
        stmt = select(func.sum(Transaction.rikis_change)).where(
            Transaction.player_id == player_id,
            Transaction.rikis_change > 0
        )
        
        if transaction_type:
            stmt = stmt.where(Transaction.transaction_type == transaction_type)
        
        result = await session.exec(stmt)
        total = result.one_or_none()
        
        return total if total else 0
    
    @staticmethod
    async def get_action_count(
        session,
        player_id: int,
        transaction_type: str
    ) -> int:
        """
        Count how many times player performed an action.
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            transaction_type: Type of transaction to count
        
        Returns:
            Count of transactions
        
        Example:
            >>> summon_count = await TransactionService.get_action_count(
            ...     session=session,
            ...     player_id=123456789,
            ...     transaction_type="summon"
            ... )
            >>> print(f"Summoned {summon_count} times")
        """
        from sqlalchemy import func
        
        stmt = select(func.count(Transaction.id)).where(
            Transaction.player_id == player_id,
            Transaction.transaction_type == transaction_type
        )
        
        result = await session.exec(stmt)
        return result.one()