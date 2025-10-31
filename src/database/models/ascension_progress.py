from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, Index
from datetime import datetime


class AscensionProgress(SQLModel, table=True):
    """
    Track player progression through the ascension tower.
    
    Infinite tower with exponentially scaling enemies.
    Current floor represents checkpoint (last defeated floor).
    Players can always attempt current_floor + 1.
    
    Attributes:
        player_id: Discord ID of player (unique)
        current_floor: Last completed floor (checkpoint)
        highest_floor: Personal record floor reached
        total_floors_cleared: Lifetime floor clears
        total_attempts: Total floor attempts (wins + losses)
        total_victories: Successful floor clears
        total_defeats: Failed floor attempts
        total_rikis_earned: Cumulative rikis from floors
        total_xp_earned: Cumulative XP from floors
        last_attempt: Timestamp of most recent attempt
        last_victory: Timestamp of most recent floor clear
    
    Indexes:
        - player_id (unique)
        - highest_floor for leaderboards
        - last_attempt for activity tracking
    """
    
    __tablename__ = "ascension_progress"
    __table_args__ = (
        Index("ix_ascension_progress_player", "player_id", unique=True),
        Index("ix_ascension_progress_highest_floor", "highest_floor"),
        Index("ix_ascension_progress_last_attempt", "last_attempt"),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(
        sa_column=Column(BigInteger, unique=True, nullable=False, index=True),
        foreign_key="players.discord_id"
    )
    
    current_floor: int = Field(default=0, ge=0)
    highest_floor: int = Field(default=0, ge=0, index=True)
    
    total_floors_cleared: int = Field(default=0, ge=0)
    total_attempts: int = Field(default=0, ge=0)
    total_victories: int = Field(default=0, ge=0)
    total_defeats: int = Field(default=0, ge=0)
    
    total_rikis_earned: int = Field(default=0, ge=0, sa_column=Column(BigInteger))
    total_xp_earned: int = Field(default=0, ge=0, sa_column=Column(BigInteger))
    
    last_attempt: Optional[datetime] = Field(default=None, index=True)
    last_victory: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    
    def get_win_rate(self) -> float:
        """Calculate win rate percentage."""
        if self.total_attempts == 0:
            return 0.0
        return (self.total_victories / self.total_attempts) * 100
    
    def get_next_floor(self) -> int:
        """Get the next floor number to attempt."""
        return self.current_floor + 1
    
    def __repr__(self) -> str:
        return (
            f"<AscensionProgress(player={self.player_id}, "
            f"current={self.current_floor}, highest={self.highest_floor}, "
            f"winrate={self.get_win_rate():.1f}%)>"
        )