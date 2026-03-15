# Celestial Bot — Design Specification

## Overview

Celestial adalah Discord bot untuk manajemen guild game dan auto role-assignment. User mendaftarkan akun game mereka dengan format `Nickname/Guild/Server/Game`, bot memproses approval, lalu assign role Discord yang sesuai secara otomatis.

---

## Command Specifications

### `/register`

- **Tipe:** User command (via button "Daftar Sekarang" di `#register-here`)
- **Aksi:** Membuka modal Discord 1 langkah dengan 3 field
- **Fields:**
  | Field | Tipe | Wajib | Keterangan |
  |---|---|---|---|
  | Server | Text | ✅ | Region server (contoh: Korea, Global, Asia, Japan, Europe) |
  | Guild | Text | ❌ | Nama guild (opsional, kosongkan jika belum punya guild) |
  | Nickname | Text | ✅ | Nickname in-game, harus unik per server (kombinasi Nickname+Server tidak boleh sama) |
- **Catatan:** Game saat ini default Epic Seven (E7). Field Game tidak ditampilkan di modal.
- **Validasi:**
  - Kombinasi Nickname + Server yang sudah ada → ditolak dengan pesan error
- **Setelah submit:**
  - `APPROVAL_MODE=manual` → status `pending`, bot kirim ke `#approval-request`

### Register Flow

```
User klik "Daftar Sekarang" di #register-here
    ↓
Modal Discord muncul (1 langkah):
  - Server     : Text input  [wajib]   contoh: Asia, Korea, Global
  - Guild      : Text input  [opsional]
  - Nickname   : Text input  [wajib]
    ↓
Submit → Bot proses registrasi → status pending → kirim ke #approval-request
```

Catatan: Game saat ini default Epic Seven (E7). Jika ke depan ada multi-game, field Game bisa ditambahkan kembali.

---

### `/unregister`

- **Tipe:** User command
- **Aksi:**
  - Jika user punya 1 akun → konfirmasi langsung
  - Jika user punya > 1 akun → tampilkan select menu untuk pilih akun mana
- **Setelah unregister:**
  - Akun dihapus dari database
  - Role yang di-assign dicabut (jika tidak ada akun approved lain dari guild yang sama)
  - Guild list auto-update

---

### `/edit`

- **Tipe:** User command
- **Aksi:** Tampilkan select menu untuk pilih akun, lalu buka modal form yang sudah terisi data lama
- **Fields yang bisa diedit:** Semua (Nickname, Guild, Server, Game)
- **Validasi:** Nickname baru tidak boleh sama dengan nickname lain yang sudah ada
- **Setelah edit:** Status kembali ke `pending` jika `APPROVAL_MODE=manual`

---

### `/profile`

- **Tipe:** User command
- **Parameter opsional:** `@user` (mention)
- **Tampilan:**
  ```
  🌌 Profile · username
  ──────────────────────────────

  ⚔️ Akun #1
  Nickname  │ Ruiza
  Guild     │ amateurs
  Server    │ Asia
  Game      │ E7
  Status    │ ✅ Approved / ⏳ Pending

  ⚔️ Akun #2
  Nickname  │ Plattt
  Guild     │ virtue
  Server    │ Asia
  Game      │ E7
  Status    │ ⏳ Pending
  ```
- **Catatan:** Jika lihat profil user lain (`/profile @user`), hanya akun `approved` yang ditampilkan

---

### `/set-guild` (Admin)

- **Tipe:** Admin command
- **Parameter:**
  | Parameter | Tipe | Keterangan |
  |---|---|---|
  | role | Role | Discord role yang di-mapping |
- **Aksi:** Simpan mapping `guild_name → role_id` ke database, dengan `guild_name` diambil otomatis dari `role.name`
- **Jika guild sudah ada:** Update role mapping yang ada
- **Catatan:** Nama guild = nama role Discord. Pastikan nama role sudah sesuai nama guild sebelum menjalankan command ini.

---

### `/guild-set-info` (Admin)

- **Tipe:** Admin command
- **Flow:**
  1. Jalankan `/guild-set-info` — muncul dropdown berisi guild dari database
  2. Pilih guild → muncul dropdown tipe (Casual / Semi Kompetitif / Kompetitif)
  3. Pilih tipe → modal terbuka dengan level + keterangan (pre-filled)
  4. Submit → guild list ter-update otomatis
- **Dropdown:**
  | Step | Pilihan |
  |---|---|
  | Guild | Daftar guild dari database |
  | Tipe | `casual` / `semi_compe` / `compe` |
- **Modal Fields:**
  | Field | Tipe | Keterangan |
  |---|---|---|
  | Level | TextInput (angka) | Level guild (contoh: 20) |
  | Keterangan | TextInput (opsional) | Deskripsi singkat guild |
- **Setelah update:** Auto-trigger update guild list channel

---

### `/guild-info` (Admin)

- **Tipe:** Admin command
- **Aksi:** Force refresh pesan di `#guild-list` channel
- **Behavior:**
  - Jika pesan lama ada → edit pesan tersebut
  - Jika pesan lama tidak ada → kirim pesan baru, simpan `message_id`

---

### `/setup-welcome` (Admin)

- **Tipe:** Admin command
- **Permission:** `manage_channels`
- **Aksi:** Jalankan di channel yang diinginkan → channel tersebut disimpan sebagai welcome channel
- **Penyimpanan:** Key `welcome_channel_id` di tabel `bot_settings`
- **Priority:** DB (via command) → env var `WELCOME_CHANNEL_ID` → tidak kirim (0 / None)
- **Catatan:** Update langsung tanpa restart; jika belum pernah diset dan env var kosong, welcome tidak dikirim (silent skip)

---

### `/bot-status` (Admin)

- **Tipe:** Admin command
- **Permission:** `manage_guild`
- **Aksi:** Tampilkan embed ephemeral berisi ringkasan status bot:
  | Field | Isi |
  |---|---|
  | Uptime | Waktu berjalan sejak `on_ready` (format: `Xj Ym Zd`) |
  | Latency | Latency ke Discord gateway (ms) |
  | Statistik Akun | Jumlah approved / pending / rejected / total dari tabel `accounts` |
  | Guild Terdaftar | Jumlah baris di tabel `guild_roles` |
  | Konfigurasi | Channel welcome, profile, dan rules message ID yang aktif |
- **Catatan:** Channel yang belum dikonfigurasi ditampilkan sebagai `— belum diset`

---

### `/admin-unregister` (Admin)

- **Tipe:** Admin command
- **Parameter:**
  | Parameter | Tipe | Keterangan |
  |---|---|---|
  | member | Member | User Discord yang akunnya ingin dihapus |
- **Aksi:**
  - Jika user tidak punya akun → reply error ephemeral
  - Jika user punya 1 akun → langsung hapus, update guild list + member list
  - Jika user punya > 1 akun → tampilkan select menu untuk pilih akun mana
- **Setelah hapus:**
  - Akun dihapus dari database (termasuk pending approval jika ada)
  - `#guild-list` dan `#member-list` embed auto-update
- **Catatan:** Berlaku untuk semua status akun (pending, approved, rejected)

---

## Role Assignment Logic

```
Input: account (nickname, guild, server, game) setelah approved

1. Query guild_roles WHERE guild_name = account.guild
   └── Jika ada  → role_id = guild_roles.role_id
   └── Jika tidak → query guild_roles WHERE server = account.server
       └── Jika ada  → role_id = server_role.role_id (fallback)
       └── Jika tidak → log warning, skip role assignment

2. discord.Guild.get_member(account.discord_id).add_roles(role_id)

3. Assign DEFAULT_ROLE_ID (jika dikonfigurasi di .env)
   → Role yang SELALU diberikan ke semua user yang approved

4. Reply ke user (ephemeral): "Role @guild berhasil di-assign"

5. Trigger: update_guild_list_channel()
```

### Syarat Discord: Role Hierarchy

Bot hanya bisa assign role yang posisinya **lebih rendah** dari role bot di server.
Jika tidak, Discord akan menolak permintaan dengan error `Forbidden`.

**Setup yang benar:**
```
Server Roles (urutan atas = tertinggi):
├── Admin
├── Mod
├── Celestial          ← role bot harus di sini (di atas semua role yang mau di-assign)
├── DAWNSEEKER         ← guild role
├── Covenants          ← guild role
├── Member
└── @everyone
```

**Gejala jika salah:** Log bot menampilkan:
```
[roles] Bot tidak punya permission untuk assign override role <nama_role>
```

**Fix:** Di Discord server settings → Roles → drag role bot ke posisi lebih tinggi
dari semua guild role yang di-mapping via `/set-guild`.

---

## Approval Flow

### Mode Manual

```
User /register
    │
    ▼
DB: INSERT accounts (status='pending')
    │
    ▼
Bot kirim embed ke #approval-request
[✅ Approve] [❌ Reject]
    │
    ├─ Admin klik Approve
    │       │
    │       ▼
    │   DB: UPDATE status='approved'
    │   assign_role(user)
    │   update_guild_list_channel()
    │   DM user: "✅ Akun {nickname} ({server}) kamu telah di-approve!"
    │
    └─ Admin klik Reject
            │
            ▼
        DB: UPDATE status='rejected'
        notify user (ephemeral/DM)
```

### Mode Otomatis

```
User /register
    │
    ▼
DB: INSERT accounts (status='approved')
assign_role(user)
update_guild_list_channel()
Reply ke user: "Registrasi berhasil!"
```

---

## Guild List Channel Format

Bot mengirim **multiple pesan** di `#guild-list` — 1 pesan per 8 guild (`GUILDS_PER_PAGE = 8`).
Setiap pesan di-edit (bukan kirim baru) menggunakan tabel `guild_list_pages`.

**Format per guild (embed field):**
```
Field name  : 🏰 {guild_name} ({N} member)
Field value : *{tipe} · Lv.{level} · {keterangan}*    ← baris header (jika ada)
              Nickname1 @mention Server  ·  Nickname2 @mention Server  ·  ...
```

Member dipisah dengan `  ·  ` (horizontal), bukan newline. Wrap ke baris bawah hanya jika baris penuh.

**Pesan pertama:** title `"✦ Daftar Guild — Celestial Server"`
**Pesan lanjutan:** title `"✦ Daftar Guild — (lanjutan)"`
**Footer** (hanya di pesan terakhir): `"Total member terdaftar: N"`

**Contoh tampilan:**
```
🏰 amateurs (3 member)
*Casual · Lv.20 · Guild untuk pemula*
Ruiza @123 Asia  ·  Player2 @456 Asia  ·  Player3 @789 Global

🏰 virtue (2 member)
*Kompetitif · Lv.45*
Plattt @321 Asia  ·  Player4 @654 Asia

👤 Tanpa Guild
FreeAgent @111 Global  ·  Wanderer @222 Korea

Total member terdaftar: 6
```

---

## Auto-update Guild List Triggers

Setiap trigger menyebabkan bot **edit semua pesan** guild list yang ada (atau kirim baru jika belum ada).

| Event | Auto-update? |
|---|---|
| User register (approved) | ✅ Ya |
| User unregister | ✅ Ya |
| Admin `/guild-set-info` | ✅ Ya |
| Admin `/guild-info` | ✅ Ya (force refresh semua halaman) |
| User `/edit` (re-approved) | ✅ Ya |

---

## Welcome Message

### Trigger
Event: `on_member_join(member)` — otomatis dipanggil setiap kali member baru join server.

### Channel
`WELCOME_CHANNEL_ID` — dikonfigurasi via `.env`.

### Embed
```
Author : avatar + username member baru
Title  : 👋 Selamat datang, @username!
Body   : Mention user + teks selamat datang + instruksi baca #rules (link via `RULES_CHANNEL_ID`)
Footer : ✦ Celestial · Selamat bergabung!
Color  : Biru (info)
```

---

## Member List Channel

### Setup
Admin jalankan `/setup-profile` di channel yang diinginkan → bot kirim daftar member ke channel tersebut.

### Embed Format

**Per baris:**
```
⚔️ **{nickname}** (<@{discord_id}>) · {guild atau "—"} · {server}
```

**Multi-pesan (100+ member):**
- Setiap pesan berisi maksimal 20 member
- Pesan pertama: title `🌌 Daftar Member Celestial`
- Pesan lanjutan: title `🌌 Daftar Member Celestial (lanjutan)`
- Footer hanya di pesan terakhir: `Total member: N`

### Storage
- Menggunakan `guild_list_pages` table dengan key `member_{channel_id}` (namespace terpisah dari guild list)
- Setiap update: edit pesan yang ada, kirim baru jika belum ada, hapus otomatis jika jumlah halaman berkurang

### Auto-update Triggers
Sama dengan guild list: approve, unregister, admin unregister, `/profile-list` (force refresh).

---

## Rules Channel

### Setup
Admin jalankan `/setup-rules` → bot post embed rules ke `#rules` channel (satu kali, pesan disematkan).

### Embed
```
Title     : 🌌 SELAMAT DATANG DI CELESTIALS SERVER!
Subtitle  : Sebelum menjelajahi channel lain, tolong Baca, Patuhi & Pahami Rules di sini.
Rules     : 6 poin rules server (lihat konten aktual)
Footer    : ✦ Celestial · Pelanggaran → kick/ban
CTA bawah : React ✅ → channel #register-here & #other-games terbuka
Color     : Kuning/warning
Thumbnail : Logo Celestial (lingkaran dengan ✦)
```

### Channel Lock / Unlock via Reaction
```
User react ✅ pada pesan rules
    │
    ▼
on_raw_reaction_add(payload)
    │
    ▼
Bot assign role "Member" ke user
    │
    ▼
Channel #register-here & #other-games unlock
(set_permissions: view_channel=True, send_messages=True untuk role "Member")
    │
    ▼
Bot kirim DM ke user dengan <#channel_id> clickable link
```

**Catatan setup manual di Discord:**
1. Buat role `Member`
2. Set permission `#register-here` dan `#other-games` → hanya visible ke role `Member`
3. Jalankan `/setup-register-here` di `#register-here` dan `/setup-other-games` di `#other-games`

### Channel Mentions di Embed
- Rules embed menggunakan **plain text nama channel** (`absensi`, `pilih-role`) — bukan `<#id>` mention
  → Menghindari "#No Access" display di Discord mobile
- Setelah react ✅, bot kirim **DM ke user** dengan `<#channel_id>` clickable link
  → DM dikirim SETELAH permissions aktif → link tampil accessible di mobile maupun desktop
- Jika user menonaktifkan DM: log debug saja, tidak error

