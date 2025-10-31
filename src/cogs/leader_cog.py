import discord
from discord.ext import commands
from typing import Optional, List, Dict, Any

from src.services.database_service import DatabaseService
from src.services.player_service import PlayerService
from src.services.leader_service import LeaderService
from src.services.transaction_logger import TransactionLogger
from src.database.models.player import Player
from src.exceptions import MaidenNotFoundError
from src.services.logger import get_logger
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class LeaderCog(commands.Cog):
    """
    Leader maiden system for passive bonuses.

    Players set a maiden as leader to gain passive bonuses based on element.
    Leader provides stat bonuses and special effects.

    RIKI LAW Compliance:
        - SELECT FOR UPDATE (Article I.1)
        - Transaction logging (Article I.2)
        - ConfigManager for bonuses (Article I.4)
        - All logic through LeaderService (Article I.7)
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="leader",
        aliases=["rl"],
        description="Set or view your leader maiden",
    )
    @ratelimit(uses=10, per_seconds=60, command_name="leader")
    async def leader(self, ctx: commands.Context):
        """Set or view your leader maiden."""
        await ctx.defer()  # Public now

        try:
            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(
                    session, ctx.author.id, lock=False
                )

                if not player:
                    embed = EmbedBuilder.error(
                        title="Not Registered",
                        description="You need to register first!",
                        help_text="Use `/register` to create your account.",
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return

                current_leader = await LeaderService.get_current_leader(
                    session, player.discord_id
                )
                available_maidens = await LeaderService.get_leader_candidates(
                    session, player.discord_id
                )

                if not available_maidens:
                    embed = EmbedBuilder.warning(
                        title="No Available Maidens",
                        description="You don't have any maidens to set as leader yet!",
                        footer="Get maidens first!",
                    )
                    embed.add_field(
                        name="How to Get Maidens",
                        value="• Use `/pray` for grace\n• Use `/summon` to get maidens",
                        inline=False,
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return

                embed = EmbedBuilder.primary(
                    title="👑 Leader Maiden System",
                    description="Your leader maiden provides passive bonuses based on their element and tier!",
                    footer=f"{len(available_maidens)} maidens available",
                )

                if current_leader:
                    embed.add_field(
                        name="Current Leader",
                        value=(
                            f"**{current_leader['name']}** (Tier {current_leader['tier']})\n"
                            f"{current_leader['element_emoji']} {current_leader['element'].title()}"
                        ),
                        inline=True,
                    )
                    embed.add_field(
                        name="Bonus Active",
                        value=current_leader.get("bonus_description", "No bonus"),
                        inline=True,
                    )
                else:
                    embed.add_field(name="Current Leader", value="None set", inline=True)

                embed.add_field(
                    name="Element Bonuses",
                    value=(
                        "🔥 **Infernal**: +10% Attack\n"
                        "🌑 **Umbral**: +10% Defense\n"
                        "🌍 **Earth**: +5% HP\n"
                        "⚡ **Tempest**: +5% Speed\n"
                        "✨ **Radiant**: +10% Grace gain\n"
                        "🌊 **Abyssal**: +5% All Stats"
                    ),
                    inline=False,
                )

                view = LeaderSelectionView(ctx.author.id, available_maidens)
                message = await ctx.send(embed=embed, view=view)
                view.set_message(message)

        except Exception as e:
            logger.error(f"Leader UI error for {ctx.author.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Leader Error",
                description="Unable to load leader interface.",
                help_text="Please try again in a moment.",
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.command(name="rl", hidden=True)
    async def leader_short(self, ctx: commands.Context):
        """Alias for /leader"""
        await self.leader(ctx)


class LeaderSelectionView(discord.ui.View):
    """Interactive view for selecting or removing leader maidens."""

    def __init__(self, user_id: int, available_maidens: List[Dict[str, Any]]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.available_maidens = available_maidens
        self.message: Optional[discord.Message] = None
        self.add_item(LeaderSelectDropdown(user_id, available_maidens))

    def set_message(self, message: discord.Message):
        self.message = message

    @discord.ui.button(
        label="❌ Remove Leader",
        style=discord.ButtonStyle.danger,
        custom_id="remove_leader",
    )
    async def remove_leader(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ):
        """Remove current leader maiden."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button is not for you!", ephemeral=True
            )
            return

        await interaction.response.defer()

        try:
            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(
                    session, self.user_id, lock=True
                )

                if player:
                    await LeaderService.remove_leader(session, player)
                    await TransactionLogger.log_transaction(
                        player_id=self.user_id,
                        transaction_type="leader_removed",
                        details={},
                        context=f"interaction:remove_leader guild:{interaction.guild_id}",
                    )

            embed = EmbedBuilder.success(
                title="Leader Removed",
                description="Your leader maiden has been unset. Bonuses are no longer active.",
                footer="Set a new leader anytime!",
            )

            await interaction.edit_original_response(embed=embed, view=None)

        except Exception as e:
            logger.error(f"Leader removal error: {e}", exc_info=True)
            await interaction.followup.send(
                "Failed to remove leader. Please try again.", ephemeral=True
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


class LeaderSelectDropdown(discord.ui.Select):
    """Dropdown for selecting leader maiden."""

    def __init__(self, user_id: int, available_maidens: List[Dict[str, Any]]):
        self.user_id = user_id
        self.available_maidens = available_maidens

        options = [
            discord.SelectOption(
                label=f"{m['name']} (T{m['tier']})",
                description=f"{m['element']} • Power: {m.get('power', 0):,}",
                value=str(m["id"]),
                emoji=m.get("element_emoji", "❓"),
            )
            for m in available_maidens[:25]
        ]

        super().__init__(
            placeholder="Select maiden as leader...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This selection is not for you!", ephemeral=True
            )
            return

        await interaction.response.defer()

        maiden_id = int(self.values[0])

        try:
            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(
                    session, self.user_id, lock=True
                )

                if not player:
                    await interaction.followup.send(
                        "Player not found!", ephemeral=True
                    )
                    return

                result = await LeaderService.set_leader(session, player, maiden_id)

                await TransactionLogger.log_transaction(
                    player_id=self.user_id,
                    transaction_type="leader_set",
                    details={
                        "maiden_id": maiden_id,
                        "maiden_name": result["maiden_name"],
                        "element": result["element"],
                    },
                    context=f"interaction:set_leader guild:{interaction.guild_id}",
                )

            embed = EmbedBuilder.success(
                title="Leader Set!",
                description=(
                    f"**{result['maiden_name']}** is now your leader!\n\n"
                    f"{result['element_emoji']} {result['element'].title()} Element"
                ),
                footer="Leader bonuses are now active!",
            )
            embed.add_field(
                name="Active Bonus",
                value=result.get("bonus_description", "No bonus"),
                inline=True,
            )
            embed.add_field(
                name="Leader Stats",
                value=f"Tier {result['tier']}\nPower: {result.get('power', 0):,}",
                inline=True,
            )

            await interaction.edit_original_response(embed=embed, view=None)

        except MaidenNotFoundError as e:
            embed = EmbedBuilder.error(title="Maiden Not Found", description=str(e))
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Leader set error: {e}", exc_info=True)
            await interaction.followup.send(
                "Failed to set leader. Please try again.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderCog(bot))
