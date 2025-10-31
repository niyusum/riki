import discord
from datetime import datetime

RIKI_COLOR = {
    "primary": 0x7289DA,     # Calm blue (neutral)
    "success": 0x57F287,     # Discord green
    "error": 0xED4245,       # Discord red
    "warning": 0xFEE75C,     # Gold/yellow
    "info": 0x5865F2,        # Indigo
}


class EmbedBuilder:
    """
    Factory for standardized Discord embeds across RIKI systems.

    Ensures consistent branding, tone, and hierarchy.
    Every embed includes:
        - title
        - description
        - optional fields
        - footer timestamp
    """

    @staticmethod
    def _base_embed(title: str, description: str, color: int, footer: str | None = None) -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        if footer:
            embed.set_footer(text=footer)
        return embed

    # --- Core Types --- #
    @staticmethod
    def primary(title: str, description: str, footer: str | None = None) -> discord.Embed:
        """Default embed for neutral/system messages."""
        return EmbedBuilder._base_embed(title, description, RIKI_COLOR["primary"], footer)

    @staticmethod
    def success(title: str, description: str, footer: str | None = None) -> discord.Embed:
        """Positive actions (rewards, victories, confirmations)."""
        return EmbedBuilder._base_embed(title, description, RIKI_COLOR["success"], footer)

    @staticmethod
    def error(title: str, description: str, help_text: str | None = None) -> discord.Embed:
        """Error embeds with optional help text."""
        desc = description
        if help_text:
            desc += f"\n\n💡 **Help:** {help_text}"
        return EmbedBuilder._base_embed(title, desc, RIKI_COLOR["error"])

    @staticmethod
    def warning(title: str, description: str, footer: str | None = None) -> discord.Embed:
        """For recoverable issues or alerts."""
        return EmbedBuilder._base_embed(title, description, RIKI_COLOR["warning"], footer)

    @staticmethod
    def info(title: str, description: str, footer: str | None = None) -> discord.Embed:
        """Informational messages."""
        return EmbedBuilder._base_embed(title, description, RIKI_COLOR["info"], footer)

    # --- Specialized --- #
    @staticmethod
    def player_stats(player, title: str) -> discord.Embed:
        """Detailed player profile display."""
        embed = discord.Embed(
            title=title,
            description=f"**Level {player.level} {player.player_class or 'Adventurer'}**",
            color=RIKI_COLOR["primary"],
            timestamp=datetime.utcnow()
        )

        # Resource summary
        embed.add_field(
            name="💰 Resources",
            value=f"Rikis: **{player.rikis:,}**\nGrace: **{player.grace}**\nGems: **{player.gems or 0}**",
            inline=True
        )

        # Energy & stamina
        embed.add_field(
            name="⚡ Energy & Stamina",
            value=f"Energy: **{player.energy}/{player.max_energy}**\nStamina: **{player.stamina}/{player.max_stamina}**",
            inline=True
        )

        # Prayer
        embed.add_field(
            name="🙏 Prayer Charges",
            value=f"**{player.prayer_charges}/{player.max_prayer_charges}**\nNext Regen: {player.get_prayer_regen_display()}",
            inline=True
        )

        # Progression
        embed.add_field(
            name="📈 Progression",
            value=f"XP: **{player.xp:,}/{player.next_level_xp:,}**\nTotal Power: **{player.total_power:,}**",
            inline=False
        )

        # Collection stats
        embed.add_field(
            name="🎴 Collection",
            value=f"Total Maidens: **{player.total_maidens_owned}**\nUnique: **{player.unique_maidens_owned}**",
            inline=True
        )

        embed.set_footer(text="RIKI RPG • Goddess blesses the prepared")
        return embed
