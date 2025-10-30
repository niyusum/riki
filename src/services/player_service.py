from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import math

from src.database.models.player import Player
from src.services.config_manager import ConfigManager
from src.services.transaction_logger import TransactionLogger
from src.config import Config
from src.exceptions import InsufficientResourcesError
from src.services.logger import get_logger

logger = get_logger(__name__)


class PlayerService:
    """
    Core service for player operations and resource management.
    
    Handles player lifecycle, resource regeneration, experience/leveling,
    prayer system, and activity tracking. All player state changes must
    go through this service (RIKI LAW Article I.7).
    
    Key Responsibilities:
        - Resource regeneration (energy, stamina, prayer charges)
        - Experience and leveling with milestone rewards
        - Prayer system with class bonuses
        - Activity tracking and scoring
    
    Usage:
        >>> async with DatabaseService.get_transaction() as session:
        ...     player = await PlayerService.get_player_with_regen(
        ...         session, discord_id, lock=True
        ...     )
        ...     result = await PlayerService.perform_prayer(session, player)
    """
    
    @staticmethod
    async def get_player_with_regen(
        session: AsyncSession,
        discord_id: int,
        lock: bool = True
    ) -> Optional[Player]:
        """
        Get player and regenerate all resources automatically.
        
        Regenerates energy, stamina, and prayer charges based on time elapsed
        since last activity. Updates last_active timestamp.
        
        Args:
            session: Database session
            discord_id: Player's Discord ID
            lock: Whether to use SELECT FOR UPDATE (required for writes)
        
        Returns:
            Player object with regenerated resources, or None if not found
        
        Example:
            >>> player = await PlayerService.get_player_with_regen(
            ...     session, discord_id, lock=True
            ... )
            >>> # Player's energy/stamina/prayer_charges are now up-to-date
        """
        if lock:
            player = await session.get(Player, discord_id, with_for_update=True)
        else:
            result = await session.execute(
                select(Player).where(Player.discord_id == discord_id)
            )
            player = result.scalar_one_or_none()
        
        if not player:
            return None
        
        PlayerService.regenerate_all_resources(player)
        player.update_activity()
        
        return player
    
    @staticmethod
    def regenerate_all_resources(player: Player) -> Dict[str, Any]:
        """
        Regenerate energy, stamina, and prayer charges based on time elapsed.
        
        Modifies player object directly. Does NOT commit to database.
        
        Args:
            player: Player object to regenerate resources for
        
        Returns:
            Dictionary with regeneration details:
                - prayer_charges_gained
                - energy_gained
                - stamina_gained
                - total_regenerated
        """
        prayer_regen = PlayerService.regenerate_prayer_charges(player)
        energy_regen = PlayerService.regenerate_energy(player)
        stamina_regen = PlayerService.regenerate_stamina(player)
        
        return {
            "prayer_charges_gained": prayer_regen,
            "energy_gained": energy_regen,
            "stamina_gained": stamina_regen,
            "total_regenerated": prayer_regen + energy_regen + stamina_regen,
        }
    
    @staticmethod
    def regenerate_prayer_charges(player: Player) -> int:
        """
        Regenerate prayer charges based on time since last regen.
        
        Default: 1 charge per 5 minutes (configurable).
        Modifies player.prayer_charges and player.last_prayer_regen.
        
        Args:
            player: Player object
        
        Returns:
            Number of charges regenerated
        """
        if player.prayer_charges >= player.max_prayer_charges:
            return 0
        
        if player.last_prayer_regen is None:
            player.last_prayer_regen = datetime.utcnow()
            return 0
        
        regen_interval = ConfigManager.get("prayer_system.regen_minutes", 5) * 60
        time_since = (datetime.utcnow() - player.last_prayer_regen).total_seconds()
        charges_to_regen = int(time_since // regen_interval)
        
        if charges_to_regen > 0:
            charges_regenerated = min(
                charges_to_regen,
                player.max_prayer_charges - player.prayer_charges
            )
            player.prayer_charges += charges_regenerated
            player.last_prayer_regen += timedelta(seconds=regen_interval * charges_to_regen)
            return charges_regenerated
        
        return 0
    
    @staticmethod
    def regenerate_energy(player: Player) -> int:
        """
        Regenerate energy based on time since last activity.
        
        Default: 1 energy per 5 minutes.
        Adapter class: 25% faster (3.75 minutes).
        Modifies player.energy directly.
        
        Args:
            player: Player object
        
        Returns:
            Amount of energy regenerated
        """
        if player.energy >= player.max_energy:
            return 0
        
        regen_minutes = ConfigManager.get("energy_system.regen_minutes", 5)
        if player.player_class == "adapter":
            regen_minutes = regen_minutes * 0.75
        
        regen_interval = regen_minutes * 60
        time_since = (datetime.utcnow() - player.last_active).total_seconds()
        energy_to_regen = int(time_since // regen_interval)
        
        if energy_to_regen > 0:
            energy_regenerated = min(energy_to_regen, player.max_energy - player.energy)
            player.energy += energy_regenerated
            return energy_regenerated
        
        return 0
    
    @staticmethod
    def regenerate_stamina(player: Player) -> int:
        """
        Regenerate stamina based on time since last activity.
        
        Default: 1 stamina per 10 minutes.
        Destroyer class: 25% faster (7.5 minutes).
        Modifies player.stamina directly.
        
        Args:
            player: Player object
        
        Returns:
            Amount of stamina regenerated
        """
        if player.stamina >= player.max_stamina:
            return 0
        
        regen_minutes = ConfigManager.get("stamina_system.regen_minutes", 10)
        if player.player_class == "destroyer":
            regen_minutes = regen_minutes * 0.75
        
        regen_interval = regen_minutes * 60
        time_since = (datetime.utcnow() - player.last_active).total_seconds()
        stamina_to_regen = int(time_since // regen_interval)
        
        if stamina_to_regen > 0:
            stamina_regenerated = min(stamina_to_regen, player.max_stamina - player.stamina)
            player.stamina += stamina_regenerated
            return stamina_regenerated
        
        return 0
    
    @staticmethod
    async def perform_prayer(
        session: AsyncSession,
        player: Player
    ) -> Dict[str, Any]:
        """
        Execute prayer action, consuming 1 charge and granting grace.
        
        Grace amount affected by player class (invoker gets +20%).
        Logs transaction and updates player stats.
        
        Args:
            session: Database session (part of transaction)
            player: Player object (must be locked)
        
        Returns:
            Dictionary with prayer results:
                - grace_gained
                - total_grace
                - charges_remaining
                - next_charge_in
        
        Raises:
            InsufficientResourcesError: If player has no prayer charges
        
        Example:
            >>> result = await PlayerService.perform_prayer(session, player)
            >>> print(f"Gained {result['grace_gained']} grace!")
        """
        if player.prayer_charges <= 0:
            raise InsufficientResourcesError(
                resource="prayer_charges",
                required=1,
                current=0
            )
        
        old_charges = player.prayer_charges
        player.prayer_charges -= 1
        
        if player.prayer_charges == player.max_prayer_charges - 1 and player.last_prayer_regen is None:
            player.last_prayer_regen = datetime.utcnow()
        
        base_grace = ConfigManager.get("prayer_system.grace_per_prayer", 5)
        class_bonuses = ConfigManager.get("prayer_system.class_bonuses", {})
        
        multiplier = 1.0
        if player.player_class:
            multiplier = class_bonuses.get(player.player_class, 1.0)
        
        grace_gained = int(base_grace * multiplier)
        old_grace = player.grace
        player.grace += grace_gained
        
        player.stats["prayers_performed"] = player.stats.get("prayers_performed", 0) + 1
        
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player.discord_id,
            transaction_type="prayer_performed",
            details={
                "grace_gained": grace_gained,
                "old_grace": old_grace,
                "new_grace": player.grace,
                "old_charges": old_charges,
                "new_charges": player.prayer_charges,
                "class_bonus": multiplier
            },
            context="prayer_command"
        )
        
        return {
            "grace_gained": grace_gained,
            "total_grace": player.grace,
            "charges_remaining": player.prayer_charges,
            "next_charge_in": player.get_prayer_regen_display()
        }
    
    @staticmethod
    def get_xp_for_next_level(level: int) -> int:
        """
        Calculate XP required to reach next level.
        
        Supports multiple curve types (exponential, polynomial, logarithmic)
        configured via ConfigManager.
        
        Args:
            level: Current level
        
        Returns:
            XP required for next level
        
        Example:
            >>> PlayerService.get_xp_for_next_level(1)
            50
            >>> PlayerService.get_xp_for_next_level(10)
            1585
        """
        curve_config = ConfigManager.get("xp_curve", {})
        curve_type = curve_config.get("type", "polynomial")
        base = curve_config.get("base", 50)
        exponent = curve_config.get("exponent", 2.2)
        
        if curve_type == "exponential":
            return int(base * (1.5 ** (level - 1)))
        elif curve_type == "polynomial":
            return int(base * (level ** exponent))
        elif curve_type == "logarithmic":
            return int(500 * level * math.log(level + 1))
        else:
            return int(base * (1.5 ** (level - 1)))
    
    @staticmethod
    async def add_xp_and_level_up(
        player: Player,
        xp_amount: int,
        allow_overcap: bool = True
    ) -> Dict[str, Any]:
        """
        Award experience and handle automatic level-ups.
        
        Grants XP and automatically levels up player if threshold exceeded.
        Handles milestone rewards (every 5/10 levels) and resource refresh.
        Can grant bonus energy/stamina if near-full (overcap system).
        
        Args:
            player: Player object (must be locked)
            xp_amount: Amount of XP to award
            allow_overcap: If True, grant 10% bonus energy/stamina when near-full
        
        Returns:
            Dictionary containing:
                - leveled_up (bool): Whether player gained levels
                - levels_gained (int): Number of levels gained
                - new_level (int): Player's level after XP gain
                - refreshed_resources (bool): Whether energy/stamina refreshed
                - overcap_energy (int): Bonus energy granted
                - overcap_stamina (int): Bonus stamina granted
                - milestone_rewards (dict): Rewards from milestone levels
                - safety_cap_hit (bool): Whether max loop limit hit (indicates bug)
        
        Example:
            >>> result = await PlayerService.add_xp_and_level_up(player, 500)
            >>> if result["leveled_up"]:
            ...     print(f"Leveled up to {result['new_level']}!")
        """
        player.experience += xp_amount
        leveled_up = False
        levels_gained = 0
        overcap_energy = 0
        overcap_stamina = 0
        milestone_rewards = {}
        
        loop_safety = 0
        max_loops = Config.MAX_LEVEL_UPS_PER_TRANSACTION
        
        milestones_config = ConfigManager.get("level_milestones", {})
        minor_interval = milestones_config.get("minor_interval", 5)
        major_interval = milestones_config.get("major_interval", 10)
        minor_rewards_config = milestones_config.get("minor_rewards", {})
        major_rewards_config = milestones_config.get("major_rewards", {})
        
        while player.experience >= PlayerService.get_xp_for_next_level(player.level):
            loop_safety += 1
            if loop_safety > max_loops:
                logger.error(
                    f"XP loop safety cap hit for player {player.discord_id} at level {player.level}. "
                    f"Check XP curve configuration."
                )
                break
            
            xp_needed = PlayerService.get_xp_for_next_level(player.level)
            player.experience -= xp_needed
            player.level += 1
            levels_gained += 1
            leveled_up = True
            
            player.last_level_up = datetime.utcnow()
            player.stats["level_ups"] = player.stats.get("level_ups", 0) + 1
            
            if allow_overcap:
                old_energy = player.energy
                old_stamina = player.stamina
                
                player.energy = player.max_energy
                player.stamina = player.max_stamina
                
                overflow_bonus = ConfigManager.get("energy_system.overcap_bonus", 0.10)
                
                if old_energy >= player.max_energy * 0.9:
                    overcap_energy = int(player.max_energy * overflow_bonus)
                    player.energy += overcap_energy
                    player.stats["overflow_energy_gained"] = \
                        player.stats.get("overflow_energy_gained", 0) + overcap_energy
                
                if old_stamina >= player.max_stamina * 0.9:
                    overcap_stamina = int(player.max_stamina * overflow_bonus)
                    player.stamina += overcap_stamina
                    player.stats["overflow_stamina_gained"] = \
                        player.stats.get("overflow_stamina_gained", 0) + overcap_stamina
            else:
                player.energy = player.max_energy
                player.stamina = player.max_stamina
            
            if player.level % minor_interval == 0:
                rikis_mult = minor_rewards_config.get("rikis_multiplier", 100)
                grace_amt = minor_rewards_config.get("grace", 5)
                gems_div = minor_rewards_config.get("gems_divisor", 10)
                
                milestone_rewards[f"level_{player.level}"] = {
                    "rikis": player.level * rikis_mult,
                    "grace": grace_amt,
                    "riki_gems": player.level // gems_div
                }
            
            if player.level % major_interval == 0:
                rikis_mult = major_rewards_config.get("rikis_multiplier", 500)
                grace_amt = major_rewards_config.get("grace", 10)
                gems_amt = major_rewards_config.get("gems", 5)
                energy_inc = major_rewards_config.get("max_energy_increase", 10)
                stamina_inc = major_rewards_config.get("max_stamina_increase", 5)
                
                milestone_rewards[f"level_{player.level}_major"] = {
                    "rikis": player.level * rikis_mult,
                    "grace": grace_amt,
                    "riki_gems": gems_amt,
                    "max_energy_increase": energy_inc,
                    "max_stamina_increase": stamina_inc
                }
        
        return {
            "leveled_up": leveled_up,
            "levels_gained": levels_gained,
            "new_level": player.level,
            "refreshed_resources": leveled_up,
            "overcap_energy": overcap_energy,
            "overcap_stamina": overcap_stamina,
            "milestone_rewards": milestone_rewards,
            "safety_cap_hit": loop_safety > max_loops
        }
    
    @staticmethod
    def can_redeem_shards(player: Player, tier: int) -> bool:
        """Check if player has enough shards for guaranteed fusion at tier."""
        shards_needed = ConfigManager.get("shard_system.shards_for_redemption", 10)
        return player.get_fusion_shards(tier) >= shards_needed
    
    @staticmethod
    def calculate_activity_score(player: Player) -> float:
        """
        Calculate player activity score (0-100) based on recent engagement.
        
        Factors:
            - Time since last active (up to 40 points)
            - Player level (up to 20 points)
            - Total fusions (up to 20 points)
            - Unique maidens owned (up to 20 points)
        
        Args:
            player: Player object
        
        Returns:
            Activity score between 0-100
        """
        score = 0
        
        time_since_active = datetime.utcnow() - player.last_active
        if time_since_active < timedelta(hours=1):
            score += 40
        elif time_since_active < timedelta(days=1):
            score += 30
        elif time_since_active < timedelta(days=3):
            score += 20
        elif time_since_active < timedelta(days=7):
            score += 10
        
        score += min(20, player.level)
        
        if player.total_fusions > 100:
            score += 20
        elif player.total_fusions > 50:
            score += 15
        elif player.total_fusions > 10:
            score += 10
        elif player.total_fusions > 0:
            score += 5
        
        score += min(20, player.unique_maidens)
        
        return min(100, score)
    
    @staticmethod
    def calculate_days_since_level_up(player: Player) -> Optional[int]:
        """
        Calculate days since player's last level-up.
        
        Returns None if player has never leveled up.
        """
        if player.last_level_up is None:
            return None
        delta = datetime.utcnow() - player.last_level_up
        return delta.days