import discord
from discord.ext import commands
from typing import Optional

from src.services.database_service import DatabaseService
from src.services.player_service import PlayerService
from src.services.redis_service import RedisService
from src.services.transaction_logger import TransactionLogger
from src.services.event_bus import EventBus
from src.services.resource_service import ResourceService
from src.exceptions import InsufficientResourcesError, ValidationError
from src.services.logger import get_logger
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class PrayCog(commands.Cog):
    """
    Prayer system for grace generation.

    Players spend prayer charges to gain grace, which is used for summoning maidens.
    Prayer charges regenerate over time. Class and leader bonuses affect grace gained.

    RIKI LAW Compliance:
        - SELECT FOR UPDATE on state changes (Article I.1)
        - Transaction logging (Article I.2)
        - Redis locks for multi-prayer (Article I.3)
        - ConfigManager for all values (Article I.4)
        - Specific exception handling (Article I.5)
        - Single commit per transaction (Article I.6)
        - All logic through PlayerService (Article I.7)
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="pray",
        aliases=["rp"],
        description="Perform prayers to gain grace for summoning",
    )
    @ratelimit(uses=10, per_seconds=60, command_name="pray")
    async def pray(self, ctx: commands.Context, charges: Optional[int] = 1):
        """Perform prayers to gain grace."""
        await ctx.defer()

        try:
            if charges < 1:
                raise ValidationError("charges", "Must pray at least 1 time")
            if charges > 5:
                raise ValidationError("charges", "Cannot pray more than 5 times at once")

            async with RedisService.acquire_lock(f"pray:{ctx.author.id}", timeout=5):
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

                    if player.prayer_charges < charges:
                        raise InsufficientResourcesError(
                            resource="prayer charges",
                            required=charges,
                            current=player.prayer_charges,
                        )

                    result = await PlayerService.perform_prayer(
                        session, player, charges_to_spend=charges
                    )

                    await TransactionLogger.log_transaction(
                        player_id=ctx.author.id,
                        transaction_type="prayer_performed",
                        details={
                            "charges_spent": charges,
                            "grace_gained": result["grace_gained"],
                            "class_bonus": result.get("class_bonus", 0),
                            "remaining_charges": result["remaining_charges"],
                            "modifiers_applied": result.get("modifiers_applied", {}),
                        },
                        context=f"command:/{ctx.command.name} guild:{ctx.guild.id if ctx.guild else 'DM'}",
                    )

                    await EventBus.publish(
                        "prayer_completed",
                        {
                            "player_id": ctx.author.id,
                            "charges_spent": charges,
                            "grace_gained": result["grace_gained"],
                            "channel_id": ctx.channel.id,
                            "__topic__": "prayer_completed",
                            "timestamp": discord.utils.utcnow(),
                        },
                    )

                    # --- Embed Construction ---
                    embed = EmbedBuilder.success(
                        title="🙏 Prayer Complete",
                        description=(
                            f"Your prayers have been answered!\n\n"
                            f"You gained **{result['grace_gained']} Grace**."
                        ),
                        footer=f"Total Grace: {result['total_grace']}",
                    )

                    embed.add_field(
                        name="Prayer Charges",
                        value=(
                            f"**Remaining:** {result['remaining_charges']}/{player.max_prayer_charges}\n"
                            f"**Next Regen:** {player.get_prayer_regen_display()}"
                        ),
                        inline=True,
                    )

                    # Class bonus (existing)
                    if result.get("class_bonus", 0) > 0:
                        embed.add_field(
                            name="✨ Class Bonus",
                            value=f"+{result['class_bonus']} grace from **{player.player_class}** class",
                            inline=True,
                        )

                    # NEW: Active modifier bonuses (leader/class effects)
                    modifiers = result.get("modifiers_applied", {})
                    income_boost = modifiers.get("income_boost", 1.0)
                    xp_boost = modifiers.get("xp_boost", 1.0)

                    if income_boost > 1.0 or xp_boost > 1.0:
                        bonus_lines = []
                        if income_boost > 1.0:
                            bonus_lines.append(f"💰 **Grace Boost:** +{(income_boost - 1.0) * 100:.0f}%")
                        if xp_boost > 1.0:
                            bonus_lines.append(f"📈 **XP Bonus:** +{(xp_boost - 1.0) * 100:.0f}%")
                        embed.add_field(
                            name="🌟 Active Modifiers",
                            value="\n".join(bonus_lines),
                            inline=False,
                        )

                    embed.add_field(
                        name="💡 Tip",
                        value="Prayer charges regenerate every 5 minutes. Use them regularly to maximize grace!",
                        inline=False,
                    )

                    view = PrayActionView(ctx.author.id, result["total_grace"])
                    await ctx.send(embed=embed, view=view)

        except InsufficientResourcesError as e:
            embed = EmbedBuilder.error(
                title="Insufficient Prayer Charges",
                description=f"You need **{e.required}** prayer charges, but only have **{e.current}**.",
                help_text="Prayer charges regenerate every 5 minutes. Wait a bit and try again!",
            )

            try:
                async with DatabaseService.get_transaction() as session:
                    player = await PlayerService.get_player_with_regen(
                        session, ctx.author.id, lock=False
                    )
                    if player:
                        embed.add_field(
                            name="⏳ Next Charge",
                            value=f"Regenerates in: {player.get_prayer_regen_display()}",
                            inline=False,
                        )
            except Exception:
                pass

            await ctx.send(embed=embed, ephemeral=True)

        except ValidationError as e:
            embed = EmbedBuilder.error(
                title="Invalid Input",
                description=str(e),
                help_text="You can pray 1–5 times at once. Example: `/pray charges:3`",
            )
            await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Prayer error for user {ctx.author.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Prayer Failed",
                description="An error occurred while performing prayers.",
                help_text="Please try again in a moment.",
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.command(name="rp", hidden=True)
    async def pray_short(self, ctx: commands.Context, charges: Optional[int] = 1):
        """Alias: rp -> pray"""
        await self.pray(ctx, charges)


class PrayActionView(discord.ui.View):
    """Action buttons after prayer completion."""

    def __init__(self, user_id: int, total_grace: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.total_grace = total_grace
        self.message: Optional[discord.Message] = None

        if total_grace < 1:
            self.summon_button.disabled = True

    def set_message(self, message: discord.Message):
        self.message = message

    @discord.ui.button(
        label="✨ Summon Now",
        style=discord.ButtonStyle.primary,
        custom_id="quick_summon_after_pray",
    )
    async def summon_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        await interaction.response.send_message(
            f"You have **{self.total_grace}** grace available!\nUse `/summon` to summon powerful maidens.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="🔁 Pray Again",
        style=discord.ButtonStyle.success,
        custom_id="pray_again",
    )
    async def pray_again_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        await interaction.response.send_message(
            "Use `/pray` to continue praying and gaining more grace!", ephemeral=True
        )

    @discord.ui.button(
        label="📊 View Profile",
        style=discord.ButtonStyle.secondary,
        custom_id="view_profile_after_pray",
    )
    async def profile_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        await interaction.response.send_message(
            "Use `/profile` to view your updated stats!", ephemeral=True
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(PrayCog(bot))
