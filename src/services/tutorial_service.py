from __future__ import annotations
from typing import Dict, Any, Optional
from datetime import datetime

from src.database.models.player import Player
from src.services.transaction_logger import TransactionLogger
from src.services.logger import get_logger

logger = get_logger(__name__)

# Ordered, tangible tutorial steps.
# Each step: key, title, trigger (EventBus topic), reward (rikis/grace), congrats text.
TUTORIAL_STEPS = [
    {
        "key": "tos_agreed",
        "title": "Accepted Terms of Service",
        "trigger": "tos_agreed",
        "reward": {"rikis": 0, "grace": 0},
        "congrats": "Thanks for agreeing to our **Terms of Service**. Welcome aboard!"
    },
    {
        "key": "first_pray",
        "title": "First Prayer",
        "trigger": "prayer_completed",
        "reward": {"rikis": 250, "grace": 1},
        "congrats": "Prayer grants **Grace** used for summoning maidens."
    },
    {
        "key": "first_summon",
        "title": "First Summon",
        "trigger": "summons_completed",
        "reward": {"rikis": 0, "grace": 1},
        "congrats": "Summoning adds new maidens to your collection."
    },
    {
        "key": "first_fusion",
        "title": "First Fusion",
        "trigger": "fusion_completed",
        "reward": {"rikis": 500, "grace": 0},
        "congrats": "Fusion upgrades tiers — save duplicates to progress faster."
    },
    {
        "key": "view_collection",
        "title": "Viewed Collection",
        "trigger": "collection_viewed",
        "reward": {"rikis": 0, "grace": 1},
        "congrats": "Use filters to plan your fusions and leaders."
    },
    {
        "key": "set_leader",
        "title": "Set a Leader",
        "trigger": "leader_set",
        "reward": {"rikis": 0, "grace": 1},
        "congrats": "Leaders grant passive element-based bonuses."
    },
]

TRIGGER_INDEX: Dict[str, Dict[str, Any]] = {s["trigger"]: s for s in TUTORIAL_STEPS}
KEY_INDEX: Dict[str, Dict[str, Any]] = {s["key"]: s for s in TUTORIAL_STEPS}


class TutorialService:
    @staticmethod
    def _ensure_state(player: Player) -> None:
        if "tutorial" not in player.stats:
            player.stats["tutorial"] = {"completed": {}}

    @staticmethod
    def is_completed(player: Player, step_key: str) -> bool:
        TutorialService._ensure_state(player)
        return bool(player.stats["tutorial"]["completed"].get(step_key))

    @staticmethod
    async def complete_step(session, player: Player, step_key: str) -> Optional[Dict[str, Any]]:
        """
        Idempotently completes a tutorial step, applies rewards, logs, returns payload for messaging.
        Returns None if already completed or unknown.
        """
        TutorialService._ensure_state(player)

        step = KEY_INDEX.get(step_key)
        if not step:
            logger.warning(f"Unknown tutorial step: {step_key}")
            return None

        if TutorialService.is_completed(player, step_key):
            return None

        player.stats["tutorial"]["completed"][step_key] = datetime.utcnow().isoformat()

        reward = step.get("reward") or {}
        rikis = int(reward.get("rikis", 0))
        grace = int(reward.get("grace", 0))
        if rikis:
            player.rikis += rikis
        if grace:
            player.grace += grace

        await TransactionLogger.log_transaction(
            player_id=player.discord_id,
            transaction_type="tutorial_step_completed",
            details={"step_key": step_key, "reward": reward},
            context="tutorial:complete"
        )

        return {
            "title": step["title"],
            "congrats": step["congrats"],
            "reward": {"rikis": rikis, "grace": grace},
        }

