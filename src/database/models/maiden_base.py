from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSON


class MaidenBase(SQLModel, table=True):
    """
    Shared template for all maidens of a specific type.
    
    Defines base stats, element, leader effects, and visual data.
    Player-owned maidens (Maiden model) reference this as their template.
    
    Attributes:
        name: Unique maiden name
        element: Element type (infernal, umbral, earth, tempest, radiant, abyssal)
        base_tier: Starting tier when summoned (1-12)
        base_atk: Base attack stat
        base_def: Base defense stat
        leader_effect: Optional leader skill effect data
        description: Lore/description text
        image_url: Link to maiden artwork
        rarity_weight: Gacha weight (lower = rarer)
        is_premium: Whether this is a premium/limited maiden
    
    Indexes:
        - name (unique)
        - element
        - base_tier
    """
    
    __tablename__ = "maiden_bases"
    __table_args__ = (
        Index("ix_maiden_bases_name", "name", unique=True),
        Index("ix_maiden_bases_element", "element"),
        Index("ix_maiden_bases_base_tier", "base_tier"),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column(String(100)), unique=True, nullable=False, index=True)
    element: str = Field(sa_column=Column(String(20)), nullable=False, index=True)
    base_tier: int = Field(default=1, ge=1, le=12, index=True)
    
    base_atk: int = Field(default=10, ge=1)
    base_def: int = Field(default=10, ge=1)
    
    leader_effect: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    
    description: str = Field(sa_column=Column(Text), nullable=False)
    image_url: str = Field(sa_column=Column(String(500)), nullable=False)
    
    rarity_weight: float = Field(default=1.0, ge=0.0)
    is_premium: bool = Field(default=False)
    
    def get_base_power(self) -> int:
        """Calculate total base power (ATK + DEF)."""
        return self.base_atk + self.base_def
    
    def get_tier_display(self) -> str:
        """Format base tier as 'Tier N' or 'Tier VII' for high tiers."""
        if self.base_tier <= 6:
            return f"Tier {self.base_tier}"
        roman = ["VII", "VIII", "IX", "X", "XI", "XII"]
        return f"Tier {roman[self.base_tier - 7]}" if self.base_tier <= 12 else f"Tier {self.base_tier}"
    
    def get_element_emoji(self) -> str:
        """Get emoji representation of maiden's element."""
        emojis = {
            "infernal": "🔥", "umbral": "🌑", "earth": "🌍",
            "tempest": "⚡", "radiant": "✨", "abyssal": "🌊"
        }
        return emojis.get(self.element, "❓")
    
    def get_rarity_tier_name(self) -> str:
        """Get human-readable rarity name based on base tier."""
        rarity_names = {
            1: "Common", 2: "Common", 3: "Uncommon",
            4: "Uncommon", 5: "Rare", 6: "Rare",
            7: "Epic", 8: "Epic", 9: "Legendary",
            10: "Legendary", 11: "Mythic", 12: "Mythic"
        }
        return rarity_names.get(self.base_tier, "Unknown")
    
    def has_leader_effect(self) -> bool:
        """Check if this maiden has a leader effect defined."""
        return bool(self.leader_effect and self.leader_effect.get("type"))
    
    def __repr__(self) -> str:
        return (
            f"<MaidenBase(id={self.id}, name='{self.name}', "
            f"element={self.element}, tier={self.base_tier}, power={self.get_base_power()})>"
        )