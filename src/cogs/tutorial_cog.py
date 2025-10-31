import discord
from discord.ext import commands

from src.services.database_service import DatabaseService
from src.services.player_service import PlayerService
from src.services.tutorial_service import TutorialService, TRIGGER_INDEX
from src.services.event_bus import EventBus
from src.services.logger import get_logger
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class TutorialCog(commands.Cog):
    """
    Reacts to gameplay events and announces tangible tutorial completions.
    Sends a public embed, followed by a plain text reward line.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Subscribe to all tutorial triggers
        for topic in TRIGGER_INDEX.keys():
            EventBus.subscribe(topic, self._handle_event)

    async def _handle_event(self, payload: dict):
        """
        Expected payload:
        {
          "player_id": int,
          "channel_id": Optional[int],
          ...other fields...
        }
        """
        try:
            player_id = payload.get("player_id")
            channel_id = payload.get("channel_id")
            topic = payload.get("topic") or payload.get("event")  # optional

            # Best effort: infer topic from subscription by checking fields we got
            # EventBus should give us the topic; if not, payload should imply it by caller convention.
            if not player_id or not channel_id:
                return

            # Determine which step to complete from topic name; fallback to payload-provided.
            # We pass the topic explicitly on publish in all cogs, so rely on that:
            trigger = payload.get("__topic__") or topic or payload.get("trigger")
            # If not provided, try a smart guess: the handler was bound to a specific topic per subscribe.
            # For simplicity, check common keys by presence:
            if not trigger:
                # No strong inference -> bail quietly
                return

            step = TRIGGER_INDEX.get(trigger)
            if not step:
                return

            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(session, player_id, lock=True)
                if not player:
                    return

                done = await TutorialService.complete_step(session, player, step["key"])
                if not done:
                    return  # already completed or invalid

            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return

            # Public congrats embed
            embed = EmbedBuilder.success(
                title=f"🎉 Tutorial Complete: {done['title']}",
                description=done["congrats"],
                footer="Keep going — complete all steps for starter boosts!"
            )
            await channel.send(embed=embed)

            # Plain text reward message (no embed)
            rikis = done["reward"].get("rikis", 0)
            grace = done["reward"].get("grace", 0)
            if rikis or grace:
                parts = []
                if rikis:
                    parts.append(f"+{rikis} rikis")
                if grace:
                    parts.append(f"+{grace} grace")
                await channel.send(f"You received {' and '.join(parts)} as a tutorial reward!")

        except Exception as e:
            logger.error(f"Tutorial event handling failed: {e}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TutorialCog(bot))

