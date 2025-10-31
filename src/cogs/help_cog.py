import discord
from discord.ext import commands
from typing import Dict, Optional

from utils.embed_builder import EmbedBuilder


class HelpCog(commands.Cog):
    """
    Interactive help system with categorized commands.

    Provides command documentation organized by category with examples
    and usage tips. Uses button interface for easy navigation.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="help",
        description="View all available commands and how to use them",
    )
    async def help(self, ctx: commands.Context, command: Optional[str] = None):
        """Display interactive help menu."""
        await ctx.defer(ephemeral=True)
        if command:
            await self._show_command_help(ctx, command)
        else:
            await self._show_main_help(ctx)

    async def _show_main_help(self, ctx: commands.Context):
        """Show main help menu with categories."""
        embed = EmbedBuilder.info(
            title="🎮 RIKI RPG Commands",
            description=(
                "Welcome to **RIKI RPG**, where you collect and empower maidens through prayers, fusions, and blessings.\n\n"
                "Use the buttons below to browse help categories or type `/help <command>` for detailed info."
            ),
            footer="RIKI RPG Help • Use /help <command> for details",
        )

        visible_cmds = [c for c in self.bot.commands if not c.hidden]
        embed.add_field(
            name="📊 Available Commands",
            value=f"**{len(visible_cmds)}** commands across multiple categories",
            inline=False,
        )

        embed.add_field(
            name="💡 Pro Tips",
            value=(
                "• Commands work with `/` or `r` prefix\n"
                "• Example: `/summon` or `r summon`\n"
                "• Use shorter aliases: `rs`, `rf`, `rp`\n"
                "• Check `/profile` and `/stats` regularly for updates"
            ),
            inline=False,
        )

        view = HelpCategoryView()
        await ctx.send(embed=embed, view=view, ephemeral=True)

    async def _show_command_help(self, ctx: commands.Context, command_name: str):
        """Show help for specific command."""
        cmd = self.bot.get_command(command_name.lower())

        if not cmd or cmd.hidden:
            embed = EmbedBuilder.error(
                title="Command Not Found",
                description=f"No command named `{command_name}` exists.",
                help_text="Use `/help` to see all available commands.",
            )
            await ctx.send(embed=embed, ephemeral=True)
            return

        embed = EmbedBuilder.info(
            title=f"Command: /{cmd.name}",
            description=cmd.description or "No description available.",
            footer="RIKI RPG Command Help",
        )

        if cmd.aliases:
            alias_str = ", ".join(f"`{alias}`" for alias in cmd.aliases)
            embed.add_field(name="Aliases", value=alias_str, inline=False)

        params = []
        for name, param in cmd.clean_params.items():
            if param.default == param.empty:
                params.append(f"<{name}>")
            else:
                params.append(f"[{name}]")

        usage = f"/{cmd.name} {' '.join(params)}"
        embed.add_field(name="Usage", value=f"`{usage}`", inline=False)

        examples: Dict[str, str] = {
            "summon": "`/summon 5` — Summon 5 maidens at once",
            "fusion": "`/fusion` — Open the fusion interface",
            "collection": "`/collection tier:5` — View Tier 5 maidens only",
            "pray": "`/pray 3` — Pray 3 times at once",
            "leader": "`/leader` — Set or view your current leader",
        }
        if cmd.name in examples:
            embed.add_field(name="Example", value=examples[cmd.name], inline=False)

        await ctx.send(embed=embed, ephemeral=True)


class HelpCategoryView(discord.ui.View):
    """Interactive view for help category navigation."""

    def __init__(self):
        super().__init__(timeout=300)
        self.message: Optional[discord.Message] = None

    def set_message(self, message: discord.Message):
        self.message = message

    @discord.ui.button(label="🎯 Getting Started", style=discord.ButtonStyle.primary)
    async def getting_started(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = EmbedBuilder.info(
            title="🎯 Getting Started",
            description="Essential commands for new players",
            footer="RIKI RPG Help",
        )
        embed.add_field(
            name="📘 Commands",
            value="`/register`, `/profile`, `/help`",
            inline=False,
        )
        embed.add_field(
            name="Quick Start Guide",
            value=(
                "1️⃣ `/register` to create your account\n"
                "2️⃣ `/pray` to gain grace\n"
                "3️⃣ `/summon` to collect maidens\n"
                "4️⃣ `/fusion` to upgrade them\n"
                "5️⃣ `/leader` to set your strongest maiden"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="💎 Resources", style=discord.ButtonStyle.success)
    async def resources(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = EmbedBuilder.info(
            title="💎 Resource Commands",
            description="Gain and manage in-game currencies and energy.",
            footer="RIKI RPG Help",
        )
        embed.add_field(
            name="Commands",
            value="`/pray`, `/daily`",
            inline=False,
        )
        embed.add_field(
            name="Resources",
            value=(
                "**Grace** — For summoning maidens\n"
                "**Rikis** — Currency for fusions\n"
                "**Gems** — Premium currency\n"
                "**Energy & Stamina** — Used for activities (coming soon)"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="👑 Maidens", style=discord.ButtonStyle.primary)
    async def maidens(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = EmbedBuilder.info(
            title="👑 Maiden Commands",
            description="Manage and empower your maiden collection.",
            footer="RIKI RPG Help",
        )
        embed.add_field(
            name="Commands",
            value="`/summon`, `/collection`, `/fusion`, `/leader`",
            inline=False,
        )
        embed.add_field(
            name="About Maidens",
            value=(
                "• Maidens have tiers (1–12)\n"
                "• Fuse 2 same-tier maidens to upgrade\n"
                "• Higher tiers = higher power\n"
                "• Leaders provide passive bonuses"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="📊 Stats", style=discord.ButtonStyle.secondary)
    async def stats(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = EmbedBuilder.info(
            title="📊 Statistics",
            description="View detailed player metrics and analytics.",
            footer="RIKI RPG Help",
        )
        embed.add_field(
            name="Commands",
            value="`/stats`, `/transactions`",
            inline=False,
        )
        embed.add_field(
            name="What You’ll See",
            value=(
                "• Summon analytics\n"
                "• Fusion success rates\n"
                "• Collection breakdowns\n"
                "• Resource transactions\n"
                "• XP & level progression"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="✨ Modifier System", style=discord.ButtonStyle.secondary)
    async def modifiers(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = EmbedBuilder.info(
            title="✨ Modifier System",
            description="How leader and class bonuses affect your gameplay.",
            footer="RIKI RPG Help",
        )
        embed.add_field(
            name="Overview",
            value=(
                "Modifiers are passive bonuses that multiply resource gains and performance.\n"
                "They come from your **Leader Maiden** and **Player Class**."
            ),
            inline=False,
        )
        embed.add_field(
            name="Leader Bonuses",
            value=(
                "• Each leader grants a unique set of modifiers.\n"
                "• Common types:\n"
                "  💰 **Income Boost** — More rikis and grace earned\n"
                "  📈 **XP Boost** — Gain experience faster\n"
                "  🔮 **Fusion Bonus** — Improves fusion success rate"
            ),
            inline=False,
        )
        embed.add_field(
            name="Class Bonuses",
            value=(
                "• Each player class adds additional effects:\n"
                "  ⚔️ Warrior — +Attack stats\n"
                "  🛡️ Guardian — +Defense bonuses\n"
                "  💫 Mystic — +Grace and XP efficiency"
            ),
            inline=False,
        )
        embed.add_field(
            name="Viewing Modifiers",
            value="Use `/profile` or `/me` to see your **Active Modifiers**.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
