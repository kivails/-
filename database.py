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
            balance INTEGER DEFAULT 0,
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
            registered TEXT
        );
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            welcome TEXT,
            rules TEXT,
            antiflood INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            name TEXT,
            content TEXT,
            UNIQUE(chat_id, name)
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            text TEXT,
            remind_at TEXT
        );
        """)
        conn.commit()

def get_user(user_id: int):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO users(user_id, balance, registered) VALUES(?, 0, ?)",
                (user_id, datetime.now().isoformat())
            )
            conn.commit()
            cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = cur.fetchone()
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

def add_balance(user_id: int, amount: int):
    get_user(user_id)
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        conn.commit()

def top_users(limit=10):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, first_name, username, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,))
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
