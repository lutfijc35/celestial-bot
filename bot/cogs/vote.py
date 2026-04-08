import logging
import re
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.utils.database import (
    create_poll, add_poll_option, get_poll, get_poll_options,
    upsert_vote, get_poll_results, get_voters_for_option,
    close_poll, get_expired_polls,
)
from config import GUILD_ID

logger = logging.getLogger("celestial")

NUMBER_EMOJIS = ["1\ufe0f\u20e3", "2\ufe0f\u20e3", "3\ufe0f\u20e3", "4\ufe0f\u20e3", "5\ufe0f\u20e3"]

DURATION_PATTERN = re.compile(r"^(\d+)([hd])$")


def parse_duration(text: str) -> timedelta | None:
    text = text.strip().lower()
    m = DURATION_PATTERN.match(text)
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        return timedelta(hours=val)
    elif unit == "d":
        return timedelta(days=val)
    return None


def build_poll_embed(title: str, results: list, total: int, poll_id: int, closed: bool = False, expires_at: str | None = None, closed_by: str | None = None):
    embed = discord.Embed(
        title=f"\U0001f4ca {title}" + (" \u2014 Closed" if closed else ""),
        color=0x4e5058 if closed else 0xffd700,
    )

    lines = []
    max_votes = max((r[2] for r in results), default=0)
    for i, (opt_id, label, votes) in enumerate(results):
        pct = (votes / total * 100) if total > 0 else 0
        bar_filled = round(pct / 10)
        bar = "\u2588" * bar_filled + "\u2591" * (10 - bar_filled)
        emoji = NUMBER_EMOJIS[i] if i < len(NUMBER_EMOJIS) else f"{i+1}."
        winner = " \U0001f3c6" if closed and votes == max_votes and votes > 0 else ""
        lines.append(f"{emoji} **{label}**{winner} \u2014 {votes} votes\n{bar} {pct:.0f}%")

    embed.description = "\n\n".join(lines) if lines else "*Belum ada opsi*"

    footer_parts = [f"Total: {total} votes"]
    if not closed and expires_at:
        try:
            exp_dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            footer_parts.append(f"Berakhir: <t:{int(exp_dt.timestamp())}:R>")
        except Exception:
            pass
    if closed and closed_by:
        footer_parts.append(f"Closed by {closed_by}")

    # Put expiry info in description if it's a Discord timestamp
    if not closed and expires_at:
        try:
            exp_dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            embed.description += f"\n\nBerakhir <t:{int(exp_dt.timestamp())}:R>"
        except Exception:
            pass

    embed.set_footer(text=f"Poll ID: {poll_id}" + (f" \u00b7 Closed by {closed_by}" if closed_by else ""))
    return embed


class VoteButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def handle_vote(self, interaction: discord.Interaction, button_index: int):
        # Get poll_id from footer
        poll_id = None
        if interaction.message and interaction.message.embeds:
            footer = interaction.message.embeds[0].footer
            if footer and footer.text:
                try:
                    poll_id = int(footer.text.split("Poll ID: ")[1].split(" ")[0].split("\u00b7")[0].strip())
                except (ValueError, IndexError):
                    pass

        if not poll_id:
            await interaction.response.send_message("\u274c Poll tidak ditemukan.", ephemeral=True)
            return

        poll = await get_poll(poll_id)
        if not poll or poll["status"] != "open":
            await interaction.response.send_message("\u26a0\ufe0f Poll ini sudah ditutup.", ephemeral=True)
            return

        options = await get_poll_options(poll_id)
        if button_index >= len(options):
            await interaction.response.send_message("\u274c Opsi tidak valid.", ephemeral=True)
            return

        option = options[button_index]
        await upsert_vote(poll_id, option["id"], str(interaction.user.id))

        # Update embed with new results
        results = await get_poll_results(poll_id)
        total = sum(r[2] for r in results)
        embed = build_poll_embed(poll["title"], results, total, poll_id, expires_at=poll["expires_at"])

        await interaction.response.edit_message(embed=embed)
        logger.info(f"[vote] {interaction.user} voted '{option['label']}' on poll #{poll_id}")

    @discord.ui.button(label="1", style=discord.ButtonStyle.primary, custom_id="celestial:vote_0", emoji="1\ufe0f\u20e3")
    async def vote_0(self, interaction, button):
        await self.handle_vote(interaction, 0)

    @discord.ui.button(label="2", style=discord.ButtonStyle.primary, custom_id="celestial:vote_1", emoji="2\ufe0f\u20e3")
    async def vote_1(self, interaction, button):
        await self.handle_vote(interaction, 1)

    @discord.ui.button(label="3", style=discord.ButtonStyle.primary, custom_id="celestial:vote_2", emoji="3\ufe0f\u20e3")
    async def vote_2(self, interaction, button):
        await self.handle_vote(interaction, 2)

    @discord.ui.button(label="4", style=discord.ButtonStyle.primary, custom_id="celestial:vote_3", emoji="4\ufe0f\u20e3")
    async def vote_3(self, interaction, button):
        await self.handle_vote(interaction, 3)

    @discord.ui.button(label="5", style=discord.ButtonStyle.primary, custom_id="celestial:vote_4", emoji="5\ufe0f\u20e3")
    async def vote_4(self, interaction, button):
        await self.handle_vote(interaction, 4)


class PollRoleAssignSelect(discord.ui.UserSelect):
    def __init__(self, poll_id: int, role_id: int):
        super().__init__(placeholder="Pilih member untuk diberi role...", min_values=1, max_values=1)
        self.poll_id = poll_id
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        member = self.values[0]
        guild = interaction.guild
        if not guild:
            return

        role = guild.get_role(self.role_id)
        if not role:
            await interaction.followup.send("\u274c Role tidak ditemukan.", ephemeral=True)
            return

        try:
            await member.add_roles(role, reason=f"Celestial: poll #{self.poll_id} role reward")
            await interaction.followup.send(
                f"\u2705 Role {role.mention} diberikan ke {member.mention}.", ephemeral=True
            )
            logger.info(f"[vote] Role '{role.name}' assigned to {member} from poll #{self.poll_id}")

            # Update embed + disable button on poll message
            poll = await get_poll(self.poll_id)
            if poll:
                ch = interaction.client.get_channel(int(poll["channel_id"]))
                if ch:
                    try:
                        poll_msg = await ch.fetch_message(int(poll["message_id"]))
                        if poll_msg.embeds:
                            embed = poll_msg.embeds[0]
                            embed.add_field(
                                name="🎁 Role Assigned",
                                value=f"{role.mention} → {member.mention}",
                                inline=False,
                            )
                        else:
                            embed = None
                        view = discord.ui.View()
                        view.add_item(discord.ui.Button(label="Closed", style=discord.ButtonStyle.secondary, disabled=True, emoji="🔒"))
                        view.add_item(discord.ui.Button(label=f"Role → {member.display_name}", style=discord.ButtonStyle.secondary, disabled=True, emoji="✅"))
                        await poll_msg.edit(embed=embed, view=view)
                    except (discord.NotFound, discord.HTTPException):
                        pass
        except discord.Forbidden:
            await interaction.followup.send("\u274c Bot tidak punya permission untuk assign role.", ephemeral=True)
        self.view.stop()


class PollRoleAssignView(discord.ui.View):
    def __init__(self, poll_id: int, role_id: int):
        super().__init__(timeout=60)
        self.add_item(PollRoleAssignSelect(poll_id, role_id))


class PollClosedView(discord.ui.View):
    """View shown after poll is closed -- disabled vote button + optional assign role button."""
    def __init__(self, has_role: bool = False):
        super().__init__(timeout=None)
        # Add disabled closed button
        closed_btn = discord.ui.Button(label="Closed", style=discord.ButtonStyle.secondary, disabled=True, emoji="\U0001f512", custom_id="celestial:vote_closed")
        self.add_item(closed_btn)

        if has_role:
            assign_btn = discord.ui.Button(label="Assign Role", style=discord.ButtonStyle.success, emoji="\U0001f381", custom_id="celestial:vote_assign_role")
            assign_btn.callback = self.assign_role_callback
            self.add_item(assign_btn)

    async def assign_role_callback(self, interaction: discord.Interaction):
        # Get poll_id from the message embed footer
        poll_id = None
        if interaction.message and interaction.message.embeds:
            footer = interaction.message.embeds[0].footer
            if footer and footer.text:
                try:
                    poll_id = int(footer.text.split("Poll ID: ")[1].split(" ")[0].split("\u00b7")[0].strip())
                except (ValueError, IndexError):
                    pass

        if not poll_id:
            await interaction.response.send_message("\u274c Poll tidak ditemukan.", ephemeral=True)
            return

        poll = await get_poll(poll_id)
        if not poll or not poll["role_id"]:
            await interaction.response.send_message("\u274c Role reward tidak diset.", ephemeral=True)
            return

        # Check permission: creator or admin
        is_creator = str(interaction.user.id) == poll["creator_id"]
        is_admin = interaction.user.guild_permissions.manage_channels if interaction.guild else False
        if not is_creator and not is_admin:
            await interaction.response.send_message("\u274c Kamu tidak punya permission.", ephemeral=True)
            return

        view = PollRoleAssignView(poll_id, int(poll["role_id"]))
        await interaction.response.send_message("Pilih member untuk diberi role:", view=view, ephemeral=True)


class VoteModal(discord.ui.Modal, title="\U0001f4ca Buat Polling"):
    judul = discord.ui.TextInput(label="Judul", required=True, max_length=200)
    opsi = discord.ui.TextInput(
        label="Opsi (pisah koma, max 5)",
        required=True,
        max_length=500,
        placeholder="Opsi A, Opsi B, Opsi C",
    )
    durasi = discord.ui.TextInput(
        label="Durasi (opsional: 1h, 6h, 1d, 3d, 7d, 30d)",
        required=False,
        max_length=10,
        placeholder="Kosongkan untuk manual close",
    )
    role_reward = discord.ui.TextInput(
        label="Role ID reward (opsional)",
        required=False,
        max_length=30,
        placeholder="Kosongkan jika tidak ada",
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Parse options
        options = [o.strip() for o in self.opsi.value.split(",") if o.strip()]
        if len(options) < 2:
            await interaction.followup.send("\u274c Minimal 2 opsi.", ephemeral=True)
            return
        if len(options) > 5:
            options = options[:5]

        # Parse duration
        expires_at = None
        expires_at_str = None
        if self.durasi.value.strip():
            delta = parse_duration(self.durasi.value)
            if not delta:
                await interaction.followup.send("\u274c Format durasi salah. Gunakan: 1h, 6h, 1d, 3d, 7d, 30d", ephemeral=True)
                return
            expires_at = datetime.now(timezone.utc) + delta
            expires_at_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")

        # Parse role
        role_id = None
        if self.role_reward.value.strip():
            try:
                role_id = str(int(self.role_reward.value.strip()))
            except ValueError:
                await interaction.followup.send("\u274c Role ID harus berupa angka.", ephemeral=True)
                return

        # Build initial embed
        results = [(0, opt, 0) for i, opt in enumerate(options)]
        embed = build_poll_embed(self.judul.value, results, 0, 0, expires_at=expires_at_str)

        # Create view with only needed buttons
        view = VoteButtonView()
        # Remove unused buttons (buttons for options that don't exist)
        children_to_keep = list(view.children)[:len(options)]
        view.clear_items()
        for child in children_to_keep:
            view.add_item(child)

        msg = await interaction.channel.send(embed=embed, view=view)

        # Create poll in DB
        poll_id = await create_poll(
            creator_id=str(interaction.user.id),
            title=self.judul.value,
            message_id=str(msg.id),
            channel_id=str(interaction.channel.id),
            role_id=role_id,
            expires_at=expires_at_str,
        )

        # Add options
        for opt in options:
            await add_poll_option(poll_id, opt)

        # Update embed with real poll_id
        results_real = await get_poll_results(poll_id)
        embed = build_poll_embed(self.judul.value, results_real, 0, poll_id, expires_at=expires_at_str)
        await msg.edit(embed=embed, view=view)

        await interaction.followup.send(f"\u2705 Poll #{poll_id} berhasil dibuat.", ephemeral=True)
        logger.info(f"[vote] Poll #{poll_id} created by {interaction.user}: '{self.judul.value}'")


async def do_close_poll(bot, poll, closed_by: str = "Auto"):
    """Shared logic to close a poll -- used by both /close-vote and auto-expire."""
    await close_poll(poll["id"])

    results = await get_poll_results(poll["id"])
    total = sum(r[2] for r in results)

    embed = build_poll_embed(poll["title"], results, total, poll["id"], closed=True, closed_by=closed_by)

    has_role = bool(poll["role_id"])
    view = PollClosedView(has_role=has_role)

    channel = bot.get_channel(int(poll["channel_id"]))
    if channel:
        try:
            msg = await channel.fetch_message(int(poll["message_id"]))
            await msg.edit(embed=embed, view=view)
        except (discord.NotFound, discord.HTTPException):
            pass

    logger.info(f"[vote] Poll #{poll['id']} closed by {closed_by}")


class VoteCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.check_expired_polls.start()

    async def cog_unload(self):
        self.check_expired_polls.cancel()

    @tasks.loop(minutes=5)
    async def check_expired_polls(self):
        expired = await get_expired_polls()
        for poll in expired:
            await do_close_poll(self.bot, poll, closed_by="Auto (durasi habis)")

    @check_expired_polls.before_loop
    async def before_check_expired(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="vote", description="Buat polling/vote baru")
    @app_commands.default_permissions(manage_channels=True)
    async def vote(self, interaction: discord.Interaction):
        await interaction.response.send_modal(VoteModal())

    @app_commands.command(name="close-vote", description="Tutup polling yang sedang aktif")
    async def close_vote(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Find open poll in this channel by checking recent messages
        # Better approach: user provides poll_id or we check all open polls in channel
        # For simplicity: find any open poll in this channel
        import aiosqlite
        from config import DB_PATH
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM polls WHERE channel_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
                (str(interaction.channel.id),)
            ) as cur:
                poll = await cur.fetchone()

        if not poll:
            await interaction.followup.send("\u274c Tidak ada poll aktif di channel ini.", ephemeral=True)
            return

        # Check permission: creator or admin
        is_creator = str(interaction.user.id) == poll["creator_id"]
        is_admin = interaction.user.guild_permissions.manage_channels if interaction.guild else False
        if not is_creator and not is_admin:
            await interaction.followup.send("\u274c Hanya pembuat poll atau admin yang bisa menutup.", ephemeral=True)
            return

        await do_close_poll(self.bot, poll, closed_by=interaction.user.display_name)
        await interaction.followup.send(f"\u2705 Poll #{poll['id']} berhasil ditutup.", ephemeral=True)
