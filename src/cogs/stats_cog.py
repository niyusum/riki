import discord
from discord.ext import commands
from typing import Optional, Dict, Any

from src.services.database_service import DatabaseService
from src.services.player_service import PlayerService
from src.database.models.player import Player
from src.services.logger import get_logger
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


def _safe_value(text: str, limit: int = 1024) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _as_dict(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _fusion_success_rate(player: Player) -> float:
    # Prefer model method if present
    method = getattr(player, "calculate_fusion_success_rate", None)
    if callable(method):
        try:
            rate = float(method())
            return max(0.0, min(rate, 100.0))
        except Exception:
            pass
    # Fallback using stats JSON
    stats = _as_dict(getattr(player, "stats", None))
    successes = int(stats.get("fusions_successful", 0))
    total = int(getattr(player, "total_fusions", 0)) or int(stats.get("fusions_total", 0)) or 0
    if total <= 0:
        return 0.0
    return round((successes / total) * 100.0, 1)


class StatsCog(commands.Cog):
    """
    Detailed statistics display system.

    Shows comprehensive analytics including summon rates, fusion success,
    resource usage, and progression metrics.

    RIKI LAW Compliance:
        - Read-only (no locks needed, Article I.11)
        - Command/Query separation (Article I.11)
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="stats",
        description="View detailed statistics and analytics",
    )
    async def stats(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """
        Display detailed player statistics.

        Args:
            user: Target player (optional, defaults to command user)
        """
        await ctx.defer()

        target_user = user or ctx.author

        try:
            async with DatabaseService.get_transaction() as session:
                try:
                    player: Optional[Player] = await PlayerService.get_player_with_regen(
                        session, target_user.id, lock=False
                    )
                except Exception as db_error:
                    logger.exception(f"[{ctx.command}] DB error during stats fetch for {target_user.id}: {db_error}")
                    await ctx.send(
                        embed=EmbedBuilder.error(
                            title="Database Error",
                            description="Something went wrong fetching player data.",
                            help_text="Please try again later.",
                        ),
                        ephemeral=True,
                    )
                    return

                if not player:
                    if target_user == ctx.author:
                        embed = EmbedBuilder.error(
                            title="Not Registered",
                            description="You haven't registered yet!",
                            help_text="Use `/register` to create your account.",
                        )
                    else:
                        embed = EmbedBuilder.error(
                            title="Player Not Found",
                            description=f"{target_user.mention} hasn't registered yet.",
                        )
                    await ctx.send(embed=embed, ephemeral=True)
                    return

                level = int(getattr(player, "level", 0))
                created_at = getattr(player, "created_at", None)
                created_ts = int(created_at.timestamp()) if created_at else None

                title = f"📊 {target_user.name}'s Statistics"
                desc_parts = [f"Level {level}"]
                if created_ts:
                    desc_parts.append(f"Playing since <t:{created_ts}:D>")

                embed = EmbedBuilder.primary(
                    title=title,
                    description=" • ".join(desc_parts),
                    footer=f"Player ID: {getattr(player, 'discord_id', target_user.id)}",
                )
                embed.timestamp = discord.utils.utcnow()

                total_summons = int(getattr(player, "total_summons", 0))
                pity_counter = int(getattr(player, "pity_counter", 0))
                unique_maidens = int(getattr(player, "unique_maidens", 0))
                pity_percentage = (pity_counter / 90) * 100 if pity_counter > 0 else 0.0

                embed.add_field(
                    name="✨ Summon Statistics",
                    value=_safe_value(
                        f"**Total Summons:** {total_summons:,}\n"
                        f"**Pity Counter:** {pity_counter}/90 ({pity_percentage:.1f}%)\n"
                        f"**Unique Maidens:** {unique_maidens:,}"
                    ),
                    inline=True,
                )

                total_fusions = int(getattr(player, "total_fusions", 0))
                success_rate = _fusion_success_rate(player)
                fusion_shards: Dict[str, int] = _as_dict(getattr(player, "fusion_shards", None))
                total_shards = int(sum(int(v or 0) for v in fusion_shards.values()))

                embed.add_field(
                    name="⚗️ Fusion Statistics",
                    value=_safe_value(
                        f"**Total Fusions:** {total_fusions:,}\n"
                        f"**Success Rate:** {success_rate:.1f}%\n"
                        f"**Fusion Shards:** {total_shards:,}"
                    ),
                    inline=True,
                )

                total_maidens_owned = int(getattr(player, "total_maidens_owned", 0))
                highest_tier_achieved = getattr(player, "highest_tier_achieved", "—")
                total_power = getattr(player, "get_power_display", None)
                total_power_str = total_power() if callable(total_power) else f"{int(getattr(player, 'total_power', 0)):,}"

                embed.add_field(
                    name="🎴 Collection",
                    value=_safe_value(
                        f"**Total Maidens:** {total_maidens_owned:,}\n"
                        f"**Highest Tier:** {highest_tier_achieved}\n"
                        f"**Total Power:** {total_power_str}"
                    ),
                    inline=True,
                )

                rikis = int(getattr(player, "rikis", 0))
                grace = int(getattr(player, "grace", 0))
                gems = int(getattr(player, "riki_gems", 0))

                embed.add_field(
                    name="💰 Resources",
                    value=_safe_value(
                        f"**Rikis:** {rikis:,}\n"
                        f"**Grace:** {grace:,}\n"
                        f"**Gems:** {gems:,}"
                    ),
                    inline=True,
                )

                stats_json = _as_dict(getattr(player, "stats", None))
                prayers_performed = int(stats_json.get("prayers_performed", 0))
                prayer_charges = int(getattr(player, "prayer_charges", 0))
                max_prayer_charges = int(getattr(player, "max_prayer_charges", 0))
                regen_disp = getattr(player, "get_prayer_regen_display", None)
                next_regen_str = regen_disp() if callable(regen_disp) else "—"

                embed.add_field(
                    name="🙏 Prayer Statistics",
                    value=_safe_value(
                        f"**Total Prayers:** {prayers_performed:,}\n"
                        f"**Current Charges:** {prayer_charges}/{max_prayer_charges}\n"
                        f"**Next Regen:** {next_regen_str}"
                    ),
                    inline=True,
                )

                experience = int(getattr(player, "experience", 0))
                level_ups = int(stats_json.get("level_ups", 0))
                player_class = getattr(player, "player_class", None) or "None"

                embed.add_field(
                    name="📈 Progression",
                    value=_safe_value(
                        f"**Experience:** {experience:,}\n"
                        f"**Level Ups:** {level_ups:,}\n"
                        f"**Class:** {player_class}"
                    ),
                    inline=True,
                )

                rikis_earned = int(stats_json.get("total_rikis_earned", 0))
                rikis_spent = int(stats_json.get("total_rikis_spent", 0))
                net_rikis = rikis_earned - rikis_spent

                embed.add_field(
                    name="💹 Economy Statistics",
                    value=_safe_value(
                        f"**Earned:** {rikis_earned:,} rikis\n"
                        f"**Spent:** {rikis_spent:,} rikis\n"
                        f"**Net:** {net_rikis:,} rikis"
                    ),
                    inline=False,
                )

                if total_shards > 0:
                    sorted_shards = sorted(
                        ((k, int(v or 0)) for k, v in fusion_shards.items()),
                        key=lambda x: x[1],
                        reverse=True,
                    )[:3]
                    shard_text = "\n".join(
                        f"**{tier.replace('_', ' ').title()}:** {count:,}" for tier, count in sorted_shards if count > 0
                    ) or "No shards collected yet"
                    embed.add_field(
                        name="🔷 Top Fusion Shards",
                        value=_safe_value(shard_text),
                        inline=True,
                    )

                if target_user.display_avatar:
                    embed.set_thumbnail(url=target_user.display_avatar.url)

                view = StatsActionView(ctx.author.id)
                message = await ctx.send(embed=embed, view=view)
                view.set_message(message)

        except Exception as e:
            logger.error(f"[{getattr(ctx, 'command', None)}] Stats display error for {target_user.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Stats Error",
                description="Unable to load statistics.",
                help_text="Please try again in a moment.",
            )
            await ctx.send(embed=embed, ephemeral=True)


class StatsActionView(discord.ui.View):
    """Action buttons for stats view."""

    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.message: Optional[discord.Message] = None

    def set_message(self, message: discord.Message) -> None:
        self.message = message

    @discord.ui.button(
        label="👤 Profile",
        style=discord.ButtonStyle.primary,
        custom_id="view_profile_from_stats",
    )
    async def profile_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return
        await interaction.response.send_message("Use `/profile` to view your basic profile!", ephemeral=True)

    @discord.ui.button(
        label="🎴 Collection",
        style=discord.ButtonStyle.secondary,
        custom_id="view_collection_from_stats",
    )
    async def collection_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return
        await interaction.response.send_message("Use `/collection` to view your maiden collection!", ephemeral=True)

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
    await bot.add_cog(StatsCog(bot))
