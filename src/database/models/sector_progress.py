from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, Index
from datetime import datetime


class SectorProgress(SQLModel, table=True):
    """
    Track player progression through exploration sectors and sublevels.
    
    Each sector contains 9 sublevels (1-8 regular, 9 boss).
    Progress accumulates as percentage (0.0 - 100.0) per sublevel.
    Minibosses must be defeated to unlock next sublevel/sector.
    
    Attributes:
        player_id: Discord ID of player
        sector_id: Sector number (1-7+)
        sublevel: Sublevel within sector (1-9)
        progress: Completion percentage (0.0 - 100.0)
        miniboss_defeated: Whether sublevel miniboss has been beaten
        times_explored: Total exploration attempts in this sublevel
        total_rikis_earned: Cumulative rikis from this sublevel
        total_xp_earned: Cumulative XP from this sublevel
        maidens_purified: Count of maidens purified in this sublevel
        last_explored: Timestamp of most recent exploration
    
    Indexes:
        - (player_id, sector_id, sublevel) composite unique
        - player_id for player queries
        - last_explored for activity tracking
    """
    
    __tablename__ = "sector_progress"
    __table_args__ = (
        Index("ix_sector_progress_player_sector_sublevel", "player_id", "sector_id", "sublevel", unique=True),
        Index("ix_sector_progress_player", "player_id"),
        Index("ix_sector_progress_last_explored", "last_explored"),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        foreign_key="players.discord_id"
    )
    
    sector_id: int = Field(ge=1, nullable=False, index=True)
    sublevel: int = Field(ge=1, le=9, nullable=False, index=True)
    
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    miniboss_defeated: bool = Field(default=False)
    
    times_explored: int = Field(default=0, ge=0)
    total_rikis_earned: int = Field(default=0, ge=0, sa_column=Column(BigInteger))
    total_xp_earned: int = Field(default=0, ge=0, sa_column=Column(BigInteger))
    maidens_purified: int = Field(default=0, ge=0)
    
    last_explored: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    
    def is_complete(self) -> bool:
        """Check if sublevel is fully explored (100% + miniboss defeated)."""
        return self.progress >= 100.0 and self.miniboss_defeated
    
    def get_progress_display(self) -> str:
        """Format progress as readable percentage."""
        return f"{self.progress:.1f}%"
    
    def __repr__(self) -> str:
        return (
            f"<SectorProgress(player={self.player_id}, "
            f"sector={self.sector_id}, sublevel={self.sublevel}, "
            f"progress={self.progress:.1f}%, miniboss={self.miniboss_defeated})>"
        )