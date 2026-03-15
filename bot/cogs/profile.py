import discord
from discord import app_commands
from discord.ext import commands
from bot.utils.database import (
    get_accounts_by_discord_id,
    get_approved_accounts_by_discord_id,
)


def build_profile_embed(user: discord.User | discord.Member, accounts: list) -> discord.Embed:
    embed = discord.Embed(
        title=f"🌌 Profile · {user.display_name}",
        color=0x5865f2,
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    if not accounts:
        embed.description = "*Tidak ada akun terdaftar.*"
        return embed

    for i, acc in enumerate(accounts, start=1):
        status_emoji = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(acc["status"], "❓")
        guild_val = acc["guild"] if acc["guild"] else "—"
        embed.add_field(
            name=f"⚔️ Akun #{i}  {status_emoji}",
            value=(
                f"Nickname `{acc['nickname']}`\n"
                f"Guild `{guild_val}`\n"
                f"Server `{acc['server']}`\n"
                f"Game `{acc['game']}`"
            ),
            inline=True,
        )

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
            # Lihat profil sendiri — tampilkan semua akun
            accounts = await get_accounts_by_discord_id(str(interaction.user.id))
            target = interaction.user
        else:
            # Lihat profil orang lain — hanya akun approved
            accounts = await get_approved_accounts_by_discord_id(str(user.id))
            target = user

        embed = build_profile_embed(target, accounts)
        await interaction.response.send_message(embed=embed, ephemeral=(user is None))
