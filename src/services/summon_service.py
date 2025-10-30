from typing import Dict, Any, List, Optional
import random
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.database.models.player import Player
from src.database.models.maiden import Maiden
from src.database.models.maiden_base import MaidenBase
from src.services.config_manager import ConfigManager
from src.services.transaction_logger import TransactionLogger
from src.exceptions import InsufficientResourcesError
from src.services.logger import get_logger

logger = get_logger(__name__)


class SummonService:
    """
    Gacha summon system with progressive tier unlocks and pity mechanics.
    
    Features:
        - Progressive tier unlocks (industry-standard model)
        - Dynamic rate distribution (higher tiers favored as pool expands)
        - Pity system (25 summons = guaranteed new maiden or next tier)
        - Batch summon support (x1, x5, x10)
        - Transaction logging
    
    Philosophy:
        As players level up, they unlock HIGHER tiers with decent rates, while
        LOWER tiers become rarer. Fusion remains primary progression path.
        This matches Genshin Impact, Fate/GO, Arknights model.
    
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
        
        As player levels up:
        - New tiers unlock and become most common
        - Previous tiers get diluted but remain available
        - Rate distribution follows exponential decay curve
        
        Example progression:
        - Level 5: T1(50%), T2(35%), T3(15%)
        - Level 15: T1(28%), T2(32%), T3(25%), T4(15%)
        - Level 40: T1-10 unlocked with T10 highest at 15%
        
        Args:
            player_level: Player's current level
        
        Returns:
            Dictionary with:
                - unlocked_tiers (list): List of tier numbers available
                - rates (dict): {tier_N: percentage}
                - highest_tier (int): Highest unlocked tier
                - tier_count (int): Number of unlocked tiers
        
        Example:
            >>> SummonService.get_rates_for_player_level(40)
            {
                'unlocked_tiers': [1,2,3,4,5,6,7,8,9,10],
                'rates': {
                    'tier_10': 15.0,
                    'tier_9': 9.75,
                    'tier_8': 6.34,
                    ...
                },
                'highest_tier': 10,
                'tier_count': 10
            }
        """
        unlock_levels = ConfigManager.get("gacha_rates.tier_unlock_levels", {})
        decay_factor = ConfigManager.get("gacha_rates.rate_distribution.decay_factor", 0.65)
        highest_tier_base = ConfigManager.get("gacha_rates.rate_distribution.highest_tier_base", 15.0)
        
        unlocked_tiers = []
        for tier_key, unlock_level in unlock_levels.items():
            if player_level >= unlock_level:
                tier_num = int(tier_key.replace("tier_", ""))
                unlocked_tiers.append(tier_num)
        
        if not unlocked_tiers:
            unlocked_tiers = [1, 2, 3]
            logger.warning(f"No tiers unlocked for level {player_level}, using default [1,2,3]")
        
        unlocked_tiers.sort(reverse=True)
        
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
        
        Uses player's level to determine unlocked tiers and their dynamic rates.
        Higher tiers have better rates when first unlocked, then dilute over time.
        
        Args:
            player_level: Player's current level
        
        Returns:
            Tier number (1-12)
        
        Example:
            >>> tier = SummonService.roll_maiden_tier(40)
            >>> # Returns 1-10 with T10 most likely, T1 least likely
        """
        rate_data = SummonService.get_rates_for_player_level(player_level)
        rates = rate_data["rates"]
        
        tiers = []
        weights = []
        
        for tier_key, rate in rates.items():
            tier_num = int(tier_key.replace("tier_", ""))
            tiers.append(tier_num)
            weights.append(rate)
        
        if not tiers:
            logger.error(f"No tiers available for level {player_level}, defaulting to tier 1")
            return 1
        
        chosen_tier = random.choices(tiers, weights=weights, k=1)[0]
        return chosen_tier
    
    @staticmethod
    async def perform_summon(
        session: AsyncSession,
        player_id: int,
        force_pity: bool = False
    ) -> Dict[str, Any]:
        """
        Perform single summon with full transaction workflow.
        
        Workflow:
        1. Lock player
        2. Validate grace
        3. Consume grace
        4. Check/trigger pity if needed
        5. Roll tier (or use pity tier)
        6. Select random maiden of that tier
        7. Add to inventory
        8. Log transaction
        9. Update stats and pity counter
        
        Args:
            session: Database session (transaction managed by caller)
            player_id: Player's Discord ID
            force_pity: Force pity trigger (for testing/admin)
        
        Returns:
            Dictionary with summon results:
                - maiden_id (int): Maiden instance ID
                - maiden_base_id (int): MaidenBase template ID
                - tier (int): Maiden tier
                - name (str): Maiden name
                - element (str): Maiden element
                - is_new (bool): Whether this is first copy
                - pity_triggered (bool): Whether pity activated
                - pity_counter (int): Current pity count after summon
        
        Raises:
            InsufficientResourcesError: If player lacks grace
        
        Example:
            >>> async with DatabaseService.get_transaction() as session:
            ...     result = await SummonService.perform_summon(session, player_id)
            ...     print(f"Summoned {result['name']} (Tier {result['tier']})!")
        """
        player = await session.get(Player, player_id, with_for_update=True)
        if not player:
            raise InsufficientResourcesError(
                resource="player",
                required=1,
                current=0
            )
        
        grace_cost = ConfigManager.get("summon_costs.grace_per_summon", 5)
        if player.grace < grace_cost:
            raise InsufficientResourcesError(
                resource="grace",
                required=grace_cost,
                current=player.grace
            )
        
        player.grace -= grace_cost
        player.pity_counter += 1
        
        pity_threshold = ConfigManager.get("pity_system.summons_for_pity", 25)
        pity_triggered = force_pity or player.pity_counter >= pity_threshold
        
        if pity_triggered:
            tier, maiden_base = await SummonService.check_and_trigger_pity(
                session, player, player.level
            )
            player.pity_counter = 0
        else:
            tier = SummonService.roll_maiden_tier(player.level)
            
            available_bases = await session.execute(
                select(MaidenBase).where(MaidenBase.base_tier == tier)
            )
            bases_list = available_bases.scalars().all()
            
            if not bases_list:
                logger.error(f"No maiden bases found for tier {tier}, falling back to tier 1")
                tier = 1
                available_bases = await session.execute(
                    select(MaidenBase).where(MaidenBase.base_tier == 1)
                )
                bases_list = available_bases.scalars().all()
            
            maiden_base = random.choice(bases_list)
        
        existing_maiden_result = await session.execute(
            select(Maiden).where(
                Maiden.player_id == player_id,
                Maiden.maiden_base_id == maiden_base.id
            ).with_for_update()
        )
        existing_maiden = existing_maiden_result.scalar_one_or_none()
        
        is_new = False
        if existing_maiden:
            existing_maiden.quantity += 1
            maiden_id = existing_maiden.id
        else:
            new_maiden = Maiden(
                player_id=player_id,
                maiden_base_id=maiden_base.id,
                tier=tier,
                quantity=1,
                is_locked=False
            )
            session.add(new_maiden)
            await session.flush()
            maiden_id = new_maiden.id
            is_new = True
            player.unique_maidens += 1
        
        player.stats["summons_performed"] = player.stats.get("summons_performed", 0) + 1
        player.stats["grace_spent_on_summons"] = player.stats.get("grace_spent_on_summons", 0) + grace_cost
        
        if pity_triggered:
            player.stats["pity_summons"] = player.stats.get("pity_summons", 0) + 1
        
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type="summon_performed",
            details={
                "maiden_base_id": maiden_base.id,
                "tier": tier,
                "grace_cost": grace_cost,
                "is_new": is_new,
                "pity_triggered": pity_triggered,
                "pity_counter": player.pity_counter
            },
            context="summon_command"
        )
        
        return {
            "maiden_id": maiden_id,
            "maiden_base_id": maiden_base.id,
            "tier": tier,
            "name": maiden_base.name,
            "element": maiden_base.element,
            "is_new": is_new,
            "pity_triggered": pity_triggered,
            "pity_counter": player.pity_counter
        }
    
    @staticmethod
    async def check_and_trigger_pity(
        session: AsyncSession,
        player: Player,
        player_level: int
    ) -> tuple[int, MaidenBase]:
        """
        Trigger pity system - Option D with fallback to next tier.
        
        Option D Logic (Progressive Unlocks):
            1. Get all maidens in player's unlocked tiers
            2. Filter for maidens player DOESN'T own
            3. If any unowned maidens exist, return random unowned maiden
            4. If player owns ALL unlocked maidens, return maiden from next highest tier
        
        This ensures pity is always exciting and provides progression.
        
        Args:
            session: Database session
            player: Player object (locked)
            player_level: Player's current level
        
        Returns:
            Tuple of (tier, maiden_base)
        
        Example:
            >>> # Level 40 player with T1-10 unlocked
            >>> tier, maiden_base = await SummonService.check_and_trigger_pity(
            ...     session, player, 40
            ... )
            >>> # Returns unowned T1-10 maiden, or T11 if all T1-10 owned
        """
        rate_data = SummonService.get_rates_for_player_level(player_level)
        unlocked_tiers = rate_data["unlocked_tiers"]
        
        available_bases_result = await session.execute(
            select(MaidenBase).where(MaidenBase.base_tier.in_(unlocked_tiers))
        )
        available_bases = available_bases_result.scalars().all()
        
        owned_maiden_bases_result = await session.execute(
            select(Maiden.maiden_base_id).where(Maiden.player_id == player.discord_id)
        )
        owned_maiden_base_ids = set(owned_maiden_bases_result.scalars().all())
        
        unowned_bases = [
            base for base in available_bases
            if base.id not in owned_maiden_base_ids
        ]
        
        if unowned_bases:
            chosen_base = random.choice(unowned_bases)
            logger.info(
                f"Pity triggered for player {player.discord_id}: "
                f"Granted unowned {chosen_base.name} (Tier {chosen_base.base_tier}) "
                f"from unlocked tiers {unlocked_tiers}"
            )
            return chosen_base.base_tier, chosen_base
        else:
            highest_unlocked = max(unlocked_tiers)
            next_tier = highest_unlocked + 1
            
            next_tier_bases_result = await session.execute(
                select(MaidenBase)
                .where(MaidenBase.base_tier == next_tier)
                .order_by(MaidenBase.base_tier)
            )
            next_tier_bases = next_tier_bases_result.scalars().all()
            
            if not next_tier_bases:
                logger.warning(
                    f"No maidens found for next tier {next_tier}, "
                    f"falling back to highest unlocked tier {highest_unlocked}"
                )
                chosen_base = random.choice(available_bases)
                return chosen_base.base_tier, chosen_base
            
            chosen_base = random.choice(next_tier_bases)
            logger.info(
                f"Pity triggered for player {player.discord_id}: "
                f"Player owns all unlocked tiers {unlocked_tiers}, "
                f"granted {chosen_base.name} (Tier {next_tier})"
            )
            return next_tier, chosen_base
    
    @staticmethod
    async def batch_summon(
        session: AsyncSession,
        player_id: int,
        count: int = 5
    ) -> Dict[str, Any]:
        """
        Perform batch summons (x5 or x10).
        
        Validates count (must be 1, 5, or 10).
        x10 is premium-only (validated by caller).
        Performs summons sequentially to handle pity correctly.
        
        Args:
            session: Database session
            player_id: Player's Discord ID
            count: Number of summons (1, 5, or 10)
        
        Returns:
            Dictionary with batch results:
                - results (list): List of individual summon results
                - total_grace_spent (int)
                - new_maidens_count (int)
                - pity_triggered_count (int)
                - tier_breakdown (dict): Count per tier
        
        Raises:
            InsufficientResourcesError: If player lacks total grace
            ValueError: If count is invalid
        
        Example:
            >>> result = await SummonService.batch_summon(session, player_id, count=5)
            >>> print(f"Summoned {len(result['results'])} maidens!")
        """
        if count not in [1, 5, 10]:
            raise ValueError(f"Invalid summon count: {count}. Must be 1, 5, or 10.")
        
        player = await session.get(Player, player_id)
        if not player:
            raise InsufficientResourcesError(
                resource="player",
                required=1,
                current=0
            )
        
        grace_cost = ConfigManager.get("summon_costs.grace_per_summon", 5)
        total_grace_needed = grace_cost * count
        
        if player.grace < total_grace_needed:
            raise InsufficientResourcesError(
                resource="grace",
                required=total_grace_needed,
                current=player.grace
            )
        
        results = []
        new_maidens_count = 0
        pity_triggered_count = 0
        tier_breakdown = {}
        
        for i in range(count):
            result = await SummonService.perform_summon(session, player_id)
            results.append(result)
            
            if result["is_new"]:
                new_maidens_count += 1
            
            if result["pity_triggered"]:
                pity_triggered_count += 1
            
            tier = result["tier"]
            tier_breakdown[tier] = tier_breakdown.get(tier, 0) + 1
        
        return {
            "results": results,
            "total_grace_spent": total_grace_needed,
            "new_maidens_count": new_maidens_count,
            "pity_triggered_count": pity_triggered_count,
            "tier_breakdown": tier_breakdown,
            "count": count
        }