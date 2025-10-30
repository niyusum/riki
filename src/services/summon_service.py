from typing import Dict, Any, Optional, List
import random
from datetime import datetime

from src.database.models.player import Player
from src.database.models.maiden import Maiden
from src.database.models.maiden_base import MaidenBase
from src.services.config_manager import ConfigManager
from src.services.logger import get_logger
from src.exceptions import InsufficientResourcesError

logger = get_logger(__name__)


class SummonService:
    """
    Progressive tier unlock gacha system with dynamic rate distribution.
    
    Players unlock higher tiers as they level up while maintaining access
    to ALL previously unlocked tiers. Rate distribution uses exponential
    decay where LOWER tiers are MORE common and HIGHER tiers are RARER.
    
    Key Mechanics:
        - Progressive tier unlocking (level gates)
        - Dynamic rate calculation (exponential decay favoring low tiers)
        - Pity system (guaranteed unowned maiden every 25 summons)
        - Batch summon support (x1, x5, x10)
    
    Rate Distribution Philosophy:
        T1: Most common (~19% at high level)
        T10: Rarest (~1.5% at high level)
    
    Usage:
        >>> rates = SummonService.get_rates_for_player_level(40)
        >>> tier = SummonService.roll_maiden_tier(40)
        >>> result = await SummonService.perform_summon(session, player_id)
        >>> results = await SummonService.batch_summon(session, player_id, count=5)
    """
    
    @staticmethod
    def get_rates_for_player_level(player_level: int) -> Dict[str, Any]:
        """
        Calculate dynamic summon rates based on player's unlocked tiers.
        
        Rates decay from LOW tiers (common) to HIGH tiers (rare).
        
        As player levels up:
        - New tiers unlock and become RAREST
        - Previous tiers remain MOST COMMON
        - Rate distribution follows exponential decay curve
        
        Example progression (with decay_factor=0.75, base=22.0):
        - Level 5: T1(58%), T2(33%), T3(19%)
        - Level 15: T4(7%), T3(11%), T2(17%), T1(27%)
        - Level 40: T1-10 unlocked with T1 HIGHEST at ~19%, T10 LOWEST at ~1.5%
        
        Args:
            player_level: Player's current level
        
        Returns:
            Dictionary with:
                - unlocked_tiers (list): List of tier numbers available (sorted)
                - rates (dict): {tier_N: percentage}
                - highest_tier (int): Highest unlocked tier
                - tier_count (int): Number of unlocked tiers
        
        Example:
            >>> SummonService.get_rates_for_player_level(40)
            {
                'unlocked_tiers': [1,2,3,4,5,6,7,8,9,10],
                'rates': {
                    'tier_1': 18.8,
                    'tier_2': 14.1,
                    'tier_3': 10.5,
                    ...
                    'tier_9': 1.9,
                    'tier_10': 1.4
                },
                'highest_tier': 10,
                'tier_count': 10
            }
        """
        unlock_levels = ConfigManager.get("gacha_rates.tier_unlock_levels", {})
        decay_factor = ConfigManager.get("gacha_rates.rate_distribution.decay_factor", 0.75)
        highest_tier_base = ConfigManager.get("gacha_rates.rate_distribution.highest_tier_base", 22.0)
        
        unlocked_tiers = []
        for tier_key, unlock_level in unlock_levels.items():
            if player_level >= unlock_level:
                tier_num = int(tier_key.replace("tier_", ""))
                unlocked_tiers.append(tier_num)
        
        if not unlocked_tiers:
            unlocked_tiers = [1, 2, 3]
            logger.warning(f"No tiers unlocked for level {player_level}, using default [1,2,3]")
        
        unlocked_tiers.sort()
        
        rates = {}
        current_rate = highest_tier_base
        
        for tier in unlocked_tiers:
            rates[f"tier_{tier}"] = current_rate
            current_rate = current_rate * decay_factor
        
        total = sum(rates.values())
        normalized_rates = {
            tier: (rate / total) * 100 
            for tier, rate in rates.items()
        }
        
        return {
            "unlocked_tiers": unlocked_tiers,
            "rates": normalized_rates,
            "highest_tier": max(unlocked_tiers),
            "tier_count": len(unlocked_tiers)
        }
    
    @staticmethod
    def roll_maiden_tier(player_level: int) -> int:
        """
        Roll for maiden tier using weighted random selection.
        
        Lower tiers have higher probability, higher tiers have lower probability.
        
        Args:
            player_level: Player's current level
        
        Returns:
            Selected tier number (1-12)
        
        Example:
            >>> SummonService.roll_maiden_tier(40)
            1
            >>> SummonService.roll_maiden_tier(40)
            10
        """
        rate_data = SummonService.get_rates_for_player_level(player_level)
        rates = rate_data["rates"]
        
        tiers = []
        weights = []
        
        for tier_key, weight in rates.items():
            tier_num = int(tier_key.replace("tier_", ""))
            tiers.append(tier_num)
            weights.append(weight)
        
        selected_tier = random.choices(tiers, weights=weights, k=1)[0]
        
        logger.debug(f"Rolled tier {selected_tier} from available tiers: {tiers}")
        return selected_tier
    
    @staticmethod
    async def perform_summon(
        session,
        player_id: int,
        cost_override: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Perform a single summon with pity tracking.
        
        Workflow:
        1. Check/deduct rikis cost
        2. Check pity counter (25 summons = guaranteed unowned maiden)
        3. Roll maiden tier based on player level
        4. Select random maiden from that tier
        5. Add to inventory
        6. Update pity counter
        7. Log transaction
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            cost_override: Optional custom cost (for events/promotions)
        
        Returns:
            Dictionary containing:
                - success (bool): Whether summon succeeded
                - maiden_base (MaidenBase): The summoned maiden
                - tier (int): Tier rolled
                - quantity (int): Always 1 for single summons
                - was_pity (bool): Whether this was a pity summon
                - new_pity_counter (int): Updated pity counter
        
        Raises:
            InsufficientResourcesError: If player lacks rikis
        
        Example:
            >>> result = await SummonService.perform_summon(session, 123456789)
            >>> print(f"Summoned {result['maiden_base'].name} at T{result['tier']}")
        """
        from src.services.maiden_service import MaidenService
        
        player = await session.get(Player, player_id, with_for_update=True)
        if not player:
            raise ValueError(f"Player {player_id} not found")
        
        cost = cost_override or ConfigManager.get("summon.cost", 100)
        if player.rikis < cost:
            raise InsufficientResourcesError(
                f"Insufficient rikis: need {cost}, have {player.rikis}"
            )
        
        player.rikis -= cost
        
        is_pity = (player.pity_counter + 1) >= ConfigManager.get("summon.pity.summons_for_pity", 25)
        
        if is_pity:
            result = await SummonService.check_and_trigger_pity(session, player)
        else:
            tier = SummonService.roll_maiden_tier(player.level)
            
            from sqlmodel import select
            stmt = select(MaidenBase).where(MaidenBase.base_tier == tier)
            maiden_bases = (await session.exec(stmt)).all()
            
            if not maiden_bases:
                logger.error(f"No maiden bases found at tier {tier}!")
                tier = 1
                stmt = select(MaidenBase).where(MaidenBase.base_tier == tier)
                maiden_bases = (await session.exec(stmt)).all()
            
            maiden_base = random.choice(maiden_bases)
            
            await MaidenService.add_maiden_to_inventory(
                session=session,
                player_id=player_id,
                maiden_base_id=maiden_base.id,
                tier=tier,
                quantity=1,
                acquired_from="summon"
            )
            
            result = {
                "success": True,
                "maiden_base": maiden_base,
                "tier": tier,
                "quantity": 1,
                "was_pity": False
            }
        
        if is_pity:
            player.pity_counter = 0
        else:
            player.pity_counter += 1
        
        result["new_pity_counter"] = player.pity_counter
        
        try:
            from src.services.transaction_service import TransactionService
            await TransactionService.log(
                session=session,
                player_id=player_id,
                transaction_type="summon",
                rikis_change=-cost,
                details={
                    "maiden_base_id": result["maiden_base"].id,
                    "tier": result["tier"],
                    "was_pity": result.get("was_pity", False),
                    "pity_counter": result["new_pity_counter"]
                }
            )
        except ImportError:
            logger.debug("TransactionService not available, skipping transaction log")
        
        await session.commit()
        
        logger.info(
            f"Player {player_id} summoned {result['maiden_base'].name} "
            f"T{result['tier']} (pity: {result.get('was_pity', False)})"
        )
        
        return result
    
    @staticmethod
    async def check_and_trigger_pity(
        session,
        player: Player
    ) -> Dict[str, Any]:
        """
        Trigger pity system: guarantee unowned maiden from unlocked tiers.
        
        Pity Logic:
        1. Get all unlocked tiers for player
        2. Find all maiden bases player doesn't own in those tiers
        3. If unowned maidens exist: give random unowned maiden at its base tier
        4. If all owned: give random maiden from next unlocked tier up
        
        Args:
            session: Active database session
            player: Player object (already locked)
        
        Returns:
            Same format as perform_summon result dict
        
        Example:
            >>> result = await SummonService.check_and_trigger_pity(session, player)
            >>> print(f"Pity triggered: {result['maiden_base'].name}")
        """
        from src.services.maiden_service import MaidenService
        from sqlmodel import select
        
        rate_data = SummonService.get_rates_for_player_level(player.level)
        unlocked_tiers = rate_data["unlocked_tiers"]
        
        stmt = select(MaidenBase).where(MaidenBase.base_tier.in_(unlocked_tiers))
        all_available_bases = (await session.exec(stmt)).all()
        
        stmt = select(Maiden.maiden_base_id).where(Maiden.player_id == player.discord_id)
        owned_base_ids = set((await session.exec(stmt)).all())
        
        unowned_bases = [
            base for base in all_available_bases 
            if base.id not in owned_base_ids
        ]
        
        if unowned_bases:
            maiden_base = random.choice(unowned_bases)
            tier = maiden_base.base_tier
        else:
            highest_tier = rate_data["highest_tier"]
            next_tier = min(highest_tier + 1, 12)
            
            stmt = select(MaidenBase).where(MaidenBase.base_tier == next_tier)
            next_tier_bases = (await session.exec(stmt)).all()
            
            if not next_tier_bases:
                stmt = select(MaidenBase).where(MaidenBase.base_tier == highest_tier)
                next_tier_bases = (await session.exec(stmt)).all()
                tier = highest_tier
            else:
                tier = next_tier
            
            maiden_base = random.choice(next_tier_bases)
        
        await MaidenService.add_maiden_to_inventory(
            session=session,
            player_id=player.discord_id,
            maiden_base_id=maiden_base.id,
            tier=tier,
            quantity=1,
            acquired_from="pity_summon"
        )
        
        logger.info(
            f"Pity triggered for player {player.discord_id}: "
            f"{maiden_base.name} T{tier}"
        )
        
        return {
            "success": True,
            "maiden_base": maiden_base,
            "tier": tier,
            "quantity": 1,
            "was_pity": True
        }
    
    @staticmethod
    async def batch_summon(
        session,
        player_id: int,
        count: int = 10
    ) -> Dict[str, Any]:
        """
        Perform multiple summons at once (x5 or x10).
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            count: Number of summons (5 or 10)
        
        Returns:
            Dictionary containing:
                - success (bool): Whether all summons succeeded
                - results (list): List of summon result dicts
                - total_cost (int): Total rikis spent
                - pity_triggers (int): Number of pity summons
        
        Raises:
            InsufficientResourcesError: If player lacks rikis for all summons
        
        Example:
            >>> results = await SummonService.batch_summon(session, player_id, count=10)
            >>> print(f"Got {len(results['results'])} maidens, {results['pity_triggers']} were pity")
        """
        cost_per_summon = ConfigManager.get("summon.cost", 100)
        total_cost = cost_per_summon * count
        
        player = await session.get(Player, player_id)
        if player.rikis < total_cost:
            raise InsufficientResourcesError(
                f"Insufficient rikis for {count}x summon: need {total_cost}, have {player.rikis}"
            )
        
        results = []
        pity_count = 0
        
        for i in range(count):
            result = await SummonService.perform_summon(session, player_id)
            results.append(result)
            if result.get("was_pity", False):
                pity_count += 1
        
        return {
            "success": True,
            "results": results,
            "total_cost": total_cost,
            "pity_triggers": pity_count
        }