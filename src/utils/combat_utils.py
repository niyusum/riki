from typing import Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.database.models.maiden import Maiden
from src.services.logger import get_logger

logger = get_logger(__name__)


class CombatUtils:
    """
    Shared utility functions for combat and power calculations.
    
    Provides centralized power calculation from maiden collection,
    HP bar rendering, and combat display formatting.
    
    Usage:
        >>> power = await CombatUtils.calculate_total_power(session, player_id)
        >>> hp_bar = CombatUtils.render_hp_bar(5000, 10000, width=20)
    """
    
    @staticmethod
    async def calculate_total_power(session: AsyncSession, player_id: int) -> int:
        """
        Calculate player's total power from ALL owned maidens.
        
        Power = sum of all maiden ATK stats.
        No squad limits, no benching - every maiden contributes.
        
        Args:
            session: Database session
            player_id: Discord ID
        
        Returns:
            Total ATK value
        """
        result = await session.execute(
            select(func.sum(Maiden.atk)).where(
                Maiden.owner_id == player_id
            )
        )
        total_power = result.scalar_one_or_none()
        
        return total_power if total_power else 0
    
    @staticmethod
    async def get_power_breakdown(session: AsyncSession, player_id: int, limit: int = 10) -> Dict:
        """
        Get detailed breakdown of player power contribution.
        
        Shows top contributing maidens and collection stats.
        
        Args:
            session: Database session
            player_id: Discord ID
            limit: Number of top maidens to return
        
        Returns:
            Dictionary with:
                - total_power: Total ATK
                - maiden_count: Total maidens owned
                - top_maidens: List of top contributors
                - average_atk: Average ATK per maiden
        """
        # Get all maidens
        result = await session.execute(
            select(Maiden).where(
                Maiden.owner_id == player_id
            ).order_by(Maiden.atk.desc())
        )
        maidens = result.scalars().all()
        
        if not maidens:
            return {
                "total_power": 0,
                "maiden_count": 0,
                "top_maidens": [],
                "average_atk": 0
            }
        
        total_power = sum(m.atk for m in maidens)
        average_atk = total_power / len(maidens)
        
        top_maidens = [
            {
                "id": m.id,
                "name": m.name,
                "atk": m.atk,
                "tier": m.tier,
                "element": m.element,
                "contribution_percent": (m.atk / total_power) * 100 if total_power > 0 else 0
            }
            for m in maidens[:limit]
        ]
        
        return {
            "total_power": total_power,
            "maiden_count": len(maidens),
            "top_maidens": top_maidens,
            "average_atk": int(average_atk)
        }
    
    @staticmethod
    def render_hp_bar(current_hp: int, max_hp: int, width: int = 20) -> str:
        """
        Render ASCII HP bar using Unicode blocks.
        
        Args:
            current_hp: Current HP value
            max_hp: Maximum HP value
            width: Bar width in characters
        
        Returns:
            Formatted HP bar string
        
        Example:
            >>> CombatUtils.render_hp_bar(7500, 10000, 20)
            '███████████████░░░░░'
        """
        if max_hp == 0:
            return "░" * width
        
        filled_width = int((current_hp / max_hp) * width)
        filled_width = max(0, min(width, filled_width))
        empty_width = width - filled_width
        
        return "█" * filled_width + "░" * empty_width
    
    @staticmethod
    def render_hp_percentage(current_hp: int, max_hp: int) -> str:
        """
        Render HP as percentage string.
        
        Returns:
            Formatted percentage (e.g., "75%")
        """
        if max_hp == 0:
            return "0%"
        
        percent = int((current_hp / max_hp) * 100)
        return f"{percent}%"
    
    @staticmethod
    def format_damage_display(damage: int, is_crit: bool = False) -> str:
        """
        Format damage number for display.
        
        Args:
            damage: Damage value
            is_crit: Whether this is a critical hit
        
        Returns:
            Formatted damage string with emojis
        """
        formatted = f"{damage:,}"
        
        if is_crit:
            return f"💥 **{formatted}** ✨ CRITICAL!"
        else:
            return f"⚔️ {formatted}"
    
    @staticmethod
    def get_element_emoji(element: str) -> str:
        """
        Get emoji for element type.
        
        Returns:
            Element emoji
        """
        emojis = {
            "infernal": "🔥",
            "abyssal": "💧",
            "tempest": "🌪️",
            "earth": "🌿",
            "radiant": "✨",
            "umbral": "🌑",
        }
        return emojis.get(element, "⚪")
    
    @staticmethod
    def get_rarity_emoji(rarity: str) -> str:
        """
        Get emoji for rarity tier.
        
        Returns:
            Rarity emoji
        """
        emojis = {
            "common": "⚪",
            "uncommon": "🟢",
            "rare": "🔵",
            "epic": "🟣",
            "legendary": "🟠",
            "mythic": "🔴",
        }
        return emojis.get(rarity, "⚪")
    
    @staticmethod
    def format_combat_log_entry(
        attacker: str,
        damage: int,
        current_hp: int,
        max_hp: int,
        is_crit: bool = False
    ) -> str:
        """
        Format single combat log entry.
        
        Returns:
            Formatted combat log line
        """
        damage_display = CombatUtils.format_damage_display(damage, is_crit)
        hp_bar = CombatUtils.render_hp_bar(current_hp, max_hp, width=20)
        hp_percent = CombatUtils.render_hp_percentage(current_hp, max_hp)
        
        return f"{damage_display}\n{hp_bar} {hp_percent}\nHP: {current_hp:,} / {max_hp:,}"


class ProgressUtils:
    """
    Utility functions for progression tracking and display.
    
    Provides progress bar rendering, unlock checks, and stat formatting.
    """
    
    @staticmethod
    def render_progress_bar(progress: float, width: int = 20) -> str:
        """
        Render progress bar for sector exploration.
        
        Args:
            progress: Progress percentage (0.0 - 100.0)
            width: Bar width in characters
        
        Returns:
            Formatted progress bar
        """
        filled_width = int((progress / 100.0) * width)
        filled_width = max(0, min(width, filled_width))
        empty_width = width - filled_width
        
        return "━" * filled_width + "░" * empty_width
    
    @staticmethod
    def format_progress_display(progress: float) -> str:
        """
        Format progress as percentage with color coding.
        
        Returns:
            Formatted string
        """
        if progress < 25:
            emoji = "🔴"
        elif progress < 50:
            emoji = "🟠"
        elif progress < 75:
            emoji = "🟡"
        elif progress < 100:
            emoji = "🟢"
        else:
            emoji = "✅"
        
        return f"{emoji} {progress:.1f}%"
    
    @staticmethod
    def format_resource_cost(resource: str, amount: int) -> str:
        """
        Format resource cost display.
        
        Args:
            resource: Resource type (energy, stamina, gems)
            amount: Cost amount
        
        Returns:
            Formatted string with emoji
        """
        emojis = {
            "energy": "⚡",
            "stamina": "💪",
            "gems": "💎",
            "rikis": "💰",
            "grace": "🙏",
        }
        
        emoji = emojis.get(resource, "•")
        return f"{emoji} {amount}"
    
    @staticmethod
    def format_reward_display(reward_type: str, amount: int) -> str:
        """
        Format reward display with appropriate emoji.
        
        Returns:
            Formatted reward string
        """
        emojis = {
            "rikis": "💰",
            "xp": "⭐",
            "gems": "💎",
            "grace": "🙏",
            "prayer_charges": "🙏",
            "fusion_catalyst": "🔮",
        }
        
        emoji = emojis.get(reward_type, "✨")
        return f"{emoji} +{amount:,}"