# Celestial — Discord Bot

Bot Discord untuk manajemen guild dan auto role-assignment berdasarkan registrasi akun game.

## Tech Stack

| Komponen | Teknologi |
|---|---|
| Language | Python 3.11+ |
| Framework | discord.py 2.x (with app_commands) |
| Database | SQLite (via `aiosqlite`) |
| Config | python-dotenv (`.env`) |

## Struktur Folder

```
celestial/
├── CLAUDE.md
├── preview.html            ← Mockup visual (bukan bagian bot)
├── README.md
├── .env
├── .env.example
├── requirements.txt
├── main.py                 ← Entry point, load cogs, init db
├── config.py               ← Konstanta dan env vars
├── docs/
│   ├── DESIGN.md
│   └── DATABASE.md
├── bot/
│   ├── __init__.py
│   ├── cogs/
│   │   ├── register.py     ← /register, /unregister, /edit
│   │   ├── profile.py      ← /profile
│   │   └── admin.py        ← /set-guild, /guild-set-info, /guild-info
│   └── utils/
│       ├── database.py     ← SQLite helper (async)
│       └── roles.py        ← Role assignment + guild list update
└── data/
    └── celestial.db
```

## Commands

### User Commands

| Command | Deskripsi |
|---|---|
| `/register` | Buka modal form untuk mendaftarkan 1 akun game (Nickname, Guild, Server, Game) |
| `/unregister` | Hapus akun yang sudah terdaftar (pilih dari list jika > 1 akun) |
| `/edit` | Edit semua field akun yang sudah ada |
| `/profile` | Lihat profil akun sendiri |
| `/profile @user` | Lihat profil akun user lain (hanya akun approved) |

### Admin Commands

| Command | Deskripsi |
|---|---|
| `/set-guild <guild> <@role>` | Mapping nama guild ke Discord role |
| `/guild-set-info <guild> <level> <tipe> <keterangan>` | Set info guild (level angka, tipe: casual/semi_compe/compe) |
| `/guild-info` | Force refresh pesan guild list di channel guild-list |
| `/setup-rules` | Admin | Post embed rules ke #rules channel (satu kali) |

## Events (Bot Listeners)

| Event | Deskripsi |
|---|---|
| `on_member_join` | Bot kirim embed welcome ke `#welcome` channel secara otomatis |
| `on_raw_reaction_add` | Deteksi react ✅ di pesan rules → assign role `Member` → unlock #register-here & #pilih-roles |

## Role Assignment Logic

```
Setelah akun di-approve:
1. Cek guild di tabel guild_roles
   → Ada role  : assign role guild
   → Tidak ada : assign role server/region sebagai fallback
2. Assign role ke user di Discord
3. Kirim notifikasi ke user (ephemeral reply)
4. Trigger auto-update guild list channel
```

## Approval Flow

Dua mode yang bisa dikonfigurasi via environment variable `APPROVAL_MODE`:

- `manual` — Bot kirim embed ke `#approval-request`, admin klik tombol ✅ Approve / ❌ Reject
- `auto`   — Setelah `/register`, akun langsung approved dan role langsung di-assign

## Guild List Auto-update

Channel `#guild-list` di-update otomatis ketika:
- User baru register **dan** akun di-approve
- User melakukan `/unregister`
- Admin menjalankan `/guild-set-info`
- Admin menjalankan `/guild-info` (force refresh)

Bot menyimpan `message_id` dari pesan guild list untuk di-edit (bukan kirim baru).

## Environment Variables

```env
# .env.example
DISCORD_TOKEN=your_bot_token
GUILD_ID=your_server_id
APPROVAL_CHANNEL_ID=channel_id_for_approval
GUILD_LIST_CHANNEL_ID=channel_id_for_guild_list
WELCOME_CHANNEL_ID=channel_id_for_welcome
RULES_MESSAGE_ID=message_id_of_rules_post
REGISTER_CHANNEL_ID=channel_id_for_register_here
PILIH_ROLES_CHANNEL_ID=channel_id_for_pilih_roles
MEMBER_ROLE_ID=role_id_assigned_after_rules_react
APPROVAL_MODE=manual   # manual | auto
DB_PATH=data/celestial.db
```

## Cara Menjalankan

```bash
# Install dependencies
pip install -r requirements.txt

# Copy env file
cp .env.example .env
# Edit .env dengan nilai yang sesuai

# Jalankan bot
python main.py
```

## Aturan Coding

- Gunakan `async/await` untuk semua operasi database dan Discord API
- Semua cog menggunakan `discord.app_commands` (slash commands)
- Modal form menggunakan `discord.ui.Modal`
- Tombol approve/reject menggunakan `discord.ui.View` dengan `discord.ui.Button`
- Error handling: selalu reply dengan ephemeral message jika error
- Naming convention: `snake_case` untuk fungsi dan variabel, `PascalCase` untuk class
- Database queries terpusat di `bot/utils/database.py`
- Role assignment logic terpusat di `bot/utils/roles.py`
