# src/services/resource_service.py
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.player import Player
from src.services.config_manager import ConfigManager
from src.services.transaction_logger import TransactionLogger
from src.services.leader_service import LeaderService
from src.exceptions import InsufficientResourcesError
from src.services.logger import get_logger

logger = get_logger(__name__)


class ResourceService:
    """
    Centralized resource transaction and modifier application system.
    
    Handles ALL resource modifications (rikis, grace, gems, energy, stamina, prayer_charges)
    with validation, global modifier application, transaction logging, and cap enforcement.
    Integrates with LeaderService for income_boost/xp_boost and class bonuses.
    
    Key Responsibilities:
        - Resource granting with modifier application (leader + class bonuses)
        - Resource consumption with validation
        - Resource checking without modification
        - Modifier calculation from multiple sources
        - Grace cap enforcement (999,999 configurable)
        - Audit trail for all changes
    
    Modifier System:
        - Multiplicative stacking: final = base * leader_mult * class_mult
        - Applies to: rikis, grace, gems, XP gains
        - Sources: Leader effects (income_boost, xp_boost), class bonuses
    
    Usage:
        >>> # Grant resources with modifiers
        >>> result = await ResourceService.grant_resources(
        ...     session, player,
        ...     {"rikis": 1000, "grace": 5},
        ...     source="daily_reward",
        ...     apply_modifiers=True
        ... )
        >>> 
        >>> # Consume resources
        >>> await ResourceService.consume_resources(
        ...     session, player,
        ...     {"grace": 5},
        ...     source="summon_cost"
        ... )
        >>> 
        >>> # Check affordability
        >>> can_afford = ResourceService.check_resources(player, {"rikis": 5000})
    """
    
    @staticmethod
    async def grant_resources(
        session: AsyncSession,
        player: Player,
        resources: Dict[str, int],
        source: str,
        apply_modifiers: bool = True,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Grant resources to player with optional modifier application.
        
        Applies leader bonuses and class bonuses multiplicatively:
        - income_boost applies to: rikis, grace, riki_gems
        - xp_boost applies to: experience
        - class bonuses apply contextually
        
        Enforces grace cap (999,999 configurable). No cap for rikis/gems.
        Logs all changes via TransactionLogger.
        
        Args:
            session: Database session (transaction managed by caller)
            player: Player object (must be locked with SELECT FOR UPDATE)
            resources: Dict of resource amounts {"rikis": 1000, "grace": 5, "xp": 100}
            source: Reason for grant ("daily_reward", "fusion_refund", "prayer_completion")
            apply_modifiers: Whether to apply leader/class bonuses (False for tutorial)
            context: Additional context for transaction log
        
        Returns:
            Dictionary with:
                - granted (dict): Actual amounts granted after modifiers
                - modifiers_applied (dict): Multipliers used
                - caps_hit (list): Resources that hit caps
                - old_values (dict): Values before grant
                - new_values (dict): Values after grant
        
        Example:
            >>> result = await ResourceService.grant_resources(
            ...     session, player,
            ...     {"rikis": 1000, "grace": 5, "experience": 100},
            ...     source="daily_reward",
            ...     apply_modifiers=True,
            ...     context={"quest_id": "daily_complete"}
            ... )
            >>> print(f"Granted {result['granted']['rikis']} rikis with {result['modifiers_applied']['income_boost']}x bonus")
        """
        granted = {}
        modifiers_applied = {}
        caps_hit = []
        old_values = {}
        new_values = {}
        
        if apply_modifiers:
            resource_types = list(resources.keys())
            modifiers = ResourceService.calculate_modifiers(player, resource_types)
            modifiers_applied = modifiers
        else:
            modifiers_applied = {}
        
        for resource, base_amount in resources.items():
            if base_amount <= 0:
                continue
            
            old_values[resource] = getattr(player, resource, 0)
            
            final_amount = base_amount
            if apply_modifiers:
                if resource in ["rikis", "grace", "riki_gems"]:
                    income_mult = modifiers_applied.get("income_boost", 1.0)
                    final_amount = int(base_amount * income_mult)
                elif resource == "experience":
                    xp_mult = modifiers_applied.get("xp_boost", 1.0)
                    final_amount = int(base_amount * xp_mult)
            
            if resource == "grace":
                grace_cap = ConfigManager.get("resource_system.grace_max_cap", 999999)
                new_value = old_values[resource] + final_amount
                if new_value > grace_cap:
                    final_amount = grace_cap - old_values[resource]
                    caps_hit.append("grace")
                    new_value = grace_cap
                player.grace = new_value
            elif resource == "rikis":
                player.rikis += final_amount
            elif resource == "riki_gems":
                player.riki_gems += final_amount
            elif resource == "experience":
                player.experience += final_amount
            elif resource == "energy":
                new_val = min(player.energy + final_amount, player.max_energy)
                final_amount = new_val - player.energy
                player.energy = new_val
            elif resource == "stamina":
                new_val = min(player.stamina + final_amount, player.max_stamina)
                final_amount = new_val - player.stamina
                player.stamina = new_val
            elif resource == "prayer_charges":
                new_val = min(player.prayer_charges + final_amount, player.max_prayer_charges)
                final_amount = new_val - player.prayer_charges
                player.prayer_charges = new_val
            else:
                logger.warning(f"Unknown resource type: {resource}")
                continue
            
            granted[resource] = final_amount
            new_values[resource] = getattr(player, resource, 0)
        
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player.discord_id,
            transaction_type=f"resource_grant_{source}",
            details={
                "resources_granted": granted,
                "base_amounts": resources,
                "modifiers": modifiers_applied,
                "caps_hit": caps_hit,
                "old_values": old_values,
                "new_values": new_values,
                "source": source,
                "context": context or {}
            },
            context=f"grant:{source}"
        )
        
        logger.info(
            f"Granted resources to player {player.discord_id}: {granted} "
            f"(modifiers: {modifiers_applied}, source: {source})"
        )
        
        return {
            "granted": granted,
            "modifiers_applied": modifiers_applied,
            "caps_hit": caps_hit,
            "old_values": old_values,
            "new_values": new_values
        }
    
    @staticmethod
    async def consume_resources(
        session: AsyncSession,
        player: Player,
        resources: Dict[str, int],
        source: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Consume resources from player with validation.
        
        Validates player has sufficient resources before consuming.
        Logs all changes via TransactionLogger.
        
        Args:
            session: Database session (transaction managed by caller)
            player: Player object (must be locked with SELECT FOR UPDATE)
            resources: Dict of resource amounts to consume {"rikis": 5000, "grace": 5}
            source: Reason for consumption ("fusion_cost", "summon_cost", "upgrade_cost")
            context: Additional context for transaction log
        
        Returns:
            Dictionary with:
                - consumed (dict): Amounts consumed
                - old_values (dict): Values before consumption
                - new_values (dict): Values after consumption
        
        Raises:
            InsufficientResourcesError: If player lacks required resources
        
        Example:
            >>> try:
            ...     result = await ResourceService.consume_resources(
            ...         session, player,
            ...         {"rikis": 5000, "grace": 5},
            ...         source="fusion_cost",
            ...         context={"tier": 3}
            ...     )
            ... except InsufficientResourcesError as e:
            ...     print(f"Need {e.required} {e.resource}, have {e.current}")
        """
        old_values = {}
        new_values = {}
        consumed = {}
        
        for resource, amount in resources.items():
            if amount <= 0:
                continue
            
            current = getattr(player, resource, 0)
            old_values[resource] = current
            
            if current < amount:
                raise InsufficientResourcesError(
                    resource=resource,
                    required=amount,
                    current=current
                )
        
        for resource, amount in resources.items():
            if amount <= 0:
                continue
            
            if resource == "grace":
                player.grace -= amount
            elif resource == "rikis":
                player.rikis -= amount
            elif resource == "riki_gems":
                player.riki_gems -= amount
            elif resource == "energy":
                player.energy -= amount
            elif resource == "stamina":
                player.stamina -= amount
            elif resource == "prayer_charges":
                player.prayer_charges -= amount
            else:
                logger.warning(f"Unknown resource type for consumption: {resource}")
                continue
            
            consumed[resource] = amount
            new_values[resource] = getattr(player, resource, 0)
        
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player.discord_id,
            transaction_type=f"resource_consume_{source}",
            details={
                "resources_consumed": consumed,
                "old_values": old_values,
                "new_values": new_values,
                "source": source,
                "context": context or {}
            },
            context=f"consume:{source}"
        )
        
        logger.info(
            f"Consumed resources from player {player.discord_id}: {consumed} (source: {source})"
        )
        
        return {
            "consumed": consumed,
            "old_values": old_values,
            "new_values": new_values
        }
    
    @staticmethod
    def check_resources(player: Player, resources: Dict[str, int]) -> bool:
        """
        Check if player has sufficient resources without consuming.
        
        Args:
            player: Player object
            resources: Dict of resource requirements {"rikis": 5000, "grace": 5}
        
        Returns:
            True if player has all required resources, False otherwise
        
        Example:
            >>> if ResourceService.check_resources(player, {"rikis": 5000, "grace": 5}):
            ...     print("Can afford!")
            ... else:
            ...     print("Insufficient resources")
        """
        for resource, amount in resources.items():
            if amount <= 0:
                continue
            
            current = getattr(player, resource, 0)
            if current < amount:
                return False
        
        return True
    
    @staticmethod
    def calculate_modifiers(player: Player, resource_types: List[str]) -> Dict[str, float]:
        """
        Calculate active modifiers from leader and class effects.
        
        Multiplicative stacking: final = base * leader_mult * class_mult
        
        Args:
            player: Player object
            resource_types: List of resource types to calculate modifiers for
        
        Returns:
            Dictionary of multipliers:
                - income_boost: Multiplier for rikis, grace, gems (1.0 = no bonus)
                - xp_boost: Multiplier for experience (1.0 = no bonus)
        
        Example:
            >>> modifiers = ResourceService.calculate_modifiers(player, ["rikis", "experience"])
            >>> print(f"Income boost: {modifiers['income_boost']}x, XP boost: {modifiers['xp_boost']}x")
        """
        modifiers = {
            "income_boost": 1.0,
            "xp_boost": 1.0
        }
        
        needs_income = any(r in resource_types for r in ["rikis", "grace", "riki_gems"])
        needs_xp = "experience" in resource_types
        
        if player.leader_maiden_id:
            leader_modifiers = LeaderService.get_active_modifiers(player)
            if needs_income and "income_boost" in leader_modifiers:
                modifiers["income_boost"] *= leader_modifiers["income_boost"]
            if needs_xp and "xp_boost" in leader_modifiers:
                modifiers["xp_boost"] *= leader_modifiers["xp_boost"]
        
        return modifiers
    
    @staticmethod
    def apply_regeneration(player: Player, regen_amounts: Dict[str, int]) -> Dict[str, int]:
        """
        Apply calculated regeneration amounts with modifier consideration.
        
        Called by PlayerService after calculating regen. This method applies
        the amounts and respects caps. Does NOT calculate regen itself.
        
        Args:
            player: Player object
            regen_amounts: Dict of regen amounts {"energy": 10, "stamina": 5, "prayer_charges": 1}
        
        Returns:
            Dictionary of actual amounts regenerated (after caps)
        
        Example:
            >>> # PlayerService calculates regen amounts
            >>> regen = {"energy": 10, "stamina": 5, "prayer_charges": 1}
            >>> actual = ResourceService.apply_regeneration(player, regen)
            >>> print(f"Regenerated {actual['energy']} energy")
        """
        actual_regen = {}
        
        if "energy" in regen_amounts and regen_amounts["energy"] > 0:
            old_energy = player.energy
            player.energy = min(player.energy + regen_amounts["energy"], player.max_energy)
            actual_regen["energy"] = player.energy - old_energy
        
        if "stamina" in regen_amounts and regen_amounts["stamina"] > 0:
            old_stamina = player.stamina
            player.stamina = min(player.stamina + regen_amounts["stamina"], player.max_stamina)
            actual_regen["stamina"] = player.stamina - old_stamina
        
        if "prayer_charges" in regen_amounts and regen_amounts["prayer_charges"] > 0:
            old_charges = player.prayer_charges
            player.prayer_charges = min(
                player.prayer_charges + regen_amounts["prayer_charges"],
                player.max_prayer_charges
            )
            actual_regen["prayer_charges"] = player.prayer_charges - old_charges
        
        return actual_regen
    
    @staticmethod
    def get_resource_summary(player: Player) -> Dict[str, Any]:
        """
        Get formatted resource display for player profile.
        
        Args:
            player: Player object
        
        Returns:
            Dictionary with formatted resource information:
                - currencies: rikis, grace, gems
                - consumables: energy, stamina, prayer_charges with max values
                - modifiers: active bonuses from leader/class
        
        Example:
            >>> summary = ResourceService.get_resource_summary(player)
            >>> print(f"Rikis: {summary['currencies']['rikis']:,}")
            >>> print(f"Energy: {summary['consumables']['energy']['current']}/{summary['consumables']['energy']['max']}")
        """
        modifiers = ResourceService.calculate_modifiers(
            player,
            ["rikis", "grace", "riki_gems", "experience"]
        )
        
        return {
            "currencies": {
                "rikis": player.rikis,
                "grace": player.grace,
                "riki_gems": player.riki_gems
            },
            "consumables": {
                "energy": {
                    "current": player.energy,
                    "max": player.max_energy,
                    "percentage": int((player.energy / player.max_energy) * 100) if player.max_energy > 0 else 0
                },
                "stamina": {
                    "current": player.stamina,
                    "max": player.max_stamina,
                    "percentage": int((player.stamina / player.max_stamina) * 100) if player.max_stamina > 0 else 0
                },
                "prayer_charges": {
                    "current": player.prayer_charges,
                    "max": player.max_prayer_charges,
                    "next_regen": player.get_prayer_regen_display()
                }
            },
            "modifiers": {
                "income_boost": f"{(modifiers['income_boost'] - 1.0) * 100:.0f}%" if modifiers['income_boost'] > 1.0 else "None",
                "xp_boost": f"{(modifiers['xp_boost'] - 1.0) * 100:.0f}%" if modifiers['xp_boost'] > 1.0 else "None"
            }
        }
    
    @staticmethod
    async def cleanup_old_audit_logs(
        session: AsyncSession,
        cutoff_days: int = 90
    ) -> int:
        """
        Delete transaction logs older than specified days.
        
        Args:
            session: Database session
            cutoff_days: Delete logs older than this many days (default 90)
        
        Returns:
            Number of logs deleted
        
        Example:
            >>> deleted = await ResourceService.cleanup_old_audit_logs(session, cutoff_days=90)
            >>> print(f"Deleted {deleted} old audit logs")
        """
        from src.database.models.transaction_log import TransactionLog
        from sqlalchemy import delete
        
        cutoff_date = datetime.utcnow() - timedelta(days=cutoff_days)
        
        stmt = delete(TransactionLog).where(TransactionLog.timestamp < cutoff_date)
        result = await session.execute(stmt)
        deleted_count = result.rowcount
        
        logger.info(f"Cleaned up {deleted_count} transaction logs older than {cutoff_days} days")
        
        return deleted_count