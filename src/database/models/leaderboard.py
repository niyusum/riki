from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, Index
from datetime import datetime


class LeaderboardSnapshot(SQLModel, table=True):
    """
    Cached leaderboard rankings for a player in a specific category.
    
    Updated periodically to avoid expensive real-time ranking queries.
    Multiple categories tracked: total_power, level, fusions, etc.
    
    Attributes:
        player_id: Discord ID
        username: Player's Discord username (denormalized for display)
        category: Leaderboard type (total_power, level, fusions, etc.)
        rank: Current ranking position
        rank_change: Change since last snapshot (positive = moving up)
        value: The actual value being ranked
        snapshot_version: Version counter for this leaderboard generation
        updated_at: When this snapshot was taken
    
    Indexes:
        - (category, rank) for fast leaderboard queries
        - player_id for player-specific lookups
        - updated_at for cleanup of old snapshots
    """
    
    __tablename__ = "leaderboard_snapshots"
    __table_args__ = (
        Index("ix_leaderboard_category_rank", "category", "rank"),
        Index("ix_leaderboard_player", "player_id"),
        Index("ix_leaderboard_updated", "updated_at"),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        foreign_key="players.discord_id"
    )
    username: str = Field(max_length=100)
    
    category: str = Field(max_length=50, nullable=False, index=True)
    rank: int = Field(nullable=False, index=True)
    rank_change: int = Field(default=0)
    value: int = Field(sa_column=Column(BigInteger), nullable=False)
    
    snapshot_version: int = Field(default=1)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    
    def get_rank_display(self) -> str:
        """Format rank with medal emojis for top 3."""
        if self.rank == 1:
            return "🥇 #1"
        elif self.rank == 2:
            return "🥈 #2"
        elif self.rank == 3:
            return "🥉 #3"
        else:
            return f"#{self.rank}"
    
    def get_rank_change_display(self) -> str:
        """Format rank change with directional indicators."""
        if self.rank_change > 0:
            return f"📈 +{self.rank_change}"
        elif self.rank_change < 0:
            return f"📉 {self.rank_change}"
        else:
            return "➡️ 0"
    
    def __repr__(self) -> str:
        return (
            f"<LeaderboardSnapshot(player={self.player_id}, "
            f"category='{self.category}', rank={self.rank}, value={self.value})>"
        )