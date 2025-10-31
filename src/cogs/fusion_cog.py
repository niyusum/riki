import discord
from discord.ext import commands
from typing import Optional, List, Dict, Any

from src.services.database_service import DatabaseService
from src.services.player_service import PlayerService
from src.services.fusion_service import FusionService
from src.services.redis_service import RedisService
from src.services.transaction_logger import TransactionLogger
from src.services.event_bus import EventBus
from src.exceptions import InsufficientResourcesError, FusionError
from src.services.logger import get_logger
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class FusionCog(commands.Cog):
    """
    Maiden fusion system for tier progression.

    Players fuse two maidens of the same tier to create one maiden of the next tier.
    Success rates decrease at higher tiers. Failed fusions grant shards.

    RIKI LAW Compliance:
        - SELECT FOR UPDATE on fusion (Article I.1)
        - Transaction logging (Article I.2)
        - Redis locks prevent double-fusion (Article I.3)
        - ConfigManager for costs/rates (Article I.4)
        - Specific exception handling (Article I.5)
        - Single commit (Article I.6)
        - All logic through FusionService (Article I.7)
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="fusion",
        aliases=["rf"],
        description="Fuse two maidens to create a higher tier maiden",
    )
    @ratelimit(uses=15, per_seconds=60, command_name="fusion")
    async def fusion(self, ctx: commands.Context):
        """Open the fusion interface."""
        await ctx.defer()  # public fusion interface

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

                fusable_maidens = await FusionService.get_fusable_maidens(
                    session, player.discord_id
                )

                if not fusable_maidens:
                    embed = EmbedBuilder.warning(
                        title="No Fusable Maidens",
                        description=(
                            "You don't have any maidens that can be fused.\n\n"
                            "You need **2 or more** of the same maiden at the same tier to fuse."
                        ),
                        footer="Tip: Summon more maidens to build your collection!",
                    )
                    embed.add_field(
                        name="How to Get Maidens",
                        value="• Use `/summon` to get new maidens\n• Use `/pray` to gain grace for summons\n• Check `/collection` to see what you have",
                        inline=False,
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    return

                embed = EmbedBuilder.primary(
                    title="⚗️ Fusion System",
                    description="Select maidens to fuse into a higher tier!\n\n**Choose carefully:** Fusion has a chance of failure at higher tiers.",
                    footer=f"{len(fusable_maidens)} fusable maidens available",
                )

                # Display by tier
                by_tier: Dict[int, List[Dict[str, Any]]] = {}
                for maiden in fusable_maidens:
                    by_tier.setdefault(maiden["tier"], []).append(maiden)

                tier_text = "\n".join(
                    f"• **Tier {tier}**: {len(maidens)} option{'s' if len(maidens) > 1 else ''}"
                    for tier, maidens in sorted(by_tier.items())
                )

                embed.add_field(
                    name="Available by Tier", value=tier_text or "None", inline=False
                )

                embed.add_field(
                    name="💡 Fusion Tips",
                    value=(
                        "• Higher tiers have lower success rates\n"
                        "• Failed fusions grant fusion shards\n"
                        "• Use shards for guaranteed fusions\n"
                        "• Save your best maidens!"
                    ),
                    inline=False,
                )

                view = FusionSelectionView(ctx.author.id, fusable_maidens)
                await ctx.send(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Fusion UI error for {ctx.author.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Fusion Error",
                description="Unable to load fusion interface.",
                help_text="Please try again in a moment.",
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.command(name="rf", hidden=True)
    async def fusion_short(self, ctx: commands.Context):
        """Alias: rf -> fusion"""
        await self.fusion(ctx)


class FusionSelectionView(discord.ui.View):
    """Interactive view for selecting maidens to fuse."""

    def __init__(self, user_id: int, fusable_maidens: List[Dict[str, Any]]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.fusable_maidens = fusable_maidens
        self.message: Optional[discord.Message] = None
        self.add_item(TierSelectDropdown(user_id, fusable_maidens))

    def set_message(self, message: discord.Message):
        self.message = message

    @discord.ui.button(
        label="📖 View Fusion Rates",
        style=discord.ButtonStyle.secondary,
        custom_id="view_fusion_rates",
    )
    async def view_rates(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button is not for you!", ephemeral=True
            )
            return

        rates_embed = EmbedBuilder.info(
            title="Fusion Success Rates",
            description="Higher tiers have lower success rates. Failed fusions grant shards!",
            footer="Rates may be boosted during events",
        )

        rates = [
            ("Tier 1 → 2", "95%"),
            ("Tier 2 → 3", "90%"),
            ("Tier 3 → 4", "85%"),
            ("Tier 4 → 5", "75%"),
            ("Tier 5 → 6", "65%"),
            ("Tier 6 → 7", "55%"),
            ("Tier 7 → 8", "45%"),
            ("Tier 8 → 9", "35%"),
            ("Tier 9 → 10", "25%"),
            ("Tier 10 → 11", "15%"),
            ("Tier 11 → 12", "10%"),
        ]

        rates_text = "\n".join([f"**{tier}**: {rate}" for tier, rate in rates])
        rates_embed.add_field(name="Base Rates", value=rates_text, inline=False)
        rates_embed.add_field(
            name="🔷 Fusion Shards",
            value="Failed fusions grant shards. Collect 10 shards of a tier to guarantee a fusion to the next tier!",
            inline=False,
        )

        await interaction.response.send_message(embed=rates_embed, ephemeral=True)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class TierSelectDropdown(discord.ui.Select):
    """Dropdown for selecting fusion tier."""

    def __init__(self, user_id: int, fusable_maidens: List[Dict[str, Any]]):
        self.user_id = user_id
        self.fusable_maidens = fusable_maidens

        by_tier: Dict[int, List[Dict[str, Any]]] = {}
        for maiden in fusable_maidens:
            by_tier.setdefault(maiden["tier"], []).append(maiden)

        options = [
            discord.SelectOption(
                label=f"Tier {tier} Fusion",
                description=f"{len(maidens)} option{'s' if len(maidens) > 1 else ''} available",
                value=str(tier),
            )
            for tier, maidens in sorted(by_tier.items())
        ]

        super().__init__(
            placeholder="Select tier to fuse...",
            min_values=1,
            max_values=1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This selection is not for you!", ephemeral=True
            )
            return

        selected_tier = int(self.values[0])
        tier_maidens = [m for m in self.fusable_maidens if m["tier"] == selected_tier]

        embed = EmbedBuilder.primary(
            title=f"Tier {selected_tier} Fusion",
            description=(
                f"Select which Tier {selected_tier} maiden to fuse.\n\n"
                f"This will fuse **2 copies** to create **1 Tier {selected_tier + 1}** maiden."
            ),
            footer=f"{len(tier_maidens)} options available",
        )

        view = MaidenSelectView(self.user_id, tier_maidens)
        await interaction.response.edit_message(embed=embed, view=view)


class MaidenSelectView(discord.ui.View):
    """View for selecting a specific maiden to fuse."""

    def __init__(self, user_id: int, tier_maidens: List[Dict[str, Any]]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.tier_maidens = tier_maidens
        self.add_item(MaidenSelectDropdown(user_id, tier_maidens))

    @discord.ui.button(
        label="« Back",
        style=discord.ButtonStyle.secondary,
        custom_id="back_to_tier_select",
    )
    async def back_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This button is not for you!", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Use `/fusion` to restart the fusion process.", ephemeral=True
        )


class MaidenSelectDropdown(discord.ui.Select):
    """Dropdown for selecting specific maiden."""

    def __init__(self, user_id: int, tier_maidens: List[Dict[str, Any]]):
        self.user_id = user_id
        self.tier_maidens = tier_maidens

        options = [
            discord.SelectOption(
                label=f"{m['name']} (Tier {m['tier']})",
                description=f"{m['element']} • x{m['quantity']} owned",
                value=str(m["id"]),
            )
            for m in tier_maidens[:25]
        ]

        super().__init__(
            placeholder="Select maiden to fuse...",
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
            async with RedisService.acquire_lock(f"fusion:{self.user_id}", timeout=10):
                async with DatabaseService.get_transaction() as session:
                    player = await PlayerService.get_player_with_regen(
                        session, self.user_id, lock=True
                    )

                    if not player:
                        await interaction.followup.send("Player not found!", ephemeral=True)
                        return

                    result = await FusionService.attempt_fusion(session, player, maiden_id)

                    await TransactionLogger.log_transaction(
                        player_id=self.user_id,
                        transaction_type="fusion_attempted",
                        details={
                            "maiden_id": maiden_id,
                            "success": result["success"],
                            "tier_from": result["tier_from"],
                            "tier_to": result["tier_to"],
                            "cost": result.get("cost", 0),
                        },
                        context=f"interaction:fusion guild:{interaction.guild_id}",
                    )

                    await EventBus.publish(
                        "fusion_completed",
                        {
                            "player_id": self.user_id,
                            "success": result["success"],
                            "tier_from": result["tier_from"],
                            "tier_to": result["tier_to"],
                            "channel_id": interaction.channel_id,  
                            "__topic__": "fusion_completed",       
                            "timestamp": discord.utils.utcnow(),   
                        },
                    )

                # Fusion outcome embeds
                if result["success"]:
                    embed = EmbedBuilder.success(
                        title="⚗️ Fusion Successful!",
                        description=(
                            f"**{result['maiden_name']}** has been upgraded!\n\n"
                            f"**Tier {result['tier_from']} → Tier {result['tier_to']}**"
                        ),
                        footer=f"Fusion #{player.total_fusions}",
                    )
                    embed.add_field(
                        name="New Stats",
                        value=f"ATK: {result.get('attack', 0):,}\nDEF: {result.get('defense', 0):,}",
                        inline=True,
                    )
                else:
                    embed = EmbedBuilder.warning(
                        title="Fusion Failed",
                        description=(
                            f"The fusion did not succeed...\n\n"
                            f"**Tier {result['tier_from']}** maidens were lost."
                        ),
                        footer="Better luck next time!",
                    )
                    embed.add_field(
                        name="🔷 Consolation",
                        value=f"+1 Tier {result['tier_from']} Fusion Shard\n\nCollect 10 shards for a guaranteed fusion!",
                        inline=False,
                    )

                await interaction.edit_original_response(embed=embed, view=None)

        except InsufficientResourcesError as e:
            embed = EmbedBuilder.error(
                title="Insufficient Resources",
                description=str(e),
                help_text="Gain more resources and try again!",
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except FusionError as e:
            embed = EmbedBuilder.error(title="Fusion Error", description=str(e))
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Fusion execution error: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Fusion Failed", description="An error occurred during fusion."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(FusionCog(bot))
