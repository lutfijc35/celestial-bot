import discord
from discord import app_commands
from discord.ext import commands
from bot.utils.database import (
    check_nickname_exists, create_account, update_account_status,
    get_accounts_by_discord_id, delete_account, update_account_fields,
    create_pending_approval, get_pending_approval_by_message,
    resolve_pending_approval, get_account, get_all_guild_roles,
    set_approval_role_override,
)
from bot.utils.roles import assign_role, update_guild_list, update_member_list
from config import APPROVAL_MODE, APPROVAL_CHANNEL_ID, GUILD_ID, DEFAULT_ROLE_ID


# ── Approval View (persistent) ──────────────────────────────────────

class ApprovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="✅ Approve",
        style=discord.ButtonStyle.success,
        custom_id="celestial:approve",
    )
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        approval = await get_pending_approval_by_message(str(interaction.message.id))
        if not approval:
            await interaction.followup.send("❌ Data approval tidak ditemukan.", ephemeral=True)
            return

        account_id = approval["account_id"]
        account = await get_account(account_id)

        if not account:
            await interaction.followup.send("❌ Akun tidak ditemukan.", ephemeral=True)
            return

        if account["status"] != "pending":
            await interaction.followup.send(
                f"⚠️ Akun ini sudah di-{account['status']}.", ephemeral=True
            )
            return

        await update_account_status(account_id, "approved")
        await resolve_pending_approval(account_id, str(interaction.user.id))

        # Assign role — gunakan override jika ada, else logika default
        role_assigned = False
        if approval["role_override"]:
            guild = interaction.client.get_guild(GUILD_ID)
            member = guild.get_member(int(account["discord_id"])) if guild else None
            if member:
                override_role = guild.get_role(int(approval["role_override"]))
                if override_role:
                    try:
                        await member.add_roles(override_role, reason="Celestial: role override oleh admin")
                        role_assigned = True
                        if DEFAULT_ROLE_ID:
                            default_role = guild.get_role(DEFAULT_ROLE_ID)
                            if default_role:
                                await member.add_roles(default_role, reason="Celestial: default role saat approve")
                        # Sinkronkan guild field supaya guild list menampilkan member di guild yg benar
                        guild_roles_data = await get_all_guild_roles()
                        guild_name_for_role = next(
                            (row["guild_name"] for row in guild_roles_data
                             if row["role_id"] == approval["role_override"]),
                            None,
                        )
                        if guild_name_for_role:
                            await update_account_fields(
                                account_id, account["nickname"], guild_name_for_role, account["server"]
                            )
                    except discord.Forbidden:
                        print(f"[roles] Bot tidak punya permission untuk assign override role {override_role.name}")
        else:
            role_assigned = await assign_role(interaction.client, account["discord_id"], account)

        # Update guild list dan member list
        await update_guild_list(interaction.client)
        await update_member_list(interaction.client)

        # Edit embed → tandai approved
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.set_footer(text=f"✅ Approved oleh {interaction.user.display_name}")
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(embed=embed, view=self)

        # Notif ke user
        guild = interaction.client.get_guild(GUILD_ID)
        member = guild.get_member(int(account["discord_id"])) if guild else None
        notif = f"✅ Akun **{account['nickname']}** ({account['server']}) kamu telah di-approve!"

        if member:
            try:
                await member.send(notif)
            except discord.Forbidden:
                channel = interaction.client.get_channel(APPROVAL_CHANNEL_ID)
                if channel:
                    await channel.send(f"{member.mention} {notif}")

        await interaction.followup.send("✅ Akun berhasil di-approve.", ephemeral=True)

    @discord.ui.button(
        label="❌ Reject",
        style=discord.ButtonStyle.danger,
        custom_id="celestial:reject",
    )
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        approval = await get_pending_approval_by_message(str(interaction.message.id))
        if not approval:
            await interaction.followup.send("❌ Data approval tidak ditemukan.", ephemeral=True)
            return

        account_id = approval["account_id"]
        account = await get_account(account_id)

        if not account:
            await interaction.followup.send("❌ Akun tidak ditemukan.", ephemeral=True)
            return

        if account["status"] != "pending":
            await interaction.followup.send(
                f"⚠️ Akun ini sudah di-{account['status']}.", ephemeral=True
            )
            return

        await update_account_status(account_id, "rejected")
        await resolve_pending_approval(account_id, str(interaction.user.id))

        # Edit embed → tandai rejected
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.set_footer(text=f"❌ Rejected oleh {interaction.user.display_name}")
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(embed=embed, view=self)

        # Notif ke user
        guild = interaction.client.get_guild(GUILD_ID)
        member = guild.get_member(int(account["discord_id"])) if guild else None
        notif = f"❌ Akun **{account['nickname']}** ({account['server']}) kamu ditolak oleh admin."

        if member:
            try:
                await member.send(notif)
            except discord.Forbidden:
                channel = interaction.client.get_channel(APPROVAL_CHANNEL_ID)
                if channel:
                    await channel.send(f"{member.mention} {notif}")

        await interaction.followup.send("✅ Akun berhasil di-reject.", ephemeral=True)

    @discord.ui.button(
        label="🔄 Ubah Role",
        style=discord.ButtonStyle.secondary,
        custom_id="celestial:change_role",
    )
    async def change_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        approval = await get_pending_approval_by_message(str(interaction.message.id))
        if not approval:
            await interaction.followup.send("❌ Data approval tidak ditemukan.", ephemeral=True)
            return

        account_id = approval["account_id"]
        account = await get_account(account_id)

        if not account:
            await interaction.followup.send("❌ Akun tidak ditemukan.", ephemeral=True)
            return

        if account["status"] != "pending":
            await interaction.followup.send(
                f"⚠️ Akun ini sudah di-{account['status']}.", ephemeral=True
            )
            return

        guild_roles = await get_all_guild_roles()
        if not guild_roles:
            await interaction.followup.send(
                "❌ Belum ada guild yang di-mapping. Gunakan `/set-guild` terlebih dahulu.",
                ephemeral=True,
            )
            return

        view = RoleSelectView(account_id, guild_roles, interaction.message)
        await interaction.followup.send(
            "Pilih role yang akan di-assign ke akun ini:",
            view=view,
            ephemeral=True,
        )


# ── Role Select View (non-persistent) ───────────────────────────────

class RoleSelect(discord.ui.Select):
    def __init__(self, account_id: int, guild_roles, message: discord.Message):
        self.account_id = account_id
        self.message = message
        options = [
            discord.SelectOption(
                label=row["guild_name"],
                description=f"Role ID: {row['role_id']}",
                value=row["role_id"],
            )
            for row in guild_roles
        ]
        super().__init__(placeholder="Pilih role...", options=options)

    async def callback(self, interaction: discord.Interaction):
        role_id = self.values[0]
        await set_approval_role_override(self.account_id, role_id)

        role = interaction.guild.get_role(int(role_id)) if interaction.guild else None
        role_name = role.name if role else f"ID {role_id}"
        role_mention = role.mention if role else f"@{role_name}"

        # Update embed pada pesan approval
        embed = self.message.embeds[0]
        roles_field_idx = next(
            (i for i, f in enumerate(embed.fields) if f.name == "Roles"),
            None,
        )
        if roles_field_idx is not None:
            embed.set_field_at(roles_field_idx, name="Roles", value=role_mention, inline=True)
        else:
            embed.add_field(name="Roles", value=role_mention, inline=True)
        await self.message.edit(embed=embed)

        await interaction.response.send_message(
            f"✅ Role diubah ke **@{role_name}**. Klik Approve untuk lanjut.",
            ephemeral=True,
        )
        self.view.stop()


class RoleSelectView(discord.ui.View):
    def __init__(self, account_id: int, guild_roles, message: discord.Message):
        super().__init__(timeout=60)
        self.add_item(RoleSelect(account_id, guild_roles, message))


# ── Server Select (step 1 of register flow) ──────────────────────────

class ServerSelect(discord.ui.Select):
    SERVER_OPTIONS = ["Asia", "Global", "Korea", "Japan", "Europe"]

    def __init__(self):
        options = [discord.SelectOption(label=s, value=s) for s in self.SERVER_OPTIONS]
        super().__init__(placeholder="Pilih server kamu...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RegisterModal(server=self.values[0]))
        self.view.stop()


class ServerSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(ServerSelect())


# ── Register Modal ───────────────────────────────────────────────────

class RegisterModal(discord.ui.Modal, title="✦ Daftarkan Akun Game Kamu"):
    def __init__(self, server: str):
        super().__init__()
        self.server_val = server
        self.guild_input = discord.ui.TextInput(
            label="Guild (opsional)",
            placeholder="Nama guild kamu di game",
            required=False,
            max_length=100,
        )
        self.nickname_input = discord.ui.TextInput(
            label="Nickname In-game *",
            placeholder="Nickname kamu di Epic Seven",
            required=True,
            max_length=100,
        )
        self.add_item(self.guild_input)
        self.add_item(self.nickname_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        server_val = self.server_val
        guild_val = self.guild_input.value.strip()
        nickname_val = self.nickname_input.value.strip()
        discord_id = str(interaction.user.id)

        # Validasi nickname unik per server
        if await check_nickname_exists(nickname_val, server_val):
            await interaction.followup.send(
                f"❌ Nickname **{nickname_val}** sudah terdaftar di server **{server_val}**. "
                "Gunakan nickname lain.",
                ephemeral=True,
            )
            return

        account_id = await create_account(discord_id, nickname_val, guild_val, server_val)

        if APPROVAL_MODE == "auto":
            await update_account_status(account_id, "approved")
            account = await get_account(account_id)
            await assign_role(interaction.client, discord_id, account)
            await update_guild_list(interaction.client)
            await update_member_list(interaction.client)
            await interaction.followup.send(
                f"✅ Registrasi berhasil!\n"
                f"**Nickname:** {nickname_val}\n"
                f"**Server:** {server_val}\n"
                f"**Guild:** {guild_val or '—'}",
                ephemeral=True,
            )
        else:
            # Manual mode — kirim embed ke approval channel
            approval_channel = interaction.client.get_channel(APPROVAL_CHANNEL_ID)
            if not approval_channel:
                await interaction.followup.send(
                    "❌ Channel approval tidak ditemukan. Hubungi admin.", ephemeral=True
                )
                return

            embed = discord.Embed(
                title="📋 Permintaan Registrasi Baru",
                color=discord.Color.blue(),
            )
            embed.set_author(
                name=f"{interaction.user.display_name} ({interaction.user})",
                icon_url=interaction.user.display_avatar.url,
            )
            embed.add_field(name="Nickname", value=nickname_val, inline=True)
            embed.add_field(name="Server", value=server_val, inline=True)
            embed.add_field(name="Guild", value=guild_val or "—", inline=True)
            embed.add_field(name="Game", value="Epic Seven (E7)", inline=True)
            embed.add_field(name="Discord", value=interaction.user.mention, inline=True)
            embed.set_footer(text=f"Account ID: {account_id}")

            view = ApprovalView()
            ping_ids = getattr(interaction.client, "approval_ping_role_ids", [])
            content = " ".join(f"<@&{rid}>" for rid in ping_ids) or None
            msg = await approval_channel.send(content=content, embed=embed, view=view)
            await create_pending_approval(account_id, str(msg.id))

            await interaction.followup.send(
                "📬 Registrasi kamu sudah dikirim dan menunggu persetujuan admin.\n"
                "Kamu akan mendapat notifikasi setelah di-review.",
                ephemeral=True,
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await interaction.followup.send("❌ Terjadi error saat proses registrasi.", ephemeral=True)
        raise error


# ── Register Button (persistent) ────────────────────────────────────

class RegisterButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Daftar Sekarang",
        style=discord.ButtonStyle.primary,
        custom_id="celestial:register",
    )
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ServerSelectView()
        await interaction.response.send_message("Pilih server kamu:", view=view, ephemeral=True)


# ── Unregister Select ────────────────────────────────────────────────

class UnregisterSelect(discord.ui.Select):
    def __init__(self, accounts):
        options = [
            discord.SelectOption(
                label=f"{acc['nickname']} [{acc['server']}]",
                description=f"Guild: {acc['guild'] or '—'} · Status: {acc['status']}",
                value=str(acc["id"]),
            )
            for acc in accounts
        ]
        super().__init__(placeholder="Pilih akun yang ingin dihapus...", options=options)

    async def callback(self, interaction: discord.Interaction):
        account_id = int(self.values[0])
        account = await get_account(account_id)

        if not account or str(account["discord_id"]) != str(interaction.user.id):
            await interaction.response.send_message("❌ Akun tidak ditemukan.", ephemeral=True)
            return

        await delete_account(account_id)
        await update_guild_list(interaction.client)
        await update_member_list(interaction.client)
        await interaction.response.send_message(
            f"✅ Akun **{account['nickname']}** ({account['server']}) berhasil dihapus.",
            ephemeral=True,
        )
        self.view.stop()


class UnregisterView(discord.ui.View):
    def __init__(self, accounts):
        super().__init__(timeout=60)
        self.add_item(UnregisterSelect(accounts))


# ── Edit Modal ───────────────────────────────────────────────────────

class EditModal(discord.ui.Modal, title="✦ Edit Akun Game"):
    def __init__(self, account):
        super().__init__()
        self.account_id = account["id"]
        self.server_input = discord.ui.TextInput(
            label="Server *",
            default=account["server"],
            required=True,
            max_length=50,
        )
        self.guild_input = discord.ui.TextInput(
            label="Guild (opsional)",
            default=account["guild"] or "",
            required=False,
            max_length=100,
        )
        self.nickname_input = discord.ui.TextInput(
            label="Nickname In-game *",
            default=account["nickname"],
            required=True,
            max_length=100,
        )
        self.add_item(self.server_input)
        self.add_item(self.guild_input)
        self.add_item(self.nickname_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        server_val = self.server_input.value.strip()
        guild_val = self.guild_input.value.strip()
        nickname_val = self.nickname_input.value.strip()

        if await check_nickname_exists(nickname_val, server_val, exclude_account_id=self.account_id):
            await interaction.followup.send(
                f"❌ Nickname **{nickname_val}** sudah dipakai di server **{server_val}**.",
                ephemeral=True,
            )
            return

        await update_account_fields(self.account_id, nickname_val, guild_val, server_val)
        account = await get_account(self.account_id)
        if account and account["status"] == "approved":
            await update_guild_list(interaction.client)

        await interaction.followup.send(
            f"✅ Akun berhasil diperbarui: **{nickname_val}** [{server_val}]",
            ephemeral=True,
        )


class EditSelect(discord.ui.Select):
    def __init__(self, accounts):
        options = [
            discord.SelectOption(
                label=f"{acc['nickname']} [{acc['server']}]",
                description=f"Guild: {acc['guild'] or '—'} · Status: {acc['status']}",
                value=str(acc["id"]),
            )
            for acc in accounts
        ]
        super().__init__(placeholder="Pilih akun yang ingin diedit...", options=options)

    async def callback(self, interaction: discord.Interaction):
        account_id = int(self.values[0])
        account = await get_account(account_id)
        if not account or str(account["discord_id"]) != str(interaction.user.id):
            await interaction.response.send_message("❌ Akun tidak ditemukan.", ephemeral=True)
            return
        await interaction.response.send_modal(EditModal(account))
        self.view.stop()


class EditView(discord.ui.View):
    def __init__(self, accounts):
        super().__init__(timeout=60)
        self.add_item(EditSelect(accounts))


# ── Cog ─────────────────────────────────────────────────────────────

class RegisterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="unregister", description="Hapus akun game yang sudah terdaftar")
    async def unregister(self, interaction: discord.Interaction):
        accounts = await get_accounts_by_discord_id(str(interaction.user.id))
        if not accounts:
            await interaction.response.send_message(
                "❌ Kamu belum memiliki akun terdaftar.", ephemeral=True
            )
            return

        if len(accounts) == 1:
            acc = accounts[0]
            await delete_account(acc["id"])
            await update_guild_list(self.bot)
            await update_member_list(self.bot)
            await interaction.response.send_message(
                f"✅ Akun **{acc['nickname']}** ({acc['server']}) berhasil dihapus.",
                ephemeral=True,
            )
        else:
            view = UnregisterView(accounts)
            await interaction.response.send_message(
                "Pilih akun yang ingin dihapus:", view=view, ephemeral=True
            )

    @app_commands.command(name="edit", description="Edit akun game yang sudah terdaftar")
    async def edit(self, interaction: discord.Interaction):
        accounts = await get_accounts_by_discord_id(str(interaction.user.id))
        if not accounts:
            await interaction.response.send_message(
                "❌ Kamu belum memiliki akun terdaftar.", ephemeral=True
            )
            return

        if len(accounts) == 1:
            account = await get_account(accounts[0]["id"])
            await interaction.response.send_modal(EditModal(account))
        else:
            view = EditView(accounts)
            await interaction.response.send_message(
                "Pilih akun yang ingin diedit:", view=view, ephemeral=True
            )
