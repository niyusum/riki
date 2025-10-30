from typing import Dict, Any, List
import random

from src.database.models.player import Player
from src.database.models.maiden import Maiden
from src.services.config_manager import ConfigManager
from src.config import Config


class FusionService:
    """
    Core fusion mechanics and element combination system.
    
    Handles fusion cost calculation, success rate determination,
    element combination resolution, and shard management.
    
    Key Features:
        - Tiered fusion costs with exponential scaling
        - Configurable success rates per tier
        - Element combination matrix
        - Shard system for guaranteed fusions
    
    Usage:
        >>> cost = FusionService.get_fusion_cost(3)
        >>> rate = FusionService.get_fusion_success_rate(3)
        >>> success = FusionService.roll_fusion_success(3, bonus_rate=5.0)
        >>> result_element = FusionService.calculate_element_result("infernal", "abyssal")
    """
    
    @staticmethod
    def get_fusion_cost(tier: int) -> int:
        """
        Calculate rikis cost for fusing maidens of given tier.
        
        Formula: base * (multiplier ^ (tier - 1))
        Capped at max_cost to prevent overflow.
        
        Args:
            tier: Maiden tier (1-12)
        
        Returns:
            Rikis cost (integer)
        
        Example:
            >>> FusionService.get_fusion_cost(1)
            1000
            >>> FusionService.get_fusion_cost(3)
            6250
            >>> FusionService.get_fusion_cost(10)
            10000000  # Capped at max
        """
        base_cost = ConfigManager.get("fusion_costs.base", 1000)
        multiplier = ConfigManager.get("fusion_costs.multiplier", 2.5)
        max_cost = ConfigManager.get("fusion_costs.max_cost", Config.MAX_FUSION_COST)
        
        calculated_cost = int(base_cost * (multiplier ** (tier - 1)))
        return min(calculated_cost, max_cost)
    
    @staticmethod
    def get_fusion_success_rate(tier: int) -> int:
        """
        Get base fusion success rate for given tier.
        
        Args:
            tier: Maiden tier (1-12)
        
        Returns:
            Success rate as integer percentage (0-100)
        
        Example:
            >>> FusionService.get_fusion_success_rate(1)
            70
            >>> FusionService.get_fusion_success_rate(11)
            20
        """
        rates = ConfigManager.get("fusion_rates", {
            "1": 70, "2": 65, "3": 60, "4": 55, "5": 50, "6": 45,
            "7": 40, "8": 35, "9": 30, "10": 25, "11": 20
        })
        return rates.get(str(tier), 50)
    
    @staticmethod
    def roll_fusion_success(tier: int, bonus_rate: float = 0.0) -> bool:
        """
        Roll for fusion success with random outcome.
        
        Args:
            tier: Maiden tier being fused
            bonus_rate: Additional success rate bonus (from events, items, etc.)
        
        Returns:
            True if fusion succeeds, False otherwise
        
        Example:
            >>> FusionService.roll_fusion_success(3)  # 60% base rate
            True
            >>> FusionService.roll_fusion_success(3, bonus_rate=10.0)  # 70% rate
            False
        """
        base_rate = FusionService.get_fusion_success_rate(tier)
        final_rate = min(100, base_rate + bonus_rate)
        
        roll = random.uniform(0, 100)
        return roll <= final_rate
    
    @staticmethod
    def _parse_element_key(element1: str, element2: str) -> str:
        """Format two elements as combination key for lookup."""
        return f"{element1}|{element2}"
    
    @staticmethod
    def calculate_element_result(element1: str, element2: str) -> str:
        """
        Determine result element from combining two elements.
        
        Uses element combination matrix from ConfigManager.
        Falls back to element1 if combination not defined.
        
        Args:
            element1: First parent's element
            element2: Second parent's element
        
        Returns:
            Resulting element type
        
        Example:
            >>> FusionService.calculate_element_result("infernal", "abyssal")
            "umbral"
            >>> FusionService.calculate_element_result("infernal", "infernal")
            "infernal"
        """
        element_combinations = ConfigManager.get("element_combinations", {})
        
        key1 = FusionService._parse_element_key(element1, element2)
        key2 = FusionService._parse_element_key(element2, element1)
        
        if key1 in element_combinations:
            return element_combinations[key1]
        elif key2 in element_combinations:
            return element_combinations[key2]
        else:
            from src.services.logger import get_logger
            logger = get_logger(__name__)
            logger.warning(
                f"Element combination not found: {element1} + {element2}, "
                f"using {element1} as fallback"
            )
            return element1
    
    @staticmethod
    async def add_fusion_shard(
        player: Player,
        tier: int,
        amount: int = 1
    ) -> Dict[str, Any]:
        """
        Award fusion shards to player for failed fusion.
        
        Shards accumulate toward guaranteed fusion at same tier.
        Modifies player.fusion_shards directly.
        
        Args:
            player: Player object
            tier: Tier of failed fusion
            amount: Number of failures (usually 1)
        
        Returns:
            Dictionary with shard details:
                - shards_gained
                - new_total
                - can_redeem
                - progress_percent
        """
        shards_per_failure = ConfigManager.get("shard_system.shards_per_failure", 1)
        actual_amount = amount * shards_per_failure
        
        key = f"tier_{tier}"
        current = player.fusion_shards.get(key, 0)
        player.fusion_shards[key] = current + actual_amount
        player.stats["shards_earned"] = player.stats.get("shards_earned", 0) + actual_amount
        
        shards_for_redemption = ConfigManager.get("shard_system.shards_for_redemption", 10)
        
        return {
            "shards_gained": actual_amount,
            "new_total": player.fusion_shards[key],
            "can_redeem": player.fusion_shards[key] >= shards_for_redemption,
            "progress_percent": (player.fusion_shards[key] / shards_for_redemption) * 100
        }
    
    @staticmethod
    async def redeem_shards(player: Player, tier: int) -> bool:
        """
        Consume shards for guaranteed fusion at tier.
        
        Args:
            player: Player object
            tier: Tier to redeem shards for
        
        Returns:
            True if redemption successful, False if insufficient shards
        """
        shards_needed = ConfigManager.get("shard_system.shards_for_redemption", 10)
        
        if player.get_fusion_shards(tier) < shards_needed:
            return False
        
        key = f"tier_{tier}"
        player.fusion_shards[key] -= shards_needed
        player.stats["shards_spent"] = player.stats.get("shards_spent", 0) + shards_needed
        return True
    
    @staticmethod
    def get_redeemable_tiers(player: Player) -> List[int]:
        """
        Get list of tiers where player can redeem shards.
        
        Returns:
            List of tier numbers with sufficient shards
        """
        shards_needed = ConfigManager.get("shard_system.shards_for_redemption", 10)
        
        return [
            int(key.split("_")[1]) 
            for key, count in player.fusion_shards.items() 
            if count >= shards_needed
        ]