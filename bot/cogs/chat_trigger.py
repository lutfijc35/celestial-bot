import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.database import (
    add_chat_trigger, get_all_chat_triggers, delete_chat_trigger,
)

logger = logging.getLogger("celestial")


class AddTriggerModal(discord.ui.Modal, title="💬 Tambah Chat Trigger"):
    pattern = discord.ui.TextInput(
        label="Pattern (regex, case-insensitive)",
        required=True,
        max_length=500,
        placeholder="Contoh: halo|hi|hai",
    )
    response_text = discord.ui.TextInput(
        label="Response Text (opsional)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=2000,
        placeholder="Pesan balasan bot",
    )
    image_url = discord.ui.TextInput(
        label="Image URL (opsional)",
        required=False,
        max_length=500,
        placeholder="https://...",
    )
    channel_id = discord.ui.TextInput(
        label="Channel ID (opsional, kosong = semua)",
        required=False,
        max_length=30,
        placeholder="Kosongkan untuk semua channel",
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        pattern = self.pattern.value.strip()
        text = self.response_text.value.strip() or None
        image = self.image_url.value.strip() or None
        ch_id = self.channel_id.value.strip() or None

        if not text and not image:
            await interaction.followup.send(
                "❌ Minimal isi salah satu: Response Text atau Image URL.", ephemeral=True
            )
            return

        # Validate regex
        try:
            re.compile(pattern)
        except re.error as e:
            await interaction.followup.send(
                f"❌ Pattern regex tidak valid: `{e}`", ephemeral=True
            )
            return

        # Validate channel ID if provided
        if ch_id:
            try:
                int(ch_id)
            except ValueError:
                await interaction.followup.send(
                    "❌ Channel ID harus berupa angka.", ephemeral=True
                )
                return

        trigger_id = await add_chat_trigger(
            pattern=pattern,
            response_text=text,
            image_url=image,
            channel_id=ch_id,
            created_by=str(interaction.user.id),
        )

        # Refresh cache
        await self.cog.reload_triggers()

        ch_label = f"<#{ch_id}>" if ch_id else "semua channel"
        await interaction.followup.send(
            f"✅ Trigger #{trigger_id} ditambah.\n"
            f"Pattern: `{pattern}`\n"
            f"Channel: {ch_label}",
            ephemeral=True,
        )
        logger.info(f"[trigger] Added trigger #{trigger_id} by {interaction.user}")


class ChatTriggerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.triggers = []  # cache

    async def cog_load(self):
        await self.reload_triggers()

    async def reload_triggers(self):
        rows = await get_all_chat_triggers()
        self.triggers = [dict(row) for row in rows]
        logger.info(f"[trigger] Loaded {len(self.triggers)} chat triggers")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.content:
            return
        if not self.triggers:
            return

        for trigger in self.triggers:
            # Channel filter
            if trigger["channel_id"] and str(message.channel.id) != trigger["channel_id"]:
                continue

            try:
                if not re.search(trigger["pattern"], message.content, re.IGNORECASE):
                    continue
            except re.error:
                continue

            # Match! Build response
            text = trigger["response_text"]
            image = trigger["image_url"]

            try:
                if image:
                    embed = discord.Embed(color=0x5865f2)
                    embed.set_image(url=image)
                    await message.reply(content=text, embed=embed, mention_author=False)
                else:
                    await message.reply(content=text, mention_author=False)
                logger.info(f"[trigger] Trigger #{trigger['id']} fired for {message.author}")
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warning(f"[trigger] Failed to respond to trigger #{trigger['id']}: {e}")

            # Only respond to first match
            break

    @app_commands.command(name="add-trigger", description="[Admin] Tambah chat trigger (auto-response regex)")
    @app_commands.default_permissions(manage_channels=True)
    async def add_trigger(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddTriggerModal(self))

    @app_commands.command(name="list-triggers", description="[Admin] Lihat semua chat trigger")
    @app_commands.default_permissions(manage_channels=True)
    async def list_triggers(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        triggers = await get_all_chat_triggers()
        if not triggers:
            await interaction.followup.send("Belum ada trigger.", ephemeral=True)
            return

        embed = discord.Embed(title="💬 Chat Triggers", color=0x5865f2)
        for t in triggers:
            ch_label = f"<#{t['channel_id']}>" if t['channel_id'] else "semua channel"
            preview_parts = []
            if t["response_text"]:
                preview = t["response_text"][:50] + ("..." if len(t["response_text"]) > 50 else "")
                preview_parts.append(f"Text: {preview}")
            if t["image_url"]:
                preview_parts.append("🖼️ ada gambar")
            preview = "\n".join(preview_parts) or "—"

            embed.add_field(
                name=f"#{t['id']} · Pattern: `{t['pattern']}`",
                value=f"Channel: {ch_label}\n{preview}",
                inline=False,
            )

        embed.set_footer(text=f"Total: {len(triggers)} trigger")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="remove-trigger", description="[Admin] Hapus chat trigger by ID")
    @app_commands.default_permissions(manage_channels=True)
    async def remove_trigger(self, interaction: discord.Interaction, trigger_id: int):
        await interaction.response.defer(ephemeral=True)

        affected = await delete_chat_trigger(trigger_id)
        if affected == 0:
            await interaction.followup.send(f"❌ Trigger #{trigger_id} tidak ditemukan.", ephemeral=True)
            return

        await self.reload_triggers()
        await interaction.followup.send(f"✅ Trigger #{trigger_id} dihapus.", ephemeral=True)
        logger.info(f"[trigger] Removed trigger #{trigger_id} by {interaction.user}")
