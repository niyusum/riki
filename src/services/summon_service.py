# src/services/summon_service.py

from typing import Dict, Any, Optional, List
import random
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.database.models.player import Player
from src.database.models.maiden import Maiden
from src.database.models.maiden_base import MaidenBase
from src.services.config_manager import ConfigManager
from src.services.logger import get_logger
from src.services.resource_service import ResourceService
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
        - ResourceService integration for grace-based summoning
    """

    # -------------------------------------------------------
    # RATE CALCULATION
    # -------------------------------------------------------
    @staticmethod
    def get_rates_for_player_level(player_level: int) -> Dict[str, Any]:
        """
        Calculate dynamic summon rates based on player's unlocked tiers.
        Favors lower tiers while unlocking rarer ones at higher levels.
        """
        unlock_levels = ConfigManager.get("gacha_rates.tier_unlock_levels", {})
        decay_factor = ConfigManager.get("gacha_rates.rate_distribution.decay_factor", 0.75)
        highest_tier_base = ConfigManager.get("gacha_rates.rate_distribution.highest_tier_base", 22.0)

        unlocked_tiers = [
            int(k.replace("tier_", ""))
            for k, lvl in unlock_levels.items()
            if player_level >= lvl
        ]

        if not unlocked_tiers:
            unlocked_tiers = [1, 2, 3]
            logger.warning(f"No tiers unlocked for level {player_level}, using default [1,2,3]")

        unlocked_tiers.sort()

        rates = {}
        current_rate = highest_tier_base
        for tier in unlocked_tiers:
            rates[f"tier_{tier}"] = current_rate
            current_rate *= decay_factor

        total = sum(rates.values())
        normalized_rates = {tier: (rate / total) * 100 for tier, rate in rates.items()}

        return {
            "unlocked_tiers": unlocked_tiers,
            "rates": normalized_rates,
            "highest_tier": max(unlocked_tiers),
            "tier_count": len(unlocked_tiers),
        }

    # -------------------------------------------------------
    # ROLL LOGIC
    # -------------------------------------------------------
    @staticmethod
    def roll_maiden_tier(player_level: int) -> int:
        """Roll for maiden tier using weighted random selection."""
        rate_data = SummonService.get_rates_for_player_level(player_level)
        rates = rate_data["rates"]

        tiers = [int(k.replace("tier_", "")) for k in rates.keys()]
        weights = list(rates.values())

        selected_tier = random.choices(tiers, weights=weights, k=1)[0]
        logger.debug(f"Rolled tier {selected_tier} from {tiers}")
        return selected_tier

    # -------------------------------------------------------
    # SINGLE SUMMON
    # -------------------------------------------------------
    @staticmethod
    async def perform_summon(
        session: AsyncSession,
        player_id: int,
        cost_override: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Perform a single summon using ResourceService for grace consumption.
        Applies pity tracking and full transaction logging.
        """
        from src.services.maiden_service import MaidenService
        from src.services.transaction_service import TransactionService

        # Lock player row
        player = await session.get(Player, player_id, with_for_update=True)
        if not player:
            raise ValueError(f"Player {player_id} not found")

        # Determine grace cost
        cost = cost_override or ConfigManager.get("summon_costs.grace_per_summon", 5)

        # ✅ Unified grace consumption via ResourceService
        await ResourceService.consume_resources(
            session=session,
            player=player,
            resources={"grace": cost},
            source="summon_cost",
            context={"cost": cost}
        )

        # Determine pity
        pity_threshold = ConfigManager.get("summon.pity.summons_for_pity", 25)
        is_pity = (player.pity_counter + 1) >= pity_threshold

        if is_pity:
            result = await SummonService.check_and_trigger_pity(session, player)
        else:
            tier = SummonService.roll_maiden_tier(player.level)

            stmt = select(MaidenBase).where(MaidenBase.base_tier == tier)
            maiden_bases = (await session.exec(stmt)).all()

            if not maiden_bases:
                logger.error(f"No maiden bases found at tier {tier}! Defaulting to T1.")
                stmt = select(MaidenBase).where(MaidenBase.base_tier == 1)
                maiden_bases = (await session.exec(stmt)).all()
                tier = 1

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

        # Update pity counter
        player.pity_counter = 0 if is_pity else player.pity_counter + 1
        result["new_pity_counter"] = player.pity_counter

        # Log transaction
        try:
            await TransactionService.log(
                session=session,
                player_id=player_id,
                transaction_type="summon",
                rikis_change=0,
                details={
                    "maiden_base_id": result["maiden_base"].id,
                    "tier": result["tier"],
                    "was_pity": result.get("was_pity", False),
                    "pity_counter": result["new_pity_counter"],
                    "grace_cost": cost
                }
            )
        except Exception as e:
            logger.debug(f"Transaction log skipped: {e}")

        await session.commit()

        logger.info(
            f"Player {player_id} summoned {result['maiden_base'].name} "
            f"T{result['tier']} (pity: {result.get('was_pity', False)})"
        )

        return result

    # -------------------------------------------------------
    # PITY SYSTEM
    # -------------------------------------------------------
    @staticmethod
    async def check_and_trigger_pity(
        session: AsyncSession,
        player: Player
    ) -> Dict[str, Any]:
        """Trigger pity: guarantee an unowned maiden from unlocked tiers."""
        from src.services.maiden_service import MaidenService

        rate_data = SummonService.get_rates_for_player_level(player.level)
        unlocked_tiers = rate_data["unlocked_tiers"]

        stmt = select(MaidenBase).where(MaidenBase.base_tier.in_(unlocked_tiers))
        all_bases = (await session.exec(stmt)).all()

        stmt = select(Maiden.maiden_base_id).where(Maiden.player_id == player.discord_id)
        owned_ids = set((await session.exec(stmt)).all())

        unowned = [b for b in all_bases if b.id not in owned_ids]

        if unowned:
            maiden_base = random.choice(unowned)
            tier = maiden_base.base_tier
        else:
            highest_tier = rate_data["highest_tier"]
            next_tier = min(highest_tier + 1, 12)
            stmt = select(MaidenBase).where(MaidenBase.base_tier == next_tier)
            candidates = (await session.exec(stmt)).all()
            if not candidates:
                stmt = select(MaidenBase).where(MaidenBase.base_tier == highest_tier)
                candidates = (await session.exec(stmt)).all()
                tier = highest_tier
            else:
                tier = next_tier
            maiden_base = random.choice(candidates)

        await MaidenService.add_maiden_to_inventory(
            session=session,
            player_id=player.discord_id,
            maiden_base_id=maiden_base.id,
            tier=tier,
            quantity=1,
            acquired_from="pity_summon"
        )

        logger.info(f"Pity triggered for player {player.discord_id}: {maiden_base.name} T{tier}")

        return {
            "success": True,
            "maiden_base": maiden_base,
            "tier": tier,
            "quantity": 1,
            "was_pity": True
        }

    # -------------------------------------------------------
    # BATCH SUMMON
    # -------------------------------------------------------
    @staticmethod
    async def batch_summon(
        session: AsyncSession,
        player_id: int,
        count: int = 10
    ) -> Dict[str, Any]:
        """
        Perform multiple summons at once (x5 or x10) using grace.
        Consumes all grace up front via ResourceService for atomic deduction.
        """
        # Lock player
        player = await session.get(Player, player_id, with_for_update=True)
        if not player:
            raise ValueError(f"Player {player_id} not found")

        cost_per = ConfigManager.get("summon_costs.grace_per_summon", 5)
        total_cost = cost_per * count

        # ✅ Deduct all grace once before loop
        await ResourceService.consume_resources(
            session=session,
            player=player,
            resources={"grace": total_cost},
            source="batch_summon_cost",
            context={"count": count, "total_cost": total_cost}
        )

        results: List[Dict[str, Any]] = []
        pity_count = 0

        for i in range(count):
            result = await SummonService.perform_summon(
                session=session,
                player_id=player_id,
                cost_override=0  # already paid
            )
            results.append(result)
            if result.get("was_pity", False):
                pity_count += 1

        return {
            "success": True,
            "results": results,
            "total_cost": total_cost,
            "pity_triggers": pity_count,
            "remaining_grace": player.grace
        }
