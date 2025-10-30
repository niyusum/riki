from typing import Optional, Dict
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, Index
from sqlalchemy.dialects.postgresql import JSON
from datetime import datetime, timedelta


class Player(SQLModel, table=True):
    """
    Core player data model representing a Discord user in RIKI RPG.
    
    Stores player progression, resources, stats, and metadata.
    All resource regeneration and activity tracking handled through this model.
    
    Attributes:
        discord_id: Unique Discord user ID (primary key)
        level: Current player level (1-∞)
        grace: Prayer currency for summoning maidens
        rikis: Primary currency for fusion and upgrades
        energy: Resource for questing and exploration
        stamina: Resource for battles and raids
        prayer_charges: Charges for prayer system (max 5)
        fusion_shards: Dictionary of shards per tier for guaranteed fusions
        total_power: Calculated combat power from all maidens
    
    Indexes:
        - discord_id (unique)
        - level
        - total_power
        - last_active
        - player_class + level composite
    """
    
    __tablename__ = "players"
    __table_args__ = (
        Index("ix_players_discord_id", "discord_id", unique=True),
        Index("ix_players_level", "level"),
        Index("ix_players_total_power", "total_power"),
        Index("ix_players_last_active", "last_active"),
        Index("ix_players_last_level_up", "last_level_up"),
        Index("ix_players_class_level", "player_class", "level"),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    discord_id: int = Field(
        sa_column=Column(BigInteger, unique=True, nullable=False, index=True)
    )
    username: str = Field(default="Unknown", max_length=100)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    last_active: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    last_level_up: Optional[datetime] = Field(default=None, index=True)
    
    level: int = Field(default=1, ge=1, index=True)
    experience: int = Field(default=0, ge=0, sa_column=Column(BigInteger))
    
    grace: int = Field(default=5, ge=0)
    rikis: int = Field(default=1000, ge=0, sa_column=Column(BigInteger))
    riki_gems: int = Field(default=0, ge=0)
    
    energy: int = Field(default=100, ge=0)
    max_energy: int = Field(default=100, ge=0)
    stamina: int = Field(default=50, ge=0)
    max_stamina: int = Field(default=50, ge=0)
    
    prayer_charges: int = Field(default=5, ge=0, le=5)
    max_prayer_charges: int = Field(default=5, ge=0)
    last_prayer_regen: Optional[datetime] = Field(default=None)
    
    fusion_shards: Dict[str, int] = Field(
        default_factory=lambda: {
            "tier_1": 0, "tier_2": 0, "tier_3": 0, "tier_4": 0,
            "tier_5": 0, "tier_6": 0, "tier_7": 0, "tier_8": 0,
            "tier_9": 0, "tier_10": 0, "tier_11": 0
        },
        sa_column=Column(JSON)
    )
    
    total_attack: int = Field(default=0, ge=0, sa_column=Column(BigInteger))
    total_defense: int = Field(default=0, ge=0, sa_column=Column(BigInteger))
    total_power: int = Field(default=0, ge=0, sa_column=Column(BigInteger), index=True)
    
    leader_maiden_id: Optional[int] = Field(default=None, foreign_key="maidens.id")
    total_maidens_owned: int = Field(default=0, ge=0)
    unique_maidens: int = Field(default=0, ge=0)
    
    total_summons: int = Field(default=0, ge=0)
    pity_counter: int = Field(default=0, ge=0)
    
    total_fusions: int = Field(default=0, ge=0)
    successful_fusions: int = Field(default=0, ge=0)
    failed_fusions: int = Field(default=0, ge=0)
    highest_tier_achieved: int = Field(default=1, ge=1)
    
    player_class: Optional[str] = Field(default=None, max_length=20, index=True)
    
    tutorial_completed: bool = Field(default=False)
    tutorial_step: int = Field(default=0, ge=0)
    
    stats: Dict[str, int] = Field(
        default_factory=lambda: {
            "battles_fought": 0,
            "battles_won": 0,
            "total_rikis_earned": 0,
            "total_rikis_spent": 0,
            "prayers_performed": 0,
            "shards_earned": 0,
            "shards_spent": 0,
            "level_ups": 0,
            "overflow_energy_gained": 0,
            "overflow_stamina_gained": 0,
        },
        sa_column=Column(JSON)
    )
    
    def get_fusion_shards(self, tier: int) -> int:
        """Get number of fusion shards for specific tier."""
        return self.fusion_shards.get(f"tier_{tier}", 0)
    
    def get_class_bonus_description(self) -> str:
        """Get human-readable description of current class bonuses."""
        bonuses = {
            "destroyer": "+25% stamina regeneration",
            "adapter": "+25% energy regeneration", 
            "invoker": "+20% grace from prayers"
        }
        return bonuses.get(self.player_class, "No class selected")
    
    def get_power_display(self) -> str:
        """Format total power with K/M abbreviations."""
        if self.total_power >= 1_000_000:
            return f"{self.total_power / 1_000_000:.1f}M"
        elif self.total_power >= 1_000:
            return f"{self.total_power / 1_000:.1f}K"
        return str(self.total_power)
    
    def get_prayer_regen_time_remaining(self) -> int:
        """
        Calculate seconds until next prayer charge regenerates.
        
        Returns:
            Seconds remaining (0 if at max charges or ready to regen)
        """
        if self.prayer_charges >= self.max_prayer_charges:
            return 0
        
        if self.last_prayer_regen is None:
            return 0
        
        from src.services.config_manager import ConfigManager
        regen_interval = ConfigManager.get("prayer_system.regen_minutes", 5) * 60
        time_since = (datetime.utcnow() - self.last_prayer_regen).total_seconds()
        return max(0, int(regen_interval - time_since))
    
    def get_prayer_regen_display(self) -> str:
        """Format prayer regeneration time as 'Xm Ys' or 'Ready!'."""
        remaining = self.get_prayer_regen_time_remaining()
        if remaining == 0:
            return "Ready!"
        
        minutes = remaining // 60
        seconds = remaining % 60
        return f"{minutes}m {seconds}s"
    
    def update_activity(self) -> None:
        """Update last_active timestamp to current time."""
        self.last_active = datetime.utcnow()
    
    def calculate_fusion_success_rate(self) -> float:
        """Calculate player's historical fusion success rate as percentage."""
        if self.total_fusions == 0:
            return 0.0
        return (self.successful_fusions / self.total_fusions) * 100
    
    def calculate_win_rate(self) -> float:
        """Calculate player's battle win rate as percentage."""
        battles = self.stats.get("battles_fought", 0)
        if battles == 0:
            return 0.0
        wins = self.stats.get("battles_won", 0)
        return (wins / battles) * 100
    
    def __repr__(self) -> str:
        return (
            f"<Player(discord_id={self.discord_id}, "
            f"level={self.level}, power={self.total_power})>"
        )