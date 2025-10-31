import discord
from discord.ext import commands
from typing import Optional

from src.services.database_service import DatabaseService
from src.services.player_service import PlayerService
from src.services.daily_service import DailyService
from src.services.transaction_logger import TransactionLogger
from src.services.event_bus import EventBus
from src.services.resource_service import ResourceService
from src.exceptions import CooldownError
from src.services.logger import get_logger
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class DailyCog(commands.Cog):
    """
    Daily rewards system.

    Players can claim daily rewards once per 24 hours. Rewards include
    rikis, grace, and bonus items based on streak. Leader and class modifiers
    can further increase rewards.

    RIKI LAW Compliance:
        - SELECT FOR UPDATE (Article I.1)
        - Transaction logging (Article I.2)
        - ConfigManager for rewards (Article I.4)
        - Specific exception handling (Article I.5)
        - All logic through DailyService (Article I.7)
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="daily",
        aliases=["rd"],
        description="Claim your daily rewards",
    )
    @ratelimit(uses=5, per_seconds=60, command_name="daily")
    async def daily(self, ctx: commands.Context):
        """Claim daily rewards."""
        await ctx.defer()

        try:
            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(
                    session, ctx.author.id, lock=True
                )

                if not player:
                    embed = EmbedBuilder.error(
                        title="Not Registered",
                        description="You need to register first!",
                        help_text="Use `/register` to create your account.",
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return

                result = await DailyService.claim_daily(session, player)

                await TransactionLogger.log_transaction(
                    player_id=ctx.author.id,
                    transaction_type="daily_claimed",
                    details={
                        "rikis_gained": result["rikis_gained"],
                        "grace_gained": result["grace_gained"],
                        "streak": result["streak"],
                        "bonus_applied": result.get("bonus_applied", False),
                        "modifiers_applied": result.get("modifiers_applied", {}),
                    },
                    context=f"command:/{ctx.command.name} guild:{ctx.guild.id if ctx.guild else 'DM'}",
                )

                await EventBus.publish(
                    "daily_claimed",
                    {
                        "player_id": ctx.author.id,
                        "streak": result["streak"],
                        "timestamp": discord.utils.utcnow(),
                    },
                )

            # --- Embed Construction ---
            embed = EmbedBuilder.success(
                title="🎁 Daily Rewards Claimed!",
                description=(
                    f"You've successfully claimed your daily rewards!\n\n"
                    f"**Day {result['streak']} Streak** 🔥"
                ),
                footer="Come back tomorrow for more rewards!",
            )

            embed.add_field(
                name="💰 Rewards Received",
                value=f"**+{result['rikis_gained']:,}** Rikis\n**+{result['grace_gained']}** Grace",
                inline=True,
            )

            if result.get("bonus_applied"):
                embed.add_field(
                    name="🎉 Streak Bonus",
                    value=f"**+{result.get('bonus_amount', 0):,}** extra rikis!\nKeep your streak going!",
                    inline=True,
                )

            # 🔹 NEW: Display applied modifiers (leader/class bonuses)
            modifiers = result.get("modifiers_applied", {})
            income_boost = modifiers.get("income_boost", 1.0)
            xp_boost = modifiers.get("xp_boost", 1.0)

            if income_boost > 1.0 or xp_boost > 1.0:
                lines = []
                if income_boost > 1.0:
                    lines.append(f"💰 **Income Boost:** +{(income_boost - 1.0) * 100:.0f}%")
                if xp_boost > 1.0:
                    lines.append(f"📈 **XP Boost:** +{(xp_boost - 1.0) * 100:.0f}%")
                embed.add_field(
                    name="✨ Modifier Bonus",
                    value="\n".join(lines),
                    inline=False,
                )

            embed.add_field(
                name="⏰ Next Daily",
                value="Available in 24 hours\nDon't break your streak!",
                inline=False,
            )

            view = DailyActionView(ctx.author.id)
            await ctx.send(embed=embed, view=view)

        except CooldownError as e:
            hours = int(e.remaining_seconds // 3600)
            minutes = int((e.remaining_seconds % 3600) // 60)

            embed = EmbedBuilder.warning(
                title="Daily Rewards On Cooldown",
                description=(
                    f"You've already claimed your daily rewards!\n\n"
                    f"⏰ **Next claim in:** {hours}h {minutes}m"
                ),
                footer="Daily rewards reset every 24 hours",
            )

            embed.add_field(
                name="💡 While You Wait",
                value=(
                    "• Use `/pray` to gain grace\n"
                    "• Use `/summon` to get maidens\n"
                    "• Try `/fusion` to upgrade your collection"
                ),
                inline=False,
            )

            await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Daily claim error for {ctx.author.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Daily Claim Failed",
                description="An error occurred while claiming daily rewards.",
                help_text="Please try again in a moment.",
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.command(name="rd", hidden=True)
    async def daily_short(self, ctx: commands.Context):
        """Alias: rd -> daily"""
        await self.daily(ctx)


class DailyActionView(discord.ui.View):
    """Action buttons after daily claim."""

    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.message: Optional[discord.Message] = None

    def set_message(self, message: discord.Message):
        self.message = message

    @discord.ui.button(
        label="📊 View Profile",
        style=discord.ButtonStyle.primary,
        custom_id="profile_after_daily",
    )
    async def profile_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button is not for you!", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Use `/profile` to view your updated stats!", ephemeral=True
        )

    @discord.ui.button(
        label="✨ Summon",
        style=discord.ButtonStyle.success,
        custom_id="summon_after_daily",
    )
    async def summon_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button is not for you!", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Use `/summon` to summon maidens with your grace!", ephemeral=True
        )

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(DailyCog(bot))
