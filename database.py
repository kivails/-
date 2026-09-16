import sqlite3
import threading
from datetime import datetime

DB_PATH = "bot.db"
lock = threading.Lock()

def init_db():
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 100,
            warns INTEGER DEFAULT 0,
            married_to INTEGER,
            bio TEXT,
            title TEXT,
            inventory TEXT DEFAULT '',
            stats_played INTEGER DEFAULT 0,
            stats_won INTEGER DEFAULT 0,
            daily_streak INTEGER DEFAULT 0,
            last_daily TEXT,
            quest_progress TEXT DEFAULT '{}',
            registered TEXT,
            is_banned INTEGER DEFAULT 0,
            achievements TEXT DEFAULT '',
            last_work TEXT,
            last_rob TEXT,
            last_fish TEXT,
            clan_id INTEGER,
            reputation INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            welcome TEXT,
            rules TEXT,
            antiflood INTEGER DEFAULT 0,
            last_seen TEXT
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            name TEXT,
            content TEXT,
            UNIQUE(chat_id, name)
        );
        CREATE TABLE IF NOT EXISTS marriages_proposals (
            proposer_id INTEGER,
            target_id INTEGER,
            created_at TEXT,
            PRIMARY KEY (proposer_id, target_id)
        );
        CREATE TABLE IF NOT EXISTS clans (
            clan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            owner_id INTEGER,
            description TEXT,
            created_at TEXT,
            balance INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS polls (
            poll_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            question TEXT,
            options TEXT,
            votes TEXT DEFAULT '{}',
            creator_id INTEGER,
            created_at TEXT,
            is_closed INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            reason TEXT,
            created_at TEXT
        );
        """)
        conn.commit()

def get_user(user_id: int, username: str = None, first_name: str = None):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO users(user_id, username, first_name, balance, registered) VALUES(?, ?, ?, 100, ?)",
                (user_id, username, first_name, datetime.now().isoformat())
            )
            conn.commit()
            cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = cur.fetchone()
        else:
            if username and row[1] != username:
                cur.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
            if first_name and row[2] != first_name:
                cur.execute("UPDATE users SET first_name=? WHERE user_id=?", (first_name, user_id))
            conn.commit()
        return row

def update_user(user_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [user_id]
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET {fields} WHERE user_id=?", values)
        conn.commit()

def get_balance(user_id: int) -> int:
    return get_user(user_id)[3]

def add_balance(user_id: int, amount: int, reason: str = "manual"):
    get_user(user_id)
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        cur.execute(
            "INSERT INTO transactions(user_id, amount, reason, created_at) VALUES(?, ?, ?, ?)",
            (user_id, amount, reason, datetime.now().isoformat())
        )
        conn.commit()

def top_users(limit=10):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT user_id, username, first_name, balance
            FROM users
            ORDER BY balance DESC
            LIMIT ?
        """, (limit,))
        return cur.fetchall()

def get_chat(chat_id: int):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,))
        row = cur.fetchone()
        if not row:
            cur.execute("INSERT INTO chats(chat_id) VALUES(?)", (chat_id,))
            conn.commit()
            cur.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,))
            row = cur.fetchone()
        return row

def update_chat(chat_id: int, **kwargs):
    get_chat(chat_id)
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [chat_id]
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE chats SET {fields} WHERE chat_id=?", values)
        conn.commit()

# ===== БРАК =====
def create_marriage_proposal(proposer_id: int, target_id: int):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO marriages_proposals(proposer_id, target_id, created_at) VALUES(?, ?, ?)",
            (proposer_id, target_id, datetime.now().isoformat())
        )
        conn.commit()

def get_marriage_proposal(proposer_id: int, target_id: int):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM marriages_proposals WHERE proposer_id=? AND target_id=?",
            (proposer_id, target_id)
        )
        return cur.fetchone()

def delete_marriage_proposal(proposer_id: int, target_id: int):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM marriages_proposals WHERE proposer_id=? AND target_id=?",
            (proposer_id, target_id)
        )
        conn.commit()

# ===== КЛАНЫ =====
def create_clan(name: str, owner_id: int, description: str = ""):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO clans(name, owner_id, description, created_at) VALUES(?, ?, ?, ?)",
                (name, owner_id, description, datetime.now().isoformat())
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

def get_clan_by_name(name: str):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM clans WHERE name=?", (name,))
        return cur.fetchone()

def get_clan(clan_id: int):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM clans WHERE clan_id=?", (clan_id,))
        return cur.fetchone()

def get_all_clans(limit=20):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM clans ORDER BY balance DESC LIMIT ?", (limit,))
        return cur.fetchall()

def get_clan_members(clan_id: int):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id, username, first_name, balance FROM users WHERE clan_id=?",
            (clan_id,)
        )
        return cur.fetchall()

def add_clan_balance(clan_id: int, amount: int):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE clans SET balance = balance + ? WHERE clan_id=?", (amount, clan_id))
        conn.commit()

def delete_clan(clan_id: int):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET clan_id=NULL WHERE clan_id=?", (clan_id,))
        cur.execute("DELETE FROM clans WHERE clan_id=?", (clan_id,))
        conn.commit()

# ===== ОПРОСЫ =====
def create_poll(chat_id: int, question: str, options: list, creator_id: int):
    import json
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO polls(chat_id, question, options, votes, creator_id, created_at) VALUES(?, ?, ?, ?, ?, ?)",
            (chat_id, question, json.dumps(options), '{}', creator_id, datetime.now().isoformat())
        )
        conn.commit()
        return cur.lastrowid

def get_poll(poll_id: int):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM polls WHERE poll_id=?", (poll_id,))
        return cur.fetchone()

def update_poll_votes(poll_id: int, votes_json: str):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE polls SET votes=? WHERE poll_id=?", (votes_json, poll_id))
        conn.commit()

def close_poll(poll_id: int):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE polls SET is_closed=1 WHERE poll_id=?", (poll_id,))
        conn.commit()

# ===== АЧИВКИ =====
def get_achievements(user_id: int):
    data = get_user(user_id)
    return data[16].split(",") if data[16] else []

def add_achievement(user_id: int, ach_id: str) -> bool:
    """Вернёт True, если ачивка была добавлена впервые"""
    cur = get_achievements(user_id)
    if ach_id in cur:
        return False
    cur.append(ach_id)
    update_user(user_id, achievements=",".join(cur))
    return True
