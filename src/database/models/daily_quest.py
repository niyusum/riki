from typing import Optional, Dict
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, Index
from sqlalchemy.dialects.postgresql import JSON
from datetime import datetime, date


class DailyQuest(SQLModel, table=True):
    """
    Daily quest progress tracking for a player.
    
    One row per player per day. Tracks completion of 5 daily objectives
    and progress toward each. Rewards claimed separately to prevent double-claiming.
    
    Quest Types:
        - prayer_performed: Use /prayer at least once
        - summon_maiden: Summon at least one maiden
        - attempt_fusion: Attempt fusion at least once
        - spend_energy: Spend energy on quests
        - spend_stamina: Spend stamina on battles
    
    Attributes:
        player_id: Owner's Discord ID
        quest_date: Date for this quest set
        quests_completed: Boolean flags for each quest
        quest_progress: Integer counters for each quest
        rewards_claimed: Whether rewards have been collected
        bonus_streak: Consecutive days completed (for bonuses)
    
    Indexes:
        - (player_id, quest_date) composite for fast lookups
    """
    
    __tablename__ = "daily_quests"
    __table_args__ = (
        Index("ix_daily_quests_player_date", "player_id", "quest_date"),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        foreign_key="players.discord_id"
    )
    quest_date: date = Field(default_factory=date.today, nullable=False, index=True)
    
    quests_completed: Dict[str, bool] = Field(
        default_factory=lambda: {
            "prayer_performed": False,
            "summon_maiden": False,
            "attempt_fusion": False,
            "spend_energy": False,
            "spend_stamina": False,
        },
        sa_column=Column(JSON)
    )
    
    quest_progress: Dict[str, int] = Field(
        default_factory=lambda: {
            "prayers_done": 0,
            "summons_done": 0,
            "fusions_attempted": 0,
            "energy_spent": 0,
            "stamina_spent": 0,
        },
        sa_column=Column(JSON)
    )
    
    rewards_claimed: bool = Field(default=False)
    bonus_streak: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    
    def is_complete(self) -> bool:
        """Check if all daily quests are completed."""
        return all(self.quests_completed.values())
    
    def get_completion_count(self) -> int:
        """Count how many quests are completed."""
        return sum(1 for completed in self.quests_completed.values() if completed)
    
    def get_completion_percent(self) -> float:
        """Calculate completion percentage (0-100)."""
        total = len(self.quests_completed)
        completed = self.get_completion_count()
        return (completed / total) * 100 if total > 0 else 0.0
    
    def __repr__(self) -> str:
        return (
            f"<DailyQuest(player={self.player_id}, date={self.quest_date}, "
            f"complete={self.is_complete()}, streak={self.bonus_streak})>"
        )