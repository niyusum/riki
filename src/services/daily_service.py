from typing import Dict, Any
from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.database.models.daily_quest import DailyQuest
from src.database.models.player import Player
from src.services.config_manager import ConfigManager
from src.services.transaction_logger import TransactionLogger
from src.exceptions import InvalidOperationError
from src.services.logger import get_logger
from src.services.resource_service import ResourceService

logger = get_logger(__name__)


class DailyService:
    """
    Daily quest system for core looping XP and currency rewards.
    
    Manages daily objectives, progress tracking, completion rewards,
    and streak bonuses. Primary engagement loop for consistent play.
    
    Daily Quests:
        - prayer_performed: Use /prayer at least once (configurable)
        - summon_maiden: Summon at least one maiden (configurable)
        - attempt_fusion: Attempt fusion at least once (configurable)
        - spend_energy: Spend energy on quests (configurable amount)
        - spend_stamina: Spend stamina on battles (configurable amount)
    
    Rewards:
        - Base: Rikis, Grace, Gems, XP
        - Completion Bonus: Extra rewards for finishing all quests
        - Streak Bonus: +10% per week of consecutive completions
    
    Usage:
        >>> daily = await DailyService.get_or_create_daily_quest(session, player_id)
        >>> await DailyService.update_quest_progress(session, player_id, "prayer_performed")
        >>> rewards = await DailyService.claim_rewards(session, player_id)
    """
    
    @staticmethod
    async def get_or_create_daily_quest(
        session: AsyncSession,
        player_id: int
    ) -> DailyQuest:
        """
        Get or create today's daily quest for player.
        
        Creates new DailyQuest if:
        - No quest exists for today
        - Quest exists but is for past date (resets daily)
        
        Args:
            session: Database session
            player_id: Player's Discord ID
        
        Returns:
            DailyQuest object for today
        
        Example:
            >>> daily = await DailyService.get_or_create_daily_quest(session, player_id)
            >>> print(f"Quest progress: {daily.get_completion_count()}/5")
        """
        today = date.today()
        
        result = await session.execute(
            select(DailyQuest).where(
                DailyQuest.player_id == player_id,
                DailyQuest.quest_date == today
            )
        )
        daily_quest = result.scalar_one_or_none()
        
        if not daily_quest:
            result = await session.execute(
                select(DailyQuest)
                .where(DailyQuest.player_id == player_id)
                .order_by(DailyQuest.quest_date.desc())
            )
            previous_quest = result.scalar_one_or_none()
            
            bonus_streak = 0
            if previous_quest:
                if previous_quest.quest_date == date.today():
                    return previous_quest
                
                if previous_quest.is_complete():
                    days_diff = (today - previous_quest.quest_date).days
                    if days_diff == 1:
                        bonus_streak = previous_quest.bonus_streak + 1
                    else:
                        bonus_streak = 0
            
            daily_quest = DailyQuest(
                player_id=player_id,
                quest_date=today,
                bonus_streak=bonus_streak
            )
            session.add(daily_quest)
            await session.flush()
            
            logger.info(
                f"Created daily quest for player {player_id} with streak {bonus_streak}"
            )
        
        return daily_quest
    
    @staticmethod
    async def update_quest_progress(
        session: AsyncSession,
        player_id: int,
        quest_type: str,
        amount: int = 1
    ) -> Dict[str, Any]:
        """
        Update quest progress and check for completion.
        
        Quest types:
            - "prayer_performed": Increment prayers_done
            - "summon_maiden": Increment summons_done
            - "attempt_fusion": Increment fusions_attempted
            - "spend_energy": Add to energy_spent
            - "spend_stamina": Add to stamina_spent
        
        Args:
            session: Database session
            player_id: Player's Discord ID
            quest_type: Type of quest to update
            amount: Amount to add (default 1)
        
        Returns:
            Dictionary with:
                - quest_completed (bool): Whether this update completed the quest
                - all_completed (bool): Whether all quests are now done
                - progress (dict): Current quest_progress
                - completion_count (int): Number of quests completed
        
        Raises:
            InvalidOperationError: If quest_type is invalid
        
        Example:
            >>> result = await DailyService.update_quest_progress(
            ...     session, player_id, "prayer_performed"
            ... )
            >>> if result["quest_completed"]:
            ...     print("Quest completed!")
        """
        valid_quest_types = {
            "prayer_performed": ("prayers_done", "daily_quests.prayer_required", 1),
            "summon_maiden": ("summons_done", "daily_quests.summon_required", 1),
            "attempt_fusion": ("fusions_attempted", "daily_quests.fusion_required", 1),
            "spend_energy": ("energy_spent", "daily_quests.energy_required", 10),
            "spend_stamina": ("stamina_spent", "daily_quests.stamina_required", 5)
        }
        
        if quest_type not in valid_quest_types:
            raise InvalidOperationError(f"Invalid quest type: {quest_type}")
        
        progress_key, config_key, default_required = valid_quest_types[quest_type]
        required_amount = ConfigManager.get(config_key, default_required)
        
        daily_quest = await DailyService.get_or_create_daily_quest(session, player_id)
        
        was_completed_before = daily_quest.quests_completed.get(quest_type, False)
        
        daily_quest.quest_progress[progress_key] += amount
        
        quest_completed = False
        if not was_completed_before:
            if daily_quest.quest_progress[progress_key] >= required_amount:
                daily_quest.quests_completed[quest_type] = True
                quest_completed = True
                
                logger.info(
                    f"Player {player_id} completed daily quest: {quest_type}"
                )
        
        await session.flush()
        
        return {
            "quest_completed": quest_completed,
            "all_completed": daily_quest.is_complete(),
            "progress": daily_quest.quest_progress.copy(),
            "quests_completed": daily_quest.quests_completed.copy(),
            "completion_count": daily_quest.get_completion_count()
        }
    
    @staticmethod
    def calculate_rewards(daily_quest: DailyQuest) -> Dict[str, int]:
        """
        Calculate rewards for daily quest completion.
        
        Reward structure:
            - Base rewards: Always granted for any progress
            - Completion bonus: Extra rewards if all quests finished
            - Streak multiplier: +10% per 7-day streak
        
        Args:
            daily_quest: DailyQuest object
        
        Returns:
            Dictionary with reward amounts:
                - rikis (int)
                - grace (int)
                - riki_gems (int)
                - xp (int)
        
        Example:
            >>> rewards = DailyService.calculate_rewards(daily_quest)
            >>> print(f"Rewards: {rewards['rikis']:,} rikis, {rewards['xp']} XP")
        """
        base_rikis = ConfigManager.get("daily_rewards.base_rikis", 500)
        base_grace = ConfigManager.get("daily_rewards.base_grace", 3)
        base_gems = ConfigManager.get("daily_rewards.base_gems", 1)
        base_xp = ConfigManager.get("daily_rewards.base_xp", 100)
        
        completion_bonus_rikis = ConfigManager.get("daily_rewards.completion_bonus_rikis", 500)
        completion_bonus_grace = ConfigManager.get("daily_rewards.completion_bonus_grace", 2)
        completion_bonus_gems = ConfigManager.get("daily_rewards.completion_bonus_gems", 1)
        completion_bonus_xp = ConfigManager.get("daily_rewards.completion_bonus_xp", 200)
        
        streak_multiplier = ConfigManager.get("daily_rewards.streak_multiplier", 0.1)
        
        rewards = {
            "rikis": base_rikis,
            "grace": base_grace,
            "riki_gems": base_gems,
            "xp": base_xp
        }
        
        if daily_quest.is_complete():
            rewards["rikis"] += completion_bonus_rikis
            rewards["grace"] += completion_bonus_grace
            rewards["riki_gems"] += completion_bonus_gems
            rewards["xp"] += completion_bonus_xp
        
        if daily_quest.bonus_streak >= 7:
            weeks = daily_quest.bonus_streak // 7
            multiplier = 1 + (weeks * streak_multiplier)
            
            for key in rewards:
                rewards[key] = int(rewards[key] * multiplier)
        
        return rewards
    
    @staticmethod
    async def claim_rewards(
        session: AsyncSession,
        player_id: int
    ) -> Dict[str, Any]:
        """
        Claim daily quest rewards with validation.
        
        Validates:
        - All quests must be complete
        - Rewards not already claimed
        - Prevents double-claiming
        
        Awards rewards to player and logs transaction.
        
        Args:
            session: Database session (transaction managed by caller)
            player_id: Player's Discord ID
        
        Returns:
            Dictionary with:
                - rewards (dict): Amounts of each currency/xp
                - leveled_up (bool): Whether player leveled from XP
                - new_level (int): Player level after rewards
                - streak (int): Current streak count
        
        Raises:
            InvalidOperationError: If quests not complete or already claimed
        
        Example:
            >>> async with DatabaseService.get_transaction() as session:
            ...     result = await DailyService.claim_rewards(session, player_id)
            ...     print(f"Claimed {result['rewards']['rikis']:,} rikis!")
        """
        daily_quest = await DailyService.get_or_create_daily_quest(session, player_id)
    
        if not daily_quest.is_complete():
            raise InvalidOperationError(
                f"Cannot claim rewards - only {daily_quest.get_completion_count()}/5 quests complete"
            )
        
        if daily_quest.rewards_claimed:
            raise InvalidOperationError("Rewards already claimed for today")
        
        player = await session.get(Player, player_id, with_for_update=True)
        if not player:
            raise InvalidOperationError(f"Player {player_id} not found")
        
        # --- Compute rewards ---
        rewards = DailyService.calculate_rewards(daily_quest)
        xp_amount = rewards.pop("xp", 0)  # Handle XP separately via PlayerService

        # --- Grant currencies & items using ResourceService ---
        grant_result = await ResourceService.grant_resources(
            session=session,
            player=player,
            resources=rewards,
            source="daily_rewards_claimed",
            apply_modifiers=True,
            context={
                "streak": daily_quest.bonus_streak,
                "quests_completed": daily_quest.get_completion_count()
            }
        )

        # --- Handle XP and level-up via PlayerService ---
        from src.services.player_service import PlayerService
        level_up_result = await PlayerService.add_xp_and_level_up(
            player,
            xp_amount,
            allow_overcap=True
        )

        daily_quest.rewards_claimed = True

        # --- Log transaction ---
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type="daily_rewards_claimed",
            details={
                "rewards": grant_result["granted"],
                "xp": xp_amount,
                "modifiers_applied": grant_result.get("modifiers_applied"),
                "streak": daily_quest.bonus_streak,
                "leveled_up": level_up_result["leveled_up"],
                "levels_gained": level_up_result["levels_gained"]
            },
            context="daily_command"
        )

        player.stats["daily_rewards_claimed"] = player.stats.get("daily_rewards_claimed", 0) + 1

        logger.info(
            f"Player {player_id} claimed daily rewards via ResourceService: "
            f"{grant_result['granted']} + {xp_amount} XP (streak {daily_quest.bonus_streak})"
        )

        return {
            "rewards": grant_result["granted"],
            "modifiers_applied": grant_result["modifiers_applied"],
            "leveled_up": level_up_result["leveled_up"],
            "new_level": player.level,
            "levels_gained": level_up_result["levels_gained"],
            "streak": daily_quest.bonus_streak,
            "milestone_rewards": level_up_result.get("milestone_rewards", {})
        }
    
    @staticmethod
    async def get_quest_status(
        session: AsyncSession,
        player_id: int
    ) -> Dict[str, Any]:
        """
        Get current daily quest status with progress details.
        
        Returns:
            Dictionary with:
                - quest_date (date): Today's date
                - quests_completed (dict): Completion flags
                - quest_progress (dict): Progress counters
                - completion_count (int): Number completed
                - completion_percent (float): Percentage complete
                - rewards_claimed (bool): Whether rewards taken
                - streak (int): Current streak
                - projected_rewards (dict): Rewards if claimed now
        
        Example:
            >>> status = await DailyService.get_quest_status(session, player_id)
            >>> print(f"Progress: {status['completion_percent']:.1f}%")
        """
        daily_quest = await DailyService.get_or_create_daily_quest(session, player_id)
        
        projected_rewards = None
        if daily_quest.is_complete() and not daily_quest.rewards_claimed:
            projected_rewards = DailyService.calculate_rewards(daily_quest)
        
        requirements = {
            "prayer_required": ConfigManager.get("daily_quests.prayer_required", 1),
            "summon_required": ConfigManager.get("daily_quests.summon_required", 1),
            "fusion_required": ConfigManager.get("daily_quests.fusion_required", 1),
            "energy_required": ConfigManager.get("daily_quests.energy_required", 10),
            "stamina_required": ConfigManager.get("daily_quests.stamina_required", 5)
        }
        
        return {
            "quest_date": daily_quest.quest_date,
            "quests_completed": daily_quest.quests_completed.copy(),
            "quest_progress": daily_quest.quest_progress.copy(),
            "requirements": requirements,
            "completion_count": daily_quest.get_completion_count(),
            "completion_percent": daily_quest.get_completion_percent(),
            "rewards_claimed": daily_quest.rewards_claimed,
            "streak": daily_quest.bonus_streak,
            "projected_rewards": projected_rewards
        }