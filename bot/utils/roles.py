import discord
from collections import defaultdict
from bot.utils.database import (
    get_guild_role, get_guild_role_by_server,
    get_all_approved_accounts, get_all_guild_roles,
    get_guild_list_message, upsert_guild_list_message,
    get_guild_list_pages, upsert_guild_list_page, delete_guild_list_pages_above,
    get_setting,
)

GUILDS_PER_PAGE = 8   # guild per embed; aman di bawah Discord limit 25 field dan 6000 char
MEMBERS_PER_PAGE = 20  # member per embed; aman di bawah limit 4096 char
from config import GUILD_ID, GUILD_LIST_CHANNEL_ID, DEFAULT_ROLE_ID


async def assign_role(bot: discord.Client, discord_id: str, account) -> bool:
    """
    Assign Discord role ke member berdasarkan guild atau server fallback.
    Returns True jika berhasil, False jika role tidak ditemukan.
    """
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print(f"[roles] Guild {GUILD_ID} tidak ditemukan")
        return False

    member = guild.get_member(int(discord_id))
    if not member:
        print(f"[roles] Member {discord_id} tidak ditemukan di guild")
        return False

    role_id = None

    # Cek berdasarkan nama guild
    if account["guild"]:
        guild_row = await get_guild_role(account["guild"])
        if guild_row:
            role_id = guild_row["role_id"]

    # Fallback: cari berdasarkan server/region
    if not role_id:
        fallback = await get_guild_role_by_server(account["server"])
        if fallback:
            role_id = fallback["role_id"]

    if not role_id:
        print(f"[roles] Tidak ada role untuk guild='{account['guild']}' server='{account['server']}'")
        return False

    role = guild.get_role(int(role_id))
    if not role:
        print(f"[roles] Role {role_id} tidak ditemukan di guild")
        return False

    try:
        await member.add_roles(role, reason="Celestial: akun game diapprove")
        if DEFAULT_ROLE_ID:
            default_role = guild.get_role(DEFAULT_ROLE_ID)
            if default_role:
                await member.add_roles(default_role, reason="Celestial: default role saat approve")
            else:
                print(f"[roles] Default role {DEFAULT_ROLE_ID} tidak ditemukan")
        return True
    except discord.Forbidden:
        print(f"[roles] Bot tidak punya permission untuk assign role {role.name}")
        return False


async def update_guild_list(bot: discord.Client):
    """Edit atau kirim pesan-pesan guild list di GUILD_LIST_CHANNEL_ID (multiple messages)."""
    channel = bot.get_channel(GUILD_LIST_CHANNEL_ID)
    if not channel:
        print(f"[roles] Channel guild-list {GUILD_LIST_CHANNEL_ID} tidak ditemukan")
        return

    embeds = await build_guild_list_embeds()
    channel_id_str = str(GUILD_LIST_CHANNEL_ID)
    existing_ids = await get_guild_list_pages(channel_id_str)

    for i, embed in enumerate(embeds):
        if i < len(existing_ids):
            try:
                msg = await channel.fetch_message(int(existing_ids[i]))
                await msg.edit(embed=embed)
            except (discord.NotFound, discord.HTTPException):
                msg = await channel.send(embed=embed)
        else:
            msg = await channel.send(embed=embed)
        await upsert_guild_list_page(channel_id_str, i, str(msg.id))

    # Hapus pesan lama jika jumlah halaman berkurang
    if len(existing_ids) > len(embeds):
        for old_id in existing_ids[len(embeds):]:
            try:
                msg = await channel.fetch_message(int(old_id))
                await msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
        await delete_guild_list_pages_above(channel_id_str, len(embeds) - 1)


async def build_guild_list_embeds() -> list[discord.Embed]:
    accounts = await get_all_approved_accounts()
    guild_roles = await get_all_guild_roles()
    guild_info = {row["guild_name"]: row for row in guild_roles}

    guild_members: dict[str, list] = defaultdict(list)
    no_guild: list = []

    for acc in accounts:
        g = acc["guild"].strip() if acc["guild"] else ""
        if g:
            guild_members[g].append(acc)
        else:
            no_guild.append(acc)

    # Bangun list semua field (guild + no-guild)
    fields = []
    for guild_name, members in sorted(guild_members.items()):
        info = guild_info.get(guild_name)
        header_parts = []
        if info:
            if info["tipe"]:
                tipe_label = {"casual": "Casual", "semi_compe": "Semi Kompetitif", "compe": "Kompetitif"}.get(info["tipe"], info["tipe"])
                header_parts.append(tipe_label)
            if info["level"]:
                header_parts.append(f"Lv.{info['level']}")
            if info["keterangan"]:
                header_parts.append(info["keterangan"])

        member_list = "  ·  ".join(
            f"{acc['nickname']} <@{acc['discord_id']}> {acc['server']}" for acc in members
        )
        field_value = f"*{' · '.join(header_parts)}*\n{member_list}" if header_parts else member_list
        fields.append((f"🏰 {guild_name} ({len(members)} member)", field_value))

    if no_guild:
        no_guild_list = "  ·  ".join(
            f"{acc['nickname']} <@{acc['discord_id']}> {acc['server']}" for acc in no_guild
        )
        fields.append(("👤 Tanpa Guild", no_guild_list))

    # Split fields ke embeds per GUILDS_PER_PAGE
    embeds = []
    chunks = [fields[i:i + GUILDS_PER_PAGE] for i in range(0, max(len(fields), 1), GUILDS_PER_PAGE)]

    for idx, chunk in enumerate(chunks):
        title = "✦ Daftar Guild — Celestial Server" if idx == 0 else "✦ Daftar Guild — (lanjutan)"
        embed = discord.Embed(title=title, color=0x5865f2)

        if not chunk:
            embed.description = "*Belum ada member yang terdaftar.*"
        else:
            for name, value in chunk:
                embed.add_field(name=name, value=value, inline=False)

        if idx == len(chunks) - 1:
            embed.set_footer(text=f"Total member terdaftar: {len(accounts)}")

        embeds.append(embed)

    return embeds


async def build_member_list_embeds() -> list[discord.Embed]:
    accounts = await get_all_approved_accounts()
    total = len(accounts)

    if not accounts:
        embed = discord.Embed(title="🌌 Daftar Member Celestial", color=0x5865f2)
        embed.description = "*Belum ada member yang terdaftar.*"
        embed.set_footer(text="Total member: 0")
        return [embed]

    chunks = [accounts[i:i + MEMBERS_PER_PAGE] for i in range(0, total, MEMBERS_PER_PAGE)]
    embeds = []

    for idx, chunk in enumerate(chunks):
        title = "🌌 Daftar Member Celestial" if idx == 0 else "🌌 Daftar Member Celestial (lanjutan)"
        embed = discord.Embed(title=title, color=0x5865f2)

        lines = []
        for acc in chunk:
            guild_val = acc["guild"] if acc["guild"] else "—"
            lines.append(
                f"⚔️ **{acc['nickname']}** (<@{acc['discord_id']}>) · {guild_val} · {acc['server']}"
            )
        embed.description = "\n".join(lines)

        if idx == len(chunks) - 1:
            embed.set_footer(text=f"Total member: {total}")

        embeds.append(embed)

    return embeds


async def update_member_list(bot: discord.Client):
    """Edit atau kirim pesan-pesan member list di profile channel (multi-pesan)."""
    channel_id_str = await get_setting("profile_channel_id")
    if not channel_id_str:
        return

    channel = bot.get_channel(int(channel_id_str))
    if not channel:
        return

    embeds = await build_member_list_embeds()
    page_key = f"member_{channel_id_str}"  # namespace terpisah dari guild_list_pages
    existing_ids = await get_guild_list_pages(page_key)

    for i, embed in enumerate(embeds):
        if i < len(existing_ids):
            try:
                msg = await channel.fetch_message(int(existing_ids[i]))
                await msg.edit(embed=embed)
            except (discord.NotFound, discord.HTTPException):
                msg = await channel.send(embed=embed)
        else:
            msg = await channel.send(embed=embed)
        await upsert_guild_list_page(page_key, i, str(msg.id))

    # Hapus pesan lama jika jumlah halaman berkurang
    if len(existing_ids) > len(embeds):
        for old_id in existing_ids[len(embeds):]:
            try:
                msg = await channel.fetch_message(int(old_id))
                await msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
        await delete_guild_list_pages_above(page_key, len(embeds) - 1)
