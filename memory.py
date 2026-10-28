'''
===============================================================
 File      : memory.py
 Project   : Discordbot
 Purpose   : Persistent memory for the bot (SQLite)
===============================================================

Two kinds of memory:
  1. Conversation history - the last few messages per channel, so the bot
     can follow a chat. Old rows are pruned automatically.
  2. Facts - short things a user explicitly asked the bot to remember
     ("!remember I'm learning Rust"). These are per user and carry across
     every channel and server.

All public methods are async. sqlite3 is blocking, so each call runs in a
worker thread to keep the Discord event loop responsive.
'''

import asyncio
import sqlite3
import time

MAX_FACTS_PER_USER = 25
MAX_FACT_LENGTH = 200
MAX_STORED_PER_CHANNEL = 200  # rows kept in the DB per channel


class Memory:
    def __init__(self, path: str = "memory.db"):
        self.path = path
        self._lock = asyncio.Lock()
        self._init_db()

    # ---------- internals ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id  INTEGER NOT NULL,
                    role        TEXT    NOT NULL,      -- 'user' or 'model'
                    author      TEXT,                  -- display name for users
                    content     TEXT    NOT NULL,
                    ts          REAL    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_channel
                    ON messages (channel_id, id);

                CREATE TABLE IF NOT EXISTS facts (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id  INTEGER NOT NULL,
                    fact     TEXT    NOT NULL,
                    ts       REAL    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_facts_user ON facts (user_id);
                """
            )

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    # ---------- conversation history ----------

    def _add_message(self, channel_id, role, author, content):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (channel_id, role, author, content, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (channel_id, role, author, content, time.time()),
            )
            # prune old rows for this channel
            conn.execute(
                "DELETE FROM messages WHERE channel_id = ? AND id NOT IN ("
                "  SELECT id FROM messages WHERE channel_id = ? "
                "  ORDER BY id DESC LIMIT ?)",
                (channel_id, channel_id, MAX_STORED_PER_CHANNEL),
            )

    async def add_message(self, channel_id: int, role: str, content: str,
                          author: str | None = None) -> None:
        await self._run(self._add_message, channel_id, role, author, content)

    def _get_history(self, channel_id, limit):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, author, content FROM messages "
                "WHERE channel_id = ? ORDER BY id DESC LIMIT ?",
                (channel_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    async def get_history(self, channel_id: int, limit: int = 20) -> list[dict]:
        return await self._run(self._get_history, channel_id, limit)

    def _clear_history(self, channel_id):
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM messages WHERE channel_id = ?", (channel_id,)
            )
            return cur.rowcount

    async def clear_history(self, channel_id: int) -> int:
        return await self._run(self._clear_history, channel_id)

    # ---------- long-term facts ----------

    def _add_fact(self, user_id, fact):
        with self._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM facts WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            if count >= MAX_FACTS_PER_USER:
                return "full"
            dupe = conn.execute(
                "SELECT 1 FROM facts WHERE user_id = ? AND lower(fact) = lower(?)",
                (user_id, fact),
            ).fetchone()
            if dupe:
                return "duplicate"
            conn.execute(
                "INSERT INTO facts (user_id, fact, ts) VALUES (?, ?, ?)",
                (user_id, fact, time.time()),
            )
            return "ok"

    async def add_fact(self, user_id: int, fact: str) -> str:
        """Returns 'ok', 'duplicate' or 'full'."""
        fact = " ".join(fact.split())[:MAX_FACT_LENGTH]
        return await self._run(self._add_fact, user_id, fact)

    def _get_facts(self, user_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT fact FROM facts WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        return [r["fact"] for r in rows]

    async def get_facts(self, user_id: int) -> list[str]:
        return await self._run(self._get_facts, user_id)

    def _forget_fact(self, user_id, number):
        # number is 1-based, matching the order shown by !memory
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM facts WHERE user_id = ? ORDER BY id", (user_id,)
            ).fetchall()
            if not 1 <= number <= len(rows):
                return False
            conn.execute("DELETE FROM facts WHERE id = ?", (rows[number - 1]["id"],))
            return True

    async def forget_fact(self, user_id: int, number: int) -> bool:
        return await self._run(self._forget_fact, user_id, number)

    def _forget_all(self, user_id):
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM facts WHERE user_id = ?", (user_id,))
            return cur.rowcount

    async def forget_all(self, user_id: int) -> int:
        return await self._run(self._forget_all, user_id)
