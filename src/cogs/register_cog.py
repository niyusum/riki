import discord
from discord.ext import commands

from src.services.database_service import DatabaseService
from src.services.player_service import PlayerService
from src.services.transaction_logger import TransactionLogger
from src.services.config_manager import ConfigManager
from src.database.models.player import Player
from src.exceptions import ValidationError, DatabaseError
from src.services.logger import get_logger
from src.services.event_bus import EventBus
from src.services.tutorial_service import TutorialService
from utils.embed_builder import EmbedBuilder

logger = get_logger(__name__)


class RegisterCog(commands.Cog):
    """
    Public registration with ToS acknowledgement and support server link.
    """

    def __init__(self, bot: commands.Bot, *, support_url: str = "https://discord.gg/yourserver"):
        self.bot = bot
        self.support_url = support_url

    @commands.hybrid_command(
        name="register",
        aliases=["rr"],
        description="Register your RIKI RPG account and begin your journey"
    )
    async def register(self, ctx: commands.Context):
        await ctx.defer()  # public

        try:
            async with DatabaseService.get_transaction() as session:
                existing = await session.get(Player, ctx.author.id, with_for_update=True)
                if existing:
                    embed = EmbedBuilder.warning(
                        title="Already Registered",
                        description=(
                            f"Welcome back, {ctx.author.mention}!\n"
                            f"You registered on <t:{int(existing.created_at.timestamp())}:D>."
                        ),
                        footer=f"Level {existing.level} • {existing.total_maidens_owned} Maidens"
                    )
                    embed.add_field(
                        name="Next Steps",
                        value="`/me` to view profile • `/pray` to gain grace • `/summon` to pull maidens",
                        inline=False
                    )
                    await ctx.send(embed=embed)
                    return

                starting_rikis = ConfigManager.get("player.starting_rikis", 1000)
                starting_grace = ConfigManager.get("player.starting_grace", 5)
                starting_energy = ConfigManager.get("player.starting_max_energy", 100)
                starting_stamina = ConfigManager.get("player.starting_max_stamina", 50)

                new_player = Player(
                    discord_id=ctx.author.id,
                    username=ctx.author.name,
                    rikis=starting_rikis,
                    grace=starting_grace,
                    energy=starting_energy,
                    max_energy=starting_energy,
                    stamina=starting_stamina,
                    max_stamina=starting_stamina,
                    tutorial_completed=False,
                    tutorial_step=0
                )

                session.add(new_player)
                await session.flush()

                await TransactionLogger.log_transaction(
                    player_id=ctx.author.id,
                    transaction_type="player_registered",
                    details={
                        "username": ctx.author.name,
                        "starting_rikis": starting_rikis,
                        "starting_grace": starting_grace,
                        "starting_energy": starting_energy,
                        "starting_stamina": starting_stamina
                    },
                    context=f"command:/{ctx.command.name} guild:{ctx.guild.id if ctx.guild else 'DM'}"
                )

            # Public welcome + ToS post
            embed = EmbedBuilder.success(
                title="🎉 Welcome to RIKI RPG!",
                description=(
                    f"{ctx.author.mention} has joined the world of RIKI!\n\n"
                    "By registering, you agree to follow our **Terms of Service** and community rules.\n"
                    "Be kind, no cheating, and have fun."
                ),
                footer="Use /help for all commands"
            )
            embed.add_field(
                name="📜 Terms of Service",
                value="Review and accept to continue using the bot.",
                inline=False
            )
            embed.add_field(
                name="💬 Support",
                value=f"[Join our Support Server]({self.support_url}) for help, events, and announcements.",
                inline=False
            )
            embed.add_field(
                name="🚀 First Steps",
                value="`/pray` to gain grace • `/summon` to pull maidens • `/me` to view your profile",
                inline=False
            )

            view = TosAgreeView(player_id=ctx.author.id)
            await ctx.send(embed=embed, view=view)

        except ValidationError as e:
            await ctx.send(
                embed=EmbedBuilder.error("Registration Failed", str(e), "Contact support."),
                ephemeral=True
            )
        except DatabaseError as e:
            logger.error(f"Registration DB error for {ctx.author.id}: {e}", exc_info=True)
            await ctx.send(
                embed=EmbedBuilder.error("Registration Error", "System error during registration.", "Try again shortly."),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Unexpected registration error for {ctx.author.id}: {e}", exc_info=True)
            await ctx.send(
                embed=EmbedBuilder.error("Something Went Wrong", "Unexpected error.", "Please try again later."),
                ephemeral=True
            )

    @commands.command(name="rr", hidden=True)
    async def register_short(self, ctx: commands.Context):
        await self.register(ctx)


class TosAgreeView(discord.ui.View):
    """Public post with buttons; only the registering user can ‘Agree’."""

    def __init__(self, player_id: int):
        super().__init__(timeout=600)
        self.player_id = player_id

    @discord.ui.button(label="✅ I Agree", style=discord.ButtonStyle.success, custom_id="tos_agree")
    async def agree(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        async with DatabaseService.get_transaction() as session:
            player = await session.get(Player, self.player_id, with_for_update=True)
            if player:
                done = await TutorialService.complete_step(session, player, "tos_agreed")
                # Announce publicly in the same channel
                try:
                    channel = interaction.channel
                    if channel and done:
                        embed = EmbedBuilder.success(
                            title=f"🎉 Tutorial Complete: {done['title']}",
                            description=done["congrats"],
                            footer="You're all set — try `/pray` next!"
                        )
                        await channel.send(embed=embed)
                        # Plain text reward line (ToS likely has no rewards)
                        rk = done["reward"].get("rikis", 0)
                        gr = done["reward"].get("grace", 0)
                        if rk or gr:
                            parts = []
                            if rk:
                                parts.append(f"+{rk} rikis")
                            if gr:
                                parts.append(f"+{gr} grace")
                            await channel.send(f"You received {' and '.join(parts)} as a tutorial reward!")
                except Exception:
                    pass

                # Also publish the tutorial event with topic metadata
                try:
                    await EventBus.publish("tos_agreed", {
                        "player_id": self.player_id,
                        "channel_id": interaction.channel_id,
                        "__topic__": "tos_agreed"
                    })
                except Exception:
                    pass

        # Private confirmation (so the clicker gets immediate feedback)
        await interaction.response.send_message(
            "Thanks! You’ve accepted the ToS. Start with `/pray`, then try `/summon`.",
            ephemeral=True
        )

    @discord.ui.button(label="🔗 Support Server", style=discord.ButtonStyle.link, url="https://discord.gg/yourserver")
    async def support(self, *_):
        pass

    async def on_timeout(self):
        for c in self.children:
            if isinstance(c, discord.ui.Button) and c.style != discord.ButtonStyle.link:
                c.disabled = True