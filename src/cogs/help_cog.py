import discord
from discord.ext import commands
from typing import Dict, List, Optional

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
        """
        Display interactive help menu.

        Args:
            command: Specific command to get help for (optional)
        """
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
                "Welcome to RIKI RPG! Select a category below to see available commands.\n\n"
                "**Quick Navigation:** Use the buttons below to browse categories."
            ),
            footer="Use /help <command> for detailed info about a specific command",
        )

        visible_cmds = [c for c in self.bot.commands if not c.hidden]
        embed.add_field(
            name="📊 Available Commands",
            value=f"**{len(visible_cmds)}** commands across multiple categories",
            inline=False,
        )

        categories: Dict[str, str] = {
            "Getting Started": "register, profile, help",
            "Resources": "pray, daily",
            "Maidens": "summon, collection, fusion, leader",
            "Progression": "stats",
            "Information": "help",
        }

        cat_lines = "\n".join(
            f"**{name}**\n`{cmds}`\n" for name, cmds in categories.items()
        )

        embed.add_field(name="📚 Command Categories", value=cat_lines, inline=False)
        embed.add_field(
            name="💡 Pro Tips",
            value=(
                "• All commands work with `/` or `r` prefix\n"
                "• Example: `/summon` or `r summon`\n"
                "• Use shorter aliases: `rs`, `rf`, `rp`\n"
                "• Check `/profile` regularly for updates"
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
            "summon": "`/summon 5` - Summon 5 maidens at once",
            "fusion": "`/fusion` - Open fusion interface",
            "collection": "`/collection tier:5` - View Tier 5 maidens only",
            "pray": "`/pray 3` - Pray 3 times at once",
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

    @discord.ui.button(
        label="🎯 Getting Started",
        style=discord.ButtonStyle.primary,
        custom_id="help_getting_started",
    )
    async def getting_started(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = EmbedBuilder.info(
            title="🎯 Getting Started",
            description="Essential commands for new players",
            footer="RIKI RPG Help",
        )

        commands_info = [
            ("**/register** (rr)", "Create your account and start playing"),
            ("**/profile** (rme)", "View your stats, resources, and collection"),
            ("**/help**", "View this help menu"),
        ]
        for cmd, desc in commands_info:
            embed.add_field(name=cmd, value=desc, inline=False)

        embed.add_field(
            name="Quick Start Guide",
            value=(
                "1. Use `/register` to create account\n"
                "2. Use `/pray` to gain grace\n"
                "3. Use `/summon` to recruit maidens\n"
                "4. Use `/fusion` to upgrade them!"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="💎 Resources",
        style=discord.ButtonStyle.success,
        custom_id="help_resources",
    )
    async def resources(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = EmbedBuilder.info(
            title="💎 Resource Commands",
            description="Commands for gaining and managing resources",
            footer="RIKI RPG Help",
        )

        commands_info = [
            ("**/pray** (rp)", "Spend prayer charges to gain grace"),
            ("**/daily** (rd)", "Claim daily rewards (rikis, grace, bonuses)"),
        ]
        for cmd, desc in commands_info:
            embed.add_field(name=cmd, value=desc, inline=False)

        embed.add_field(
            name="Resource Types",
            value=(
                "**Grace** — Used for summoning maidens\n"
                "**Rikis** — Primary fusion currency\n"
                "**Energy** — Used for quests (coming soon)\n"
                "**Stamina** — Used for battles (coming soon)"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="👑 Maidens",
        style=discord.ButtonStyle.primary,
        custom_id="help_maidens",
    )
    async def maidens(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = EmbedBuilder.info(
            title="👑 Maiden Commands",
            description="Commands for managing your maiden collection",
            footer="RIKI RPG Help",
        )

        commands_info = [
            ("**/summon** (rs)", "Summon maidens using grace (1x, 5x, or 10x)"),
            ("**/collection** (rm)", "View your collection with filters"),
            ("**/fusion** (rf)", "Fuse maidens to upgrade tiers"),
            ("**/leader** (rl)", "Set leader maiden for passive bonuses"),
        ]
        for cmd, desc in commands_info:
            embed.add_field(name=cmd, value=desc, inline=False)

        embed.add_field(
            name="Maiden System",
            value=(
                "• Maidens have tiers (1–12)\n"
                "• Fuse 2 same-tier maidens to upgrade\n"
                "• Higher tiers = more power\n"
                "• Set a leader for passive bonuses"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="📊 Stats",
        style=discord.ButtonStyle.secondary,
        custom_id="help_stats",
    )
    async def stats(self, interaction: discord.Interaction, _: discord.ui.Button):
        embed = EmbedBuilder.info(
            title="📊 Statistics",
            description="View detailed player analytics and metrics",
            footer="RIKI RPG Help",
        )

        embed.add_field(
            name="**/stats**",
            value=(
                "View detailed statistics including:\n"
                "• Summon analytics\n"
                "• Fusion success rates\n"
                "• Collection breakdown\n"
                "• Resource usage\n"
                "• Progression metrics"
            ),
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
    await bot.add_cog(HelpCog(bot))
