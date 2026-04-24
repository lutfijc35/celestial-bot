import io
import logging
from datetime import datetime, timezone, timedelta

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.utils.database import (
    create_sticker_poll, get_sticker_poll, upsert_sticker_vote,
    delete_sticker_vote, get_sticker_vote, get_sticker_vote_counts,
    get_last_sticker_submission_by_user,
    get_active_retention_poll_for_sticker,
    close_sticker_poll, set_sticker_poll_status, set_sticker_discord_id,
    get_expired_sticker_polls, get_active_sticker_polls,
    get_setting, set_setting, delete_setting,
)
from config import GUILD_ID

logger = logging.getLogger("celestial")

VOTE_DURATION = timedelta(days=7)
COOLDOWN = timedelta(days=1)
MAX_FILE_SIZE = 512 * 1024
THRESHOLD_NET = 5
THRESHOLD_MIN_VOTERS = 10


# ── Embed builders ────────────────────────────────────────────────

def _progress_bar(value: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    filled = round(value / total * width)
    return "█" * filled + "░" * (width - filled)


def _status_line_submit(up: int, down: int) -> str:
    net = up - down
    total = up + down
    ok = net >= THRESHOLD_NET and total >= THRESHOLD_MIN_VOTERS
    mark = "✓" if ok else "✗"
    color = "\U0001f7e2" if ok else "\U0001f534"
    return f"{color} Net: **{net:+d}** · Voter: **{total}** · Threshold: net ≥ {THRESHOLD_NET} & min {THRESHOLD_MIN_VOTERS} voter {mark}"


def _status_line_retention(keep: int, remove: int) -> str:
    net_remove = remove - keep
    total = keep + remove
    will_remove = net_remove >= THRESHOLD_NET and total >= THRESHOLD_MIN_VOTERS
    mark = "✓ remove" if will_remove else "✗ tidak cukup untuk remove"
    return f"Net Remove: **{net_remove:+d}** · Voter: **{total}** · Threshold: {mark}"


def build_submit_embed(poll: dict, up: int, down: int, state: str = "voting") -> discord.Embed:
    """state: voting | pending_approval | added | rejected"""
    if state == "voting":
        color = 0xffd700
        title = f"\U0001f3a8 Sticker Submission: {poll['sticker_name']}"
    elif state == "pending_approval":
        color = 0x3ba55c
        title = f"\U0001f3a8 {poll['sticker_name']} — Pending Approval"
    elif state == "added":
        color = 0x3ba55c
        title = f"\U0001f389 {poll['sticker_name']} — Added to Server!"
    else:  # rejected
        color = 0xed4245
        title = f"\U0001f3a8 {poll['sticker_name']} — Not Enough Votes"

    embed = discord.Embed(title=title, color=color)
    embed.description = (
        f"Disubmit oleh <@{poll['initiator_id']}> · Tag: {poll['sticker_tag'] or '—'}"
    )
    if poll.get("image_url"):
        embed.set_image(url=poll["image_url"])

    total = up + down
    up_pct = (up / total * 100) if total > 0 else 0
    down_pct = (down / total * 100) if total > 0 else 0

    bar_up = _progress_bar(up, max(total, 1))
    bar_down = _progress_bar(down, max(total, 1))

    embed.add_field(
        name="\U0001f44d Upvote",
        value=f"`{bar_up}` **{up}** ({up_pct:.0f}%)",
        inline=False,
    )
    embed.add_field(
        name="\U0001f44e Downvote",
        value=f"`{bar_down}` **{down}** ({down_pct:.0f}%)",
        inline=False,
    )

    if state == "voting":
        status = _status_line_submit(up, down)
        try:
            exp_dt = datetime.strptime(poll["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            expires_str = f"Berakhir <t:{int(exp_dt.timestamp())}:R>"
        except Exception:
            expires_str = ""
        embed.add_field(name="Status", value=f"{status}\n{expires_str}".strip(), inline=False)
    elif state == "pending_approval":
        net = up - down
        embed.add_field(
            name="Hasil Voting",
            value=f"\U0001f7e2 Net **+{net}** dari **{up+down} voter** — nunggu approval admin.",
            inline=False,
        )
    elif state == "added":
        net = up - down
        embed.add_field(name="Final Score", value=f"\U0001f44d {up} · \U0001f44e {down} (net +{net})", inline=True)
        if poll.get("discord_sticker_id"):
            embed.add_field(name="Sticker ID", value=f"`{poll['discord_sticker_id']}`", inline=True)
        embed.add_field(name="Status", value="✅ Live di sticker picker", inline=False)
    else:  # rejected
        net = up - down
        embed.add_field(
            name="Hasil Voting",
            value=f"\U0001f534 Net **{net:+d}** dari **{up+down} voter** — threshold tidak tercapai.",
            inline=False,
        )

    embed.set_footer(text=f"Submission #{poll['id']} · Threshold: net ≥ {THRESHOLD_NET} & min {THRESHOLD_MIN_VOTERS} voter")
    return embed


def build_retention_embed(poll: dict, keep: int, remove: int, state: str = "voting") -> discord.Embed:
    """state: voting | pending_removal | removed | kept | kept_override"""
    if state == "voting":
        color = 0xfaa61a
        title = f"\U0001f5f3️ Retention Poll: {poll['sticker_name']}"
    elif state == "pending_removal":
        color = 0xed4245
        title = f"\U0001f5f3️ {poll['sticker_name']} — Pending Removal"
    elif state == "removed":
        color = 0x4e5058
        title = f"\U0001f5d1️ {poll['sticker_name']} — Removed from Server"
    elif state == "kept_override":
        color = 0xfaa61a
        title = f"\U0001f5f3️ {poll['sticker_name']} — Kept (Admin Override)"
    else:  # kept
        color = 0x3ba55c
        title = f"\U0001f5f3️ {poll['sticker_name']} — Kept by Vote"

    embed = discord.Embed(title=title, color=color)
    embed.description = (
        f"Di-trigger oleh <@{poll['initiator_id']}> · Masih mau dipertahankan?"
    )
    if poll.get("image_url"):
        embed.set_image(url=poll["image_url"])

    total = keep + remove
    keep_pct = (keep / total * 100) if total > 0 else 0
    rem_pct = (remove / total * 100) if total > 0 else 0

    bar_keep = _progress_bar(keep, max(total, 1))
    bar_rem = _progress_bar(remove, max(total, 1))

    embed.add_field(
        name="\U0001f49a Keep",
        value=f"`{bar_keep}` **{keep}** ({keep_pct:.0f}%)",
        inline=False,
    )
    embed.add_field(
        name="\U0001f5d1️ Remove",
        value=f"`{bar_rem}` **{remove}** ({rem_pct:.0f}%)",
        inline=False,
    )

    if state == "voting":
        status = _status_line_retention(keep, remove)
        try:
            exp_dt = datetime.strptime(poll["expires_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            expires_str = f"Berakhir <t:{int(exp_dt.timestamp())}:R>"
        except Exception:
            expires_str = ""
        embed.add_field(name="Status", value=f"{status}\n{expires_str}".strip(), inline=False)
    elif state == "pending_removal":
        embed.add_field(
            name="Hasil Voting",
            value=f"\U0001f7e0 Community vote: **hapus** — nunggu konfirmasi admin.",
            inline=False,
        )
    elif state == "removed":
        net = remove - keep
        embed.add_field(name="Final Score", value=f"\U0001f49a {keep} · \U0001f5d1️ {remove} (net remove +{net})", inline=True)
        embed.add_field(name="Status", value="\U0001f5d1️ Removed permanen", inline=False)
    elif state == "kept_override":
        embed.add_field(
            name="Hasil Voting",
            value="⚠️ Admin meng-override hasil voting — sticker tetap dipertahankan.",
            inline=False,
        )
    else:  # kept
        embed.add_field(
            name="Hasil Voting",
            value="\U0001f49a Community vote: **keep** — sticker dipertahankan.",
            inline=False,
        )

    embed.set_footer(text=f"Retention Poll #{poll['id']} · Threshold remove: net ≥ {THRESHOLD_NET} & min {THRESHOLD_MIN_VOTERS} voter")
    return embed


# ── Vote views (active voting) ────────────────────────────────────

async def _extract_poll_id(interaction: discord.Interaction) -> int | None:
    if not (interaction.message and interaction.message.embeds):
        return None
    footer = interaction.message.embeds[0].footer
    if not (footer and footer.text):
        return None
    # Footer format: "Submission #12 ..." or "Retention Poll #15 ..."
    text = footer.text
    try:
        return int(text.split("#")[1].split(" ")[0].split("·")[0].strip())
    except (ValueError, IndexError):
        return None


async def _handle_sticker_vote(interaction: discord.Interaction, vote_type: str, poll_type: str):
    poll_id = await _extract_poll_id(interaction)
    if not poll_id:
        await interaction.response.send_message("❌ Poll tidak ditemukan.", ephemeral=True)
        return

    poll = await get_sticker_poll(poll_id)
    if not poll or poll["status"] != "voting":
        await interaction.response.send_message("⚠️ Voting ini sudah ditutup.", ephemeral=True)
        return
    if poll["poll_type"] != poll_type:
        await interaction.response.send_message("❌ Tipe poll tidak cocok.", ephemeral=True)
        return

    voter_id = str(interaction.user.id)
    existing = await get_sticker_vote(poll_id, voter_id)

    if existing == vote_type:
        # Same button → cancel vote
        await delete_sticker_vote(poll_id, voter_id)
        msg = f"❌ Vote kamu dibatalkan."
    else:
        await upsert_sticker_vote(poll_id, voter_id, vote_type)
        label_map = {"up": "\U0001f44d Upvote", "down": "\U0001f44e Downvote",
                     "keep": "\U0001f49a Keep", "remove": "\U0001f5d1️ Remove"}
        msg = f"✅ Vote tercatat: **{label_map.get(vote_type, vote_type)}**. (Klik tombol yang sama untuk batal.)"

    # Update embed
    if poll_type == "submit":
        up, down = await get_sticker_vote_counts(poll_id, "up", "down")
        embed = build_submit_embed(dict(poll), up, down, state="voting")
    else:
        keep, remove = await get_sticker_vote_counts(poll_id, "keep", "remove")
        embed = build_retention_embed(dict(poll), keep, remove, state="voting")

    await interaction.response.edit_message(embed=embed)
    await interaction.followup.send(msg, ephemeral=True)
    logger.info(f"[sticker] {interaction.user} voted '{vote_type}' on {poll_type} poll #{poll_id}")


class StickerSubmitVoteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Upvote", style=discord.ButtonStyle.success, custom_id="celestial:sticker_vote:up", emoji="\U0001f44d")
    async def up(self, interaction: discord.Interaction, button):
        await _handle_sticker_vote(interaction, "up", "submit")

    @discord.ui.button(label="Downvote", style=discord.ButtonStyle.danger, custom_id="celestial:sticker_vote:down", emoji="\U0001f44e")
    async def down(self, interaction: discord.Interaction, button):
        await _handle_sticker_vote(interaction, "down", "submit")


class StickerRetentionVoteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Keep", style=discord.ButtonStyle.success, custom_id="celestial:sticker_retain:keep", emoji="\U0001f49a")
    async def keep(self, interaction: discord.Interaction, button):
        await _handle_sticker_vote(interaction, "keep", "retention")

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.danger, custom_id="celestial:sticker_retain:remove", emoji="\U0001f5d1️")
    async def remove(self, interaction: discord.Interaction, button):
        await _handle_sticker_vote(interaction, "remove", "retention")


# ── Admin permission helper ───────────────────────────────────────

async def _is_sticker_admin(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    if interaction.user.guild_permissions.manage_emojis_and_stickers:
        return True
    if interaction.user.guild_permissions.manage_guild:
        return True
    role_id = await get_setting("sticker_admin_role_id")
    if role_id:
        try:
            role = interaction.guild.get_role(int(role_id))
            if role and role in interaction.user.roles:
                return True
        except (ValueError, AttributeError):
            pass
    return False


# ── Approval view (submit closed → admin approve/reject) ──────────

async def _upload_sticker_to_guild(bot: commands.Bot, poll: dict) -> tuple[bool, str, str | None]:
    """Return (success, message, sticker_id)."""
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return False, "Guild tidak ditemukan.", None

    if len(guild.stickers) >= guild.sticker_limit:
        return False, (
            f"⚠️ Slot sticker penuh ({len(guild.stickers)}/{guild.sticker_limit}). "
            f"Hapus sticker lama via **Server Settings → Stickers** dulu, lalu klik Approve lagi."
        ), None

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(poll["image_url"]) as resp:
                if resp.status != 200:
                    return False, f"Gagal download file (HTTP {resp.status}).", None
                file_bytes = await resp.read()
    except Exception as e:
        return False, f"Error download file: {e}", None

    try:
        sticker = await guild.create_sticker(
            name=poll["sticker_name"],
            emoji=poll["sticker_tag"] or "\U0001f3a8",
            description=f"Submitted by user {poll['initiator_id']}",
            file=discord.File(io.BytesIO(file_bytes), filename="sticker.png"),
            reason=f"Celestial sticker submission #{poll['id']}",
        )
        return True, "OK", str(sticker.id)
    except discord.Forbidden:
        return False, "❌ Bot tidak punya permission Manage Expressions.", None
    except discord.HTTPException as e:
        return False, f"❌ Gagal upload: {e}", None


class StickerApprovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Approve & Upload", style=discord.ButtonStyle.success, custom_id="celestial:sticker_approve", emoji="✅")
    async def approve(self, interaction: discord.Interaction, button):
        if not await _is_sticker_admin(interaction):
            await interaction.response.send_message("❌ Kamu tidak punya permission.", ephemeral=True)
            return

        poll_id = await _extract_poll_id(interaction)
        if not poll_id:
            await interaction.response.send_message("❌ Poll tidak ditemukan.", ephemeral=True)
            return

        poll = await get_sticker_poll(poll_id)
        if not poll or poll["status"] != "pending_approval":
            await interaction.response.send_message("⚠️ Submission sudah diproses.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        success, msg, sticker_id = await _upload_sticker_to_guild(interaction.client, dict(poll))
        if not success:
            # Slot penuh atau error lain — status tetap pending_approval, tombol tetap aktif
            await interaction.followup.send(msg, ephemeral=True)
            return

        await set_sticker_discord_id(poll_id, sticker_id)
        await close_sticker_poll(poll_id, "added")

        # Re-fetch with discord_sticker_id
        poll = await get_sticker_poll(poll_id)
        up, down = await get_sticker_vote_counts(poll_id, "up", "down")
        embed = build_submit_embed(dict(poll), up, down, state="added")

        disabled_view = discord.ui.View()
        disabled_view.add_item(discord.ui.Button(label="Added", style=discord.ButtonStyle.success, disabled=True, emoji="✅"))

        try:
            await interaction.message.edit(embed=embed, view=disabled_view)
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            f"✅ Sticker **{poll['sticker_name']}** berhasil di-upload ke server!",
            ephemeral=True,
        )
        logger.info(f"[sticker] Submission #{poll_id} approved & uploaded by {interaction.user}")

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="celestial:sticker_reject", emoji="❌")
    async def reject(self, interaction: discord.Interaction, button):
        if not await _is_sticker_admin(interaction):
            await interaction.response.send_message("❌ Kamu tidak punya permission.", ephemeral=True)
            return

        poll_id = await _extract_poll_id(interaction)
        if not poll_id:
            await interaction.response.send_message("❌ Poll tidak ditemukan.", ephemeral=True)
            return

        poll = await get_sticker_poll(poll_id)
        if not poll or poll["status"] != "pending_approval":
            await interaction.response.send_message("⚠️ Submission sudah diproses.", ephemeral=True)
            return

        await close_sticker_poll(poll_id, "rejected")

        up, down = await get_sticker_vote_counts(poll_id, "up", "down")
        embed = build_submit_embed(dict(poll), up, down, state="rejected")

        disabled_view = discord.ui.View()
        disabled_view.add_item(discord.ui.Button(label="Rejected", style=discord.ButtonStyle.danger, disabled=True, emoji="❌"))

        try:
            await interaction.message.edit(embed=embed, view=disabled_view)
        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            f"❌ Submission **{poll['sticker_name']}** di-reject.", ephemeral=True,
        )
        logger.info(f"[sticker] Submission #{poll_id} rejected by {interaction.user}")


# ── Removal view (retention closed → admin confirm/cancel) ────────

class StickerRemovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Confirm Remove", style=discord.ButtonStyle.danger, custom_id="celestial:sticker_confirm_remove", emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button):
        if not await _is_sticker_admin(interaction):
            await interaction.response.send_message("❌ Kamu tidak punya permission.", ephemeral=True)
            return

        poll_id = await _extract_poll_id(interaction)
        if not poll_id:
            await interaction.response.send_message("❌ Poll tidak ditemukan.", ephemeral=True)
            return

        poll = await get_sticker_poll(poll_id)
        if not poll or poll["status"] != "pending_removal":
            await interaction.response.send_message("⚠️ Poll sudah diproses.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.client.get_guild(GUILD_ID)
        if not guild:
            await interaction.followup.send("❌ Guild tidak ditemukan.", ephemeral=True)
            return

        sticker_id_str = poll["discord_sticker_id"]
        deleted = False
        if sticker_id_str:
            try:
                sticker = discord.utils.get(guild.stickers, id=int(sticker_id_str))
                if sticker is None:
                    # Try fetch
                    try:
                        sticker = await guild.fetch_sticker(int(sticker_id_str))
                    except discord.NotFound:
                        sticker = None
                if sticker:
                    await sticker.delete(reason=f"Celestial retention poll #{poll_id}")
                    deleted = True
                else:
                    # Sticker sudah hilang — anggap selesai
                    deleted = True
            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ Bot tidak punya permission Manage Expressions untuk hapus sticker.",
                    ephemeral=True,
                )
                return
            except discord.HTTPException as e:
                await interaction.followup.send(f"❌ Gagal hapus sticker: {e}", ephemeral=True)
                return
            except ValueError:
                pass

        await close_sticker_poll(poll_id, "removed")

        keep, remove = await get_sticker_vote_counts(poll_id, "keep", "remove")
        embed = build_retention_embed(dict(poll), keep, remove, state="removed")

        disabled_view = discord.ui.View()
        disabled_view.add_item(discord.ui.Button(label="Removed", style=discord.ButtonStyle.secondary, disabled=True, emoji="\U0001f5d1️"))

        try:
            await interaction.message.edit(embed=embed, view=disabled_view)
        except discord.HTTPException:
            pass

        note = "" if deleted else " (sticker tidak ditemukan, hanya update status)"
        await interaction.followup.send(
            f"✅ Sticker **{poll['sticker_name']}** dihapus{note}.", ephemeral=True,
        )
        logger.info(f"[sticker] Retention poll #{poll_id} confirmed remove by {interaction.user}")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="celestial:sticker_cancel_remove", emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button):
        if not await _is_sticker_admin(interaction):
            await interaction.response.send_message("❌ Kamu tidak punya permission.", ephemeral=True)
            return

        poll_id = await _extract_poll_id(interaction)
        if not poll_id:
            await interaction.response.send_message("❌ Poll tidak ditemukan.", ephemeral=True)
            return

        poll = await get_sticker_poll(poll_id)
        if not poll or poll["status"] != "pending_removal":
            await interaction.response.send_message("⚠️ Poll sudah diproses.", ephemeral=True)
            return

        await close_sticker_poll(poll_id, "kept")

        keep, remove = await get_sticker_vote_counts(poll_id, "keep", "remove")
        embed = build_retention_embed(dict(poll), keep, remove, state="kept_override")

        disabled_view = discord.ui.View()
        disabled_view.add_item(discord.ui.Button(label="Kept (override)", style=discord.ButtonStyle.secondary, disabled=True, emoji="\U0001f49a"))

        try:
            await interaction.message.edit(embed=embed, view=disabled_view)
        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            f"✅ Sticker **{poll['sticker_name']}** dipertahankan (admin override).",
            ephemeral=True,
        )
        logger.info(f"[sticker] Retention poll #{poll_id} cancelled by {interaction.user}")


# ── Cog ───────────────────────────────────────────────────────────

class StickerVoteCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.check_expired_sticker_polls.start()

    async def cog_unload(self):
        self.check_expired_sticker_polls.cancel()

    @tasks.loop(minutes=10)
    async def check_expired_sticker_polls(self):
        try:
            expired = await get_expired_sticker_polls()
            for poll in expired:
                await self._auto_close(dict(poll))
        except Exception as e:
            logger.error(f"[sticker] check_expired error: {e}")

    @check_expired_sticker_polls.before_loop
    async def before_check_expired(self):
        await self.bot.wait_until_ready()

    async def _auto_close(self, poll: dict):
        channel = self.bot.get_channel(int(poll["channel_id"]))
        if poll["poll_type"] == "submit":
            up, down = await get_sticker_vote_counts(poll["id"], "up", "down")
            net = up - down
            total = up + down
            passed = net >= THRESHOLD_NET and total >= THRESHOLD_MIN_VOTERS
            new_status = "pending_approval" if passed else "rejected"
            await set_sticker_poll_status(poll["id"], new_status)
            state = "pending_approval" if passed else "rejected"
            embed = build_submit_embed(poll, up, down, state=state)
            view = StickerApprovalView() if passed else self._disabled_view("Not Enough Votes", "danger")
        else:
            keep, remove = await get_sticker_vote_counts(poll["id"], "keep", "remove")
            net_remove = remove - keep
            total = keep + remove
            remove_wins = net_remove >= THRESHOLD_NET and total >= THRESHOLD_MIN_VOTERS
            new_status = "pending_removal" if remove_wins else "kept"
            if remove_wins:
                await set_sticker_poll_status(poll["id"], new_status)
                embed = build_retention_embed(poll, keep, remove, state="pending_removal")
                view = StickerRemovalView()
            else:
                await close_sticker_poll(poll["id"], "kept")
                embed = build_retention_embed(poll, keep, remove, state="kept")
                view = self._disabled_view("Voting Closed · Kept", "secondary")

        if channel:
            try:
                msg = await channel.fetch_message(int(poll["message_id"]))
                await msg.edit(embed=embed, view=view)
            except (discord.NotFound, discord.HTTPException) as e:
                logger.warning(f"[sticker] auto_close edit message failed poll #{poll['id']}: {e}")

        logger.info(f"[sticker] Poll #{poll['id']} auto-closed: {poll['poll_type']} → {new_status}")

    def _disabled_view(self, label: str, style: str) -> discord.ui.View:
        style_map = {
            "success": discord.ButtonStyle.success,
            "danger": discord.ButtonStyle.danger,
            "secondary": discord.ButtonStyle.secondary,
        }
        v = discord.ui.View()
        v.add_item(discord.ui.Button(label=label, style=style_map.get(style, discord.ButtonStyle.secondary), disabled=True, emoji="\U0001f512"))
        return v

    # ── /submit-sticker ───────────────────────────────────────────

    @app_commands.command(name="submit-sticker", description="Submit sticker baru untuk voting community")
    @app_commands.describe(
        sticker="File sticker (PNG/APNG, max 512KB)",
        nama="Nama sticker (2-30 karakter)",
        tag="Tag emoji (1 emoji)",
    )
    async def submit_sticker(
        self,
        interaction: discord.Interaction,
        sticker: discord.Attachment,
        nama: str,
        tag: str,
    ):
        await interaction.response.defer(ephemeral=True)

        ch_id = await get_setting("sticker_vote_channel_id")
        if not ch_id:
            await interaction.followup.send(
                "❌ Channel sticker voting belum di-setup. Admin: pakai `/setup-sticker-channel` di channel yang diinginkan.",
                ephemeral=True,
            )
            return

        channel = self.bot.get_channel(int(ch_id))
        if not channel:
            await interaction.followup.send("❌ Channel voting tidak ditemukan.", ephemeral=True)
            return

        # Validate file
        if not sticker.content_type or not sticker.content_type.startswith("image/"):
            await interaction.followup.send(
                f"❌ File harus berupa image (PNG/APNG). Terdeteksi: `{sticker.content_type}`.",
                ephemeral=True,
            )
            return
        if sticker.size > MAX_FILE_SIZE:
            kb = sticker.size / 1024
            await interaction.followup.send(
                f"❌ File terlalu besar ({kb:.0f} KB). Max **{MAX_FILE_SIZE // 1024} KB**.",
                ephemeral=True,
            )
            return

        # Validate name & tag
        nama = nama.strip()
        tag = tag.strip()
        if len(nama) < 2 or len(nama) > 30:
            await interaction.followup.send("❌ Nama harus 2-30 karakter.", ephemeral=True)
            return
        if len(tag) < 1 or len(tag) > 10:
            await interaction.followup.send("❌ Tag emoji harus 1-10 karakter.", ephemeral=True)
            return

        # Cooldown check
        last = await get_last_sticker_submission_by_user(str(interaction.user.id))
        if last:
            try:
                last_dt = datetime.strptime(last["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                elapsed = datetime.now(timezone.utc) - last_dt
                if elapsed < COOLDOWN:
                    remain = COOLDOWN - elapsed
                    hrs = int(remain.total_seconds() // 3600)
                    mins = int((remain.total_seconds() % 3600) // 60)
                    await interaction.followup.send(
                        f"⏰ Kamu baru submit. Tunggu **{hrs}j {mins}m** lagi sebelum submit berikutnya.",
                        ephemeral=True,
                    )
                    return
            except Exception:
                pass

        # Create poll
        expires_at = datetime.now(timezone.utc) + VOTE_DURATION
        expires_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")

        poll_stub = {
            "id": 0,
            "initiator_id": str(interaction.user.id),
            "sticker_name": nama,
            "sticker_tag": tag,
            "image_url": sticker.url,
            "expires_at": expires_str,
        }
        initial_embed = build_submit_embed(poll_stub, 0, 0, state="voting")
        view = StickerSubmitVoteView()

        msg = await channel.send(embed=initial_embed, view=view)

        poll_id = await create_sticker_poll(
            poll_type="submit",
            initiator_id=str(interaction.user.id),
            sticker_name=nama,
            sticker_tag=tag,
            image_url=sticker.url,
            discord_sticker_id=None,
            message_id=str(msg.id),
            channel_id=str(channel.id),
            expires_at=expires_str,
        )

        # Re-build embed with real poll_id in footer
        poll = await get_sticker_poll(poll_id)
        embed = build_submit_embed(dict(poll), 0, 0, state="voting")
        try:
            await msg.edit(embed=embed, view=view)
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            f"✅ Sticker **{nama}** sudah di-submit! Voting dibuka selama 7 hari di {channel.mention}.",
            ephemeral=True,
        )
        logger.info(f"[sticker] Submit poll #{poll_id} created by {interaction.user}: '{nama}'")

    # ── /poll-sticker-keep ────────────────────────────────────────

    async def _sticker_autocomplete(self, interaction: discord.Interaction, current: str):
        if not interaction.guild:
            return []
        current_lower = current.lower()
        return [
            app_commands.Choice(name=f"{s.name} {s.emoji}"[:100], value=str(s.id))
            for s in interaction.guild.stickers
            if current_lower in s.name.lower()
        ][:25]

    @app_commands.command(name="poll-sticker-keep", description="[Admin] Trigger retention poll untuk sticker existing (keep/remove)")
    @app_commands.default_permissions(manage_emojis_and_stickers=True)
    @app_commands.describe(sticker="Pilih sticker yang mau di-voting")
    async def poll_sticker_keep(
        self,
        interaction: discord.Interaction,
        sticker: str,
    ):
        await interaction.response.defer(ephemeral=True)

        if not await _is_sticker_admin(interaction):
            await interaction.followup.send("❌ Kamu tidak punya permission.", ephemeral=True)
            return

        ch_id = await get_setting("sticker_vote_channel_id")
        if not ch_id:
            await interaction.followup.send(
                "❌ Channel sticker voting belum di-setup. Pakai `/setup-sticker-channel` dulu.",
                ephemeral=True,
            )
            return

        channel = self.bot.get_channel(int(ch_id))
        if not channel:
            await interaction.followup.send("❌ Channel voting tidak ditemukan.", ephemeral=True)
            return

        try:
            sticker_id_int = int(sticker)
        except ValueError:
            await interaction.followup.send("❌ Sticker ID tidak valid.", ephemeral=True)
            return

        guild_sticker = discord.utils.get(interaction.guild.stickers, id=sticker_id_int)
        if not guild_sticker:
            await interaction.followup.send("❌ Sticker tidak ditemukan di server.", ephemeral=True)
            return

        existing = await get_active_retention_poll_for_sticker(str(sticker_id_int))
        if existing:
            await interaction.followup.send(
                f"⚠️ Sticker **{guild_sticker.name}** sudah punya retention poll aktif (#{existing['id']}).",
                ephemeral=True,
            )
            return

        expires_at = datetime.now(timezone.utc) + VOTE_DURATION
        expires_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")

        poll_stub = {
            "id": 0,
            "initiator_id": str(interaction.user.id),
            "sticker_name": guild_sticker.name,
            "sticker_tag": str(guild_sticker.emoji) if guild_sticker.emoji else None,
            "expires_at": expires_str,
        }
        poll_stub["image_url"] = guild_sticker.url
        initial_embed = build_retention_embed(poll_stub, 0, 0, state="voting")
        view = StickerRetentionVoteView()

        msg = await channel.send(embed=initial_embed, view=view)

        poll_id = await create_sticker_poll(
            poll_type="retention",
            initiator_id=str(interaction.user.id),
            sticker_name=guild_sticker.name,
            sticker_tag=str(guild_sticker.emoji) if guild_sticker.emoji else None,
            image_url=guild_sticker.url,
            discord_sticker_id=str(sticker_id_int),
            message_id=str(msg.id),
            channel_id=str(channel.id),
            expires_at=expires_str,
        )

        poll = await get_sticker_poll(poll_id)
        embed = build_retention_embed(dict(poll), 0, 0, state="voting")
        try:
            await msg.edit(embed=embed, view=view)
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            f"✅ Retention poll untuk **{guild_sticker.name}** dibuka di {channel.mention} (7 hari).",
            ephemeral=True,
        )
        logger.info(f"[sticker] Retention poll #{poll_id} created by {interaction.user} for sticker {sticker_id_int}")

    @poll_sticker_keep.autocomplete("sticker")
    async def _poll_sticker_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._sticker_autocomplete(interaction, current)

    # ── /setup-sticker-channel ────────────────────────────────────

    @app_commands.command(name="setup-sticker-channel", description="[Admin] Toggle channel ini sebagai tempat sticker voting")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_sticker_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        current = await get_setting("sticker_vote_channel_id")
        if current == str(interaction.channel.id):
            await delete_setting("sticker_vote_channel_id")
            await interaction.followup.send(
                f"✅ Channel {interaction.channel.mention} **dilepas** dari sticker voting.",
                ephemeral=True,
            )
            logger.info(f"[sticker] Channel unset by {interaction.user}")
        else:
            await set_setting("sticker_vote_channel_id", str(interaction.channel.id))
            await interaction.followup.send(
                f"✅ Channel {interaction.channel.mention} di-set sebagai sticker voting channel.",
                ephemeral=True,
            )
            logger.info(f"[sticker] Channel set to {interaction.channel.id} by {interaction.user}")

    # ── /setup-sticker-admin-role ─────────────────────────────────

    @app_commands.command(name="setup-sticker-admin-role", description="[Admin] Set role yang bisa approve/reject/confirm sticker")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_sticker_admin_role(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        await set_setting("sticker_admin_role_id", str(role.id))
        await interaction.followup.send(
            f"✅ Role {role.mention} di-set sebagai sticker admin.", ephemeral=True,
        )
        logger.info(f"[sticker] Admin role set to {role.id} by {interaction.user}")

    # ── /list-sticker-polls ───────────────────────────────────────

    @app_commands.command(name="list-sticker-polls", description="[Admin] Lihat semua sticker poll aktif")
    @app_commands.default_permissions(manage_channels=True)
    async def list_sticker_polls(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        polls = await get_active_sticker_polls()
        if not polls:
            await interaction.followup.send("Tidak ada poll aktif.", ephemeral=True)
            return

        embed = discord.Embed(title="\U0001f3a8 Active Sticker Polls", color=0x5865f2)
        for p in polls:
            if p["poll_type"] == "submit":
                up, down = await get_sticker_vote_counts(p["id"], "up", "down")
                score = f"\U0001f44d {up} / \U0001f44e {down} (net {up-down:+d})"
            else:
                keep, remove = await get_sticker_vote_counts(p["id"], "keep", "remove")
                score = f"\U0001f49a {keep} / \U0001f5d1️ {remove} (net remove {remove-keep:+d})"

            type_label = "Submit" if p["poll_type"] == "submit" else "Retention"
            embed.add_field(
                name=f"#{p['id']} · {type_label} · {p['sticker_name']}",
                value=f"Status: `{p['status']}` · {score}\nBerakhir: {p['expires_at']} UTC",
                inline=False,
            )

        embed.set_footer(text=f"Total: {len(polls)} poll")
        await interaction.followup.send(embed=embed, ephemeral=True)
