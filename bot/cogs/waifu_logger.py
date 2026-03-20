import json
import logging
import os
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.database import get_setting, set_setting, delete_setting

logger = logging.getLogger("celestial")


class WaifuLoggerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.waifu_channel_id: int = 0
        self.waifu_bot_id: int = 0

    async def cog_load(self):
        ch = await get_setting("waifu_channel_id")
        self.waifu_channel_id = int(ch) if ch else 0
        bot_id = await get_setting("waifu_bot_id")
        self.waifu_bot_id = int(bot_id) if bot_id else 0

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.author.bot:
            return
        if not self.waifu_channel_id or message.channel.id != self.waifu_channel_id:
            return
        if self.waifu_bot_id and message.author.id != self.waifu_bot_id:
            return
        if not message.embeds:
            return

        embed = message.embeds[0]
        title = (embed.title or "").strip("*").strip()
        if title != "Character":
            return

        # Parse initials from description
        initials = ""
        description = embed.description or ""
        for line in description.split("\n"):
            if "initials" in line.lower():
                start = line.find("'")
                end = line.rfind("'")
                if start != -1 and end != -1 and start != end:
                    initials = line[start + 1:end]
                break

        image_url = embed.image.url if embed.image else ""
        thumbnail_url = embed.thumbnail.url if embed.thumbnail else ""

        entry = {
            "timestamp": message.created_at.isoformat(),
            "initials": initials,
            "image_url": image_url,
            "thumbnail_url": thumbnail_url,
            "message_id": str(message.id),
            "bot_name": message.author.name,
        }

        # Log rotation: data/waifu-log/YYYY-MM/week-WW.json
        now = datetime.now(timezone.utc)
        month_dir = os.path.join("data", "waifu-log", now.strftime("%Y-%m"))
        os.makedirs(month_dir, exist_ok=True)
        week_num = now.isocalendar()[1]
        log_path = os.path.join(month_dir, f"week-{week_num:02d}.json")

        data = []
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                data = json.load(f)

        data.append(entry)

        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"[waifu-log] Logged character: initials={initials} msg={message.id}")

    # ── Setup commands ──

    @app_commands.command(name="setup-waifu-log", description="[Admin] Set/unset channel ini sebagai waifu logger")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_waifu_log(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        current = await get_setting("waifu_channel_id")
        if current and int(current) == interaction.channel.id:
            await delete_setting("waifu_channel_id")
            self.waifu_channel_id = 0
            await interaction.followup.send("❌ Waifu logger channel dinonaktifkan.", ephemeral=True)
        else:
            await set_setting("waifu_channel_id", str(interaction.channel.id))
            self.waifu_channel_id = interaction.channel.id
            await interaction.followup.send(
                f"✅ Waifu logger channel diset ke <#{interaction.channel.id}>.", ephemeral=True
            )

    @app_commands.command(name="setup-waifu-bot", description="[Admin] Set bot yang dimonitor untuk waifu logger")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_waifu_bot(self, interaction: discord.Interaction, bot_user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        if not bot_user.bot:
            await interaction.followup.send("❌ User yang dipilih bukan bot.", ephemeral=True)
            return
        await set_setting("waifu_bot_id", str(bot_user.id))
        self.waifu_bot_id = bot_user.id
        await interaction.followup.send(
            f"✅ Waifu bot diset ke {bot_user.mention} (ID: `{bot_user.id}`).", ephemeral=True
        )
