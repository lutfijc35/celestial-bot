import logging
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.utils.database import (
    get_starboard_entry, create_starboard_entry,
    update_starboard_star_count, get_expired_starboard_roles,
    mark_starboard_role_removed, get_starboard_leaderboard,
    get_starboard_leaderboard_monthly, get_monthly_starboard_count,
    check_mvp_notified, mark_mvp_notified,
    get_setting, set_setting, delete_setting,
)
from config import GUILD_ID

logger = logging.getLogger("celestial")

STAR_EMOJI = "⭐"
DEFAULT_THRESHOLD = 5
ROLE_DURATION_DAYS = 30
MVP_THRESHOLD = 5
WIB = timezone(timedelta(hours=7))
BULAN_ID = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
    9: "September", 10: "Oktober", 11: "November", 12: "Desember",
}


class StarboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.starboard_channel_id: int = 0
        self.source_channel_id: int = 0
        self.starboard_role_id: int = 0
        self.star_threshold: int = DEFAULT_THRESHOLD

    async def cog_load(self):
        sb_ch = await get_setting("starboard_channel_id")
        self.starboard_channel_id = int(sb_ch) if sb_ch else 0

        src_ch = await get_setting("starboard_source_channel_id")
        self.source_channel_id = int(src_ch) if src_ch else 0

        sb_role = await get_setting("starboard_role_id")
        self.starboard_role_id = int(sb_role) if sb_role else 0

        threshold = await get_setting("starboard_threshold")
        self.star_threshold = int(threshold) if threshold else DEFAULT_THRESHOLD

        mvp_ch = await get_setting("mvp_channel_id")
        self.mvp_channel_id = int(mvp_ch) if mvp_ch else 0

        mvp_img = await get_setting("mvp_image_url")
        self.mvp_image_url = mvp_img or ""

        self.check_role_expiry.start()

    async def cog_unload(self):
        self.check_role_expiry.cancel()

    # ── Background task: remove expired roles ──

    @tasks.loop(hours=1)
    async def check_role_expiry(self):
        expired = await get_expired_starboard_roles()
        if not expired:
            return

        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return

        role = guild.get_role(self.starboard_role_id) if self.starboard_role_id else None
        if not role:
            return

        for entry in expired:
            member = guild.get_member(int(entry["author_discord_id"]))
            if member and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Celestial: starboard role expired (30 hari)")
                    logger.info(f"[starboard] Removed role '{role.name}' from {member}")
                except discord.Forbidden:
                    logger.error(f"[starboard] Cannot remove role from {member}")
            await mark_starboard_role_removed(entry["source_message_id"])

    @check_role_expiry.before_loop
    async def before_check_role_expiry(self):
        await self.bot.wait_until_ready()

    # ── Reaction listener ──

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) != STAR_EMOJI:
            return
        if not self.source_channel_id or payload.channel_id != self.source_channel_id:
            return
        if not self.starboard_channel_id or not self.starboard_role_id:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.HTTPException):
            return

        star_count = 0
        for reaction in message.reactions:
            if str(reaction.emoji) == STAR_EMOJI:
                star_count = reaction.count
                break

        existing = await get_starboard_entry(str(message.id))

        if existing:
            await update_starboard_star_count(str(message.id), star_count)
            sb_channel = self.bot.get_channel(self.starboard_channel_id)
            if sb_channel:
                try:
                    sb_msg = await sb_channel.fetch_message(int(existing["starboard_message_id"]))
                    if sb_msg.embeds:
                        embed = sb_msg.embeds[0]
                        embed.set_footer(text=f"⭐ {star_count} | #{channel.name}")
                        await sb_msg.edit(embed=embed)
                except (discord.NotFound, discord.HTTPException):
                    pass
            return

        if star_count < self.star_threshold:
            return

        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return

        sb_channel = self.bot.get_channel(self.starboard_channel_id)
        if not sb_channel:
            return

        # Build starboard embed
        embed = discord.Embed(
            description=message.content or "*[no text content]*",
            color=0xffd700,
            timestamp=message.created_at,
        )
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url,
        )
        embed.add_field(
            name="Source",
            value=f"[Jump to message]({message.jump_url})",
            inline=False,
        )
        if message.attachments:
            first = message.attachments[0]
            if first.content_type and first.content_type.startswith("image/"):
                embed.set_image(url=first.url)
        embed.set_footer(text=f"⭐ {star_count} | #{channel.name}")

        sb_msg = await sb_channel.send(embed=embed)

        # Assign temp role
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=ROLE_DURATION_DAYS)
        role_assigned_at = now.strftime("%Y-%m-%d %H:%M:%S")
        role_expires_at = expires.strftime("%Y-%m-%d %H:%M:%S")

        member = guild.get_member(message.author.id)
        if member:
            role = guild.get_role(self.starboard_role_id)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Celestial: starboard threshold reached")
                    logger.info(f"[starboard] Assigned role '{role.name}' to {member} for 30 days")
                except discord.Forbidden:
                    logger.error(f"[starboard] Cannot assign role to {member}")
                    role_assigned_at = None
                    role_expires_at = None

        await create_starboard_entry(
            source_message_id=str(message.id),
            starboard_message_id=str(sb_msg.id),
            author_discord_id=str(message.author.id),
            star_count=star_count,
            role_assigned_at=role_assigned_at,
            role_expires_at=role_expires_at,
        )
        logger.info(f"[starboard] Message {message.id} by {message.author} starboarded ({star_count} stars)")

        # MVP check — jika user masuk starboard >= 5x bulan ini (WIB)
        if self.mvp_channel_id:
            now_wib = datetime.now(WIB)
            author_id = str(message.author.id)
            monthly_count = await get_monthly_starboard_count(author_id, now_wib.year, now_wib.month)
            if monthly_count >= MVP_THRESHOLD:
                already = await check_mvp_notified(author_id, now_wib.year, now_wib.month)
                if not already:
                    mvp_ch = self.bot.get_channel(self.mvp_channel_id)
                    if mvp_ch:
                        embed = discord.Embed(
                            title="🏆 Sahabat Hitam!",
                            description=(
                                f"Selamat {message.author.mention}! "
                                f"Kamu menjadi sahabat hitam, sering-sering jadi orang hitam ya 😎\n\n"
                                f"⭐ **{monthly_count}x** masuk starboard bulan {BULAN_ID[now_wib.month]} {now_wib.year}"
                            ),
                            color=0xffd700,
                        )
                        if self.mvp_image_url:
                            embed.set_image(url=self.mvp_image_url)
                        await mvp_ch.send(content=message.author.mention, embed=embed)
                        await mark_mvp_notified(author_id, now_wib.year, now_wib.month)
                        logger.info(f"[starboard] MVP notification sent for {message.author}")

    # ── Setup commands ──

    @app_commands.command(name="setup-starboard", description="[Admin] Set channel ini sebagai starboard target")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_starboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        current = await get_setting("starboard_channel_id")
        if current and int(current) == interaction.channel.id:
            await delete_setting("starboard_channel_id")
            self.starboard_channel_id = 0
            await interaction.followup.send("❌ Starboard channel dinonaktifkan.", ephemeral=True)
        else:
            await set_setting("starboard_channel_id", str(interaction.channel.id))
            self.starboard_channel_id = interaction.channel.id
            await interaction.followup.send(
                f"✅ Starboard channel diset ke <#{interaction.channel.id}>.", ephemeral=True
            )

    @app_commands.command(name="setup-starboard-source", description="[Admin] Set channel ini sebagai sumber starboard")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_starboard_source(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        current = await get_setting("starboard_source_channel_id")
        if current and int(current) == interaction.channel.id:
            await delete_setting("starboard_source_channel_id")
            self.source_channel_id = 0
            await interaction.followup.send("❌ Starboard source channel dinonaktifkan.", ephemeral=True)
        else:
            await set_setting("starboard_source_channel_id", str(interaction.channel.id))
            self.source_channel_id = interaction.channel.id
            await interaction.followup.send(
                f"✅ Starboard source channel diset ke <#{interaction.channel.id}>.", ephemeral=True
            )

    @app_commands.command(name="setup-starboard-role", description="[Admin] Set role sementara untuk starboard (30 hari)")
    @app_commands.default_permissions(manage_roles=True)
    async def setup_starboard_role(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        await set_setting("starboard_role_id", str(role.id))
        self.starboard_role_id = role.id
        await interaction.followup.send(
            f"✅ Starboard role diset ke {role.mention} (diberikan selama 30 hari).",
            ephemeral=True,
        )

    @app_commands.command(name="setup-starboard-threshold", description="[Admin] Set minimum bintang untuk starboard")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_starboard_threshold(self, interaction: discord.Interaction, count: int):
        await interaction.response.defer(ephemeral=True)
        if count < 1:
            await interaction.followup.send("❌ Threshold harus minimal 1.", ephemeral=True)
            return
        await set_setting("starboard_threshold", str(count))
        self.star_threshold = count
        await interaction.followup.send(
            f"✅ Star threshold diset ke **{count}** bintang.",
            ephemeral=True,
        )

    @app_commands.command(name="setup-mvp-channel", description="[Admin] Set/unset channel untuk notifikasi MVP bulanan")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_mvp_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        current = await get_setting("mvp_channel_id")
        if current and int(current) == interaction.channel.id:
            await delete_setting("mvp_channel_id")
            self.mvp_channel_id = 0
            await interaction.followup.send("❌ MVP channel dinonaktifkan.", ephemeral=True)
        else:
            await set_setting("mvp_channel_id", str(interaction.channel.id))
            self.mvp_channel_id = interaction.channel.id
            await interaction.followup.send(
                f"✅ MVP channel diset ke <#{interaction.channel.id}>.", ephemeral=True
            )

    @app_commands.command(name="setup-mvp-image", description="[Admin] Set URL gambar untuk notifikasi MVP")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_mvp_image(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer(ephemeral=True)
        await set_setting("mvp_image_url", url.strip())
        self.mvp_image_url = url.strip()
        await interaction.followup.send(f"✅ MVP image diset.", ephemeral=True)

    # ── Leaderboard ──

    @app_commands.command(name="leaderboard", description="Lihat top 10 user dengan pesan paling banyak di starboard")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        medals = ["🥇", "🥈", "🥉"]

        def format_ranks(rows):
            lines = []
            for i, row in enumerate(rows):
                prefix = medals[i] if i < 3 else f"{i + 1}."
                lines.append(f"{prefix} <@{row[0]}> — **{row[1]}** pesan")
            return "\n".join(lines)

        now_wib = datetime.now(WIB)
        month_label = f"{BULAN_ID[now_wib.month]} {now_wib.year}"

        monthly = await get_starboard_leaderboard_monthly(now_wib.year, now_wib.month, 10)
        all_time = await get_starboard_leaderboard(10)

        if not monthly and not all_time:
            await interaction.followup.send("Belum ada pesan yang masuk starboard.", ephemeral=True)
            return

        embed = discord.Embed(title="⭐ Starboard Leaderboard", color=0xffd700)

        if monthly:
            embed.add_field(name=f"⭐ {month_label}", value=format_ranks(monthly), inline=False)
        else:
            embed.add_field(name=f"⭐ {month_label}", value="*Belum ada data bulan ini*", inline=False)

        if all_time:
            embed.add_field(name="🏆 All Time", value=format_ranks(all_time), inline=False)

        embed.set_footer(text="Ranking berdasarkan jumlah pesan yang masuk starboard")

        await interaction.followup.send(embed=embed)
