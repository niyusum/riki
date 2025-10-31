import asyncio
from src.services.event_bus import EventBus
from src.services.tutorial_service import TutorialService
from src.services.database_service import DatabaseService
from src.services.logger import get_logger

logger = get_logger(__name__)

async def _handle_tutorial_event(event_name: str, data):
    """Handle tutorial step completion and reward distribution."""
    player_id = data.get("player_id")
    bot = data.get("bot")
    channel_id = data.get("channel_id")

    if not player_id or not bot:
        logger.warning(f"Tutorial event {event_name} missing required data")
        return

    async with DatabaseService.get_transaction() as session:
        from src.database.models.player import Player
        player = await session.get(Player, player_id, with_for_update=True)
        if not player:
            return

        result = await TutorialService.complete_step(session, player, event_name)
        if not result:
            return  # Already completed or invalid

        # Send congrats message to channel
        channel = bot.get_channel(channel_id)
        if channel:
            await channel.send(
                f"🎉 **Tutorial Complete:** {result['title']}\n"
                f"{result['congrats']}\n\n"
                f"💰 Rewards: +{result['reward']['rikis']} Rikis, +{result['reward']['grace']} Grace"
            )

async def register_tutorial_listeners(bot):
    """Bind tutorial steps to the EventBus."""
    for trigger in ["tos_agreed", "prayer_completed", "summons_completed", "fusion_completed", "collection_viewed", "leader_set"]:
        EventBus.subscribe(trigger, lambda data, e=trigger: asyncio.create_task(_handle_tutorial_event(e, data)))
