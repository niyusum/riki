from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import random
import math

from src.database.models.player import Player
from src.database.models.ascension_progress import AscensionProgress
from src.services.config_manager import ConfigManager
from src.services.resource_service import ResourceService
from src.services.transaction_logger import TransactionLogger
from src.exceptions import InsufficientResourcesError, InvalidOperationError
from src.services.logger import get_logger

logger = get_logger(__name__)


class AscensionService:
    """
    Infinite tower climbing system with exponentially scaling difficulty.
    
    Players use collective maiden power to climb floors, earning rewards
    at each level. Stamina cost increases with player level. Checkpoints
    at each completed floor.
    
    Features:
        - Exponential HP scaling (never trivial)
        - Dynamic stamina costs
        - x1/x5/x20 attack options
        - Milestone rewards every 50 floors
        - Leaderboard tracking
    
    Usage:
        >>> progress = await AscensionService.get_or_create_progress(session, player_id)
        >>> enemy = AscensionService.generate_floor_enemy(progress.get_next_floor())
        >>> result = await AscensionService.resolve_combat(session, player, floor, damage_dealt, attacks_used)
    """
    
    @staticmethod
    async def get_or_create_progress(session: AsyncSession, player_id: int) -> AscensionProgress:
        """
        Get existing ascension progress or create new record.
        
        Args:
            session: Database session
            player_id: Discord ID
        
        Returns:
            AscensionProgress record
        """
        result = await session.execute(
            select(AscensionProgress).where(AscensionProgress.player_id == player_id)
        )
        progress = result.scalar_one_or_none()
        
        if not progress:
            progress = AscensionProgress(player_id=player_id)
            session.add(progress)
            await session.flush()
            logger.info(f"Created ascension progress for player {player_id}")
        
        return progress
    
    @staticmethod
    def calculate_stamina_cost(player_level: int) -> int:
        """
        Calculate stamina cost for floor attempt.
        
        Base cost + 1 per 10 player levels.
        
        Args:
            player_level: Player's current level
        
        Returns:
            Stamina cost
        """
        base_cost = ConfigManager.get("ascension_system.base_stamina_cost", 5)
        increase_per_10 = ConfigManager.get("ascension_system.stamina_increase_per_10_levels", 1)
        
        additional_cost = (player_level // 10) * increase_per_10
        return base_cost + additional_cost
    
    @staticmethod
    def generate_floor_enemy(floor: int) -> Dict[str, Any]:
        """
        Generate enemy stats for specific floor.
        
        HP scales exponentially to always remain challenging.
        
        Args:
            floor: Floor number (1+)
        
        Returns:
            Dictionary with enemy name, HP, rewards
        """
        base_hp = ConfigManager.get("ascension_system.enemy_hp_base", 1000)
        growth_rate = ConfigManager.get("ascension_system.enemy_hp_growth_rate", 1.12)
        
        hp = int(base_hp * (growth_rate ** floor))
        
        # Generate thematic name
        name = AscensionService._generate_enemy_name(floor)
        
        # Calculate rewards
        rewards = AscensionService._calculate_floor_rewards(floor)
        
        return {
            "name": name,
            "hp": hp,
            "floor": floor,
            "rewards": rewards,
        }
    
    @staticmethod
    def _generate_enemy_name(floor: int) -> str:
        """Generate thematic enemy name based on floor tier."""
        if floor <= 10:
            prefixes = ["Lesser", "Minor", "Weak"]
        elif floor <= 50:
            prefixes = ["Guardian", "Sentinel", "Watcher"]
        elif floor <= 100:
            prefixes = ["Elite", "Champion", "Veteran"]
        elif floor <= 200:
            prefixes = ["Ascended", "Exalted", "Divine"]
        else:
            prefixes = ["Transcendent", "Eternal", "Absolute"]
        
        types = ["Warrior", "Mage", "Beast", "Construct", "Wraith"]
        
        prefix = random.choice(prefixes)
        enemy_type = random.choice(types)
        
        if floor % 50 == 0:
            return f"Floor {floor} Guardian"
        
        return f"{prefix} {enemy_type}"
    
    @staticmethod
    def _calculate_floor_rewards(floor: int) -> Dict[str, Any]:
        """
        Calculate rewards for clearing specific floor.
        
        Base rewards scale exponentially. Bonus rewards at intervals.
        
        Returns:
            Dictionary with rikis, xp, and optional bonus items
        """
        base_rikis = ConfigManager.get("ascension_system.reward_base_rikis", 50)
        base_xp = ConfigManager.get("ascension_system.reward_base_xp", 20)
        growth_rate = ConfigManager.get("ascension_system.reward_growth_rate", 1.1)
        
        rikis = int(base_rikis * (growth_rate ** floor))
        xp = int(base_xp * (growth_rate ** floor))
        
        rewards = {
            "rikis": rikis,
            "xp": xp,
        }
        
        # Bonus rewards at intervals
        bonus_intervals = ConfigManager.get("ascension_system.bonus_intervals", {})
        
        egg_interval = bonus_intervals.get("egg_every_n_floors", 5)
        if floor % egg_interval == 0:
            rewards["maiden_egg"] = {
                "rarity": AscensionService._get_egg_rarity_for_floor(floor),
                "element": "random"
            }
        
        prayer_interval = bonus_intervals.get("prayer_charge_every_n_floors", 10)
        if floor % prayer_interval == 0:
            rewards["prayer_charges"] = 1
        
        catalyst_interval = bonus_intervals.get("fusion_catalyst_every_n_floors", 25)
        if floor % catalyst_interval == 0:
            rewards["fusion_catalyst"] = 1
        
        # Milestone rewards
        milestones = ConfigManager.get("ascension_system.milestones", {})
        if floor in milestones:
            milestone_rewards = milestones[floor]
            rewards["milestone"] = milestone_rewards
        
        return rewards
    
    @staticmethod
    def _get_egg_rarity_for_floor(floor: int) -> str:
        """Determine maiden egg rarity based on floor number."""
        egg_rarity_floors = ConfigManager.get("ascension_system.egg_rarity_floors", {})
        
        for rarity, (min_floor, max_floor) in egg_rarity_floors.items():
            if min_floor <= floor <= max_floor:
                return rarity
        
        return "epic"  # Default fallback
    
    @staticmethod
    def calculate_damage(player_power: int, attack_count: int, is_gem_attack: bool = False) -> int:
        """
        Calculate damage dealt based on player power and attack multiplier.
        
        Gem attacks (x20) get bonus crit damage.
        
        Args:
            player_power: Total ATK from all maidens
            attack_count: Attack multiplier (1, 5, or 20)
            is_gem_attack: Whether this is x20 gem attack
        
        Returns:
            Total damage dealt
        """
        base_damage = player_power * attack_count
        
        if is_gem_attack:
            crit_bonus = ConfigManager.get("ascension_system.x20_attack_crit_bonus", 0.2)
            base_damage = int(base_damage * (1 + crit_bonus))
        
        return base_damage
    
    @staticmethod
    def get_gem_attack_cost() -> int:
        """Get gem cost for x20 attack."""
        return ConfigManager.get("ascension_system.x20_attack_gem_cost", 10)
    
    @staticmethod
    async def attempt_floor(
        session: AsyncSession,
        player: Player,
        player_power: int
    ) -> Dict[str, Any]:
        """
        Initiate floor attempt, consuming stamina.
        
        Returns floor enemy data and validates stamina cost.
        Does NOT resolve combat - that's done via attack actions.
        
        Args:
            session: Database session
            player: Player object (with_for_update=True)
            player_power: Total ATK from maiden collection
        
        Returns:
            Dictionary with:
                - floor: Floor number
                - enemy: Enemy data
                - stamina_cost: Stamina consumed
                - estimated_attacks: Attacks needed estimate
        
        Raises:
            InsufficientResourcesError: Not enough stamina
        """
        progress = await AscensionService.get_or_create_progress(session, player.discord_id)
        
        floor = progress.get_next_floor()
        stamina_cost = AscensionService.calculate_stamina_cost(player.level)
        
        # Validate stamina
        if player.stamina < stamina_cost:
            raise InsufficientResourcesError(
                resource="stamina",
                required=stamina_cost,
                current=player.stamina
            )
        
        # Consume stamina
        player.stamina -= stamina_cost
        
        # Generate enemy
        enemy = AscensionService.generate_floor_enemy(floor)
        
        # Update progress stats
        progress.total_attempts += 1
        progress.last_attempt = datetime.utcnow()
        
        # Estimate attacks needed
        estimated_attacks = math.ceil(enemy["hp"] / player_power) if player_power > 0 else 999
        
        # Update daily quest
        from src.services.daily_service import DailyService
        await DailyService.update_quest_progress(
            session, player.discord_id, "spend_stamina", stamina_cost
        )
        
        await session.flush()
        
        logger.info(
            f"Player {player.discord_id} attempting floor {floor}: "
            f"enemy HP {enemy['hp']}, power {player_power}, est. attacks {estimated_attacks}"
        )
        
        return {
            "floor": floor,
            "enemy": enemy,
            "stamina_cost": stamina_cost,
            "estimated_attacks": estimated_attacks,
        }
    
    @staticmethod
    async def resolve_combat(
        session: AsyncSession,
        player: Player,
        floor: int,
        damage_dealt: int,
        attacks_used: int,
        gems_spent: int = 0
    ) -> Dict[str, Any]:
        """
        Resolve floor combat after player attacks complete.
        
        Updates progress, grants rewards on victory.
        
        Args:
            session: Database session
            player: Player object (with_for_update=True)
            floor: Floor number attempted
            damage_dealt: Total damage player dealt
            attacks_used: Number of attacks made
            gems_spent: Gems consumed for x20 attacks
        
        Returns:
            Dictionary with:
                - victory: True if floor cleared
                - rewards: Rewards granted (if victory)
                - new_floor: Next floor number (if victory)
                - remaining_hp: Enemy HP left (if defeat)
        """
        progress = await AscensionService.get_or_create_progress(session, player.discord_id)
        
        # Generate enemy for validation
        enemy = AscensionService.generate_floor_enemy(floor)
        enemy_hp = enemy["hp"]
        
        victory = damage_dealt >= enemy_hp
        
        if victory:
            # Update progress
            progress.current_floor = floor
            progress.total_floors_cleared += 1
            progress.total_victories += 1
            progress.last_victory = datetime.utcnow()
            
            if floor > progress.highest_floor:
                progress.highest_floor = floor
                
                # Update player global stat
                if floor > player.highest_floor_ascended:
                    player.highest_floor_ascended = floor
            
            # Grant rewards
            rewards = enemy["rewards"]
            
            # Rikis and XP via ResourceService
            await ResourceService.grant_resources(
                session=session,
                player=player,
                rikis=rewards["rikis"],
                context="ascension_victory",
                details={
                    "floor": floor,
                    "enemy": enemy["name"],
                    "attacks_used": attacks_used
                }
            )
            
            # Update progress stats
            progress.total_rikis_earned += rewards["rikis"]
            progress.total_xp_earned += rewards["xp"]
            
            # TODO: Grant maiden eggs, prayer charges, catalysts
            # TODO: Grant milestone rewards
            
            # Log victory
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type="ascension_victory",
                details={
                    "floor": floor,
                    "enemy": enemy,
                    "damage_dealt": damage_dealt,
                    "attacks_used": attacks_used,
                    "gems_spent": gems_spent,
                    "rewards": rewards
                },
                context="ascension_battle"
            )
            
            logger.info(
                f"Player {player.discord_id} cleared floor {floor} in {attacks_used} attacks "
                f"(gems: {gems_spent}, new record: {floor > progress.highest_floor})"
            )
            
            await session.flush()
            
            return {
                "victory": True,
                "rewards": rewards,
                "new_floor": progress.get_next_floor(),
                "remaining_hp": 0,
                "is_record": floor == progress.highest_floor
            }
        
        else:
            # Defeat
            progress.total_defeats += 1
            remaining_hp = enemy_hp - damage_dealt
            
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type="ascension_defeat",
                details={
                    "floor": floor,
                    "enemy": enemy,
                    "damage_dealt": damage_dealt,
                    "attacks_used": attacks_used,
                    "gems_spent": gems_spent,
                    "remaining_hp": remaining_hp
                },
                context="ascension_battle"
            )
            
            logger.info(
                f"Player {player.discord_id} failed floor {floor}: "
                f"{remaining_hp}/{enemy_hp} HP remaining after {attacks_used} attacks"
            )
            
            await session.flush()
            
            return {
                "victory": False,
                "rewards": None,
                "new_floor": None,
                "remaining_hp": remaining_hp,
                "is_record": False
            }
    
    @staticmethod
    def calculate_attacks_needed(player_power: int, enemy_hp: int) -> int:
        """
        Estimate attacks needed to defeat enemy.
        
        Args:
            player_power: Total ATK from all maidens
            enemy_hp: Enemy total HP
        
        Returns:
            Number of attacks needed
        """
        if player_power == 0:
            return 999
        
        return math.ceil(enemy_hp / player_power)