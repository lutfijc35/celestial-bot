import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from config import (
    DISCORD_TOKEN, GUILD_ID, WELCOME_CHANNEL_ID,
    RULES_CHANNEL_ID, RULES_MESSAGE_ID, MEMBER_ROLE_ID, APPROVAL_MODE, DEFAULT_ROLE_ID,
    REGISTER_CHANNEL_ID, OTHER_GAMES_CHANNEL_ID,
)
from bot.utils.database import init_db, get_setting
from bot.cogs.register import RegisterCog, ApprovalView, RegisterButton
from bot.cogs.admin import AdminCog
from bot.cogs.profile import ProfileCog
from bot.cogs.starboard import StarboardCog
from bot.cogs.waifu_logger import WaifuLoggerCog
from bot.cogs.promote import PromoteCog, TaskInterestButton, TaskAssignView
from bot.cogs.vote import VoteCog, VoteButtonView, PollClosedView

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("celestial")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error(f"Command error: {error}")
    msg = "❌ Terjadi error saat menjalankan command."
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
    except Exception:
        pass


@bot.event
async def on_ready():
    # Init database
    await init_db()

    bot.start_time = datetime.now(timezone.utc)

    # Load rules_message_id: prioritas DB, fallback ke env var
    _db_rules_id = await get_setting("rules_message_id")
    bot.rules_message_id = int(_db_rules_id) if _db_rules_id else RULES_MESSAGE_ID

    # Load welcome_channel_id: prioritas DB, fallback ke env var
    _db_welcome_id = await get_setting("welcome_channel_id")
    bot.welcome_channel_id = int(_db_welcome_id) if _db_welcome_id else WELCOME_CHANNEL_ID

    # Load register_channel_id: prioritas DB, fallback ke env var
    _db_register_id = await get_setting("register_channel_id")
    bot.register_channel_id = int(_db_register_id) if _db_register_id else REGISTER_CHANNEL_ID

    # Load other_games_channel_id: prioritas DB, fallback ke env var
    _db_other_id = await get_setting("other_games_channel_id")
    bot.other_games_channel_id = int(_db_other_id) if _db_other_id else OTHER_GAMES_CHANNEL_ID

    # Load approval_ping_role_ids: dari DB, comma-separated, tidak ada fallback env
    _db_ping_ids = await get_setting("approval_ping_role_ids")
    bot.approval_ping_role_ids = [int(x) for x in _db_ping_ids.split(",") if x] if _db_ping_ids else []

    # Load cogs
    await bot.add_cog(RegisterCog(bot))
    await bot.add_cog(AdminCog(bot))
    await bot.add_cog(ProfileCog(bot))
    await bot.add_cog(StarboardCog(bot))
    await bot.add_cog(WaifuLoggerCog(bot))
    await bot.add_cog(PromoteCog(bot))
    await bot.add_cog(VoteCog(bot))

    # Re-register persistent views (agar button tetap berfungsi setelah restart)
    bot.add_view(ApprovalView())
    bot.add_view(RegisterButton())
    bot.add_view(TaskInterestButton())
    bot.add_view(TaskAssignView())
    bot.add_view(VoteButtonView())
    bot.add_view(PollClosedView(has_role=False))
    bot.add_view(PollClosedView(has_role=True))

    # Sync slash commands ke guild
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)

    logger.info(f"Bot siap: {bot.user} ({bot.user.id})")
    logger.info(f"Synced {len(synced)} command(s) to guild {GUILD_ID}")
    _welcome_src = "db" if _db_welcome_id else "env"
    logger.info(f"[config] WELCOME_CHANNEL_ID  = {bot.welcome_channel_id} (source: {_welcome_src})")
    logger.info(f"[config] RULES_CHANNEL_ID    = {RULES_CHANNEL_ID}")
    _reg_src = "db" if _db_register_id else "env"
    logger.info(f"[config] REGISTER_CHANNEL_ID = {bot.register_channel_id} (source: {_reg_src})")
    _other_src = "db" if _db_other_id else "env"
    logger.info(f"[config] OTHER_GAMES_CHANNEL_ID = {bot.other_games_channel_id} (source: {_other_src})")
    _src = "db" if _db_rules_id else "env"
    logger.info(f"[config] RULES_MESSAGE_ID   = {bot.rules_message_id} (source: {_src})")
    logger.info(f"[config] MEMBER_ROLE_ID     = {MEMBER_ROLE_ID}")
    logger.info(f"[config] DEFAULT_ROLE_ID    = {DEFAULT_ROLE_ID}")
    logger.info(f"[config] APPROVAL_MODE      = {APPROVAL_MODE}")


@bot.event
async def on_member_join(member: discord.Member):
    channel = bot.get_channel(bot.welcome_channel_id)
    if not channel:
        logger.warning(f"[welcome] welcome_channel_id ({bot.welcome_channel_id}) tidak ditemukan")
        return

    embed = discord.Embed(
        description=(
            f"Halo {member.mention}! Selamat bergabung di **Celestial Server**.\n\n"
            f"📖 Baca peraturan di <#{RULES_CHANNEL_ID}> terlebih dahulu."
        ),
        color=0x5865f2,
    )
    embed.set_author(
        name=f"👋 Selamat datang, {member.display_name}!",
        icon_url=member.display_avatar.url,
    )
    embed.set_footer(text="✦ Celestial · Selamat bergabung!")

    await channel.send(embed=embed)
    logger.info(f"[welcome] Sent welcome message for {member} ({member.id})")


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    # Deteksi boost baru: sebelumnya tidak boost, sekarang boost
    if before.premium_since is None and after.premium_since is not None:
        channel = bot.get_channel(bot.welcome_channel_id)
        if not channel:
            return

        embed = discord.Embed(
            description=(
                f"## 🎉 Terima Kasih Sudah Boost!\n\n"
                f"{after.mention} baru saja **boost** server! "
                f"Makasih banyak atas dukungannya! 💜\n\n"
                f"Semoga makin betah di **Celestial Server** ya! ✨"
            ),
            color=0xf47fff,
        )
        embed.set_thumbnail(url=after.display_avatar.url)
        embed.set_image(url="https://media.tenor.com/ttqmTHRfjcgAAAAM/%E6%88%91%E5%9C%A8%E9%80%99%E8%A3%A1.gif")
        embed.set_footer(text="✦ Celestial · Server Boost")

        await channel.send(content=after.mention, embed=embed)
        logger.info(f"[boost] {after} ({after.id}) boosted the server")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    rules_message_id = getattr(bot, "rules_message_id", RULES_MESSAGE_ID)
    logger.info(f"[reaction] msg={payload.message_id} emoji={payload.emoji} user={payload.user_id}")

    if not rules_message_id:
        logger.warning("[reaction] RULES_MESSAGE_ID belum diset (env maupun /setup-rules) — diabaikan")
        return
    if payload.message_id != rules_message_id:
        logger.debug(
            f"[reaction] msg {payload.message_id} bukan rules message "
            f"({rules_message_id}), skip"
        )
        return
    if str(payload.emoji) != "✅":
        return
    if payload.user_id == bot.user.id:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        logger.error(f"[reaction] Guild tidak ditemukan: {payload.guild_id}")
        return

    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        logger.debug(f"[reaction] Member tidak ditemukan atau bot: {payload.user_id}")
        return

    if not MEMBER_ROLE_ID:
        logger.warning("[reaction] MEMBER_ROLE_ID belum diset di .env")
        return

    role = guild.get_role(MEMBER_ROLE_ID)
    if not role:
        logger.error(f"[reaction] Role Member (ID: {MEMBER_ROLE_ID}) tidak ditemukan di guild")
        return

    if role not in member.roles:
        try:
            await member.add_roles(role, reason="Celestial: react ✅ di rules")
            logger.info(f"[reaction] Assigned role '{role.name}' ke {member} ({member.id})")

            # Unlock channel untuk role Member
            register_ch_id = getattr(bot, "register_channel_id", REGISTER_CHANNEL_ID)
            if register_ch_id:
                register_ch = guild.get_channel(register_ch_id)
                if register_ch:
                    await register_ch.set_permissions(role, view_channel=True, send_messages=True)
                    logger.info(f"[reaction] Unlocked #{register_ch.name} untuk role '{role.name}'")

            other_ch_id = getattr(bot, "other_games_channel_id", OTHER_GAMES_CHANNEL_ID)
            if other_ch_id:
                other_ch = guild.get_channel(other_ch_id)
                if other_ch:
                    await other_ch.set_permissions(role, view_channel=True, send_messages=True)
                    logger.info(f"[reaction] Unlocked #{other_ch.name} untuk role '{role.name}'")

            # DM ke user dengan link channel yang sudah terbuka
            try:
                _dm_register_id = getattr(bot, "register_channel_id", REGISTER_CHANNEL_ID)
                _dm_other_id = getattr(bot, "other_games_channel_id", OTHER_GAMES_CHANNEL_ID)
                lines = ["✅ Kamu sudah diverifikasi! Channel berikut sekarang terbuka:"]
                if _dm_register_id:
                    lines.append(f"• <#{_dm_register_id}>")
                if _dm_other_id:
                    lines.append(f"• <#{_dm_other_id}>")
                await member.send("\n".join(lines))
                logger.info(f"[reaction] DM terkirim ke {member} ({member.id})")
            except discord.Forbidden:
                logger.debug(f"[reaction] DM tidak bisa dikirim ke {member} (DM dinonaktifkan)")
            except discord.HTTPException as e:
                logger.warning(f"[reaction] Gagal kirim DM ke {member}: {e}")

        except discord.Forbidden:
            logger.error(f"[reaction] Forbidden: tidak bisa assign role ke {member} — cek hierarki role bot")
        except discord.HTTPException as e:
            logger.error(f"[reaction] HTTPException: {e}")
    else:
        logger.debug(f"[reaction] {member} sudah punya role '{role.name}', skip")


def main():
    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN belum di-set di .env")
    asyncio.run(bot.start(DISCORD_TOKEN))


if __name__ == "__main__":
    main()
