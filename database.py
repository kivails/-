import sqlite3
import threading
from datetime import datetime, timedelta

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
            reputation INTEGER DEFAULT 0,
            crystals REAL DEFAULT 0,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            messages INTEGER DEFAULT 0,
            marriage_level INTEGER DEFAULT 1,
            marriage_xp INTEGER DEFAULT 0,
            last_message TEXT,
            is_frozen INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            welcome TEXT,
            rules TEXT,
            antiflood INTEGER DEFAULT 0,
            last_seen TEXT
        );
        CREATE TABLE IF NOT EXISTS chat_stats (
            chat_id INTEGER,
            user_id INTEGER,
            messages INTEGER DEFAULT 0,
            last_message TEXT,
            PRIMARY KEY (chat_id, user_id)
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
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER UNIQUE,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS custom_rp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            command TEXT UNIQUE,
            emoji TEXT,
            action TEXT
        );
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            created_at TEXT
        );
        """)
        conn.commit()


_KEYS = [
    "user_id", "username", "first_name", "balance", "warns", "married_to",
    "bio", "title", "inventory", "stats_played", "stats_won",
    "daily_streak", "last_daily", "quest_progress", "registered",
    "is_banned", "achievements", "last_work", "last_rob", "last_fish",
    "clan_id", "reputation", "crystals", "referred_by", "referral_count",
    "messages", "marriage_level", "marriage_xp", "last_message", "is_frozen"
]


def _row(row):
    if not row:
        return None
    return dict(zip(_KEYS, row))


def get_user(user_id, username=None, first_name=None):
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
        return _row(row)


def update_user(user_id, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [user_id]
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET {fields} WHERE user_id=?", values)
        conn.commit()


def get_balance(user_id):
    u = get_user(user_id)
    return u["balance"] if u else 0


def add_balance(user_id, amount):
    get_user(user_id)
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        conn.commit()


def add_crystals(user_id, amount):
    get_user(user_id)
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET crystals = crystals + ? WHERE user_id=?", (amount, user_id))
        conn.commit()


def top_users(limit=10):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""SELECT user_id, username, first_name, balance
                       FROM users ORDER BY balance DESC LIMIT ?""", (limit,))
        return cur.fetchall()


def top_crystals(limit=3):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""SELECT user_id, username, first_name, crystals
                       FROM users ORDER BY crystals DESC LIMIT ?"""), (limitimport sqlite3)
import threading
from datetime import datetime, timedelta

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
            nickname TEXT,
            balance INTEGER DEFAULT 100,
            crystals REAL DEFAULT 0,
            donat INTEGER DEFAULT 0,
            warns INTEGER DEFAULT 0,
            married_to INTEGER,
            marriage_level INTEGER DEFAULT 1,
            marriage_xp INTEGER DEFAULT 0,
            marriage_last_task TEXT,
            marriage_task_key TEXT,
            bio TEXT,
            title TEXT,
            inventory TEXT DEFAULT '',
            gifts TEXT DEFAULT '',
            pinned_achievement TEXT,
            stats_played INTEGER DEFAULT 0,
            stats_won INTEGER DEFAULT 0,
            messages INTEGER DEFAULT 0,
            last_message TEXT,
            daily_streak INTEGER DEFAULT 0,
            last_daily TEXT,
            work_xp INTEGER DEFAULT 0,
            work_level INTEGER DEFAULT 1,
            last_work TEXT,
            last_rob TEXT,
            last_fish TEXT,
            clan_id INTEGER,
            reputation INTEGER DEFAULT 0,
            quest_progress TEXT DEFAULT '{}',
            achievements TEXT DEFAULT '',
            is_banned INTEGER DEFAULT 0,
            is_frozen INTEGER DEFAULT 0,
            is_vip INTEGER DEFAULT 0,
            has_crown INTEGER DEFAULT 0,
            registered TEXT,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            biz_last_collect TEXT
        );
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            welcome TEXT,
            rules TEXT
        );
        CREATE TABLE IF NOT EXISTS chat_stats (
            chat_id INTEGER,
            user_id INTEGER,
            messages INTEGER DEFAULT 0,
            last_message TEXT,
            PRIMARY KEY (chat_id, user_id)
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
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER UNIQUE,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS custom_rp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            command TEXT UNIQUE,
            emoji TEXT,
            action TEXT
        );
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            biz_key TEXT,
            purchased_at TEXT,
            last_collect TEXT
        );
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            rate REAL,
            end_at TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS promos (
            code TEXT PRIMARY KEY,
            reward INTEGER,
            activations INTEGER,
            max_activations INTEGER,
            expires_at TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS promo_uses (
            code TEXT,
            user_id INTEGER,
            used_at TEXT,
            PRIMARY KEY (code, user_id)
        );
        CREATE TABLE IF NOT EXISTS sponsors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            title TEXT,
            url TEXT,
            reward INTEGER,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sponsor_done (
            sponsor_id INTEGER,
            user_id INTEGER,
            done_at TEXT,
            PRIMARY KEY (sponsor_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS custom_achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ach_key TEXT UNIQUE,
            name TEXT,
            description TEXT,
            emoji TEXT,
            created_by INTEGER,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS limited_gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gift_key TEXT,
            name TEXT,
            price INTEGER,
            available_from TEXT,
            available_to TEXT
        );
        """)
        conn.commit()


_KEYS = [
    "user_id", "username", "first_name", "nickname", "balance", "crystals", "donat",
    "warns", "married_to", "marriage_level", "marriage_xp", "marriage_last_task",
    "marriage_task_key", "bio", "title", "inventory", "gifts", "pinned_achievement",
    "stats_played", "stats_won", "messages", "last_message", "daily_streak",
    "last_daily", "work_xp", "work_level", "last_work", "last_rob", "last_fish",
    "clan_id", "reputation", "quest_progress", "achievements", "is_banned",
    "is_frozen", "is_vip", "has_crown", "registered", "referred_by",
    "referral_count", "biz_last_collect"
]


def _row(row):
    if not row:
        return None
    return dict(zip(_KEYS, row))


def get_user(user_id, username=None, first_name=None):
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
        return _row(row)


def update_user(user_id, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [user_id]
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET {fields} WHERE user_id=?", values)
        conn.commit()


def get_balance(user_id):
    u = get_user(user_id)
    return u["balance"] if u else 0


def add_balance(user_id, amount):
    get_user(user_id)
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        conn.commit()


def add_crystals(user_id, amount):
    get_user(user_id)
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET crystals = crystals + ? WHERE user_id=?", (amount, user_id))
        conn.commit()


def add_donat(user_id, amount):
    get_user(user_id)
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET donat = donat + ? WHERE user_id=?", (amount, user_id))
        conn.commit()


def top_users(limit=10):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, nickname, first_name, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,))
        return cur.fetchall()


def top_crystals(limit=3):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, nickname, first_name, crystals FROM users ORDER BY crystals DESC LIMIT ?", (limit,))
        return cur.fetchall()


def top_donat(limit=10):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, nickname, first_name, donat FROM users ORDER BY donat DESC LIMIT ?", (limit,))
        return cur.fetchall()


def top_wins(limit=3):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, nickname, first_name, stats_won FROM users ORDER BY stats_won DESC LIMIT ?", (limit,))
        return cur.fetchall()


def top_messages(chat_id=None, limit=10, hours=None):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        if chat_id and hours:
            from_date = (datetime.now() - timedelta(hours=hours)).isoformat()
            cur.execute("""SELECT cs.user_id, u.username, u.nickname, u.first_name, cs.messages
                           FROM chat_stats cs LEFT JOIN users u ON cs.user_id=u.user_id
                           WHERE cs.chat_id=? AND cs.last_message>=?
                           ORDER BY cs.messages DESC LIMIT ?""", (chat_id, from_date, limit))
        elif chat_id:
            cur.execute("""SELECT cs.user_id, u.username, u.nickname, u.first_name, cs.messages
                           FROM chat_stats cs LEFT JOIN users u ON cs.user_id=u.user_id
                           WHERE cs.chat_id=? ORDER BY cs.messages DESC LIMIT ?""", (chat_id, limit))
        else:
            cur.execute("SELECT user_id, username, nickname, first_name, messages FROM users ORDER BY messages DESC LIMIT ?", (limit,))
        return cur.fetchall()


def add_message(user_id, chat_id):
    now = datetime.now().isoformat()
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET messages = messages + 1, last_message=? WHERE user_id=?", (now, user_id))
        cur.execute("""INSERT INTO chat_stats(chat_id, user_id, messages, last_message)
                       VALUES(?, ?, 1, ?)
                       ON CONFLICT(chat_id, user_id) DO UPDATE SET
                       messages = messages + 1, last_message = ?""", (chat_id, user_id, now, now))
        conn.commit()


def get_chat(chat_id):
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


def update_chat(chat_id, **kwargs):
    get_chat(chat_id)
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [chat_id]
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE chats SET {fields} WHERE chat_id=?", values)
        conn.commit()


def get_all_chats():
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT chat_id FROM chats")
        return [r[0] for r in cur.fetchall()]


# ===== БРАК =====
def create_marriage_proposal(proposer_id, target_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO marriages_proposals(proposer_id, target_id, created_at) VALUES(?, ?, ?)",
                    (proposer_id, target_id, datetime.now().isoformat()))
        conn.commit()


def get_marriage_proposal(proposer_id, target_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM marriages_proposals WHERE proposer_id=? AND target_id=?", (proposer_id, target_id))
        return cur.fetchone()


def delete_marriage_proposal(proposer_id, target_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM marriages_proposals WHERE proposer_id=? AND target_id=?", (proposer_id, target_id))
        conn.commit()


def add_marriage_xp(user_id, amount):
    u = get_user(user_id)
    new_xp = (u["marriage_xp"] or 0) + amount
    lvl = u["marriage_level"] or 1
    while new_xp >= lvl * 100 and lvl < 10:
        new_xp -= lvl * 100
        lvl += 1
    update_user(user_id, marriage_xp=new_xp, marriage_level=lvl)
    return lvl


# ===== КЛАНЫ =====
def create_clan(name, owner_id, description=""):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO clans(name, owner_id, description, created_at) VALUES(?, ?, ?, ?)",
                        (name, owner_id, description, datetime.now().isoformat()))
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def get_clan_by_name(name):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM clans WHERE LOWER(name)=LOWER(?)", (name,))
        return cur.fetchone()


def get_clan(clan_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM clans WHERE clan_id=?", (clan_id,))
        return cur.fetchone()


def get_all_clans(limit=20):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM clans ORDER BY balance DESC LIMIT ?", (limit,))
        return cur.fetchall()


def get_clan_members(clan_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, nickname, first_name, balance FROM users WHERE clan_id=?", (clan_id,))
        return cur.fetchall()


def add_clan_balance(clan_id, amount):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE clans SET balance = balance + ? WHERE clan_id=?", (amount, clan_id))
        conn.commit()


def delete_clan(clan_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET clan_id=NULL WHERE clan_id=?", (clan_id,))
        cur.execute("DELETE FROM clans WHERE clan_id=?", (clan_id,))
        conn.commit()


# ===== АЧИВКИ =====
def get_achievements(user_id):
    u = get_user(user_id)
    return (u["achievements"] or "").split(",") if u and u["achievements"] else []


def add_achievement(user_id, ach_id):
    cur = get_achievements(user_id)
    if ach_id in cur:
        return False
    cur.append(ach_id)
    update_user(user_id, achievements=",".join(cur))
    return True


# ===== РЕФЕРАЛЫ =====
def add_referral(referrer_id, referred_id):
    if referrer_id == referred_id:
        return False
    get_user(referrer_id)
    get_user(referred_id)
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM referrals WHERE referred_id=?", (referred_id,))
        if cur.fetchone():
            return False
        cur.execute("INSERT INTO referrals(referrer_id, referred_id, created_at) VALUES(?, ?, ?)",
                    (referrer_id, referred_id, datetime.now().isoformat()))
        cur.execute("UPDATE users SET crystals = crystals + 0.5, referral_count = referral_count + 1 WHERE user_id=?", (referrer_id,))
        cur.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referrer_id, referred_id))
        conn.commit()
    return True


def get_crystals(user_id):
    u = get_user(user_id)
    return (u["crystals"] or 0.0) if u else 0.0


def get_donat(user_id):
    u = get_user(user_id)
    return (u["donat"] or 0) if u else 0


# ===== СВОИ RP =====
def add_custom_rp(owner_id, command, emoji, action):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO custom_rp(owner_id, command, emoji, action) VALUES(?, ?, ?, ?)",
                        (owner_id, command.lower(), emoji, action))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def get_custom_rp(command):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM custom_rp WHERE command=?", (command.lower(),))
        return cur.fetchone()


def get_my_custom_rp(owner_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT command, emoji, action FROM custom_rp WHERE owner_id=?", (owner_id,))
        return cur.fetchall()


# ===== ОБЪЯВЛЕНИЯ =====
def add_announcement(user_id, text):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO announcements(user_id, text, created_at) VALUES(?, ?, ?)",
                    (user_id, text, datetime.now().isoformat()))
        conn.commit()


def get_last_announcements(limit=5):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, text, created_at FROM announcements ORDER BY id DESC LIMIT ?", (limit,))
        return cur.fetchall()


# ===== БИЗНЕСЫ =====
def add_business(user_id, biz_key):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO businesses(user_id, biz_key, purchased_at, last_collect) VALUES(?, ?, ?, ?)",
                    (user_id, biz_key, datetime.now().isoformat(), datetime.now().isoformat()))
        conn.commit()


def get_user_businesses(user_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, biz_key, last_collect FROM businesses WHERE user_id=?", (user_id,))
        return cur.fetchall()


def update_business_last_collect(biz_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE businesses SET last_collect=? WHERE id=?", (datetime.now().isoformat(), biz_id))
        conn.commit()


# ===== ВКЛАДЫ =====
def add_deposit(user_id, amount, rate, end_at):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO deposits(user_id, amount, rate, end_at, created_at) VALUES(?, ?, ?, ?, ?)",
                    (user_id, amount, rate, end_at, datetime.now().isoformat()))
        conn.commit()


def get_active_deposits(user_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, amount, rate, end_at FROM deposits WHERE user_id=?", (user_id,))
        return cur.fetchall()


def remove_deposit(dep_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM deposits WHERE id=?", (dep_id,))
        conn.commit()


# ===== ПРОМОКОДЫ =====
def create_promo(code, reward, max_activations, expires_hours=24):
    expires_at = (datetime.now() + timedelta(hours=expires_hours)).isoformat()
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO promos(code, reward, activations, max_activations, expires_at, created_at) VALUES(?, ?, 0, ?, ?, ?)",
                        (code.upper(), reward, max_activations, expires_at, datetime.now().isoformat()))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def use_promo(code, user_id):
    code = code.upper()
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT reward, activations, max_activations, expires_at FROM promos WHERE code=?", (code,))
        row = cur.fetchone()
        if not row:
            return None, "Промокод не найден"
        reward, acts, max_acts, expires = row
        if datetime.fromisoformat(expires) < datetime.now():
            return None, "Промокод истёк"
        if acts >= max_acts:
            return None, "Лимит активаций исчерпан"
        cur.execute("SELECT 1 FROM promo_uses WHERE code=? AND user_id=?", (code, user_id))
        if cur.fetchone():
            return None, "Ты уже активировал этот промокод"
        cur.execute("INSERT INTO promo_uses(code, user_id, used_at) VALUES(?, ?, ?)",
                    (code, user_id, datetime.now().isoformat()))
        cur.execute("UPDATE promos SET activations = activations + 1 WHERE code=?", (code,))
        conn.commit()
        return reward, "OK"


# ===== СПОНСОРЫ =====
def add_sponsor(chat_id, title, url, reward):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO sponsors(chat_id, title, url, reward, created_at) VALUES(?, ?, ?, ?, ?)",
                    (chat_id, title, url, reward, datetime.now().isoformat()))
        conn.commit()


def get_all_sponsors():
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, chat_id, title, url, reward FROM sponsors")
        return cur.fetchall()


def mark_sponsor_done(sponsor_id, user_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO sponsor_done(sponsor_id, user_id, done_at) VALUES(?, ?, ?)",
                        (sponsor_id, user_id, datetime.now().isoformat()))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def is_sponsor_done(sponsor_id, user_id):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM sponsor_done WHERE sponsor_id=? AND user_id=?", (sponsor_id, user_id))
        return bool(cur.fetchone())


# ===== КАСТОМНЫЕ АЧИВКИ =====
def add_custom_achievement(ach_key, name, description, emoji, created_by):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO custom_achievements(ach_key, name, description, emoji, created_by, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                        (ach_key, name, description, emoji, created_by, datetime.now().isoformat()))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def get_custom_achievement(ach_key):
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM custom_achievements WHERE ach_key=?", (ach_key,))
        return cur.fetchone()


# ===== ЛИМИТИРОВАННЫЕ ПОДАРКИ =====
def add_limited_gift(gift_key, name, price, days=5):
    available_from = datetime.now().isoformat()
    available_to = (datetime.now() + timedelta(days=days)).isoformat()
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO limited_gifts(gift_key, name, price, available_from, available_to) VALUES(?, ?, ?, ?, ?)",
                    (gift_key, name, price, available_from, available_to))
        conn.commit()


def get_active_limited_gifts():
    now = datetime.now().isoformat()
    with lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, gift_key, name, price FROM limited_gifts WHERE available_from<=? AND available_to>=?", (now, now))
        return cur.fetchall()
