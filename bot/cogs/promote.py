import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.database import (
    get_setting, set_setting, delete_setting,
    create_active_task, get_active_task, get_active_task_by_channel,
    update_task_assign, update_task_closed,
)
from config import GUILD_ID

logger = logging.getLogger("celestial")


# ── Task Assign Flow ─────────────────────────────────────────────

class TaskAssignSelect(discord.ui.UserSelect):
    def __init__(self, task_id: int):
        super().__init__(placeholder="Pilih joki yang akan di-assign...", min_values=1, max_values=1)
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        joki = self.values[0]
        task = await get_active_task(self.task_id)
        if not task:
            await interaction.followup.send("❌ Task tidak ditemukan.", ephemeral=True)
            return

        if task["status"] != "open":
            await interaction.followup.send("⚠️ Task ini sudah di-assign.", ephemeral=True)
            return

        guild = interaction.guild
        if not guild:
            return

        # Get requester member
        requester = guild.get_member(int(task["requester_id"]))

        # Get task role for admin access
        task_role_id = await get_setting("task_role_id")
        task_role = guild.get_role(int(task_role_id)) if task_role_id else None

        # Create private channel with permission overwrites
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            joki: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        if requester:
            overwrites[requester] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        if task_role:
            overwrites[task_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        try:
            channel = await guild.create_text_channel(
                name=f"task-{self.task_id}",
                overwrites=overwrites,
                reason=f"Celestial: task #{self.task_id} assigned to {joki}",
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak punya permission untuk membuat channel.", ephemeral=True)
            return

        # Update DB
        await update_task_assign(self.task_id, str(joki.id), str(channel.id))

        # Send task info in new channel
        embed = discord.Embed(
            title=f"🔒 Task #{self.task_id} — Assigned",
            color=0x9b59b6,
        )
        embed.add_field(name="Requester", value=requester.mention if requester else f"<@{task['requester_id']}>", inline=True)
        embed.add_field(name="Joki", value=joki.mention, inline=True)
        embed.add_field(name="IGN", value=f"`{task['requester_ign']}`", inline=True)
        embed.add_field(name="Promosi", value=task["promo_title"], inline=True)
        embed.add_field(name="Budget", value=f"`{task['budget'] or '—'}`", inline=True)
        embed.add_field(name="Detail", value=task["detail"], inline=False)
        embed.set_footer(text="Silakan diskusi di channel ini · Admin: /close-task untuk menutup")

        requester_mention = requester.mention if requester else f"<@{task['requester_id']}>"
        await channel.send(
            content=f"{requester_mention} {joki.mention}",
            embed=embed,
        )

        # Edit original embed in #task-joki — mark as assigned
        try:
            original_msg = interaction.message
            if original_msg and original_msg.embeds:
                embed_edit = original_msg.embeds[0]
                embed_edit.color = discord.Color.green()
                embed_edit.add_field(name="Assigned", value=f"{joki.mention} → {channel.mention}", inline=False)
                # Disable the assign button
                view = discord.ui.View()
                btn = discord.ui.Button(label="Assigned", style=discord.ButtonStyle.secondary, disabled=True, emoji="✅")
                view.add_item(btn)
                await original_msg.edit(embed=embed_edit, view=view)
        except discord.HTTPException:
            pass

        # DM requester
        if requester:
            try:
                await requester.send(
                    f"✅ **Task kamu sudah di-assign!**\n"
                    f"Joki: {joki.mention}\n"
                    f"Channel: {channel.mention}\n"
                    f"Silakan diskusi di channel tersebut."
                )
            except discord.Forbidden:
                pass

        await interaction.followup.send(
            f"✅ Task #{self.task_id} di-assign ke {joki.mention} → {channel.mention}",
            ephemeral=True,
        )
        logger.info(f"[task] Task #{self.task_id} assigned to {joki} — channel {channel.name}")
        self.view.stop()


class TaskAssignSelectView(discord.ui.View):
    def __init__(self, task_id: int):
        super().__init__(timeout=60)
        self.add_item(TaskAssignSelect(task_id))


class TaskAssignView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Assign",
        style=discord.ButtonStyle.success,
        emoji="👤",
        custom_id="celestial:task_assign",
    )
    async def assign(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Get task_id from embed footer
        task_id = None
        if interaction.message and interaction.message.embeds:
            footer = interaction.message.embeds[0].footer
            if footer and footer.text:
                # Footer format: "Task ID: 5"
                try:
                    task_id = int(footer.text.replace("Task ID: ", ""))
                except ValueError:
                    pass

        if not task_id:
            await interaction.response.send_message("❌ Task ID tidak ditemukan.", ephemeral=True)
            return

        task = await get_active_task(task_id)
        if not task:
            await interaction.response.send_message("❌ Task tidak ditemukan.", ephemeral=True)
            return

        if task["status"] != "open":
            await interaction.response.send_message("⚠️ Task ini sudah di-assign.", ephemeral=True)
            return

        view = TaskAssignSelectView(task_id)
        await interaction.response.send_message(
            "Pilih member yang akan jadi joki:", view=view, ephemeral=True
        )


# ── Task Request Modal ───────────────────────────────────────────

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

        # Send with assign button — footer will be updated with task_id after DB insert
        task_role_id = await get_setting("task_role_id")
        content = f"<@&{task_role_id}>" if task_role_id else None

        # Temporary footer, will be updated
        embed.set_footer(text="Task ID: ...")

        view = TaskAssignView()
        msg = await channel.send(content=content, embed=embed, view=view)

        # Insert to DB
        task_id = await create_active_task(
            requester_id=str(interaction.user.id),
            requester_ign=self.nickname.value.strip(),
            promo_title=self.promo_title,
            detail=self.detail.value.strip(),
            budget=budget_val if budget_val != "—" else None,
            request_msg_id=str(msg.id),
        )

        # Update footer with actual task_id
        embed.set_footer(text=f"Task ID: {task_id}")
        await msg.edit(embed=embed, view=view)

        # DM user konfirmasi
        try:
            await interaction.user.send(
                f"✅ **Request kamu sudah dikirim!**\n"
                f"Promosi: **{self.promo_title}**\n"
                f"Task ID: `#{task_id}`\n"
                f"Admin akan segera menghubungi kamu."
            )
        except discord.Forbidden:
            pass

        await interaction.followup.send(
            f"✅ Request kamu sudah dikirim (Task #{task_id}). Cek DM untuk konfirmasi.",
            ephemeral=True,
        )
        logger.info(f"[task] New task #{task_id} from {interaction.user} for '{self.promo_title}'")


# ── Interest Button (persistent) ─────────────────────────────────

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
        promo_title = "Promosi"
        if interaction.message and interaction.message.embeds:
            promo_title = interaction.message.embeds[0].title or "Promosi"

        await interaction.response.send_modal(TaskRequestModal(promo_title))


# ── Promote Modal ────────────────────────────────────────────────

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


# ── Cog ──────────────────────────────────────────────────────────

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

    @app_commands.command(name="close-task", description="Tutup task dan hapus channel ini")
    async def close_task(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Cek permission: manage_channels ATAU punya task role
        task_role_id = await get_setting("task_role_id")
        has_task_role = False
        if task_role_id and interaction.guild:
            role = interaction.guild.get_role(int(task_role_id))
            if role and role in interaction.user.roles:
                has_task_role = True

        has_manage = interaction.user.guild_permissions.manage_channels if interaction.guild else False

        if not has_task_role and not has_manage:
            await interaction.followup.send(
                "❌ Kamu tidak punya permission untuk menutup task.", ephemeral=True
            )
            return

        task = await get_active_task_by_channel(str(interaction.channel.id))
        if not task:
            await interaction.followup.send(
                "❌ Channel ini bukan task channel atau task sudah closed.", ephemeral=True
            )
            return

        # Save transcript
        transcript_lines = []
        transcript_lines.append(f"=== Transcript Task #{task['id']} ===")
        transcript_lines.append(f"Requester: {task['requester_id']} (IGN: {task['requester_ign']})")
        transcript_lines.append(f"Joki: {task['joki_id'] or '—'}")
        transcript_lines.append(f"Promosi: {task['promo_title']}")
        transcript_lines.append(f"Detail: {task['detail']}")
        transcript_lines.append(f"Budget: {task['budget'] or '—'}")
        transcript_lines.append(f"Created: {task['created_at']}")
        transcript_lines.append(f"Closed by: {interaction.user} ({interaction.user.id})")
        transcript_lines.append("")
        transcript_lines.append("=== Chat Log ===")

        async for msg in interaction.channel.history(limit=None, oldest_first=True):
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author = f"{msg.author.display_name} ({msg.author.id})"
            content = msg.content or ""
            if msg.embeds:
                content += " [embed]"
            if msg.attachments:
                urls = ", ".join(a.url for a in msg.attachments)
                content += f" [attachments: {urls}]"
            transcript_lines.append(f"[{timestamp}] {author}: {content}")

        # Save to data/task-transcripts/task-{id}.txt
        import os
        transcript_dir = os.path.join("data", "task-transcripts")
        os.makedirs(transcript_dir, exist_ok=True)
        transcript_path = os.path.join(transcript_dir, f"task-{task['id']}.txt")

        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write("\n".join(transcript_lines))

        logger.info(f"[task] Transcript saved: {transcript_path}")

        # Send summary to #task-joki
        task_ch_id = await get_setting("task_channel_id")
        if task_ch_id:
            task_channel = interaction.client.get_channel(int(task_ch_id))
            if task_channel:
                now = datetime.now(timezone.utc)
                created = task["created_at"]
                duration = "—"
                if created:
                    try:
                        created_dt = datetime.strptime(created, "%Y-%m-%d %H:%M:%S")
                        delta = now - created_dt.replace(tzinfo=timezone.utc)
                        days = delta.days
                        hours = delta.seconds // 3600
                        duration = f"{days}d {hours}h" if days > 0 else f"{hours}h"
                    except Exception:
                        pass

                summary = discord.Embed(
                    title=f"✅ Task #{task['id']} — Closed",
                    color=discord.Color.green(),
                )
                summary.add_field(name="Requester", value=f"<@{task['requester_id']}>", inline=True)
                summary.add_field(name="Joki", value=f"<@{task['joki_id']}>" if task["joki_id"] else "—", inline=True)
                summary.add_field(name="Durasi", value=f"`{duration}`", inline=True)
                summary.add_field(name="Promosi", value=task["promo_title"], inline=True)
                summary.add_field(name="Transcript", value=f"`{transcript_path}`", inline=False)
                summary.set_footer(text=f"Closed by {interaction.user.display_name}")

                await task_channel.send(embed=summary)

        # Update DB
        await update_task_closed(task["id"])

        await interaction.followup.send("✅ Task closed. Transcript tersimpan. Channel akan dihapus dalam 5 detik...", ephemeral=True)

        # Delete channel
        import asyncio
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Celestial: task #{task['id']} closed")
            logger.info(f"[task] Task #{task['id']} closed by {interaction.user}")
        except discord.Forbidden:
            logger.error(f"[task] Cannot delete channel for task #{task['id']}")
