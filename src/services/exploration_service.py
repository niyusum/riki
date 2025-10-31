from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import random

from src.database.models.player import Player
from src.database.models.sector_progress import SectorProgress
from src.services.config_manager import ConfigManager
from src.services.resource_service import ResourceService
from src.services.transaction_logger import TransactionLogger
from src.exceptions import InsufficientResourcesError, InvalidOperationError
from src.services.logger import get_logger

logger = get_logger(__name__)


class ExplorationService:
    """
    Sector exploration system with percentage-based progression.
    
    Manages sector/sublevel progression, maiden purification encounters,
    miniboss battles, and exploration rewards. Integrates with ResourceService
    for energy consumption and reward distribution.
    
    Features:
        - 7 sectors with 9 sublevels each
        - Dynamic progress rates (fast early, slow late)
        - Random maiden encounters with capture mechanics
        - Miniboss gates at 100% progress
        - Branching sector unlocks
    
    Usage:
        >>> result = await ExplorationService.explore_sublevel(session, player, sector_id=1, sublevel=1)
        >>> if result["maiden_encounter"]:
        >>>     success = await ExplorationService.attempt_purification(session, player, maiden_data, use_gems=False)
    """
    
    @staticmethod
    async def get_or_create_progress(
        session: AsyncSession,
        player_id: int,
        sector_id: int,
        sublevel: int
    ) -> SectorProgress:
        """
        Get existing progress or create new record for sector/sublevel.
        
        Args:
            session: Database session
            player_id: Discord ID
            sector_id: Sector number (1-7)
            sublevel: Sublevel number (1-9)
        
        Returns:
            SectorProgress record
        """
        result = await session.execute(
            select(SectorProgress).where(
                SectorProgress.player_id == player_id,
                SectorProgress.sector_id == sector_id,
                SectorProgress.sublevel == sublevel
            )
        )
        progress = result.scalar_one_or_none()
        
        if not progress:
            progress = SectorProgress(
                player_id=player_id,
                sector_id=sector_id,
                sublevel=sublevel
            )
            session.add(progress)
            await session.flush()
            logger.info(f"Created sector progress for player {player_id}: sector {sector_id}, sublevel {sublevel}")
        
        return progress
    
    @staticmethod
    async def get_unlocked_sectors(session: AsyncSession, player_id: int) -> List[int]:
        """
        Get list of sectors player has unlocked.
        
        Sector 1 always unlocked. Higher sectors require previous sector 100% completion.
        
        Returns:
            List of unlocked sector IDs
        """
        result = await session.execute(
            select(SectorProgress).where(
                SectorProgress.player_id == player_id
            )
        )
        all_progress = result.scalars().all()
        
        unlocked = [1]  # Sector 1 always available
        
        # Check each sector for completion
        for sector_id in range(2, 8):  # Check sectors 2-7
            previous_sector = sector_id - 1
            
            # Get all sublevels for previous sector
            prev_sector_progress = [
                p for p in all_progress 
                if p.sector_id == previous_sector
            ]
            
            # Need all 9 sublevels completed
            if len(prev_sector_progress) == 9:
                all_complete = all(p.is_complete() for p in prev_sector_progress)
                if all_complete:
                    unlocked.append(sector_id)
                else:
                    break  # Stop checking higher sectors
            else:
                break  # Stop checking higher sectors
        
        return unlocked
    
    @staticmethod
    def calculate_energy_cost(sector_id: int, sublevel: int) -> int:
        """
        Calculate energy cost for exploring specific sublevel.
        
        Cost increases per sector and per sublevel within sector.
        Boss sublevels (9) cost more.
        
        Returns:
            Energy cost
        """
        base_cost = ConfigManager.get(f"exploration_system.energy_costs.sector_{sector_id}_base", 5)
        increment = ConfigManager.get("exploration_system.energy_costs.sublevel_increment", 1)
        boss_mult = ConfigManager.get("exploration_system.energy_costs.boss_multiplier", 1.5)
        
        cost = base_cost + (increment * (sublevel - 1))
        
        if sublevel == 9:
            cost = int(cost * boss_mult)
        
        return cost
    
    @staticmethod
    def calculate_progress_gain(sector_id: int, sublevel: int) -> float:
        """
        Calculate progress percentage gained per exploration.
        
        Early sectors progress faster. Miniboss sublevels progress slower.
        
        Returns:
            Progress percentage (0.0 - 100.0)
        """
        base_rate = ConfigManager.get(f"exploration_system.progress_rates.sector_{sector_id}", 3.0)
        miniboss_mult = ConfigManager.get("exploration_system.miniboss_progress_multiplier", 0.5)
        
        if sublevel == 9:
            return base_rate * miniboss_mult
        
        return base_rate
    
    @staticmethod
    def calculate_rewards(sector_id: int, sublevel: int) -> Dict[str, int]:
        """
        Calculate rikis and XP rewards for exploration.
        
        Scales with sector difficulty.
        
        Returns:
            Dictionary with 'rikis' and 'xp' keys
        """
        # Riki rewards
        riki_min = ConfigManager.get("exploration_system.riki_rewards.sector_1_min", 50)
        riki_max = ConfigManager.get("exploration_system.riki_rewards.sector_1_max", 100)
        riki_scaling = ConfigManager.get("exploration_system.riki_rewards.sector_scaling", 1.5)
        
        scaled_riki_min = int(riki_min * (riki_scaling ** (sector_id - 1)))
        scaled_riki_max = int(riki_max * (riki_scaling ** (sector_id - 1)))
        rikis = random.randint(scaled_riki_min, scaled_riki_max)
        
        # XP rewards
        xp_min = ConfigManager.get("exploration_system.xp_rewards.sector_1_min", 10)
        xp_max = ConfigManager.get("exploration_system.xp_rewards.sector_1_max", 30)
        xp_scaling = ConfigManager.get("exploration_system.xp_rewards.sector_scaling", 1.5)
        
        scaled_xp_min = int(xp_min * (xp_scaling ** (sector_id - 1)))
        scaled_xp_max = int(xp_max * (xp_scaling ** (sector_id - 1)))
        xp = random.randint(scaled_xp_min, scaled_xp_max)
        
        return {"rikis": rikis, "xp": xp}
    
    @staticmethod
    def roll_maiden_encounter(sector_id: int) -> bool:
        """
        Roll for random maiden encounter during exploration.
        
        Higher sectors have higher encounter rates.
        
        Returns:
            True if maiden encountered
        """
        encounter_rate = ConfigManager.get(f"exploration_system.encounter_rates.sector_{sector_id}", 10.0)
        roll = random.random() * 100
        return roll < encounter_rate
    
    @staticmethod
    def generate_encounter_maiden(sector_id: int, player_level: int) -> Dict[str, Any]:
        """
        Generate maiden data for purification encounter.
        
        Rarity and tier based on sector and player level.
        This is a stub - actual maiden generation should use MaidenService.
        
        Returns:
            Dictionary with maiden info for encounter UI
        """
        # TODO: Integrate with actual maiden generation system
        # For now, return placeholder data structure
        
        rarity_pool = {
            1: ["common", "uncommon"],
            2: ["uncommon", "rare"],
            3: ["rare", "epic"],
            4: ["epic", "legendary"],
            5: ["epic", "legendary"],
            6: ["legendary", "mythic"],
            7: ["legendary", "mythic"],
        }
        
        rarities = rarity_pool.get(sector_id, ["common", "uncommon"])
        rarity = random.choice(rarities)
        
        return {
            "name": f"Wild Maiden",  # Placeholder
            "rarity": rarity,
            "element": random.choice(["infernal", "abyssal", "tempest", "earth", "radiant", "umbral"]),
            "tier": min(player_level // 5 + 1, 11),
            "sector_id": sector_id,
        }
    
    @staticmethod
    def calculate_capture_rate(maiden_rarity: str, player_level: int, sector_id: int) -> float:
        """
        Calculate purification success rate.
        
        Base rate by rarity, modified by player level vs sector difficulty.
        
        Returns:
            Capture rate percentage (0.0 - 100.0)
        """
        base_rate = ConfigManager.get(f"exploration_system.capture_rates.{maiden_rarity}", 30.0)
        level_modifier_per_level = ConfigManager.get("exploration_system.capture_level_modifier", 2.0)
        
        # Player level advantage
        sector_recommended_level = sector_id * 10  # Rough estimate
        level_diff = player_level - sector_recommended_level
        level_bonus = level_diff * level_modifier_per_level
        
        final_rate = base_rate + level_bonus
        return max(5.0, min(95.0, final_rate))  # Clamp 5-95%
    
    @staticmethod
    def get_guaranteed_purification_cost(maiden_rarity: str) -> int:
        """
        Get gem cost for guaranteed maiden purification.
        
        Returns:
            Gem cost
        """
        return ConfigManager.get(f"exploration_system.guaranteed_purification_costs.{maiden_rarity}", 100)
    
    @staticmethod
    async def explore_sublevel(
        session: AsyncSession,
        player: Player,
        sector_id: int,
        sublevel: int
    ) -> Dict[str, Any]:
        """
        Process single exploration attempt in sector sublevel.
        
        Consumes energy, grants rewards, adds progress, rolls for encounters.
        Does NOT trigger miniboss automatically - that's a separate command.
        
        Args:
            session: Database session
            player: Player object (with_for_update=True)
            sector_id: Target sector
            sublevel: Target sublevel
        
        Returns:
            Dictionary with:
                - energy_cost: Energy consumed
                - rikis_gained: Rikis rewarded
                - xp_gained: XP rewarded
                - progress_gained: Progress % added
                - current_progress: New progress %
                - maiden_encounter: Maiden data dict if encountered, else None
                - miniboss_ready: True if progress hit 100%
        
        Raises:
            InsufficientResourcesError: Not enough energy
            InvalidOperationError: Sector/sublevel not unlocked or already complete
        """
        # Validate unlock status
        unlocked_sectors = await ExplorationService.get_unlocked_sectors(session, player.discord_id)
        if sector_id not in unlocked_sectors:
            raise InvalidOperationError(f"Sector {sector_id} is not unlocked")
        
        # Get progress
        progress = await ExplorationService.get_or_create_progress(
            session, player.discord_id, sector_id, sublevel
        )
        
        # Check if already complete
        if progress.is_complete():
            raise InvalidOperationError(f"Sector {sector_id}, Sublevel {sublevel} is already complete")
        
        # Calculate costs and rewards
        energy_cost = ExplorationService.calculate_energy_cost(sector_id, sublevel)
        
        # Validate energy
        if player.energy < energy_cost:
            raise InsufficientResourcesError(
                resource="energy",
                required=energy_cost,
                current=player.energy
            )
        
        # Consume energy
        player.energy -= energy_cost
        
        # Calculate rewards
        rewards = ExplorationService.calculate_rewards(sector_id, sublevel)
        
        # Grant rewards via ResourceService
        await ResourceService.grant_resources(
            session=session,
            player=player,
            rikis=rewards["rikis"],
            context="exploration",
            details={"sector": sector_id, "sublevel": sublevel}
        )
        
        # Add progress
        progress_gain = ExplorationService.calculate_progress_gain(sector_id, sublevel)
        progress.progress = min(100.0, progress.progress + progress_gain)
        progress.times_explored += 1
        progress.total_rikis_earned += rewards["rikis"]
        progress.total_xp_earned += rewards["xp"]
        progress.last_explored = datetime.utcnow()
        
        # Roll for maiden encounter (only if not at 100% yet)
        maiden_encounter = None
        if progress.progress < 100.0:
            if ExplorationService.roll_maiden_encounter(sector_id):
                maiden_encounter = ExplorationService.generate_encounter_maiden(sector_id, player.level)
        
        # Update daily quest
        from src.services.daily_service import DailyService
        await DailyService.update_quest_progress(
            session, player.discord_id, "spend_energy", energy_cost
        )
        
        # Log transaction
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player.discord_id,
            transaction_type="exploration",
            details={
                "sector": sector_id,
                "sublevel": sublevel,
                "energy_cost": energy_cost,
                "rikis": rewards["rikis"],
                "xp": rewards["xp"],
                "progress_gain": progress_gain,
                "new_progress": progress.progress,
                "maiden_encountered": maiden_encounter is not None
            },
            context="explore_command"
        )
        
        logger.info(
            f"Player {player.discord_id} explored sector {sector_id} sublevel {sublevel}: "
            f"+{progress_gain:.1f}% progress (now {progress.progress:.1f}%), "
            f"+{rewards['rikis']} rikis, encounter={maiden_encounter is not None}"
        )
        
        await session.flush()
        
        return {
            "energy_cost": energy_cost,
            "rikis_gained": rewards["rikis"],
            "xp_gained": rewards["xp"],
            "progress_gained": progress_gain,
            "current_progress": progress.progress,
            "maiden_encounter": maiden_encounter,
            "miniboss_ready": progress.progress >= 100.0 and not progress.miniboss_defeated
        }
    
    @staticmethod
    async def attempt_purification(
        session: AsyncSession,
        player: Player,
        maiden_data: Dict[str, Any],
        use_gems: bool = False
    ) -> Dict[str, Any]:
        """
        Attempt to purify encountered maiden.
        
        Either RNG-based capture or guaranteed with gems.
        
        Args:
            session: Database session
            player: Player object (with_for_update=True)
            maiden_data: Maiden info from encounter
            use_gems: If True, use gems for guaranteed capture
        
        Returns:
            Dictionary with:
                - success: Whether purification succeeded
                - capture_rate: Roll percentage (if RNG)
                - gem_cost: Gems spent (if guaranteed)
                - maiden_data: Full maiden info
        
        Raises:
            InsufficientResourcesError: Not enough gems for guaranteed
        """
        rarity = maiden_data["rarity"]
        
        if use_gems:
            # Guaranteed purification
            gem_cost = ExplorationService.get_guaranteed_purification_cost(rarity)
            
            if player.riki_gems < gem_cost:
                raise InsufficientResourcesError(
                    resource="riki_gems",
                    required=gem_cost,
                    current=player.riki_gems
                )
            
            player.riki_gems -= gem_cost
            success = True
            
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type="purification_guaranteed",
                details={
                    "maiden": maiden_data,
                    "gem_cost": gem_cost
                },
                context="purify_command"
            )
            
            logger.info(f"Player {player.discord_id} used {gem_cost} gems for guaranteed purification ({rarity})")
            
            return {
                "success": True,
                "capture_rate": 100.0,
                "gem_cost": gem_cost,
                "maiden_data": maiden_data
            }
        
        else:
            # RNG-based purification
            capture_rate = ExplorationService.calculate_capture_rate(
                rarity, player.level, maiden_data["sector_id"]
            )
            
            roll = random.random() * 100
            success = roll < capture_rate
            
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type="purification_attempt",
                details={
                    "maiden": maiden_data,
                    "capture_rate": capture_rate,
                    "roll": roll,
                    "success": success
                },
                context="purify_command"
            )
            
            logger.info(
                f"Player {player.discord_id} purification attempt: "
                f"{capture_rate:.1f}% rate, roll {roll:.1f}, success={success}"
            )
            
            return {
                "success": success,
                "capture_rate": capture_rate,
                "gem_cost": 0,
                "maiden_data": maiden_data
            }