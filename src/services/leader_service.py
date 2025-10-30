from typing import Dict, Any, Optional

from src.database.models.maiden_base import MaidenBase


class LeaderService:
    """
    Leader effect calculation and application system.
    
    Handles scaling of leader effects based on maiden tier difference,
    applying leader bonuses to player stats, and formatting effect descriptions.
    
    Leader Effect Types:
        - stat_boost: Percentage increase to ATK/DEF/ALL
        - element_boost: Percentage increase to specific element
        - fusion_bonus: Increase fusion success rates
        - income_boost: Increase currency gains
        - energy_efficiency: Reduce energy costs
        - stamina_efficiency: Reduce stamina costs
        - prayer_cooldown: Reduce prayer cooldown
        - xp_boost: Increase experience gain
    
    Usage:
        >>> effect_value = LeaderService.calculate_effect_value(maiden_base, current_tier=5)
        >>> description = LeaderService.get_effect_description(maiden_base, current_tier=5)
        >>> stats = LeaderService.apply_to_stats(maiden_base, 5, player_atk, player_def)
    """
    
    @staticmethod
    def calculate_effect_value(
        maiden_base: MaidenBase,
        current_tier: int
    ) -> float:
        """
        Calculate leader effect value with tier scaling.
        
        Leader effects can scale with tier difference from base.
        Formula: base_value * (1 + (tier_diff * (multiplier - 1)))
        
        Args:
            maiden_base: MaidenBase with leader_effect data
            current_tier: Current tier of the maiden instance
        
        Returns:
            Calculated effect value (percentage or flat value)
        
        Example:
            >>> # Maiden with 10% ATK boost at base tier 3
            >>> # If scaled to tier 7 with 1.5x multiplier:
            >>> # 10% * (1 + (4 * 0.5)) = 10% * 3 = 30%
            >>> LeaderService.calculate_effect_value(maiden_base, 7)
            30.0
        """
        if not maiden_base.has_leader_effect():
            return 0.0
        
        base_value = maiden_base.leader_effect.get("value", 0)
        scaling_config = maiden_base.leader_effect.get("scaling", {})
        
        if not scaling_config.get("enabled", False):
            return base_value
        
        tier_diff = current_tier - maiden_base.base_tier
        if tier_diff <= 0:
            return base_value
        
        tier_multiplier = scaling_config.get("tier_multiplier", 1.0)
        bonus_multiplier = 1.0 + (tier_diff * (tier_multiplier - 1.0))
        
        max_bonus = scaling_config.get("max_bonus", float('inf'))
        bonus_percent = min((bonus_multiplier - 1.0) * 100, max_bonus)
        
        final_value = base_value * (1.0 + bonus_percent / 100)
        
        return final_value
    
    @staticmethod
    def get_effect_description(
        maiden_base: MaidenBase,
        current_tier: Optional[int] = None
    ) -> str:
        """
        Get human-readable description of leader effect.
        
        Args:
            maiden_base: MaidenBase with leader_effect data
            current_tier: Optional current tier for scaled description
        
        Returns:
            Formatted effect description string
        
        Example:
            >>> LeaderService.get_effect_description(maiden_base)
            "+15.0% ATK to all maidens"
            >>> LeaderService.get_effect_description(maiden_base, current_tier=7)
            "+30.0% ATK to all maidens (base: 15.0%, +15.0% from scaling)"
        """
        if not maiden_base.has_leader_effect():
            return "No leader effect"
        
        effect_type = maiden_base.leader_effect.get("type")
        base_value = maiden_base.leader_effect.get("value", 0)
        
        if current_tier is not None:
            actual_value = LeaderService.calculate_effect_value(maiden_base, current_tier)
        else:
            actual_value = base_value
        
        descriptions = {
            "stat_boost": lambda v: f"+{v:.1f}% {maiden_base.leader_effect.get('stat', 'stat').upper()} to all maidens",
            "element_boost": lambda v: f"+{v:.1f}% power to {maiden_base.leader_effect.get('element', 'element')} maidens",
            "fusion_bonus": lambda v: f"+{v:.1f}% fusion success rate",
            "income_boost": lambda v: f"+{v:.1f}% {maiden_base.leader_effect.get('currency', 'currency')} from all sources",
            "energy_efficiency": lambda v: f"-{v:.1f}% energy costs for quests",
            "stamina_efficiency": lambda v: f"-{v:.1f}% stamina costs for battles",
            "prayer_cooldown": lambda v: f"-{v:.1f}% prayer cooldown time",
            "xp_boost": lambda v: f"+{v:.1f}% experience gained",
        }
        
        desc = descriptions.get(effect_type, lambda v: f"Unknown effect: {v}")(actual_value)
        
        scaling_config = maiden_base.leader_effect.get("scaling", {})
        if scaling_config.get("enabled", False) and current_tier:
            tier_diff = current_tier - maiden_base.base_tier
            if tier_diff > 0:
                desc += f" (base: {base_value}%, +{actual_value - base_value:.1f}% from scaling)"
        
        return desc
    
    @staticmethod
    def apply_to_stats(
        maiden_base: MaidenBase,
        current_tier: int,
        player_attack: int,
        player_defense: int
    ) -> Dict[str, Any]:
        """
        Apply leader effect to player stats.
        
        Currently only implements stat_boost effects for ATK/DEF.
        Other effect types would be applied contextually in relevant systems.
        
        Args:
            maiden_base: MaidenBase with leader_effect data
            current_tier: Current tier of the leader maiden
            player_attack: Player's base attack stat
            player_defense: Player's base defense stat
        
        Returns:
            Dictionary with boosted stats and bonus breakdown:
                - attack (int): Total attack after bonus
                - defense (int): Total defense after bonus
                - bonus_attack (int): Attack bonus granted
                - bonus_defense (int): Defense bonus granted
                - effect_type (str): Type of effect applied
                - effect_value (float): Calculated effect value
        
        Example:
            >>> stats = LeaderService.apply_to_stats(
            ...     maiden_base, tier=5, player_attack=1000, player_defense=800
            ... )
            >>> print(f"Total ATK: {stats['attack']} (+{stats['bonus_attack']})")
        """
        if not maiden_base.has_leader_effect():
            return {
                "attack": player_attack,
                "defense": player_defense,
                "bonus_attack": 0,
                "bonus_defense": 0
            }
        
        effect_type = maiden_base.leader_effect.get("type")
        effect_value = LeaderService.calculate_effect_value(maiden_base, current_tier)
        
        bonus_attack = 0
        bonus_defense = 0
        
        if effect_type == "stat_boost":
            stat = maiden_base.leader_effect.get("stat", "").lower()
            if stat == "attack":
                bonus_attack = int(player_attack * (effect_value / 100))
            elif stat == "defense":
                bonus_defense = int(player_defense * (effect_value / 100))
            elif stat == "all":
                bonus_attack = int(player_attack * (effect_value / 100))
                bonus_defense = int(player_defense * (effect_value / 100))
        
        return {
            "attack": player_attack + bonus_attack,
            "defense": player_defense + bonus_defense,
            "bonus_attack": bonus_attack,
            "bonus_defense": bonus_defense,
            "effect_type": effect_type,
            "effect_value": effect_value
        }