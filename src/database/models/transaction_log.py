from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, Index, Text
from sqlalchemy.dialects.postgresql import JSON
from datetime import datetime


class TransactionLog(SQLModel, table=True):
    """
    Audit trail for all significant player actions.
    
    Records every resource change, fusion attempt, summon, and other operations
    for debugging, support, and anti-cheat purposes.
    
    Attributes:
        player_id: Discord ID of player
        transaction_type: Type of transaction (fusion_attempt, resource_change, etc.)
        details: Structured JSON data about the transaction
        context: Where the transaction originated (command, event, system)
        timestamp: When the transaction occurred
    
    Indexes:
        - (player_id, timestamp) for player history queries
        - transaction_type for aggregate queries
        - timestamp for cleanup of old logs
    """
    
    __tablename__ = "transaction_logs"
    __table_args__ = (
        Index("ix_transaction_logs_player_time", "player_id", "timestamp"),
        Index("ix_transaction_logs_type", "transaction_type"),
        Index("ix_transaction_logs_timestamp", "timestamp"),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        foreign_key="players.discord_id"
    )
    
    transaction_type: str = Field(max_length=100, nullable=False, index=True)
    details: Dict[str, Any] = Field(sa_column=Column(JSON), nullable=False)
    context: str = Field(sa_column=Column(Text), nullable=False)
    
    timestamp: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    
    def __repr__(self) -> str:
        return (
            f"<TransactionLog(id={self.id}, player={self.player_id}, "
            f"type='{self.transaction_type}', time={self.timestamp})>"
        )