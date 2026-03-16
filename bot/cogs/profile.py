import discord
from datetime import datetime
from discord import app_commands
from discord.ext import commands
from bot.utils.database import (
    get_accounts_by_discord_id,
    get_approved_accounts_by_discord_id,
)


STATUS_MAP = {
    "approved": "✅ Approved",
    "pending": "⏳ Pending",
    "rejected": "❌ Rejected",
}


def format_date(raw):
    if not raw:
        return "—"
    try:
        dt = datetime.strptime(raw[:10], "%Y-%m-%d")
        return dt.strftime("%d %b %Y")
    except Exception:
        return raw[:10]


def build_profile_embed(user: discord.User | discord.Member, accounts: list) -> discord.Embed:
    embed = discord.Embed(
        title=f"🌌 Profile · {user.display_name}",
        color=0x5865f2,
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    if not accounts:
        embed.description = "*Tidak ada akun terdaftar.*"
        return embed

    if isinstance(user, discord.Member) and user.joined_at:
        embed.description = f"Member since {user.joined_at.strftime('%d %b %Y')}"

    for i, acc in enumerate(accounts, start=1):
        status = STATUS_MAP.get(acc["status"], "Unknown")
        guild_val = acc["guild"] if acc["guild"] else "—"
        created = format_date(acc["created_at"])

        embed.add_field(
            name=f"⚔️ Akun #{i} · {status}",
            value=(
                f"Nickname : `{acc['nickname']}`\n"
                f"Guild    : `{guild_val}`\n"
                f"Server   : `{acc['server']}`\n"
                f"Terdaftar: `{created}`"
            ),
            inline=False,
        )

    embed.set_footer(text=f"Total: {len(accounts)} akun terdaftar")
    return embed


class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profile", description="Lihat profil akun game kamu atau user lain")
    @app_commands.describe(user="User yang ingin dilihat profilnya (opsional)")
    async def profile(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
    ):
        if user is None:
            accounts = await get_accounts_by_discord_id(str(interaction.user.id))
            target = interaction.user
        else:
            accounts = await get_approved_accounts_by_discord_id(str(user.id))
            target = user

        embed = build_profile_embed(target, accounts)
        await interaction.response.send_message(embed=embed, ephemeral=(user is None))
