import discord
from datetime import datetime, timezone
from discord import app_commands
from discord.ext import commands
from bot.utils.database import (
    upsert_guild_role, update_guild_info, delete_guild_role, get_guild_role,
    get_all_guild_roles, set_setting, get_setting,
    get_accounts_by_discord_id, get_account, delete_account,
    get_account_stats, get_guild_count,
    update_account_fields, check_nickname_exists,
)
from bot.utils.roles import update_guild_list, update_member_list, assign_role
from bot.cogs.register import RegisterButton
from config import (
    REGISTER_CHANNEL_ID, OTHER_GAMES_CHANNEL_ID, WELCOME_CHANNEL_ID,
    APPROVAL_CHANNEL_ID, GUILD_LIST_CHANNEL_ID, RULES_CHANNEL_ID,
    MEMBER_ROLE_ID, DEFAULT_ROLE_ID, APPROVAL_MODE,
)


class GuildInfoModal(discord.ui.Modal, title="✦ Set Info Guild"):
    def __init__(self, guild_name: str, tipe: str, current):
        super().__init__()
        self.guild_name = guild_name
        self.tipe = tipe

        self.level_input = discord.ui.TextInput(
            label="Level (angka)",
            default=str(current["level"]) if current["level"] else "",
            required=True,
            max_length=10,
        )
        self.keterangan_input = discord.ui.TextInput(
            label="Keterangan",
            default=current["keterangan"] or "",
            required=False,
            max_length=200,
        )
        self.add_item(self.level_input)
        self.add_item(self.keterangan_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            level = int(self.level_input.value.strip())
        except ValueError:
            await interaction.followup.send(
                "❌ Level harus berupa angka.", ephemeral=True
            )
            return

        keterangan = self.keterangan_input.value.strip()
        await update_guild_info(self.guild_name, level, self.tipe, keterangan)
        await update_guild_list(interaction.client)

        await interaction.followup.send(
            f"✅ Info guild **{self.guild_name}** berhasil diperbarui.\n"
            f"Level: {level} · Tipe: {self.tipe} · Keterangan: {keterangan or '—'}",
            ephemeral=True,
        )


TIPE_OPTIONS = [
    discord.SelectOption(label="Casual", value="casual"),
    discord.SelectOption(label="Semi Kompetitif", value="semi_compe"),
    discord.SelectOption(label="Kompetitif", value="compe"),
]


class TipeSelect(discord.ui.Select):
    def __init__(self, guild_name: str, current):
        self.guild_name = guild_name
        self.current = current
        super().__init__(placeholder="Pilih tipe guild...", options=TIPE_OPTIONS)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            GuildInfoModal(self.guild_name, self.values[0], self.current)
        )
        self.view.stop()


class TipeSelectView(discord.ui.View):
    def __init__(self, guild_name: str, current):
        super().__init__(timeout=60)
        self.add_item(TipeSelect(guild_name, current))


class GuildSelect(discord.ui.Select):
    def __init__(self, guild_roles):
        options = [
            discord.SelectOption(
                label=row["guild_name"],
                description=(
                    f"Level {row['level']} · {row['tipe']}"
                    if row["level"] or row["tipe"] else "Belum ada info"
                ),
                value=row["guild_name"],
            )
            for row in guild_roles
        ]
        super().__init__(placeholder="Pilih guild...", options=options)

    async def callback(self, interaction: discord.Interaction):
        guild_name = self.values[0]
        current = await get_guild_role(guild_name)
        view = TipeSelectView(guild_name, current)
        await interaction.response.edit_message(
            content="Pilih tipe guild:", view=view
        )
        self.view.stop()


class GuildSelectView(discord.ui.View):
    def __init__(self, guild_roles):
        super().__init__(timeout=60)
        self.add_item(GuildSelect(guild_roles))


class GuildDeleteSelect(discord.ui.Select):
    def __init__(self, guild_roles):
        options = [
            discord.SelectOption(
                label=row["guild_name"],
                description=(
                    f"Level {row['level']} · {row['tipe']}"
                    if row["level"] or row["tipe"] else "Belum ada info"
                ),
                value=row["guild_name"],
            )
            for row in guild_roles
        ]
        super().__init__(placeholder="Pilih guild yang ingin dihapus...", options=options)

    async def callback(self, interaction: discord.Interaction):
        guild_name = self.values[0]
        await delete_guild_role(guild_name)
        await update_guild_list(interaction.client)
        await interaction.response.send_message(
            f"✅ Guild **{guild_name}** berhasil dihapus dari database.",
            ephemeral=True,
        )
        self.view.stop()


class GuildDeleteView(discord.ui.View):
    def __init__(self, guild_roles):
        super().__init__(timeout=60)
        self.add_item(GuildDeleteSelect(guild_roles))


class AdminEditModal(discord.ui.Modal, title="✦ Admin Edit Akun"):
    def __init__(self, account, target_member: discord.Member):
        super().__init__()
        self.account_id = account["id"]
        self.target_member = target_member
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
            await assign_role(interaction.client, account["discord_id"], account)
            await update_guild_list(interaction.client)
            await update_member_list(interaction.client)

        await interaction.followup.send(
            f"✅ Akun **{nickname_val}** [{server_val}] milik {self.target_member.mention} berhasil diperbarui.",
            ephemeral=True,
        )


class AdminEditSelect(discord.ui.Select):
    def __init__(self, accounts, target_member: discord.Member):
        self.target_member = target_member
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
        if not account:
            await interaction.response.send_message("❌ Akun tidak ditemukan.", ephemeral=True)
            return
        await interaction.response.send_modal(AdminEditModal(account, self.target_member))
        self.view.stop()


class AdminEditView(discord.ui.View):
    def __init__(self, accounts, target_member: discord.Member):
        super().__init__(timeout=60)
        self.add_item(AdminEditSelect(accounts, target_member))


class AdminUnregisterSelect(discord.ui.Select):
    def __init__(self, accounts, target_member: discord.Member):
        self.target_member = target_member
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
        await delete_account(account_id)
        await update_guild_list(interaction.client)
        await update_member_list(interaction.client)
        await interaction.response.send_message(
            f"✅ Akun **{account['nickname']}** ({account['server']}) "
            f"milik {self.target_member.mention} berhasil dihapus.",
            ephemeral=True,
        )
        self.view.stop()


class AdminUnregisterView(discord.ui.View):
    def __init__(self, accounts, target_member: discord.Member):
        super().__init__(timeout=60)
        self.add_item(AdminUnregisterSelect(accounts, target_member))


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="set-guild", description="[Admin] Mapping nama guild ke Discord role (nama guild = nama role)")
    @app_commands.default_permissions(manage_roles=True)
    async def set_guild(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ):
        await interaction.response.defer(ephemeral=True)
        await upsert_guild_role(role.name, str(role.id))
        await interaction.followup.send(
            f"✅ Guild **{role.name}** berhasil di-mapping ke role {role.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="guild-list", description="[Admin] Lihat semua guild yang sudah di-mapping")
    @app_commands.default_permissions(manage_roles=True)
    async def guild_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_roles = await get_all_guild_roles()
        if not guild_roles:
            await interaction.followup.send(
                "❌ Belum ada guild yang terdaftar. Gunakan `/set-guild` terlebih dahulu.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="🏰 Guild Mapping — Celestial", color=0x5865f2)
        for row in guild_roles:
            info_parts = []
            if row["tipe"]:
                info_parts.append(row["tipe"])
            if row["level"]:
                info_parts.append(f"Lv.{row['level']}")
            info_line = " · ".join(info_parts) if info_parts else "—"
            ket = row["keterangan"] or "—"

            embed.add_field(
                name=row["guild_name"],
                value=(
                    f"Role: <@&{row['role_id']}>\n"
                    f"Info: {info_line}\n"
                    f"Ket: {ket}"
                ),
                inline=True,
            )
        embed.set_footer(text=f"Total: {len(guild_roles)} guild terdaftar")

        view = GuildDeleteView(guild_roles)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="remove-guild", description="[Admin] Hapus mapping guild dari database")
    @app_commands.default_permissions(manage_roles=True)
    async def remove_guild(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_roles = await get_all_guild_roles()
        if not guild_roles:
            await interaction.followup.send(
                "❌ Belum ada guild yang terdaftar.", ephemeral=True
            )
            return

        view = GuildDeleteView(guild_roles)
        await interaction.followup.send(
            "Pilih guild yang ingin dihapus:", view=view, ephemeral=True
        )

    @app_commands.command(name="guild-set-info", description="[Admin] Set info guild (level, tipe, keterangan)")
    @app_commands.default_permissions(manage_roles=True)
    async def guild_set_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_roles = await get_all_guild_roles()
        if not guild_roles:
            await interaction.followup.send(
                "❌ Belum ada guild yang terdaftar. Gunakan `/set-guild` terlebih dahulu.",
                ephemeral=True,
            )
            return

        view = GuildSelectView(guild_roles)
        await interaction.followup.send(
            "Pilih guild yang ingin diatur info-nya:",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="guild-info", description="[Admin] Force refresh pesan guild list")
    @app_commands.default_permissions(manage_roles=True)
    async def guild_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await update_guild_list(self.bot)
        await interaction.followup.send("✅ Guild list berhasil diperbarui.", ephemeral=True)

    @app_commands.command(name="setup-register", description="[Admin] Post embed 'Daftar Sekarang' ke channel ini")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_register(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="✦ Daftarkan Akun Epic Seven Kamu",
            description=(
                "Bergabunglah dengan komunitas Epic Seven di server ini!\n\n"
                "Klik tombol di bawah untuk membuka form pendaftaran.\n\n"
                "**Apa yang perlu disiapkan:**\n"
                "- Server tempat kamu bermain (Asia, Global, Korea, dll)\n"
                "- Nama guild kamu (opsional)\n"
                "- Nickname in-game kamu"
            ),
            color=0x5865f2,
        )
        embed.set_footer(text="Celestial Server · Epic Seven")

        view = RegisterButton()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.followup.send(
            "✅ Embed registrasi berhasil di-post.", ephemeral=True
        )

    @app_commands.command(name="setup-rules", description="[Admin] Post embed rules ke channel ini")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_rules(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="🌌 SELAMAT DATANG DI CELESTIALS SERVER!",
            color=0xfaa61a,
        )
        embed.description = (
            "*Sebelum menjelajahi channel lain, tolong Baca, Patuhi & Pahami Rules di sini.*\n\n"
            "─────────────────────────────────────\n"
            "**RULES:**\n\n"
            "**1.** 🚫 NO DRAMA! Jangan bawa-bawa masalah pribadi ke server.\n\n"
            "**2.** 🗣️ Biasakan berbahasa yang baik. Toxic boleh tapi jangan keterlaluan. "
            "Dan gak boleh baperan kalo di-toxic-in balik.\n\n"
            "**3.** 📌 Gunakan channel sesuai nama dan sebagaimana mestinya.\n\n"
            "**4.** 🖼️ Kirim foto/video sewajarnya. Share pict SFW channel. "
            "Nude tidak apa-apa asal jangan berlebihan/porn*.\n\n"
            "**5.** 🌍 Jangan rasis. Hindari isu SARA dan segala bentuk ujaran kebencian.\n\n"
            "**6.** 🔇 Jangan rusuh / chat spam! Kalo ada akun yang ke-hack ngirim spam = kick.\n\n"
            "─────────────────────────────────────\n"
            "Jika sudah membaca dan setuju, react ✅ pada pesan ini.\n\n"
            "Setelah react, channel berikut akan terbuka:\n"
            "🎮 absensi — Daftarkan akun Epic Seven kamu\n"
            "🎭 pilih-role — Ambil role selain Epic Seven"
        )
        embed.set_footer(text="✦ Celestial · Pelanggaran → kick/ban")

        msg = await interaction.channel.send(embed=embed)
        await msg.add_reaction("✅")
        await set_setting("rules_message_id", str(msg.id))
        interaction.client.rules_message_id = msg.id
        await interaction.followup.send(
            f"✅ Rules berhasil di-post. Message ID: `{msg.id}` (tersimpan otomatis).",
            ephemeral=True,
        )

    @app_commands.command(name="setup-profile", description="[Admin] Set channel ini sebagai daftar member (auto-update)")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_profile(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await set_setting("profile_channel_id", str(interaction.channel.id))
        await update_member_list(interaction.client)
        await interaction.followup.send(
            "✅ Channel profile berhasil diset dan daftar member sudah di-post.",
            ephemeral=True,
        )

    @app_commands.command(name="setup-welcome", description="[Admin] Set channel ini sebagai welcome channel")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_welcome(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        await set_setting("welcome_channel_id", str(interaction.channel.id))
        interaction.client.welcome_channel_id = interaction.channel.id

        await interaction.followup.send(
            f"✅ Welcome channel berhasil diset ke <#{interaction.channel.id}>.",
            ephemeral=True,
        )

    @app_commands.command(name="setup-register-here", description="[Admin] Set channel ini sebagai register channel (dibuka setelah react rules)")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_register_here(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        await set_setting("register_channel_id", str(interaction.channel.id))
        interaction.client.register_channel_id = interaction.channel.id

        await interaction.followup.send(
            f"✅ Register channel berhasil diset ke <#{interaction.channel.id}>.",
            ephemeral=True,
        )

    @app_commands.command(name="setup-other-games", description="[Admin] Set channel ini sebagai other-games channel (dibuka setelah react rules)")
    @app_commands.default_permissions(manage_channels=True)
    async def setup_other_games(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        await set_setting("other_games_channel_id", str(interaction.channel.id))
        interaction.client.other_games_channel_id = interaction.channel.id

        await interaction.followup.send(
            f"✅ Other-games channel berhasil diset ke <#{interaction.channel.id}>.",
            ephemeral=True,
        )

    @app_commands.command(name="setup-approval-ping", description="[Admin] Toggle role yang di-ping saat ada approval request")
    @app_commands.default_permissions(manage_roles=True)
    async def setup_approval_ping(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)

        raw = await get_setting("approval_ping_role_ids") or ""
        current_ids = [x for x in raw.split(",") if x]
        role_id_str = str(role.id)

        if role_id_str in current_ids:
            current_ids.remove(role_id_str)
            action = "dihapus dari"
        else:
            current_ids.append(role_id_str)
            action = "ditambahkan ke"

        await set_setting("approval_ping_role_ids", ",".join(current_ids))
        interaction.client.approval_ping_role_ids = [int(x) for x in current_ids]

        await interaction.followup.send(
            f"✅ {role.mention} berhasil {action} daftar approval ping.",
            ephemeral=True,
        )

    @app_commands.command(name="profile-list", description="[Admin] Force refresh daftar member")
    @app_commands.default_permissions(manage_roles=True)
    async def profile_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await update_member_list(interaction.client)
        await interaction.followup.send("✅ Daftar member berhasil diperbarui.", ephemeral=True)

    @app_commands.command(name="admin-edit", description="[Admin] Edit akun game milik user tertentu")
    @app_commands.default_permissions(manage_roles=True)
    async def admin_edit(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        accounts = await get_accounts_by_discord_id(str(member.id))
        if not accounts:
            await interaction.followup.send(
                f"❌ {member.mention} tidak memiliki akun terdaftar.", ephemeral=True
            )
            return

        if len(accounts) == 1:
            account = await get_account(accounts[0]["id"])
            modal = AdminEditModal(account, member)
            # followup tidak bisa send_modal, jadi kirim view dulu
            view = AdminEditView(accounts, member)
            await interaction.followup.send(
                f"Pilih akun milik {member.mention} yang ingin diedit:",
                view=view,
                ephemeral=True,
            )
        else:
            view = AdminEditView(accounts, member)
            await interaction.followup.send(
                f"Pilih akun milik {member.mention} yang ingin diedit:",
                view=view,
                ephemeral=True,
            )

    @app_commands.command(name="admin-unregister", description="[Admin] Hapus akun game milik user tertentu")
    @app_commands.default_permissions(manage_roles=True)
    async def admin_unregister(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        accounts = await get_accounts_by_discord_id(str(member.id))
        if not accounts:
            await interaction.followup.send(
                f"❌ {member.mention} tidak memiliki akun terdaftar.", ephemeral=True
            )
            return

        if len(accounts) == 1:
            acc = accounts[0]
            await delete_account(acc["id"])
            await update_guild_list(self.bot)
            await update_member_list(self.bot)
            await interaction.followup.send(
                f"✅ Akun **{acc['nickname']}** ({acc['server']}) "
                f"milik {member.mention} berhasil dihapus.",
                ephemeral=True,
            )
        else:
            view = AdminUnregisterView(accounts, member)
            await interaction.followup.send(
                f"Pilih akun milik {member.mention} yang ingin dihapus:",
                view=view,
                ephemeral=True,
            )

    @app_commands.command(name="help", description="Lihat daftar semua command bot")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(title="✦ Celestial Bot — Command List", color=0x5865f2)

        embed.add_field(
            name="👤 User Commands",
            value=(
                "`/profile [user]` — Lihat profil akun game\n"
                "`/edit` — Edit akun game yang sudah terdaftar\n"
                "`/unregister` — Hapus akun game yang sudah terdaftar"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏰 Guild Management",
            value=(
                "`/set-guild <role>` — Mapping guild ke Discord role\n"
                "`/guild-list` — Lihat semua guild mapping\n"
                "`/remove-guild` — Hapus mapping guild\n"
                "`/guild-set-info` — Set info guild (level, tipe, ket)\n"
                "`/guild-info` — Force refresh guild list"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ Setup",
            value=(
                "`/setup-register` — Post embed registrasi\n"
                "`/setup-rules` — Post embed rules\n"
                "`/setup-profile` — Set channel daftar member\n"
                "`/setup-welcome` — Set welcome channel\n"
                "`/setup-register-here` — Set register channel\n"
                "`/setup-other-games` — Set other-games channel\n"
                "`/setup-approval-ping <role>` — Toggle approval ping role"
            ),
            inline=False,
        )
        embed.add_field(
            name="🛠️ Utilities",
            value=(
                "`/help` — Lihat daftar command ini\n"
                "`/profile-list` — Force refresh daftar member\n"
                "`/admin-edit <member>` — Edit akun user\n"
                "`/admin-unregister <member>` — Hapus akun user\n"
                "`/bot-status` — Status bot & statistik"
            ),
            inline=False,
        )
        embed.set_footer(text="<wajib> · [opsional] · Admin commands perlu permission khusus")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="bot-status", description="[Admin] Lihat status bot dan statistik server")
    @app_commands.default_permissions(manage_guild=True)
    async def botstatus(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        now = datetime.now(timezone.utc)
        delta = now - interaction.client.start_time
        total_seconds = int(delta.total_seconds())
        hours, rem = divmod(total_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        uptime_str = f"{hours}j {minutes}m {seconds}d"

        latency_ms = round(interaction.client.latency * 1000)
        acc_stats = await get_account_stats()
        guild_count = await get_guild_count()

        welcome_id = getattr(interaction.client, "welcome_channel_id", WELCOME_CHANNEL_ID)
        register_id = getattr(interaction.client, "register_channel_id", REGISTER_CHANNEL_ID)
        other_id = getattr(interaction.client, "other_games_channel_id", OTHER_GAMES_CHANNEL_ID)
        profile_id_str = await get_setting("profile_channel_id")
        rules_msg_id = getattr(interaction.client, "rules_message_id", None)

        def fmt_channel(ch_id):
            return f"<#{ch_id}>" if ch_id else "— belum diset"

        def fmt_role(role_id):
            return f"<@&{role_id}>" if role_id else "— belum diset"

        embed = discord.Embed(title="🌌 Bot Status — Celestial", color=0x5865f2)
        embed.add_field(name="⏱️ Uptime", value=f"`{uptime_str}`", inline=True)
        embed.add_field(name="📡 Latency", value=f"`{latency_ms}ms`", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        embed.add_field(
            name="📊 Statistik Akun",
            value=(
                f"Approved  │ {acc_stats['approved']}\n"
                f"Pending   │ {acc_stats['pending']}\n"
                f"Rejected  │ {acc_stats['rejected']}\n"
                f"**Total   │ {acc_stats['total']}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="🏰 Guild Terdaftar",
            value=f"`{guild_count}` guild",
            inline=True,
        )
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        profile_id = int(profile_id_str) if profile_id_str else None
        rules_val = f"`{rules_msg_id}` ✅" if rules_msg_id else "— belum diset ❌"
        embed.add_field(
            name="📢 Channels",
            value=(
                f"Welcome     │ {fmt_channel(welcome_id)}\n"
                f"Rules       │ {fmt_channel(RULES_CHANNEL_ID)}\n"
                f"Approval    │ {fmt_channel(APPROVAL_CHANNEL_ID)}\n"
                f"Guild List  │ {fmt_channel(GUILD_LIST_CHANNEL_ID)}\n"
                f"Register    │ {fmt_channel(register_id)}\n"
                f"Other Games │ {fmt_channel(other_id)}\n"
                f"Profile     │ {fmt_channel(profile_id)}\n"
                f"Rules Msg   │ {rules_val}"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎭 Roles",
            value=(
                f"Member  │ {fmt_role(MEMBER_ROLE_ID)}\n"
                f"Default │ {fmt_role(DEFAULT_ROLE_ID)}"
            ),
            inline=True,
        )
        ping_ids = getattr(interaction.client, "approval_ping_role_ids", [])
        ping_val = " ".join(fmt_role(rid) for rid in ping_ids) if ping_ids else "— belum diset"
        embed.add_field(
            name="⚙️ Settings",
            value=(
                f"Approval Mode │ `{APPROVAL_MODE}`\n"
                f"Approval Ping │ {ping_val}"
            ),
            inline=True,
        )
        embed.set_footer(text=f"Celestial · {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        await interaction.followup.send(embed=embed, ephemeral=True)
