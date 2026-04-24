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
| `/register` | Buka modal 1 langkah: Server (wajib), Guild (opsional), Nickname (wajib). Game default E7. |
| `/unregister` | Hapus akun yang sudah terdaftar (pilih dari list jika > 1 akun) |
| `/edit` | Edit semua field akun yang sudah ada |
| `/profile` | Lihat profil akun sendiri |
| `/profile @user` | Lihat profil akun user lain (hanya akun approved) |

### Admin Commands

| Command | Deskripsi |
|---|---|
| `/set-guild <@role>` | Mapping nama guild ke Discord role (nama guild = nama role) |
| `/guild-set-info` | Pilih guild → pilih tipe → isi level/keterangan via modal |
| `/guild-info` | Force refresh pesan guild list di channel guild-list |
| `/setup-rules` | Admin | Post embed rules ke #rules channel (satu kali) |
| `/setup-profile` | Set channel ini sebagai daftar member auto-update |
| `/setup-welcome` | Set channel ini sebagai welcome channel (on_member_join) |
| `/bot-status` | Lihat status bot: uptime, latency, statistik akun, konfigurasi channel |
| `/profile-list` | Force refresh daftar member |
| `/admin-edit @user` | Edit akun game milik user tertentu |
| `/admin-unregister @user` | Hapus akun game milik user tertentu (tanpa perlu minta user unregister) |
| `/guild-list` | Lihat semua guild yang sudah di-mapping |
| `/remove-guild` | Hapus mapping guild dari database |
| `/setup-register` | Post embed registrasi ke channel ini |
| `/setup-register-here` | Set channel ini sebagai register channel (dibuka setelah react rules) |
| `/setup-other-games` | Set channel ini sebagai other-games channel (dibuka setelah react rules) |
| `/setup-approval-ping <@role>` | Toggle role yang di-ping saat ada approval request |
| `/setup-changelog` | Set channel ini sebagai changelog channel |
| `/changelog` | Post changelog dari git commits terbaru |
| `/announce` | Post pengumuman fleksibel via modal (judul, isi, warna) |
| `/promote` | Post promosi dengan button "Saya Tertarik" |
| `/setup-task-channel` | Set channel task/joki (toggle) |
| `/setup-task-role <@role>` | Set role yang di-ping saat ada task request |
| `/close-task` | Tutup task, save transcript, hapus private channel |
| `/setup-waifu-log` | Set/unset channel waifu logger (toggle) |
| `/setup-waifu-bot <@bot>` | Set bot yang dimonitor untuk waifu logger |
| `/help` | Lihat daftar semua command bot |

### Starboard Commands

| Command | Deskripsi |
|---|---|
| `/setup-starboard` | Set channel ini sebagai starboard target (tempat repost) |
| `/setup-starboard-source` | Set channel ini sebagai sumber starboard (pesan yang dimonitor) |
| `/setup-starboard-role <@role>` | Set role sementara yang diberikan (30 hari) |
| `/setup-starboard-threshold <count>` | Set minimum bintang untuk masuk starboard (default: 5) |
| `/leaderboard` | Top 10 user dengan pesan paling banyak di starboard |

### Sticker Voting Commands

| Command | Deskripsi |
|---|---|
| `/submit-sticker <file> <nama> <tag>` | Submit sticker baru (semua member, cooldown 1 hari, max 512KB) |
| `/poll-sticker-keep <sticker>` | Admin trigger retention poll keep/remove untuk sticker existing |
| `/setup-sticker-channel` | Toggle channel ini sebagai tempat voting sticker |
| `/setup-sticker-admin-role <@role>` | Set role yang bisa approve/reject submit & confirm/cancel retention |
| `/list-sticker-polls` | Lihat semua sticker poll aktif (submit + retention) |
| `/close-sticker-poll <id>` | Admin paksa tutup poll sekarang (evaluate state saat ini, skip deadline) |

## Events (Bot Listeners)

| Event | Deskripsi |
|---|---|
| `on_member_join` | Bot kirim embed welcome ke `#welcome` channel secara otomatis |
| `on_raw_reaction_add` | Deteksi react ✅ di pesan rules → assign role `Member` → unlock #register-here & #other-games |
| `on_raw_reaction_add` | Deteksi react ⭐ di channel starboard source → jika threshold tercapai, repost ke starboard + assign temp role |

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
RULES_CHANNEL_ID=channel_id_for_rules
REGISTER_CHANNEL_ID=channel_id_for_register_here
OTHER_GAMES_CHANNEL_ID=channel_id_for_other_games
MEMBER_ROLE_ID=role_id_assigned_after_rules_react
DEFAULT_ROLE_ID=role_id_assigned_after_approval
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
