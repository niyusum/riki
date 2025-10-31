import discord
from discord.ext import commands
from typing import Optional

from src.services.database_service import DatabaseService
from src.services.player_service import PlayerService
from src.services.resource_service import ResourceService
from src.database.models.player import Player
from src.exceptions import PlayerNotFoundError
from src.services.logger import get_logger
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class MeCog(commands.Cog):
    """
    Player profile display system.

    Shows detailed player information: resources, progression, and collection metrics.
    Public for all viewers (including self), fully read-only.

    RIKI LAW Compliance:
        - Read-only (no locks, Article I.11)
        - Player activity tracking (Article I.7)
        - Specific exception handling (Article I.5)
        - Command/Query separation (Article I.11)
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="me",
        aliases=["rme"],
        description="View your player profile and stats",
    )
    async def me(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """
        Display player profile.

        Shows all major stats, resources, fusion history, and collection metrics.
        Always public.
        """
        await ctx.defer()

        target = user or ctx.author

        try:
            async with DatabaseService.get_transaction() as session:
                player = await PlayerService.get_player_with_regen(
                    session, target.id, lock=False
                )

                if not player:
                    if target.id == ctx.author.id:
                        embed = EmbedBuilder.error(
                            title="Not Registered",
                            description="You haven't registered yet!",
                            help_text="Use `/register` to create your account.",
                        )
                    else:
                        embed = EmbedBuilder.error(
                            title="Player Not Found",
                            description=f"{target.mention} hasn't registered yet.",
                            footer="They can use /register to join RIKI RPG.",
                        )
                    await ctx.send(embed=embed)
                    return

                # 🧭 Build main profile embed
                title = f"{target.display_name}'s Profile"
                embed = EmbedBuilder.player_stats(player, title=title)

                # ⚗️ Fusion summary
                success_rate = player.calculate_fusion_success_rate()
                embed.add_field(
                    name="⚗️ Fusion Stats",
                    value=(
                        f"**Success:** {player.successful_fusions}/{player.total_fusions}\n"
                        f"**Rate:** {success_rate:.1f}%\n"
                        f"**Highest:** Tier {player.highest_tier_achieved}"
                    ),
                    inline=True,
                )

                # 🔷 Fusion shards summary
                total_shards = sum(player.fusion_shards.values())
                early = sum(
                    player.fusion_shards.get(k, 0)
                    for k in ("tier_1", "tier_2", "tier_3")
                )
                embed.add_field(
                    name="🔷 Fusion Shards",
                    value=f"**Total:** {total_shards}\n**T1–T3:** {early}\n**T4+:** {total_shards - early}",
                    inline=True,
                )

                # 🌟 Active Modifiers Section
                try:
                    summary = ResourceService.get_resource_summary(player)
                    modifiers = summary.get("modifiers", {})
                    income_boost = modifiers.get("income_boost", 1.0)
                    xp_boost = modifiers.get("xp_boost", 1.0)

                    if income_boost > 1.0 or xp_boost > 1.0:
                        bonus_lines = []
                        if income_boost > 1.0:
                            bonus_lines.append(f"💰 **Income Boost:** +{(income_boost - 1.0) * 100:.0f}%")
                        if xp_boost > 1.0:
                            bonus_lines.append(f"📈 **XP Boost:** +{(xp_boost - 1.0) * 100:.0f}%")
                        embed.add_field(
                            name="✨ Active Modifiers",
                            value="\n".join(bonus_lines),
                            inline=False,
                        )
                    else:
                        embed.add_field(
                            name="✨ Active Modifiers",
                            value="None active",
                            inline=False,
                        )
                except Exception as e:
                    logger.warning(f"Failed to load modifiers for {target.id}: {e}")

                # Thumbnail and footer
                embed.set_thumbnail(url=target.display_avatar.url)
                days = (discord.utils.utcnow() - player.created_at).days
                embed.set_footer(
                    text=f"Player ID: {player.discord_id} • Joined {days} days ago"
                )

                view = ProfileActionView(ctx.author.id)
                await ctx.send(embed=embed, view=view)  # <-- Always public

        except Exception as e:
            logger.error(f"Profile load error for {target.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Profile Error",
                description="Unable to load profile data.",
                help_text="Please try again shortly.",
            )
            await ctx.send(embed=embed)


class ProfileActionView(discord.ui.View):
    """Action buttons under profile display."""

    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

    @discord.ui.button(label="🎴 Collection", style=discord.ButtonStyle.primary)
    async def collection(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button isn’t for you!", ephemeral=True)
            return
        await interaction.response.send_message("Use `/collection` to view your maidens.", ephemeral=True)

    @discord.ui.button(label="🙏 Pray", style=discord.ButtonStyle.success)
    async def pray(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button isn’t for you!", ephemeral=True)
            return
        await interaction.response.send_message("Use `/pray` to gain grace!", ephemeral=True)

    @discord.ui.button(label="✨ Summon", style=discord.ButtonStyle.success)
    async def summon(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button isn’t for you!", ephemeral=True)
            return
        await interaction.response.send_message("Use `/summon` to call new maidens!", ephemeral=True)

    @discord.ui.button(label="📊 Stats", style=discord.ButtonStyle.secondary)
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button isn’t for you!", ephemeral=True)
            return
        await interaction.response.send_message("Use `/stats` for detailed analytics.", ephemeral=True)

    async def on_timeout(self):
        for i in self.children:
            i.disabled = True


async def setup(bot: commands.Bot):
    """Required for Discord cog loading."""
    await bot.add_cog(MeCog(bot))
