import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.database import get_setting, set_setting, delete_setting

logger = logging.getLogger("celestial")


class TaskRequestModal(discord.ui.Modal, title="📋 Detail Request"):
    def __init__(self, promo_title: str):
        super().__init__()
        self.promo_title = promo_title

    nickname = discord.ui.TextInput(
        label="Nickname IGN", required=True, max_length=100
    )
    detail = discord.ui.TextInput(
        label="Detail Request",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000,
        placeholder="Jelaskan apa yang kamu butuhkan...",
    )
    budget = discord.ui.TextInput(
        label="Budget (opsional)",
        required=False,
        max_length=100,
        placeholder="Misal: 50k, nego, dll",
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        task_ch_id = await get_setting("task_channel_id")
        if not task_ch_id:
            await interaction.followup.send(
                "❌ Task channel belum diset oleh admin.", ephemeral=True
            )
            return

        channel = interaction.client.get_channel(int(task_ch_id))
        if not channel:
            await interaction.followup.send(
                "❌ Task channel tidak ditemukan.", ephemeral=True
            )
            return

        budget_val = self.budget.value.strip() or "—"

        embed = discord.Embed(
            title="📋 Task Request Baru",
            color=0xffa500,
        )
        embed.add_field(name="From", value=interaction.user.mention, inline=True)
        embed.add_field(name="Promosi", value=self.promo_title, inline=True)
        embed.add_field(name="IGN", value=f"`{self.nickname.value}`", inline=True)
        embed.add_field(name="Detail", value=self.detail.value, inline=False)
        embed.add_field(name="Budget", value=f"`{budget_val}`", inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        # Ping role jika diset
        task_role_id = await get_setting("task_role_id")
        content = f"<@&{task_role_id}>" if task_role_id else None

        await channel.send(content=content, embed=embed)

        # DM user konfirmasi
        try:
            await interaction.user.send(
                f"✅ **Request kamu sudah dikirim!**\n"
                f"Promosi: **{self.promo_title}**\n"
                f"Admin akan segera menghubungi kamu."
            )
        except discord.Forbidden:
            pass

        await interaction.followup.send(
            "✅ Request kamu sudah dikirim ke admin. Cek DM untuk konfirmasi.",
            ephemeral=True,
        )
        logger.info(f"[promote] Task request dari {interaction.user} untuk '{self.promo_title}'")


class TaskInterestButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Saya Tertarik",
        style=discord.ButtonStyle.primary,
        emoji="📩",
        custom_id="celestial:task_interest",
    )
    async def interest(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ambil judul promosi dari embed pesan
        promo_title = "Promosi"
        if interaction.message and interaction.message.embeds:
            promo_title = interaction.message.embeds[0].title or "Promosi"

        await interaction.response.send_modal(TaskRequestModal(promo_title))


class PromoteModal(discord.ui.Modal, title="💼 Buat Promosi"):
    judul = discord.ui.TextInput(label="Judul", required=True, max_length=200)
    deskripsi = discord.ui.TextInput(
        label="Deskripsi",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000,
    )
    harga = discord.ui.TextInput(
        label="Harga (opsional)",
        required=False,
        max_length=100,
        placeholder="Misal: 50k, 100k, nego",
    )

    async def on_submit(self, interaction: discord.Interaction):
        harga_val = self.harga.value.strip() or "Hubungi admin"

        embed = discord.Embed(
            title=self.judul.value,
            description=self.deskripsi.value,
            color=0x5865f2,
        )
        embed.add_field(name="💰 Harga", value=f"`{harga_val}`", inline=False)
        embed.set_footer(text="✦ Celestial Server · Klik tombol di bawah jika tertarik")

        view = TaskInterestButton()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Promosi berhasil di-post.", ephemeral=True)


class PromoteCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="promote", description="[Admin] Post promosi dengan tombol tertarik")
    @app_commands.default_permissions(manage_channels=True)
    async def promote(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PromoteModal())

    @app_commands.command(name="setup-task-channel", description="[Admin] Set/unset channel ini sebagai task channel")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_task_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        current = await get_setting("task_channel_id")
        if current and int(current) == interaction.channel.id:
            await delete_setting("task_channel_id")
            await interaction.followup.send("❌ Task channel dinonaktifkan.", ephemeral=True)
        else:
            await set_setting("task_channel_id", str(interaction.channel.id))
            await interaction.followup.send(
                f"✅ Task channel diset ke <#{interaction.channel.id}>.", ephemeral=True
            )

    @app_commands.command(name="setup-task-role", description="[Admin] Set role yang di-mention saat ada task request")
    @app_commands.default_permissions(manage_roles=True)
    async def setup_task_role(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        await set_setting("task_role_id", str(role.id))
        await interaction.followup.send(
            f"✅ Task role diset ke {role.mention}.", ephemeral=True
        )
