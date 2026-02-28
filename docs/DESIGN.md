# Celestial Bot — Design Specification

## Overview

Celestial adalah Discord bot untuk manajemen guild game dan auto role-assignment. User mendaftarkan akun game mereka dengan format `Nickname/Guild/Server/Game`, bot memproses approval, lalu assign role Discord yang sesuai secara otomatis.

---

## Command Specifications

### `/register`

- **Tipe:** User command
- **Aksi:** Membuka modal form Discord
- **Fields:**
  | Field | Tipe | Wajib | Keterangan |
  |---|---|---|---|
  | Nickname | Text | ✅ | Nickname in-game, harus unik di seluruh database |
  | Guild | Text | ✅ | Nama guild di game |
  | Server | Text | ✅ | Region server (contoh: Asia, NA, EU) |
  | Game | Text | ✅ | Nama game (contoh: E7) |
- **Validasi:**
  - Nickname yang sudah ada di database → ditolak dengan pesan error
- **Setelah submit:**
  - `APPROVAL_MODE=manual` → status `pending`, bot kirim ke `#approval-request`
  - `APPROVAL_MODE=auto` → status langsung `approved`, role di-assign, guild list update

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
  | guild | String | Nama guild |
  | role | Role | Discord role yang di-mapping |
- **Aksi:** Simpan mapping `guild_name → role_id` ke database
- **Jika guild sudah ada:** Update role mapping yang ada

---

### `/guild-set-info` (Admin)

- **Tipe:** Admin command
- **Parameter:**
  | Parameter | Tipe | Keterangan |
  |---|---|---|
  | guild | String | Nama guild |
  | level | Integer | Level guild (angka, contoh: 20) |
  | tipe | Choice | `casual` / `semi_compe` / `compe` |
  | keterangan | String | Deskripsi singkat guild |
- **Setelah update:** Auto-trigger update guild list channel

---

### `/guild-info` (Admin)

- **Tipe:** Admin command
- **Aksi:** Force refresh pesan di `#guild-list` channel
- **Behavior:**
  - Jika pesan lama ada → edit pesan tersebut
  - Jika pesan lama tidak ada → kirim pesan baru, simpan `message_id`

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

3. Reply ke user (ephemeral): "Role @guild berhasil di-assign"

4. Trigger: update_guild_list_channel()
```

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
    │   notify user (ephemeral/DM)
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

```
🏰 amateurs  [Casual]
"Deskripsi guild..."
Level: 20  │  Server: Asia · E7
Members (3): Ruiza, Player2, Player3

🏰 virtue  [Competitive]
"Deskripsi guild..."
Level: 45  │  Server: Asia · E7
Members (2): Plattt, Player4

──────────────────────────────────────
✦ Celestial · Terakhir diperbarui: [timestamp]
Total guild: 2 · Total member: 5
```

---

## Auto-update Guild List Triggers

| Event | Auto-update? |
|---|---|
| User register (approved) | ✅ Ya |
| User unregister | ✅ Ya |
| Admin `/guild-set-info` | ✅ Ya |
| Admin `/guild-info` | ✅ Ya (force refresh) |
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
Body   : Mention user + teks selamat datang + instruksi baca #rules
Footer : ✦ Celestial · Selamat bergabung!
Color  : Biru (info)
```

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
CTA bawah : React ✅ → channel #register-here & #pilih-roles terbuka
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
Channel #register-here & #pilih-roles unlock
(permission Discord: hanya visible untuk role "Member")
```

**Catatan setup manual di Discord:**
1. Buat role `Member`
2. Set permission `#register-here` dan `#pilih-roles` → hanya visible ke role `Member`
3. Channel mention di embed menggunakan `<#CHANNEL_ID>` (dikonfigurasi via env var)

### Channel Mentions di Embed
- `REGISTER_CHANNEL_ID` → `<#channel_id>` di teks rules
- `PILIH_ROLES_CHANNEL_ID` → `<#channel_id>` di teks rules

