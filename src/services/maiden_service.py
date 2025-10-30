from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.database.models.maiden import Maiden
from src.database.models.maiden_base import MaidenBase
from src.database.models.player import Player
from src.exceptions import MaidenNotFoundError
from src.services.logger import get_logger

logger = get_logger(__name__)


class MaidenService:
    """
    Maiden inventory and collection management service.
    
    Handles querying, adding, updating, and removing maidens from player inventories.
    Provides filtering, sorting, and power calculation utilities.
    
    Key Responsibilities:
        - Inventory queries with filtering
        - Maiden addition/removal
        - Power calculation with leader bonuses
        - Fusable maiden identification
    
    Usage:
        >>> maidens = await MaidenService.get_player_maidens(session, player_id)
        >>> fusable = await MaidenService.get_fusable_maidens(session, player_id)
        >>> power = await MaidenService.calculate_player_total_power(session, player_id)
    """
    
    @staticmethod
    async def get_player_maidens(
        session: AsyncSession,
        player_id: int,
        tier_filter: Optional[int] = None,
        element_filter: Optional[str] = None,
        sort_by: str = "tier_desc",
        lock: bool = False
    ) -> List[Maiden]:
        """
        Get all maidens for player with optional filtering and sorting.
        
        Args:
            session: Database session
            player_id: Player's Discord ID
            tier_filter: Optional tier to filter by
            element_filter: Optional element to filter by
            sort_by: Sort method - "tier_desc", "tier_asc", "name", "quantity"
            lock: Whether to use SELECT FOR UPDATE
        
        Returns:
            List of Maiden objects with maiden_base relationship loaded
        
        Example:
            >>> # Get all Tier 5 infernal maidens
            >>> maidens = await MaidenService.get_player_maidens(
            ...     session, player_id, tier_filter=5, element_filter="infernal"
            ... )
        """
        query = (
            select(Maiden)
            .join(MaidenBase)
            .where(Maiden.player_id == player_id)
        )
        
        if tier_filter is not None:
            query = query.where(Maiden.tier == tier_filter)
        
        if element_filter:
            query = query.where(MaidenBase.element == element_filter)
        
        if sort_by == "tier_desc":
            query = query.order_by(Maiden.tier.desc())
        elif sort_by == "tier_asc":
            query = query.order_by(Maiden.tier.asc())
        elif sort_by == "name":
            query = query.order_by(MaidenBase.name)
        elif sort_by == "quantity":
            query = query.order_by(Maiden.quantity.desc())
        
        if lock:
            query = query.with_for_update()
        
        result = await session.execute(query)
        maidens = result.scalars().all()
        
        for maiden in maidens:
            await session.refresh(maiden, ["maiden_base"])
        
        return maidens
    
    @staticmethod
    async def get_maiden_by_id(
        session: AsyncSession,
        maiden_id: int,
        player_id: Optional[int] = None,
        lock: bool = False
    ) -> Optional[Maiden]:
        """
        Get specific maiden by ID with optional ownership validation.
        
        Args:
            session: Database session
            maiden_id: Maiden instance ID
            player_id: Optional player ID to validate ownership
            lock: Whether to use SELECT FOR UPDATE
        
        Returns:
            Maiden object or None if not found
        
        Raises:
            MaidenNotFoundError: If player_id provided and ownership doesn't match
        
        Example:
            >>> maiden = await MaidenService.get_maiden_by_id(
            ...     session, maiden_id, player_id=user_id, lock=True
            ... )
        """
        query = select(Maiden).where(Maiden.id == maiden_id)
        
        if lock:
            query = query.with_for_update()
        
        result = await session.execute(query)
        maiden = result.scalar_one_or_none()
        
        if not maiden:
            return None
        
        if player_id is not None and maiden.player_id != player_id:
            raise MaidenNotFoundError(f"Maiden {maiden_id} not owned by player {player_id}")
        
        await session.refresh(maiden, ["maiden_base"])
        
        return maiden
    
    @staticmethod
    async def get_fusable_maidens(
        session: AsyncSession,
        player_id: int,
        tier: Optional[int] = None
    ) -> List[Maiden]:
        """
        Get maidens that can be fused (quantity >= 2 and tier < 12).
        
        Args:
            session: Database session
            player_id: Player's Discord ID
            tier: Optional specific tier to filter
        
        Returns:
            List of Maiden objects that meet fusion requirements
        
        Example:
            >>> # Get all fusable Tier 3 maidens
            >>> fusable = await MaidenService.get_fusable_maidens(
            ...     session, player_id, tier=3
            ... )
        """
        query = (
            select(Maiden)
            .join(MaidenBase)
            .where(
                Maiden.player_id == player_id,
                Maiden.quantity >= 2,
                Maiden.tier < 12
            )
        )
        
        if tier is not None:
            query = query.where(Maiden.tier == tier)
        
        query = query.order_by(Maiden.tier.desc())
        
        result = await session.execute(query)
        maidens = result.scalars().all()
        
        for maiden in maidens:
            await session.refresh(maiden, ["maiden_base"])
        
        return maidens
    
    @staticmethod
    async def add_maiden_to_inventory(
        session: AsyncSession,
        player_id: int,
        maiden_base_id: int,
        tier: int,
        quantity: int = 1
    ) -> Maiden:
        """
        Add maiden to player inventory or increment quantity if exists.
        
        Args:
            session: Database session
            player_id: Player's Discord ID
            maiden_base_id: MaidenBase template ID
            tier: Maiden tier
            quantity: Number to add (default 1)
        
        Returns:
            Maiden object (existing or newly created)
        
        Example:
            >>> maiden = await MaidenService.add_maiden_to_inventory(
            ...     session, player_id, maiden_base_id=5, tier=3, quantity=2
            ... )
        """
        existing_result = await session.execute(
            select(Maiden).where(
                Maiden.player_id == player_id,
                Maiden.maiden_base_id == maiden_base_id
            ).with_for_update()
        )
        existing_maiden = existing_result.scalar_one_or_none()
        
        if existing_maiden:
            existing_maiden.quantity += quantity
            await session.refresh(existing_maiden, ["maiden_base"])
            return existing_maiden
        else:
            new_maiden = Maiden(
                player_id=player_id,
                maiden_base_id=maiden_base_id,
                tier=tier,
                quantity=quantity,
                is_locked=False
            )
            session.add(new_maiden)
            await session.flush()
            await session.refresh(new_maiden, ["maiden_base"])
            
            player = await session.get(Player, player_id)
            if player:
                player.unique_maidens += 1
            
            return new_maiden
    
    @staticmethod
    async def update_maiden_quantity(
        session: AsyncSession,
        maiden_id: int,
        quantity_change: int
    ) -> Optional[Maiden]:
        """
        Modify maiden quantity and delete if quantity reaches 0.
        
        Args:
            session: Database session
            maiden_id: Maiden instance ID
            quantity_change: Amount to add (positive) or remove (negative)
        
        Returns:
            Updated Maiden object, or None if deleted
        
        Example:
            >>> # Remove 1 from quantity
            >>> maiden = await MaidenService.update_maiden_quantity(
            ...     session, maiden_id, quantity_change=-1
            ... )
        """
        maiden = await session.get(Maiden, maiden_id, with_for_update=True)
        
        if not maiden:
            raise MaidenNotFoundError(f"Maiden {maiden_id} not found")
        
        maiden.quantity += quantity_change
        
        if maiden.quantity <= 0:
            player = await session.get(Player, maiden.player_id)
            if player:
                player.unique_maidens -= 1
            
            await session.delete(maiden)
            return None
        
        return maiden
    
    @staticmethod
    async def get_maiden_base_by_id(
        session: AsyncSession,
        maiden_base_id: int
    ) -> Optional[MaidenBase]:
        """
        Get MaidenBase template by ID.
        
        Args:
            session: Database session
            maiden_base_id: MaidenBase ID
        
        Returns:
            MaidenBase object or None if not found
        
        Example:
            >>> maiden_base = await MaidenService.get_maiden_base_by_id(session, 5)
        """
        return await session.get(MaidenBase, maiden_base_id)
    
    @staticmethod
    async def calculate_player_total_power(
        session: AsyncSession,
        player_id: int
    ) -> int:
        """
        Calculate player's total power from all maidens with leader bonus.
        
        Formula:
            Total Power = Sum of (maiden_stats × quantity) × leader_bonus
        
        Args:
            session: Database session
            player_id: Player's Discord ID
        
        Returns:
            Total power value
        
        Example:
            >>> power = await MaidenService.calculate_player_total_power(session, player_id)
            >>> print(f"Total Power: {power:,}")
        """
        maidens = await MaidenService.get_player_maidens(session, player_id)
        
        player = await session.get(Player, player_id)
        if not player:
            return 0
        
        total_power = 0
        
        for maiden in maidens:
            if not maiden.maiden_base:
                continue
            
            maiden_base = maiden.maiden_base
            
            maiden_power = (
                maiden_base.base_attack +
                maiden_base.base_defense +
                maiden_base.base_hp
            )
            
            total_power += maiden_power * maiden.quantity
        
        if player.leader_maiden_id:
            leader_maiden = await MaidenService.get_maiden_by_id(
                session, player.leader_maiden_id
            )
            
            if leader_maiden and leader_maiden.maiden_base:
                leader_base = leader_maiden.maiden_base
                
                if leader_base.has_leader_effect():
                    effect_type = leader_base.leader_effect.get("type")
                    
                    if effect_type == "stat_boost":
                        from src.services.leader_service import LeaderService
                        
                        bonus_percent = LeaderService.calculate_effect_value(
                            leader_base,
                            leader_maiden.tier
                        )
                        
                        bonus_multiplier = 1 + (bonus_percent / 100)
                        total_power = int(total_power * bonus_multiplier)
        
        return total_power
    
    @staticmethod
    async def get_collection_stats(
        session: AsyncSession,
        player_id: int
    ) -> Dict[str, Any]:
        """
        Get player's collection statistics.
        
        Returns:
            Dictionary with:
                - total_maidens (int): Sum of all quantities
                - unique_maidens (int): Count of unique maidens
                - tier_distribution (dict): Count per tier
                - element_distribution (dict): Count per element
                - highest_tier (int): Highest tier owned
                - total_power (int): Calculated power
        
        Example:
            >>> stats = await MaidenService.get_collection_stats(session, player_id)
            >>> print(f"Collection: {stats['unique_maidens']} unique maidens")
        """
        maidens = await MaidenService.get_player_maidens(session, player_id)
        
        total_maidens = sum(maiden.quantity for maiden in maidens)
        unique_maidens = len(maidens)
        
        tier_distribution = {}
        element_distribution = {}
        highest_tier = 0
        
        for maiden in maidens:
            tier = maiden.tier
            tier_distribution[tier] = tier_distribution.get(tier, 0) + maiden.quantity
            highest_tier = max(highest_tier, tier)
            
            if maiden.maiden_base:
                element = maiden.maiden_base.element
                element_distribution[element] = element_distribution.get(element, 0) + maiden.quantity
        
        total_power = await MaidenService.calculate_player_total_power(session, player_id)
        
        return {
            "total_maidens": total_maidens,
            "unique_maidens": unique_maidens,
            "tier_distribution": tier_distribution,
            "element_distribution": element_distribution,
            "highest_tier": highest_tier,
            "total_power": total_power
        }