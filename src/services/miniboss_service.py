from datetime import datetime
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
import random
import math

from src.database.models.player import Player
from src.database.models.sector_progress import SectorProgress
from src.services.config_manager import ConfigManager
from src.services.resource_service import ResourceService
from src.services.transaction_logger import TransactionLogger
from src.exceptions import InvalidOperationError
from src.services.logger import get_logger

logger = get_logger(__name__)


class MinibossService:
    """
    Miniboss generation and battle system for sector progression.
    
    Minibosses appear at 100% sublevel progress and must be defeated
    to unlock next sublevel or sector. Non-capturable but grant guaranteed rewards.
    
    Features:
        - Dynamic HP scaling by sector/sublevel
        - Rarity 1-2 tiers above sector average
        - Guaranteed maiden egg drops
        - Bonus rewards for sector bosses (sublevel 9)
    
    Usage:
        >>> miniboss = MinibossService.generate_miniboss(sector_id=1, sublevel=9, player_level=15)
        >>> result = await MinibossService.resolve_battle(session, player, miniboss, attacks_used=6)
    """
    
    @staticmethod
    def generate_miniboss(sector_id: int, sublevel: int, player_level: int) -> Dict[str, Any]:
        """
        Generate miniboss stats for sector sublevel.
        
        Miniboss rarity is 1-2 tiers above sector average.
        HP scales exponentially with sector and sublevel.
        
        Args:
            sector_id: Sector number (1-7)
            sublevel: Sublevel number (1-9)
            player_level: Player's current level
        
        Returns:
            Dictionary with:
                - name: Generated name
                - rarity: Miniboss rarity
                - element: Element type
                - hp: Total HP
                - rewards: Reward dictionary
        """
        # Get sector average rarity
        avg_rarity = ConfigManager.get(f"miniboss_system.sector_avg_rarity.sector_{sector_id}", "uncommon")
        
        # Calculate miniboss rarity (1-2 tiers higher)
        rarity_progression = ["common", "uncommon", "rare", "epic", "legendary", "mythic"]
        avg_index = rarity_progression.index(avg_rarity)
        tier_increase = random.choice(ConfigManager.get("miniboss_system.rarity_tier_increase", [1, 2]))
        miniboss_index = min(avg_index + tier_increase, len(rarity_progression) - 1)
        miniboss_rarity = rarity_progression[miniboss_index]
        
        # Calculate HP
        base_hp = ConfigManager.get(f"miniboss_system.hp_base.{miniboss_rarity}", 5000)
        sector_mult = ConfigManager.get("miniboss_system.hp_sector_multiplier", 0.5)
        sublevel_mult = ConfigManager.get("miniboss_system.hp_sublevel_multiplier", 0.1)
        
        hp_multiplier = 1 + (sector_id * sector_mult) + (sublevel * sublevel_mult)
        final_hp = int(base_hp * hp_multiplier)
        
        # Generate name
        name = MinibossService._generate_name(sector_id, sublevel, miniboss_rarity)
        
        # Calculate rewards
        rewards = MinibossService._calculate_rewards(sector_id, sublevel, miniboss_rarity)
        
        # Random element
        element = random.choice(["infernal", "abyssal", "tempest", "earth", "radiant", "umbral"])
        
        return {
            "name": name,
            "rarity": miniboss_rarity,
            "element": element,
            "hp": final_hp,
            "rewards": rewards,
            "sector_id": sector_id,
            "sublevel": sublevel,
        }
    
    @staticmethod
    def _generate_name(sector_id: int, sublevel: int, rarity: str) -> str:
        """Generate thematic miniboss name."""
        sector_themes = {
            1: "Withered",
            2: "Ancient",
            3: "Corrupted",
            4: "Infernal",
            5: "Radiant",
            6: "Void",
            7: "Eternal",
        }
        
        boss_types = {
            "uncommon": ["Guardian", "Sentinel", "Watcher"],
            "rare": ["Keeper", "Protector", "Champion"],
            "epic": ["Overlord", "Tyrant", "Destroyer"],
            "legendary": ["Primordial", "Ancient", "Eternal"],
            "mythic": ["Absolute", "Supreme", "Transcendent"],
        }
        
        theme = sector_themes.get(sector_id, "Mysterious")
        types = boss_types.get(rarity, ["Guardian"])
        boss_type = random.choice(types)
        
        if sublevel == 9:
            return f"{theme} Sector Lord"
        else:
            return f"{theme} {boss_type}"
    
    @staticmethod
    def _calculate_rewards(sector_id: int, sublevel: int, miniboss_rarity: str) -> Dict[str, Any]:
        """
        Calculate rewards for defeating miniboss.
        
        Returns:
            Dictionary with rikis, xp, maiden_egg, and optional special items
        """
        base_rikis = ConfigManager.get("miniboss_system.reward_base_rikis", 500)
        base_xp = ConfigManager.get("miniboss_system.reward_base_xp", 100)
        sector_mult = ConfigManager.get("miniboss_system.reward_sector_multiplier", 1.0)
        boss_bonus = ConfigManager.get("miniboss_system.boss_sublevel_bonus", 2.0)
        
        multiplier = sector_id * sector_mult
        if sublevel == 9:
            multiplier *= boss_bonus
        
        rikis = int(base_rikis * multiplier)
        xp = int(base_xp * multiplier)
        
        # Maiden egg reward (1 tier above miniboss)
        egg_upgrade = ConfigManager.get("miniboss_system.egg_rarity_upgrade", True)
        rarity_progression = ["common", "uncommon", "rare", "epic", "legendary", "mythic"]
        
        if egg_upgrade:
            miniboss_index = rarity_progression.index(miniboss_rarity)
            egg_index = min(miniboss_index + 1, len(rarity_progression) - 1)
            egg_rarity = rarity_progression[egg_index]
        else:
            egg_rarity = miniboss_rarity
        
        rewards = {
            "rikis": rikis,
            "xp": xp,
            "maiden_egg": {
                "rarity": egg_rarity,
                "element": "random"
            }
        }
        
        # Boss-only rewards (sublevel 9)
        if sublevel == 9:
            boss_rewards = ConfigManager.get("miniboss_system.boss_rewards", {})
            rewards.update(boss_rewards)
        
        return rewards
    
    @staticmethod
    async def resolve_battle(
        session: AsyncSession,
        player: Player,
        miniboss: Dict[str, Any],
        damage_dealt: int
    ) -> Dict[str, Any]:
        """
        Resolve miniboss battle and grant rewards on victory.
        
        Args:
            session: Database session
            player: Player object (with_for_update=True)
            miniboss: Miniboss data from generate_miniboss()
            damage_dealt: Total damage player dealt
        
        Returns:
            Dictionary with:
                - victory: True if miniboss defeated
                - rewards: Rewards granted (if victory)
                - remaining_hp: Enemy HP remaining (if defeat)
        """
        miniboss_hp = miniboss["hp"]
        victory = damage_dealt >= miniboss_hp
        
        if victory:
            # Update sector progress
            sector_id = miniboss["sector_id"]
            sublevel = miniboss["sublevel"]
            
            from src.services.exploration_service import ExplorationService
            progress = await ExplorationService.get_or_create_progress(
                session, player.discord_id, sector_id, sublevel
            )
            
            if progress.miniboss_defeated:
                raise InvalidOperationError("Miniboss already defeated")
            
            progress.miniboss_defeated = True
            progress.last_explored = datetime.utcnow()
            
            # Grant rewards
            rewards = miniboss["rewards"]
            
            # Rikis and XP via ResourceService
            await ResourceService.grant_resources(
                session=session,
                player=player,
                rikis=rewards["rikis"],
                context="miniboss_victory",
                details={
                    "sector": sector_id,
                    "sublevel": sublevel,
                    "miniboss": miniboss["name"]
                }
            )
            
            # TODO: Grant maiden egg (requires maiden system integration)
            # TODO: Grant special items (prayer charges, fusion catalyst)
            
            # Update player progression stats
            if sector_id > player.highest_sector_reached:
                player.highest_sector_reached = sector_id
            
            # Log victory
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type="miniboss_victory",
                details={
                    "miniboss": miniboss,
                    "damage_dealt": damage_dealt,
                    "rewards": rewards
                },
                context="miniboss_battle"
            )
            
            logger.info(
                f"Player {player.discord_id} defeated miniboss: {miniboss['name']} "
                f"(sector {sector_id}, sublevel {sublevel})"
            )
            
            await session.flush()
            
            return {
                "victory": True,
                "rewards": rewards,
                "remaining_hp": 0
            }
        
        else:
            # Defeat - no progress
            remaining_hp = miniboss_hp - damage_dealt
            
            await TransactionLogger.log_transaction(
                session=session,
                player_id=player.discord_id,
                transaction_type="miniboss_defeat",
                details={
                    "miniboss": miniboss,
                    "damage_dealt": damage_dealt,
                    "remaining_hp": remaining_hp
                },
                context="miniboss_battle"
            )
            
            logger.info(
                f"Player {player.discord_id} failed miniboss: {miniboss['name']} "
                f"({remaining_hp}/{miniboss_hp} HP remaining)"
            )
            
            return {
                "victory": False,
                "rewards": None,
                "remaining_hp": remaining_hp
            }
    
    @staticmethod
    def calculate_attacks_needed(player_power: int, miniboss_hp: int) -> int:
        """
        Estimate attacks needed to defeat miniboss.
        
        Args:
            player_power: Total ATK from all maidens
            miniboss_hp: Miniboss total HP
        
        Returns:
            Number of attacks needed
        """
        if player_power == 0:
            return 999
        
        return math.ceil(miniboss_hp / player_power)