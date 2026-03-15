# Celestial Bot — Database Schema

Database: **SQLite** via `aiosqlite`
File: `data/celestial.db`

---

## Tabel: `accounts`

Menyimpan semua akun game yang sudah didaftarkan user.

```sql
CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id  TEXT    NOT NULL,               -- Discord user ID
    nickname    TEXT    NOT NULL,                -- Nickname in-game (unik per server)
    guild       TEXT    NOT NULL,               -- Nama guild
    server      TEXT    NOT NULL,               -- Region/server (contoh: Asia)
    game        TEXT    NOT NULL,               -- Nama game (contoh: E7)
    status      TEXT    NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

UNIQUE(nickname, server)  -- nickname harus unik per server, boleh sama di server berbeda

CREATE INDEX IF NOT EXISTS idx_accounts_discord_id ON accounts(discord_id);
CREATE INDEX IF NOT EXISTS idx_accounts_guild      ON accounts(guild);
CREATE INDEX IF NOT EXISTS idx_accounts_status     ON accounts(status);
```

**Contoh data:**
| id | discord_id | nickname | guild | server | game | status |
|---|---|---|---|---|---|---|
| 1 | 123456789 | Ruiza | amateurs | Asia | E7 | approved |
| 2 | 123456789 | Plattt | virtue | Asia | E7 | pending |
| 3 | 987654321 | ロオ | Octagram | Asia | E7 | approved |

---

## Tabel: `guild_roles`

Menyimpan mapping guild → Discord role, plus info tambahan yang diset admin.

```sql
CREATE TABLE IF NOT EXISTS guild_roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_name  TEXT    NOT NULL UNIQUE,         -- Nama guild (key)
    role_id     TEXT    NOT NULL,               -- Discord role ID
    server      TEXT,                           -- Region untuk fallback matching
    keterangan  TEXT,                           -- Deskripsi guild (diset admin)
    level       INTEGER,                        -- Level guild angka (diset admin)
    tipe        TEXT,                           -- casual | semi_compe | compe
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Contoh data:**
| id | guild_name | role_id | server | keterangan | level | tipe |
|---|---|---|---|---|---|---|
| 1 | amateurs | 111222333 | Asia | Guild untuk pemula | 20 | casual |
| 2 | virtue | 444555666 | Asia | Guild kompetitif | 45 | compe |
| 3 | Octagram | 777888999 | Asia | Guild semi-kompetitif | 32 | semi_compe |

**Catatan `tipe`:**
- `casual` — santai, tidak ada kewajiban
- `semi_compe` — balance antara fun dan kompetitif
- `compe` — fokus kompetitif, aktif di content ranked

---

## Tabel: `pending_approvals`

Queue untuk approval manual. Menyimpan ID pesan di `#approval-request` agar bisa di-edit setelah admin approve/reject.

```sql
CREATE TABLE IF NOT EXISTS pending_approvals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    message_id  TEXT,           -- ID pesan bot di #approval-request
    reviewed_by TEXT,           -- Discord ID admin yang mereview
    reviewed_at DATETIME,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pending_account ON pending_approvals(account_id);
```

---

## Tabel: `guild_list_message`

Menyimpan ID pesan bot di `#guild-list` channel agar bisa di-edit (bukan kirim baru) setiap update.

```sql
CREATE TABLE IF NOT EXISTS guild_list_message (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id  TEXT    NOT NULL UNIQUE,        -- Discord channel ID
    message_id  TEXT    NOT NULL,               -- ID pesan yang akan di-edit
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Tabel: `guild_list_pages`

Menyimpan message ID tiap halaman guild list. Mendukung multiple messages untuk server dengan 30+ guild
(Discord limit 25 field dan 6000 char per embed).

```sql
CREATE TABLE IF NOT EXISTS guild_list_pages (
    channel_id  TEXT    NOT NULL,
    page_index  INTEGER NOT NULL,           -- Nomor halaman (0-based)
    message_id  TEXT    NOT NULL,           -- ID pesan Discord yang akan di-edit
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_id, page_index)
);
```

**Fungsi helper:**
- `get_guild_list_pages(channel_id)` → `list[str]` — semua message ID urut page_index asc
- `upsert_guild_list_page(channel_id, page_index, message_id)` — insert/update satu halaman
- `delete_guild_list_pages_above(channel_id, max_index)` — hapus halaman ekstra saat jumlah guild berkurang

**Catatan:** Tabel `guild_list_message` tetap dipakai oleh `update_member_list()` untuk `#member-list` channel (single message).

---

## Tabel: `bot_settings`

Menyimpan konfigurasi bot yang di-set via command (bukan env var).

```sql
CREATE TABLE IF NOT EXISTS bot_settings (
    key    TEXT NOT NULL UNIQUE,
    value  TEXT NOT NULL
);
```

**Contoh data:**
| key | value |
|---|---|
| rules_message_id | 1234567890123456789 |
| profile_channel_id | 9876543210987654321 |

**Diisi oleh:** Admin via `/setup-rules` dan `/setup-profile` (otomatis, tidak perlu edit `.env`).

---

## Relasi Antar Tabel

```
accounts (discord_id) ──────────── Discord User
accounts (guild) ──────────────── guild_roles (guild_name)
accounts (id) ─────────────────── pending_approvals (account_id)
guild_list_pages (channel_id) ──── Discord Channel (#guild-list)  ← multi-page guild list
guild_list_message (channel_id) ── Discord Channel (#member-list) ← single message member list
```

---

## Query Penting

### Ambil semua akun user tertentu
```sql
SELECT * FROM accounts
WHERE discord_id = ?
ORDER BY created_at ASC;
```

### Cek nickname sudah ada (per server)
```sql
SELECT id FROM accounts WHERE nickname = ? AND server = ? LIMIT 1;
```

### Ambil semua member per guild (untuk guild list)
```sql
SELECT a.nickname, a.discord_id, a.server, a.game
FROM accounts a
WHERE a.guild = ? AND a.status = 'approved'
ORDER BY a.created_at ASC;
```

### Ambil semua guild dengan info dan member count
```sql
SELECT
    gr.guild_name,
    gr.role_id,
    gr.keterangan,
    gr.level,
    gr.tipe,
    gr.server,
    COUNT(a.id) AS member_count
FROM guild_roles gr
LEFT JOIN accounts a
    ON a.guild = gr.guild_name AND a.status = 'approved'
GROUP BY gr.guild_name
ORDER BY gr.guild_name ASC;
```

### Role assignment: cek guild dulu, fallback ke server
```sql
-- 1. Cek guild
SELECT role_id FROM guild_roles WHERE guild_name = ? LIMIT 1;

-- 2. Fallback: cek server
SELECT role_id FROM guild_roles WHERE server = ? LIMIT 1;
```
