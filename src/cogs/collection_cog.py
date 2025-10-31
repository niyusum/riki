import discord
from discord.ext import commands
from typing import Optional, List
import math

from src.services.database_service import DatabaseService
from src.services.maiden_service import MaidenService
from src.database.models.player import Player
from src.services.logger import get_logger
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class CollectionCog(commands.Cog):
    """
    Maiden collection display system.

    Shows player's maiden collection with pagination, filtering by tier/element,
    and sorting options. Read-only command optimized for fast queries.

    RIKI LAW Compliance:
        - No locks (read-only, Article I.11)
        - Command/Query separation (Article I.11)
        - Efficient pagination
        - Specific exception handling (Article I.5)
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="collection",
        aliases=["maidens", "rm"],
        description="View your maiden collection",
    )
    async def collection(
        self,
        ctx: commands.Context,
        tier: Optional[int] = None,
        element: Optional[str] = None,
        page: int = 1,
    ):
        """View maiden collection with optional filtering."""
        await ctx.defer()  # public

        try:
            # Validate input filters
            if tier is not None and (tier < 1 or tier > 12):
                embed = EmbedBuilder.error(
                    title="Invalid Tier",
                    description=f"Tier must be between 1 and 12. You entered: {tier}",
                    help_text="Example: `/collection tier:5`",
                )
                await ctx.send(embed=embed, ephemeral=True)
                return

            if element is not None:
                valid_elements = [
                    "infernal",
                    "umbral",
                    "earth",
                    "tempest",
                    "radiant",
                    "abyssal",
                ]
                element = element.lower()
                if element not in valid_elements:
                    embed = EmbedBuilder.error(
                        title="Invalid Element",
                        description=f"Element must be one of: {', '.join(valid_elements)}",
                        help_text="Example: `/collection element:infernal`",
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return

            async with DatabaseService.get_transaction() as session:
                player = await session.get(Player, ctx.author.id)
                if not player:
                    embed = EmbedBuilder.error(
                        title="Not Registered",
                        description="You need to register first!",
                        help_text="Use `/register` to create your account.",
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return

                maidens = await MaidenService.get_player_maidens(
                    session,
                    player.discord_id,
                    tier_filter=tier,
                    element_filter=element,
                )

                if not maidens:
                    filter_desc = ""
                    if tier:
                        filter_desc += f" at Tier {tier}"
                    if element:
                        filter_desc += f" with {element.title()} element"

                    embed = EmbedBuilder.warning(
                        title="No Maidens Found",
                        description=f"You don't have any maidens{filter_desc}.",
                        footer="Tip: Use /summon to get maidens!",
                    )
                    embed.add_field(
                        name="Get Started",
                        value=(
                            "• Use `/pray` to gain grace\n"
                            "• Use `/summon` to get maidens\n"
                            "• Try `/collection` without filters"
                        ),
                        inline=False,
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return

                # Pagination
                per_page = 10
                total_pages = max(1, math.ceil(len(maidens) / per_page))
                page = max(1, min(page, total_pages))
                start_idx = (page - 1) * per_page
                end_idx = min(start_idx + per_page, len(maidens))
                page_maidens = maidens[start_idx:end_idx]

                filter_text = ""
                if tier:
                    filter_text += f" • Tier {tier}"
                if element:
                    filter_text += f" • {element.title()}"

                title = f"🎴 {ctx.author.name}'s Collection{filter_text}"

                embed = EmbedBuilder.primary(
                    title=title,
                    description=f"Showing {len(maidens)} maiden{'s' if len(maidens) != 1 else ''}",
                    footer=f"Page {page}/{total_pages} • Total Power: {player.get_power_display()}",
                )

                # Add maiden entries
                for maiden in page_maidens:
                    name = maiden.get("name", "Unknown")
                    m_tier = maiden.get("tier", 1)
                    m_element = maiden.get("element", "unknown")
                    quantity = maiden.get("quantity", 1)
                    attack = maiden.get("attack", 0)
                    defense = maiden.get("defense", 0)
                    element_emoji = maiden.get("element_emoji", "❓")

                    field_name = f"{element_emoji} {name} (Tier {m_tier})"
                    if quantity > 1:
                        field_name += f" ×{quantity}"

                    field_value = f"ATK: {attack:,} • DEF: {defense:,}\nPower: {attack + defense:,}"

                    embed.add_field(name=field_name, value=field_value, inline=True)

                stats_text = (
                    f"**Total Maidens:** {player.total_maidens_owned}\n"
                    f"**Unique:** {player.unique_maidens}\n"
                    f"**Highest Tier:** {player.highest_tier_achieved}"
                )

                embed.add_field(
                    name="📊 Collection Stats", value=stats_text, inline=False
                )

                if total_pages > 1:
                    view = CollectionPaginationView(
                        ctx.author.id, page, total_pages, tier, element
                    )
                    await ctx.send(embed=embed, view=view)
                else:
                    await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Collection display error for {ctx.author.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Collection Error",
                description="Unable to load collection.",
                help_text="Please try again in a moment.",
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.command(name="rm", hidden=True)
    async def collection_short(self, ctx: commands.Context):
        """Alias: rm -> collection"""
        await self.collection(ctx)

    @commands.command(name="maidens", hidden=True)
    async def maidens_alias(self, ctx: commands.Context):
        """Alias: maidens -> collection"""
        await self.collection(ctx)


class CollectionPaginationView(discord.ui.View):
    """Pagination view for collection display."""

    def __init__(
        self,
        user_id: int,
        current_page: int,
        total_pages: int,
        tier_filter: Optional[int],
        element_filter: Optional[str],
    ):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.current_page = current_page
        self.total_pages = total_pages
        self.tier_filter = tier_filter
        self.element_filter = element_filter
        self.message: Optional[discord.Message] = None

        if current_page <= 1:
            self.previous_button.disabled = True
        if current_page >= total_pages:
            self.next_button.disabled = True

    def set_message(self, message: discord.Message):
        self.message = message

    @discord.ui.button(
        label="◀️ Previous",
        style=discord.ButtonStyle.secondary,
        custom_id="collection_previous",
    )
    async def previous_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This collection is not for you!", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Use `/collection page:{self.current_page - 1}` to view the previous page.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Next ▶️",
        style=discord.ButtonStyle.secondary,
        custom_id="collection_next",
    )
    async def next_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This collection is not for you!", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Use `/collection page:{self.current_page + 1}` to view the next page.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="🔍 Filter",
        style=discord.ButtonStyle.primary,
        custom_id="collection_filter",
    )
    async def filter_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This collection is not for you!", ephemeral=True
            )
            return

        embed = EmbedBuilder.info(
            title="Collection Filters",
            description="You can filter your collection by tier and element!",
            footer="Use the command options to apply filters",
        )

        embed.add_field(
            name="Filter by Tier",
            value="`/collection tier:5`\nShows only Tier 5 maidens",
            inline=True,
        )

        embed.add_field(
            name="Filter by Element",
            value="`/collection element:infernal`\nShows only Infernal maidens",
            inline=True,
        )

        embed.add_field(
            name="Combine Filters",
            value="`/collection tier:5 element:infernal`\nShows Tier 5 Infernal maidens only",
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

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
    await bot.add_cog(CollectionCog(bot))
