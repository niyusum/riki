from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, Index, String, UniqueConstraint
from datetime import datetime


class Maiden(SQLModel, table=True):
    """
    Player-owned maiden instance representing a specific tier of a maiden base.
    
    Multiple maidens of same base+tier are stacked as quantity.
    Each unique (player, maiden_base, tier) combination is one row.
    
    Attributes:
        player_id: Owner's Discord ID
        maiden_base_id: Reference to MaidenBase (shared template)
        quantity: Number of this specific maiden+tier owned
        tier: Current upgrade tier (1-12)
        element: Element type (inherited from base, for indexing)
        times_fused: How many times this maiden was used in fusion
    
    Unique Constraint:
        (player_id, maiden_base_id, tier) - prevents duplicate stacks
    
    Indexes:
        - player_id
        - maiden_base_id
        - tier
        - element
        - (player_id, tier, quantity) for fusion queries
    """
    
    __tablename__ = "maidens"
    __table_args__ = (
        UniqueConstraint("player_id", "maiden_base_id", "tier", name="uq_player_maiden_tier"),
        Index("ix_maidens_player_id", "player_id"),
        Index("ix_maidens_base_id", "maiden_base_id"),
        Index("ix_maidens_tier", "tier"),
        Index("ix_maidens_element", "element"),
        Index("ix_maidens_fusable", "player_id", "tier", "quantity"),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True),
        foreign_key="players.discord_id"
    )
    maiden_base_id: int = Field(foreign_key="maiden_bases.id", nullable=False, index=True)
    
    quantity: int = Field(default=1, ge=0, sa_column=Column(BigInteger))
    tier: int = Field(default=1, ge=1, le=12, index=True)
    
    element: str = Field(sa_column=Column(String(20)), nullable=False, index=True)
    
    acquired_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    last_modified: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    
    acquired_from: str = Field(default="summon", max_length=50)
    times_fused: int = Field(default=0, ge=0)
    
    def get_tier_display(self) -> str:
        """Format tier as 'Tier N' or 'Tier VII' for high tiers."""
        if self.tier <= 6:
            return f"Tier {self.tier}"
        roman = ["VII", "VIII", "IX", "X", "XI", "XII"]
        return f"Tier {roman[self.tier - 7]}" if self.tier <= 12 else f"Tier {self.tier}"
    
    def get_stack_display(self) -> str:
        """Format tier with quantity indicator (e.g., 'Tier 3 ×5')."""
        if self.quantity == 0:
            return f"{self.get_tier_display()} (Used)"
        elif self.quantity == 1:
            return self.get_tier_display()
        else:
            return f"{self.get_tier_display()} ×{self.quantity:,}"
    
    def can_fuse(self) -> bool:
        """Check if this maiden can be fused (has 2+ quantity and under tier 12)."""
        return self.quantity >= 2 and self.tier < 12
    
    def get_element_emoji(self) -> str:
        """Get emoji representation of maiden's element."""
        emojis = {
            "infernal": "🔥", "umbral": "🌑", "earth": "🌍",
            "tempest": "⚡", "radiant": "✨", "abyssal": "🌊"
        }
        return emojis.get(self.element, "❓")
    
    def update_modification_time(self) -> None:
        """Update last_modified timestamp to current time."""
        self.last_modified = datetime.utcnow()
    
    def __repr__(self) -> str:
        return (
            f"<Maiden(id={self.id}, player={self.player_id}, "
            f"base={self.maiden_base_id}, T{self.tier}, qty={self.quantity})>"
        )