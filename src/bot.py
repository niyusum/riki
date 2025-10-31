import discord
from discord.ext import commands
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, List

# Add src to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from src.config import Config
from src.services.database_service import DatabaseService
from src.services.redis_service import RedisService
from src.services.config_manager import ConfigManager
from src.services.logger import get_logger
from src.exceptions import RIKIException, RateLimitError, InsufficientResourcesError
from src.utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class RIKIBot(commands.Bot):
    """
    RIKI RPG Discord Bot.

    Implements hybrid command system supporting both slash commands and
    text-based prefix commands (r/riki). Handles database connections,
    cog loading, and graceful shutdown.

    RIKI LAW Compliance:
        - All business logic in services
        - Transaction-based state management
        - Redis locks for concurrency
        - Comprehensive error handling
        - Event-driven architecture
    """

    def __init__(self):
        """Initialize bot with hybrid command support."""
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        super().__init__(
            command_prefix=self._get_prefix,
            intents=intents,
            help_command=None,
            case_insensitive=True,
            strip_after_prefix=True,
            description=Config.BOT_DESCRIPTION,
        )

        self.initial_extensions: List[str] = [
            "cogs.register_cog",
            "cogs.profile_cog",
            "cogs.pray_cog",
            "cogs.summon_cog",
            "cogs.fusion_cog",
            "cogs.collection_cog",
            "cogs.daily_cog",
            "cogs.leader_cog",
            "cogs.help_cog",
            "cogs.stats_cog",
        ]

    def _get_prefix(self, bot: commands.Bot, message: discord.Message) -> List[str]:
        """
        Dynamic prefix getter supporting multiple formats.

        Supported prefixes:
            - r / riki
            - r (with or without space)
            - mention-based

        Returns:
            List of valid prefixes for this message
        """
        return commands.when_mentioned_or("r", "r ", "riki", "riki ")(bot, message)

    async def setup_hook(self):
        """
        Setup hook called during bot startup.

        Performs initialization:
            - Initialize database, Redis, config manager (in parallel)
            - Load all cogs
            - Sync slash commands (dev/prod)
        """
        logger.info("Starting RIKI RPG Bot setup...")

        try:
            # Initialize core services concurrently
            logger.info("Initializing core services (DB, Redis, Config)...")
            await asyncio.gather(
                DatabaseService.initialize(),
                RedisService.initialize(),
                ConfigManager.initialize(),
            )
            logger.info("✓ Core services initialized [SUCCESS]")

            # Load all cogs
            logger.info("Loading cogs...")
            for extension in self.initial_extensions:
                try:
                    await self.load_extension(extension)
                    logger.info(f"✓ Loaded {extension} [SUCCESS]")
                except Exception as e:
                    logger.error(f"✗ Failed to load {extension}: {e}", exc_info=True)

            # Sync slash commands
            if Config.is_development() and Config.DISCORD_GUILD_ID:
                logger.info("Syncing slash commands to test guild...")
                guild = discord.Object(id=Config.DISCORD_GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info("✓ Slash commands synced [DEV]")
            elif Config.is_production():
                logger.info("Syncing global slash commands...")
                await self.tree.sync()
                logger.info("✓ Slash commands synced [PROD]")

            logger.info("Bot setup complete! 🚀")

        except Exception as e:
            logger.critical(f"Fatal error during bot setup: {e}", exc_info=True)
            raise

    async def on_ready(self):
        """Called when bot is ready and connected to Discord."""
        logger.info(f"Bot is ready!")
        logger.info(f"Logged in as: {self.user.name} ({self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guilds")
        logger.info(f"Serving {sum(g.member_count for g in self.guilds):,} users")

        activity = discord.Activity(
            type=discord.ActivityType.playing,
            name=f"/help | r help | Serving {len(self.guilds)} servers",
        )
        await self.change_presence(activity=activity)

        logger.info("RIKI RPG Bot is now online! 🎮")

    async def safe_send(self, ctx: commands.Context, embed: discord.Embed, ephemeral: bool = True):
        """
        Safely send messages that might be ephemeral.

        Ensures no errors for prefix commands (which don't support ephemeral).
        """
        try:
            if hasattr(ctx, "interaction") and ctx.interaction:
                await ctx.send(embed=embed, ephemeral=ephemeral)
            else:
                await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error sending message: {e}")

    async def on_command_error(self, ctx: commands.Context, error: Exception):
        """Global error handler for prefix commands."""
        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, commands.CommandInvokeError):
            original = error.original

            if isinstance(original, RateLimitError):
                embed = EmbedBuilder.warning(
                    title="Rate Limited",
                    description=f"Please wait **{original.retry_after:.1f}s** before using this command again.",
                    footer="Rate limits prevent spam and ensure fair usage",
                )
                return await self.safe_send(ctx, embed)

            if isinstance(original, InsufficientResourcesError):
                embed = EmbedBuilder.error(
                    title="Insufficient Resources",
                    description=f"You need **{original.required:,}** {original.resource}, but only have **{original.current:,}**.",
                    help_text=f"Gain more {original.resource} and try again!",
                )
                return await self.safe_send(ctx, embed)

            if isinstance(original, RIKIException):
                embed = EmbedBuilder.error(
                    title="Error",
                    description=original.message,
                    help_text="If this persists, contact support",
                )
                return await self.safe_send(ctx, embed)

        if isinstance(error, commands.MissingRequiredArgument):
            embed = EmbedBuilder.error(
                title="Missing Argument",
                description=f"Missing required argument: `{error.param.name}`",
                help_text=f"Use `/help {ctx.command.name}` for correct usage",
            )
            return await self.safe_send(ctx, embed)

        if isinstance(error, commands.BadArgument):
            embed = EmbedBuilder.error(
                title="Invalid Argument",
                description=str(error),
                help_text=f"Use `/help {ctx.command.name}` for correct usage",
            )
            return await self.safe_send(ctx, embed)

        if isinstance(error, commands.CheckFailure):
            embed = EmbedBuilder.error(
                title="Permission Denied",
                description="You don't have permission to use this command.",
                footer="Some commands require specific roles or permissions",
            )
            return await self.safe_send(ctx, embed)

        if isinstance(error, commands.CommandOnCooldown):
            embed = EmbedBuilder.warning(
                title="Command On Cooldown",
                description=f"Please wait **{error.retry_after:.1f}s** before using this command again.",
                footer="Cooldowns ensure fair usage",
            )
            return await self.safe_send(ctx, embed)

        # Unexpected errors
        logger.error(f"Unhandled error in command {ctx.command}: {error}", exc_info=error)
        embed = EmbedBuilder.error(
            title="Something Went Wrong",
            description="An unexpected error occurred while processing your command.",
            help_text="Our team has been notified. Please try again later.",
        )
        await self.safe_send(ctx, embed)

    async def on_guild_join(self, guild: discord.Guild):
        """Called when bot joins a new guild."""
        logger.info(f"Joined new guild: {guild.name} (ID: {guild.id}, Members: {guild.member_count})")

        activity = discord.Activity(
            type=discord.ActivityType.playing,
            name=f"/help | r help | Serving {len(self.guilds)} servers",
        )
        await self.change_presence(activity=activity)

        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            embed = EmbedBuilder.success(
                title="Thanks for adding RIKI RPG! 🎮",
                description="Welcome to RIKI RPG! An epic Discord RPG featuring maiden collection, fusion, and strategic gameplay.\n\nGet started with `/register` or `r register`!",
                footer="Use /help to see all commands",
            )
            embed.add_field(
                name="Quick Start",
                value="1. **Register**: `/register`\n2. **Pray**: `/pray`\n3. **Summon**: `/summon`\n4. **Fuse**: `/fusion`",
                inline=False,
            )
            embed.add_field(
                name="Need Help?",
                value="• Use `/help` for command list\n• Join our support server (link in profile)",
                inline=False,
            )
            try:
                await guild.system_channel.send(embed=embed)
            except discord.HTTPException:
                pass

    async def on_guild_remove(self, guild: discord.Guild):
        """Called when bot is removed from a guild."""
        logger.info(f"Removed from guild: {guild.name} (ID: {guild.id})")
        activity = discord.Activity(
            type=discord.ActivityType.playing,
            name=f"/help | r help | Serving {len(self.guilds)} servers",
        )
        await self.change_presence(activity=activity)

    async def close(self):
        """Graceful shutdown procedure."""
        logger.info("Shutting down RIKI RPG Bot...")

        try:
            logger.info("Closing database connections...")
            await DatabaseService.close()
            logger.info("✓ Database closed [SUCCESS]")
        except Exception as e:
            logger.error(f"Error closing database: {e}", exc_info=True)

        try:
            logger.info("Closing Redis connections...")
            await RedisService.close()
            logger.info("✓ Redis closed [SUCCESS]")
        except Exception as e:
            logger.error(f"Error closing Redis: {e}", exc_info=True)

        await super().close()
        logger.info("Bot shutdown complete. 👋")


async def main():
    """Main entry point for the bot."""
    try:
        Config.validate()
    except Exception as e:
        logger.critical(f"Configuration validation failed: {e}")
        sys.exit(1)

    bot = RIKIBot()

    try:
        logger.info("Starting RIKI RPG Bot...")
        await bot.start(Config.DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.critical("Failed to login: Invalid Discord token")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Failed to start bot: {e}", exc_info=True)
        sys.exit(1)
