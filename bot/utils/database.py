import aiosqlite
import os
from config import DB_PATH


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id  TEXT NOT NULL,
                nickname    TEXT NOT NULL,
                guild       TEXT NOT NULL DEFAULT '',
                server      TEXT NOT NULL,
                game        TEXT NOT NULL DEFAULT 'E7',
                status      TEXT NOT NULL DEFAULT 'pending',
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(nickname, server)
            );

            CREATE TABLE IF NOT EXISTS guild_roles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_name  TEXT NOT NULL UNIQUE,
                role_id     TEXT NOT NULL,
                server      TEXT,
                keterangan  TEXT,
                level       INTEGER,
                tipe        TEXT,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pending_approvals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id  INTEGER REFERENCES accounts(id),
                message_id  TEXT,
                role_override TEXT,
                reviewed_by TEXT,
                reviewed_at DATETIME,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS guild_list_message (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id  TEXT NOT NULL UNIQUE,
                message_id  TEXT NOT NULL,
                updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bot_settings (
                key    TEXT NOT NULL UNIQUE,
                value  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS guild_list_pages (
                channel_id  TEXT    NOT NULL,
                page_index  INTEGER NOT NULL,
                message_id  TEXT    NOT NULL,
                updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (channel_id, page_index)
            );

            CREATE TABLE IF NOT EXISTS starboard_entries (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                source_message_id    TEXT NOT NULL UNIQUE,
                starboard_message_id TEXT NOT NULL,
                author_discord_id    TEXT NOT NULL,
                star_count           INTEGER NOT NULL DEFAULT 0,
                role_assigned_at     DATETIME,
                role_expires_at      DATETIME,
                role_removed         INTEGER NOT NULL DEFAULT 0,
                created_at           DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS active_tasks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                requester_id     TEXT NOT NULL,
                requester_ign    TEXT NOT NULL,
                promo_title      TEXT NOT NULL,
                detail           TEXT NOT NULL,
                budget           TEXT,
                joki_id          TEXT,
                channel_id       TEXT,
                request_msg_id   TEXT,
                status           TEXT NOT NULL DEFAULT 'open',
                created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
                assigned_at      DATETIME,
                closed_at        DATETIME
            );
        """)
        await db.commit()

        # Migration: add role_override column if not exists
        try:
            await db.execute("ALTER TABLE pending_approvals ADD COLUMN role_override TEXT")
            await db.commit()
        except Exception:
            pass  # column already exists


async def get_account(account_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ) as cur:
            return await cur.fetchone()


async def get_accounts_by_discord_id(discord_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM accounts WHERE discord_id = ? ORDER BY created_at",
            (discord_id,)
        ) as cur:
            return await cur.fetchall()


async def get_approved_accounts_by_discord_id(discord_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM accounts WHERE discord_id = ? AND status = 'approved' ORDER BY created_at",
            (discord_id,)
        ) as cur:
            return await cur.fetchall()


async def check_nickname_exists(nickname: str, server: str, exclude_account_id: int = None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        if exclude_account_id:
            async with db.execute(
                "SELECT id FROM accounts WHERE nickname = ? AND server = ? AND id != ? LIMIT 1",
                (nickname, server, exclude_account_id)
            ) as cur:
                return await cur.fetchone() is not None
        else:
            async with db.execute(
                "SELECT id FROM accounts WHERE nickname = ? AND server = ? LIMIT 1",
                (nickname, server)
            ) as cur:
                return await cur.fetchone() is not None


async def create_account(discord_id: str, nickname: str, guild: str, server: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "INSERT INTO accounts (discord_id, nickname, guild, server) VALUES (?, ?, ?, ?)",
            (discord_id, nickname, guild, server)
        ) as cur:
            account_id = cur.lastrowid
        await db.commit()
        return account_id


async def update_account_status(account_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE accounts SET status = ? WHERE id = ?",
            (status, account_id)
        )
        await db.commit()


async def update_account_fields(account_id: int, nickname: str, guild: str, server: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE accounts SET nickname = ?, guild = ?, server = ? WHERE id = ?",
            (nickname, guild, server, account_id)
        )
        await db.commit()


async def delete_account(account_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM pending_approvals WHERE account_id = ?", (account_id,))
        await db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        await db.commit()


async def get_guild_role(guild_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM guild_roles WHERE guild_name = ? COLLATE NOCASE",
            (guild_name,)
        ) as cur:
            return await cur.fetchone()


async def get_guild_role_by_server(server: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM guild_roles WHERE server = ? COLLATE NOCASE LIMIT 1",
            (server,)
        ) as cur:
            return await cur.fetchone()


async def get_all_guild_roles():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM guild_roles ORDER BY guild_name") as cur:
            return await cur.fetchall()


async def upsert_guild_role(guild_name: str, role_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO guild_roles (guild_name, role_id)
               VALUES (?, ?)
               ON CONFLICT(guild_name) DO UPDATE SET role_id = excluded.role_id""",
            (guild_name, role_id)
        )
        await db.commit()


async def update_guild_info(guild_name: str, level: int, tipe: str, keterangan: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE guild_roles
               SET level = ?, tipe = ?, keterangan = ?
               WHERE guild_name = ? COLLATE NOCASE""",
            (level, tipe, keterangan, guild_name)
        )
        await db.commit()


async def delete_guild_role(guild_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM guild_roles WHERE guild_name = ? COLLATE NOCASE",
            (guild_name,)
        )
        await db.commit()


async def create_pending_approval(account_id: int, message_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO pending_approvals (account_id, message_id) VALUES (?, ?)",
            (account_id, message_id)
        )
        await db.commit()


async def get_pending_approval_by_message(message_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM pending_approvals WHERE message_id = ? ORDER BY created_at DESC LIMIT 1",
            (message_id,)
        ) as cur:
            return await cur.fetchone()


async def resolve_pending_approval(account_id: int, reviewed_by: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE pending_approvals
               SET reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
               WHERE account_id = ? AND reviewed_at IS NULL""",
            (reviewed_by, account_id)
        )
        await db.commit()


async def set_approval_role_override(account_id: int, role_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE pending_approvals SET role_override = ? WHERE account_id = ? AND reviewed_at IS NULL",
            (role_id, account_id)
        )
        await db.commit()


async def get_guild_list_message(channel_id: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT message_id FROM guild_list_message WHERE channel_id = ?",
            (channel_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def upsert_guild_list_message(channel_id: str, message_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO guild_list_message (channel_id, message_id, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(channel_id) DO UPDATE SET message_id = excluded.message_id,
               updated_at = CURRENT_TIMESTAMP""",
            (channel_id, message_id)
        )
        await db.commit()


async def get_guild_list_pages(channel_id: str) -> list[str]:
    """Ambil semua message_id untuk channel guild list, urut page_index asc."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT message_id FROM guild_list_pages WHERE channel_id = ? ORDER BY page_index",
            (channel_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [row[0] for row in rows]


async def upsert_guild_list_page(channel_id: str, page_index: int, message_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO guild_list_pages (channel_id, page_index, message_id, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(channel_id, page_index) DO UPDATE SET
                   message_id = excluded.message_id,
                   updated_at = CURRENT_TIMESTAMP""",
            (channel_id, page_index, message_id)
        )
        await db.commit()


async def delete_guild_list_pages_above(channel_id: str, max_index: int):
    """Hapus halaman dengan page_index > max_index (ketika jumlah halaman berkurang)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM guild_list_pages WHERE channel_id = ? AND page_index > ?",
            (channel_id, max_index)
        )
        await db.commit()


async def get_all_approved_accounts():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM accounts WHERE status = 'approved' ORDER BY guild, nickname"
        ) as cur:
            return await cur.fetchall()


async def get_setting(key: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM bot_settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def delete_setting(key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bot_settings WHERE key = ?", (key,))
        await db.commit()


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO bot_settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value)
        )
        await db.commit()


async def get_account_stats() -> dict:
    """Return count of accounts per status."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM accounts GROUP BY status"
        )
        rows = await cursor.fetchall()
    stats = {"pending": 0, "approved": 0, "rejected": 0}
    for status, count in rows:
        if status in stats:
            stats[status] = count
    stats["total"] = sum(stats.values())
    return stats


async def get_guild_count() -> int:
    """Return total number of guilds in guild_roles."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM guild_roles")
        row = await cursor.fetchone()
    return row[0] if row else 0


# ── Starboard ─────────────────────────────────────────────────────

async def get_starboard_entry(source_message_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM starboard_entries WHERE source_message_id = ?",
            (source_message_id,)
        ) as cur:
            return await cur.fetchone()


async def create_starboard_entry(
    source_message_id: str,
    starboard_message_id: str,
    author_discord_id: str,
    star_count: int,
    role_assigned_at: str | None,
    role_expires_at: str | None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """INSERT INTO starboard_entries
               (source_message_id, starboard_message_id, author_discord_id,
                star_count, role_assigned_at, role_expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source_message_id, starboard_message_id, author_discord_id,
             star_count, role_assigned_at, role_expires_at)
        ) as cur:
            entry_id = cur.lastrowid
        await db.commit()
        return entry_id


async def update_starboard_star_count(source_message_id: str, star_count: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE starboard_entries SET star_count = ? WHERE source_message_id = ?",
            (star_count, source_message_id)
        )
        await db.commit()


async def get_expired_starboard_roles():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM starboard_entries
               WHERE role_expires_at <= datetime('now')
               AND role_removed = 0
               AND role_assigned_at IS NOT NULL"""
        ) as cur:
            return await cur.fetchall()


async def mark_starboard_role_removed(source_message_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE starboard_entries SET role_removed = 1 WHERE source_message_id = ?",
            (source_message_id,)
        )
        await db.commit()


async def get_starboard_leaderboard(limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT author_discord_id, COUNT(*) as count
               FROM starboard_entries
               GROUP BY author_discord_id
               ORDER BY count DESC
               LIMIT ?""",
            (limit,)
        ) as cur:
            return await cur.fetchall()


# ── Active Tasks ──────────────────────────────────────────────────

async def create_active_task(
    requester_id: str, requester_ign: str, promo_title: str,
    detail: str, budget: str | None, request_msg_id: str,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """INSERT INTO active_tasks
               (requester_id, requester_ign, promo_title, detail, budget, request_msg_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (requester_id, requester_ign, promo_title, detail, budget, request_msg_id)
        ) as cur:
            task_id = cur.lastrowid
        await db.commit()
        return task_id


async def get_active_task(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM active_tasks WHERE id = ?", (task_id,)
        ) as cur:
            return await cur.fetchone()


async def get_active_task_by_channel(channel_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM active_tasks WHERE channel_id = ? AND status = 'assigned'",
            (channel_id,)
        ) as cur:
            return await cur.fetchone()


async def update_task_assign(task_id: int, joki_id: str, channel_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE active_tasks
               SET joki_id = ?, channel_id = ?, status = 'assigned',
                   assigned_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (joki_id, channel_id, task_id)
        )
        await db.commit()


async def update_task_closed(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE active_tasks
               SET status = 'closed', closed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (task_id,)
        )
        await db.commit()
