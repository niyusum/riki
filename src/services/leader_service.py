# src/services/leader_service.py
from typing import Dict
from src.database.models.player import Player
from src.database.models.maiden import Maiden
from src.database.models.maiden_base import MaidenBase
from src.services.database_service import DatabaseService
from src.services.logger import get_logger

logger = get_logger(__name__)


class LeaderService:
    """
    Leader effect calculation and application system.
    
    Handles scaling of leader effects based on maiden tier difference,
    applying leader bonuses to player stats, and formatting effect descriptions.
    """

    @staticmethod
    async def get_active_modifiers(player: Player) -> Dict[str, float]:
        """
        Get active modifier multipliers from player's leader maiden.
        
        Fully functional version — fetches maiden + base data from DB.
        
        Returns:
            {
                "income_boost": 1.15,
                "xp_boost": 1.10,
                "fusion_bonus": 0.05,
                "energy_efficiency": 0.10,
                "stamina_efficiency": 0.05
            }
        """
        modifiers = {
            "income_boost": 1.0,
            "xp_boost": 1.0,
            "fusion_bonus": 0.0,
            "energy_efficiency": 0.0,
            "stamina_efficiency": 0.0,
        }

        # No leader assigned
        if not player.leader_maiden_id:
            return modifiers

        try:
            async with DatabaseService.get_session() as session:
                leader = await session.get(Maiden, player.leader_maiden_id)
                if not leader:
                    logger.warning(f"Leader maiden not found for player {player.discord_id}")
                    return modifiers

                maiden_base = await session.get(MaidenBase, leader.maiden_base_id)
                if not maiden_base or not maiden_base.has_leader_effect():
                    return modifiers

                effect_data = maiden_base.leader_effect
                effect_type = effect_data.get("type")
                base_value = effect_data.get("value", 0.0)

                # Calculate scaled value based on tier difference
                current_tier = leader.tier
                base_tier = maiden_base.base_tier
                scaling = effect_data.get("scaling", {})
                tier_diff = max(0, current_tier - base_tier)
                if scaling.get("enabled", False):
                    tier_mult = scaling.get("tier_multiplier", 1.0)
                    scaled_value = base_value * (1 + (tier_diff * (tier_mult - 1.0)))
                    max_bonus = scaling.get("max_bonus", float("inf"))
                    final_value = min(scaled_value, base_value * (1 + max_bonus / 100))
                else:
                    final_value = base_value

                # Map effect type to modifier keys
                if effect_type == "income_boost":
                    modifiers["income_boost"] = 1.0 + (final_value / 100)
                elif effect_type == "xp_boost":
                    modifiers["xp_boost"] = 1.0 + (final_value / 100)
                elif effect_type == "fusion_bonus":
                    modifiers["fusion_bonus"] = final_value / 100
                elif effect_type == "energy_efficiency":
                    modifiers["energy_efficiency"] = final_value / 100
                elif effect_type == "stamina_efficiency":
                    modifiers["stamina_efficiency"] = final_value / 100

                logger.debug(
                    f"Leader modifiers for player {player.discord_id} ({maiden_base.name} T{leader.tier}): {modifiers}"
                )

        except Exception as e:
            logger.error(f"Error calculating leader modifiers for player {player.discord_id}: {e}")

        return modifiers
