from typing import Dict, Any, List, Optional
import random
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.database.models.player import Player
from src.database.models.maiden import Maiden
from src.database.models.maiden_base import MaidenBase
from src.services.config_manager import ConfigManager
from src.services.transaction_logger import TransactionLogger
from src.config import Config
from src.exceptions import (
    InsufficientResourcesError,
    MaidenNotFoundError,
    InvalidFusionError
)
from src.services.logger import get_logger

logger = get_logger(__name__)


class FusionService:
    """
    Core fusion mechanics and element combination system.
    
    Handles fusion cost calculation, success rate determination,
    element combination resolution, shard management, and complete fusion execution.
    
    Key Features:
        - Tiered fusion costs with exponential scaling
        - Configurable success rates per tier
        - Element combination matrix
        - Variable shard system (1-12 random shards per failure)
        - Complete fusion workflow with pessimistic locking
    
    Usage:
        >>> cost = FusionService.get_fusion_cost(3)
        >>> rate = FusionService.get_fusion_success_rate(3)
        >>> success = FusionService.roll_fusion_success(3, bonus_rate=5.0)
        >>> result_element = FusionService.calculate_element_result("infernal", "abyssal")
        >>> result = await FusionService.execute_fusion(session, player_id, maiden_ids)
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
            logger.warning(
                f"Element combination not found: {element1} + {element2}, "
                f"using {element1} as fallback"
            )
            return element1
    
    @staticmethod
    async def execute_fusion(
        session: AsyncSession,
        player_id: int,
        maiden_ids: List[int],
        use_shards: bool = False
    ) -> Dict[str, Any]:
        """
        Execute complete fusion workflow with pessimistic locking.
        
        Full transaction-safe fusion process:
        1. Lock player and maidens
        2. Validate fusion requirements
        3. Consume resources and maidens
        4. Roll for success (or guarantee if using shards)
        5. Create result maiden or grant shards
        6. Log transaction
        7. Update player stats
        
        Args:
            session: Database session (transaction managed by caller)
            player_id: Player's Discord ID
            maiden_ids: List of exactly 2 maiden IDs to fuse
            use_shards: Whether to use shards for guaranteed fusion
        
        Returns:
            Dictionary with fusion results:
                - success (bool): Whether fusion succeeded
                - tier (int): Input maiden tier
                - result_tier (int): Output maiden tier (if success)
                - result_maiden_id (int): New maiden ID (if success)
                - element (str): Result element
                - cost (int): Rikis consumed
                - shards_gained (int): Shards from failure (if failed)
                - shards_used (int): Shards consumed (if use_shards)
        
        Raises:
            InvalidFusionError: If maiden_ids length != 2 or tier >= 12
            MaidenNotFoundError: If maidens don't exist or aren't owned
            InsufficientResourcesError: If player lacks rikis or shards
        
        Example:
            >>> async with DatabaseService.get_transaction() as session:
            ...     result = await FusionService.execute_fusion(
            ...         session, player_id, [maiden_id1, maiden_id2]
            ...     )
            ...     if result["success"]:
            ...         print(f"Created Tier {result['result_tier']} maiden!")
        """
        if len(maiden_ids) != 2:
            raise InvalidFusionError(f"Fusion requires exactly 2 maidens, got {len(maiden_ids)}")
        
        player = await session.get(Player, player_id, with_for_update=True)
        if not player:
            raise MaidenNotFoundError(f"Player {player_id} not found")
        
        maiden_1 = await session.get(Maiden, maiden_ids[0], with_for_update=True)
        maiden_2 = await session.get(Maiden, maiden_ids[1], with_for_update=True)
        
        if not maiden_1 or not maiden_2:
            raise MaidenNotFoundError("One or both maidens not found")
        
        if maiden_1.player_id != player_id or maiden_2.player_id != player_id:
            raise MaidenNotFoundError("You don't own these maidens")
        
        if maiden_1.tier != maiden_2.tier:
            raise InvalidFusionError("Maidens must be same tier to fuse")
        
        if maiden_1.tier >= 12:
            raise InvalidFusionError("Cannot fuse Tier 12+ maidens")
        
        if maiden_1.quantity < 1 or maiden_2.quantity < 1:
            raise InvalidFusionError("Maidens must have quantity >= 1")
        
        tier = maiden_1.tier
        cost = FusionService.get_fusion_cost(tier)
        
        if player.rikis < cost:
            raise InsufficientResourcesError(
                resource="rikis",
                required=cost,
                current=player.rikis
            )
        
        if use_shards:
            shards_needed = ConfigManager.get("shard_system.shards_for_redemption", 100)
            if player.get_fusion_shards(tier) < shards_needed:
                raise InsufficientResourcesError(
                    resource=f"tier_{tier}_shards",
                    required=shards_needed,
                    current=player.get_fusion_shards(tier)
                )
        
        player.rikis -= cost
        
        maiden_base_1 = await session.get(MaidenBase, maiden_1.maiden_base_id)
        maiden_base_2 = await session.get(MaidenBase, maiden_2.maiden_base_id)
        
        if not maiden_base_1 or not maiden_base_2:
            raise MaidenNotFoundError("Maiden base data not found")
        
        result_element = FusionService.calculate_element_result(
            maiden_base_1.element,
            maiden_base_2.element
        )
        
        success = False
        shards_used = 0
        shards_gained = 0
        result_maiden_id = None
        result_tier = tier + 1
        
        if use_shards:
            shards_needed = ConfigManager.get("shard_system.shards_for_redemption", 100)
            key = f"tier_{tier}"
            player.fusion_shards[key] -= shards_needed
            shards_used = shards_needed
            success = True
            player.stats["shards_spent"] = player.stats.get("shards_spent", 0) + shards_needed
        else:
            event_bonus = ConfigManager.get("event_modifiers.fusion_rate_boost", 0.0)
            success = FusionService.roll_fusion_success(tier, event_bonus)
        
        if success:
            result_maiden_bases = await session.execute(
                select(MaidenBase).where(
                    MaidenBase.base_tier == result_tier,
                    MaidenBase.element == result_element
                )
            )
            available_bases = result_maiden_bases.scalars().all()
            
            if not available_bases:
                logger.error(f"No maiden base found for tier {result_tier} element {result_element}")
                raise InvalidFusionError(f"No maiden available for tier {result_tier} {result_element}")
            
            chosen_base = random.choice(available_bases)
            
            existing_result = await session.execute(
                select(Maiden).where(
                    Maiden.player_id == player_id,
                    Maiden.maiden_base_id == chosen_base.id
                ).with_for_update()
            )
            existing_maiden = existing_result.scalar_one_or_none()
            
            if existing_maiden:
                existing_maiden.quantity += 1
                result_maiden_id = existing_maiden.id
            else:
                new_maiden = Maiden(
                    player_id=player_id,
                    maiden_base_id=chosen_base.id,
                    tier=result_tier,
                    quantity=1,
                    is_locked=False
                )
                session.add(new_maiden)
                await session.flush()
                result_maiden_id = new_maiden.id
                player.unique_maidens += 1
            
            maiden_1.quantity -= 1
            maiden_2.quantity -= 1
            
            if maiden_1.quantity == 0:
                await session.delete(maiden_1)
            if maiden_2.quantity == 0:
                await session.delete(maiden_2)
            
            player.successful_fusions += 1
            player.stats["successful_fusions"] = player.stats.get("successful_fusions", 0) + 1
        else:
            shards_min = ConfigManager.get("shard_system.shards_per_failure_min", 1)
            shards_max = ConfigManager.get("shard_system.shards_per_failure_max", 12)
            shards_gained = random.randint(shards_min, shards_max)
            
            key = f"tier_{tier}"
            current_shards = player.fusion_shards.get(key, 0)
            player.fusion_shards[key] = current_shards + shards_gained
            player.stats["shards_earned"] = player.stats.get("shards_earned", 0) + shards_gained
            
            maiden_1.quantity -= 1
            maiden_2.quantity -= 1
            
            if maiden_1.quantity == 0:
                await session.delete(maiden_1)
            if maiden_2.quantity == 0:
                await session.delete(maiden_2)
        
        player.total_fusions += 1
        player.stats["total_fusions"] = player.stats.get("total_fusions", 0) + 1
        player.stats["rikis_spent_on_fusion"] = player.stats.get("rikis_spent_on_fusion", 0) + cost
        
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type="fusion_attempt",
            details={
                "success": success,
                "input_tier": tier,
                "result_tier": result_tier if success else None,
                "result_maiden_id": result_maiden_id,
                "element": result_element,
                "cost": cost,
                "use_shards": use_shards,
                "shards_used": shards_used,
                "shards_gained": shards_gained,
                "maiden_1_id": maiden_ids[0],
                "maiden_2_id": maiden_ids[1]
            },
            context="fusion_command"
        )
        
        return {
            "success": success,
            "tier": tier,
            "result_tier": result_tier if success else None,
            "result_maiden_id": result_maiden_id,
            "element": result_element,
            "cost": cost,
            "shards_gained": shards_gained,
            "shards_used": shards_used
        }
    
    @staticmethod
    async def add_fusion_shard(
        player: Player,
        tier: int,
        amount: int = 1
    ) -> Dict[str, Any]:
        """
        Award fusion shards to player for failed fusion.
        
        Grants 1-12 random shards per failure (configurable).
        Shards accumulate toward guaranteed fusion at same tier (100 shards required).
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
        
        Example:
            >>> result = await FusionService.add_fusion_shard(player, 3)
            >>> print(f"Gained {result['shards_gained']} shards!")
        """
        shards_min = ConfigManager.get("shard_system.shards_per_failure_min", 1)
        shards_max = ConfigManager.get("shard_system.shards_per_failure_max", 12)
        
        actual_amount = random.randint(shards_min, shards_max) * amount
        
        key = f"tier_{tier}"
        current = player.fusion_shards.get(key, 0)
        player.fusion_shards[key] = current + actual_amount
        player.stats["shards_earned"] = player.stats.get("shards_earned", 0) + actual_amount
        
        shards_for_redemption = ConfigManager.get("shard_system.shards_for_redemption", 100)
        
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
        
        Example:
            >>> if await FusionService.redeem_shards(player, 3):
            ...     print("Shards redeemed!")
        """
        shards_needed = ConfigManager.get("shard_system.shards_for_redemption", 100)
        
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
        
        Args:
            player: Player object
        
        Returns:
            List of tier numbers with sufficient shards (>= 100)
        
        Example:
            >>> redeemable = FusionService.get_redeemable_tiers(player)
            >>> print(f"Can redeem tiers: {redeemable}")
        """
        shards_needed = ConfigManager.get("shard_system.shards_for_redemption", 100)
        
        return [
            int(key.split("_")[1]) 
            for key, count in player.fusion_shards.items() 
            if count >= shards_needed
        ]