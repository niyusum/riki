import discord
from discord.ext import commands
from typing import List, Dict, Any

from src.services.database_service import DatabaseService
from src.services.player_service import PlayerService
from src.services.summon_service import SummonService
from src.services.redis_service import RedisService
from src.services.transaction_logger import TransactionLogger
from src.services.config_manager import ConfigManager
from src.services.event_bus import EventBus
from src.database.models.player import Player
from src.exceptions import InsufficientResourcesError, ValidationError
from src.services.logger import get_logger
from src.utils.decorators import ratelimit
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class SummonCog(commands.Cog):
    """
    Maiden summoning system with batch support.
    Players spend grace to summon maidens. Batch summons (x5/x10) use
    an interactive sequence to reveal results before the final summary.

    RIKI LAW Compliance:
        - SELECT FOR UPDATE on summons (Article I.1)
        - Transaction logging (Article I.2)
        - Redis locks for summon sessions (Article I.3)
        - ConfigManager for all rates/costs (Article I.4)
        - Specific exception handling (Article I.5)
        - Single commit per transaction (Article I.6)
        - All logic through SummonService (Article I.7)
        - Event publishing for achievements (Article I.8)
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_summon_sessions: Dict[int, List[Dict[str, Any]]] = {}

    @commands.hybrid_command(
        name="summon",
        aliases=["rs"],
        description="Summon powerful maidens using grace"
    )
    @ratelimit(uses=20, per_seconds=60, command_name="summon")
    async def summon(self, ctx: commands.Context, count: int = 1):
        """
        Summon maidens using grace.

        Single summons show results immediately. Batch summons (x5/x10)
        use an interactive flow to reveal each result before a summary.
        """
        await ctx.defer()  # public by default

        try:
            if count not in (1, 5, 10):
                raise ValidationError("count", f"Must be 1, 5, or 10. You entered {count}.")

            async with RedisService.acquire_lock(f"summon:{ctx.author.id}", timeout=60):
                async with DatabaseService.get_transaction() as session:
                    player = await PlayerService.get_player_with_regen(session, ctx.author.id, lock=True)

                    if not player:
                        embed = EmbedBuilder.error(
                            title="Not Registered",
                            description="You need to register first!",
                            help_text="Use `/register` to create your account."
                        )
                        await ctx.send(embed=embed, ephemeral=True)
                        return

                    grace_cost = ConfigManager.get("summon.grace_cost", 1) * count
                    if player.grace < grace_cost:
                        raise InsufficientResourcesError(
                            resource="grace", required=grace_cost, current=player.grace
                        )

                    results = await SummonService.perform_summons(session, player, count=count)

                    await TransactionLogger.log_transaction(
                        player_id=ctx.author.id,
                        transaction_type="summons_performed",
                        details={
                            "count": count,
                            "grace_spent": grace_cost,
                            "maidens": [
                                {"id": r["maiden_id"], "tier": r["tier"], "element": r["element"]}
                                for r in results
                            ],
                            "pity_triggered": any(r.get("pity_triggered", False) for r in results)
                        },
                        context=f"command:/{ctx.command.name} guild:{ctx.guild.id if ctx.guild else 'DM'}"
                    )

                    await EventBus.publish("summons_completed", {
                        "player_id": ctx.author.id,
                        "count": count,
                        "results": results,
                        "channel_id": ctx.channel.id,          
                        "__topic__": "prayer_completed",  
                        "timestamp": discord.utils.utcnow()
                    })

                remaining = player.grace - grace_cost

                if count == 1:
                    await self._display_single(ctx, results[0], remaining)
                else:
                    self.active_summon_sessions[ctx.author.id] = results
                    view = BatchSummonView(ctx.author.id, results, self.active_summon_sessions)
                    first = self._build_result_embed(results[0], 1, count, remaining)
                    await ctx.send(embed=first, view=view)

        except InsufficientResourcesError as e:
            embed = EmbedBuilder.error(
                title="Insufficient Grace",
                description=f"You need **{e.required}**, but only have **{e.current}**.",
                help_text="Use `/pray` to gain more grace."
            )
            await ctx.send(embed=embed, ephemeral=True)

        except ValidationError as e:
            embed = EmbedBuilder.error(
                title="Invalid Summon Count",
                description=str(e),
                help_text="Valid: `/summon 1`, `/summon 5`, `/summon 10`."
            )
            await ctx.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Summon error for {ctx.author.id}: {e}", exc_info=True)
            embed = EmbedBuilder.error(
                title="Summon Failed",
                description="An error occurred while summoning.",
                help_text="Please try again shortly."
            )
            await ctx.send(embed=embed, ephemeral=True)

    async def _display_single(self, ctx: commands.Context, result: Dict[str, Any], remaining: int):
        """Display a single summon result."""
        embed = self._build_result_embed(result, 1, 1, remaining)
        view = SingleSummonView(ctx.author.id, remaining)
        await ctx.send(embed=embed, view=view)

    def _build_result_embed(
        self,
        result: Dict[str, Any],
        index: int,
        total: int,
        remaining: int
    ) -> discord.Embed:
        """Create embed for an individual summon result."""
        name = result.get("maiden_name", "Unknown Maiden")
        tier = result.get("tier", 1)
        element = result.get("element", "Unknown")
        emoji = result.get("element_emoji", "❓")
        is_new = result.get("is_new", False)
        pity = result.get("pity_triggered", False)

        title = f"{'🌟 PITY! ' if pity else '✨ '}{name} Summoned!"
        desc = f"{emoji} **{element.title()}** Element • **Tier {tier}**\n"
        desc += "🆕 New to your collection!" if is_new else "📦 Added to your collection."

        flavor = {
            1: "Common maiden - fusion material",
            2: "Uncommon maiden - steady ally",
            3: "Rare maiden - solid find",
            4: "Epic maiden - excellent pull!",
            5: "Legendary maiden - incredible luck!",
            6: "Mythic maiden - extremely rare!",
            7: "Divine maiden - blessed by fate!",
            8: "Transcendent maiden - one in a million!",
            9: "Celestial maiden - beyond mortal power!",
            10: "Primordial maiden - ancient force reborn!",
            11: "Eternal maiden - timeless perfection!",
            12: "Absolute maiden - ultimate existence!"
        }
        desc += f"\n\n*{flavor.get(tier, 'Mysterious maiden...')}*"

        embed = EmbedBuilder.success(
            title=title,
            description=desc,
            footer=f"Summon {index}/{total} • {remaining} grace remaining"
        )

        atk = result.get("attack", 0)
        dfs = result.get("defense", 0)
        embed.add_field(
            name="⚔️ Stats",
            value=f"ATK: {atk:,} • DEF: {dfs:,}\nPower: {atk + dfs:,}",
            inline=True
        )

        return embed


class BatchSummonView(discord.ui.View):
    """Interactive viewer for batch summons."""

    def __init__(self, user_id: int, results: List[Dict[str, Any]], session: Dict[int, List[Dict[str, Any]]]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.results = results
        self.session = session
        self.index = 0

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This summon is not for you!", ephemeral=True)
            return

        self.index += 1
        if self.index >= len(self.results):
            await self._show_summary(interaction)
            return

        embed = SummonCog._build_result_embed(self=SummonCog, result=self.results[self.index],
                                              index=self.index + 1, total=len(self.results),
                                              remaining=0)
        if self.index == len(self.results) - 1:
            button.label = "Finish ✓"
            button.style = discord.ButtonStyle.success

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⏩ Skip to Summary", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This summon is not for you!", ephemeral=True)
            return
        await self._show_summary(interaction)

    async def _show_summary(self, interaction: discord.Interaction):
        for i in self.children:
            i.disabled = True

        total = len(self.results)
        tiers, new_count, high = {}, 0, 0
        for r in self.results:
            t = r["tier"]
            tiers[t] = tiers.get(t, 0) + 1
            new_count += 1 if r.get("is_new") else 0
            high = max(high, t)

        text = f"You summoned **{total}** maidens!\n"
        if new_count:
            text += f"🆕 **{new_count}** new to your collection!\n\n"
        text += "**Tier Breakdown:**\n"
        for t in sorted(tiers.keys(), reverse=True):
            text += f"• Tier {t}: **{tiers[t]}**\n"

        embed = EmbedBuilder.success(
            title=f"🎊 Summon Summary ({total} Summons)",
            description=text,
            footer=f"Highest Tier: {high} • New Maidens: {new_count}/{total}"
        )
        embed.add_field(
            name="Next Steps",
            value="`/collection` to view maidens\n`/fusion` to upgrade\n`/stats` for progress",
            inline=False
        )

        if self.user_id in self.session:
            del self.session[self.user_id]

        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for i in self.children:
            i.disabled = True
        if self.user_id in self.session:
            del self.session[self.user_id]


class SingleSummonView(discord.ui.View):
    """Actions available after a single summon."""

    def __init__(self, user_id: int, remaining: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.remaining = remaining
        if remaining < 1:
            self.summon_again.disabled = True

    @discord.ui.button(label="✨ Summon Again", style=discord.ButtonStyle.primary)
    async def summon_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button isn't for you!", ephemeral=True)
            return
        await interaction.response.send_message(f"Use `/summon` again! ({self.remaining} grace left)", ephemeral=True)

    @discord.ui.button(label="🎴 View Collection", style=discord.ButtonStyle.secondary)
    async def view_collection(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button isn't for you!", ephemeral=True)
            return
        await interaction.response.send_message("Use `/collection` to see your maidens!", ephemeral=True)

    async def on_timeout(self):
        for i in self.children:
            i.disabled = True


async def setup(bot: commands.Bot):
    """Required for Discord cog loading."""
    await bot.add_cog(SummonCog(bot))
