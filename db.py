"""Ma'lumotlar bazasi (SQLite, aiosqlite)."""
import os
import time
from typing import Any, Optional

import aiosqlite

from config import DB_PATH

_db: Optional[aiosqlite.Connection] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY,
    name TEXT,
    username TEXT,
    joined INTEGER,
    last_seen INTEGER,
    banned INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS animes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE,
    name TEXT,
    descr TEXT,
    poster TEXT,
    created INTEGER,
    views INTEGER DEFAULT 0,
    post_msg_id INTEGER
);
CREATE TABLE IF NOT EXISTS episodes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anime_id INTEGER,
    num INTEGER,
    kind TEXT,
    file_id TEXT,
    storage_msg_id INTEGER,
    UNIQUE(anime_id, num)
);
CREATE TABLE IF NOT EXISTS favs(
    user_id INTEGER,
    anime_id INTEGER,
    PRIMARY KEY(user_id, anime_id)
);
CREATE TABLE IF NOT EXISTS ratings(
    user_id INTEGER,
    anime_id INTEGER,
    stars INTEGER,
    PRIMARY KEY(user_id, anime_id)
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS channels(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT,
    title TEXT,
    link TEXT
);
CREATE TABLE IF NOT EXISTS admins(
    user_id INTEGER PRIMARY KEY
);
"""


async def init() -> None:
    global _db
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.commit()


async def close() -> None:
    if _db is not None:
        await _db.close()


async def one(sql: str, args: tuple = ()) -> Optional[aiosqlite.Row]:
    cur = await _db.execute(sql, args)
    row = await cur.fetchone()
    await cur.close()
    return row


async def all_(sql: str, args: tuple = ()) -> list:
    cur = await _db.execute(sql, args)
    rows = await cur.fetchall()
    await cur.close()
    return rows


async def run(sql: str, args: tuple = ()) -> int:
    cur = await _db.execute(sql, args)
    await _db.commit()
    last = cur.lastrowid
    await cur.close()
    return last


async def scalar(sql: str, args: tuple = (), default: Any = 0) -> Any:
    row = await one(sql, args)
    if row is None or row[0] is None:
        return default
    return row[0]


# ------------------------------------------------------------------ users
async def touch_user(u) -> None:
    now = int(time.time())
    name = (u.full_name or "")[:100]
    await run(
        "INSERT INTO users(id,name,username,joined,last_seen,active) VALUES(?,?,?,?,?,1) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, username=excluded.username, "
        "last_seen=excluded.last_seen, active=1",
        (u.id, name, u.username or "", now, now),
    )


async def is_banned(uid: int) -> bool:
    return bool(await scalar("SELECT banned FROM users WHERE id=?", (uid,)))


async def set_banned(uid: int, value: bool) -> bool:
    """Foydalanuvchi bazada bo'lsa True qaytaradi."""
    row = await one("SELECT id FROM users WHERE id=?", (uid,))
    if row is None:
        await run("INSERT INTO users(id,name,username,joined,last_seen,banned) VALUES(?,?,?,?,?,?)",
                  (uid, "", "", int(time.time()), int(time.time()), 1 if value else 0))
        return False
    await run("UPDATE users SET banned=? WHERE id=?", (1 if value else 0, uid))
    return True


async def mark_inactive(uid: int) -> None:
    await run("UPDATE users SET active=0 WHERE id=?", (uid,))


async def broadcast_ids() -> list:
    rows = await all_("SELECT id FROM users WHERE banned=0 AND active=1")
    return [r[0] for r in rows]


# ----------------------------------------------------------------- animes
async def add_anime(code: str, name: str, descr: str, poster: str) -> int:
    return await run(
        "INSERT INTO animes(code,name,descr,poster,created) VALUES(?,?,?,?,?)",
        (code, name, descr, poster, int(time.time())),
    )


async def get_anime(aid: int):
    return await one("SELECT * FROM animes WHERE id=?", (aid,))


async def get_anime_by_code(code: str):
    return await one("SELECT * FROM animes WHERE lower(code)=lower(?)", (code,))


async def code_exists(code: str) -> bool:
    return await get_anime_by_code(code) is not None


async def update_anime(aid: int, field: str, value: Any) -> None:
    if field not in ("code", "name", "descr", "poster", "post_msg_id"):
        raise ValueError("bad field")
    await run(f"UPDATE animes SET {field}=? WHERE id=?", (value, aid))


async def delete_anime(aid: int) -> None:
    await run("DELETE FROM episodes WHERE anime_id=?", (aid,))
    await run("DELETE FROM favs WHERE anime_id=?", (aid,))
    await run("DELETE FROM ratings WHERE anime_id=?", (aid,))
    await run("DELETE FROM animes WHERE id=?", (aid,))


async def add_view(aid: int) -> None:
    await run("UPDATE animes SET views=views+1 WHERE id=?", (aid,))


_ORDERS = {
    "new": "created DESC, id DESC",
    "top": "views DESC, id DESC",
    "az": "name COLLATE NOCASE ASC",
}


async def list_animes(order: str = "new", limit: int = 10, offset: int = 0) -> list:
    o = _ORDERS.get(order, _ORDERS["new"])
    return await all_(
        "SELECT a.*, (SELECT COUNT(*) FROM episodes e WHERE e.anime_id=a.id) AS eps, "
        "(SELECT ROUND(AVG(stars),1) FROM ratings r WHERE r.anime_id=a.id) AS rating "
        f"FROM animes a ORDER BY {o} LIMIT ? OFFSET ?",
        (limit, offset),
    )


async def count_animes() -> int:
    return await scalar("SELECT COUNT(*) FROM animes")


async def search_animes(q: str, limit: int = 20) -> list:
    like = f"%{q.strip()}%"
    return await all_(
        "SELECT a.*, (SELECT COUNT(*) FROM episodes e WHERE e.anime_id=a.id) AS eps, "
        "(SELECT ROUND(AVG(stars),1) FROM ratings r WHERE r.anime_id=a.id) AS rating "
        "FROM animes a WHERE name LIKE ? OR code LIKE ? ORDER BY views DESC, id DESC LIMIT ?",
        (like, like, limit),
    )


async def fav_animes(uid: int, limit: int = 10, offset: int = 0) -> list:
    return await all_(
        "SELECT a.*, (SELECT COUNT(*) FROM episodes e WHERE e.anime_id=a.id) AS eps, "
        "(SELECT ROUND(AVG(stars),1) FROM ratings r WHERE r.anime_id=a.id) AS rating "
        "FROM animes a JOIN favs f ON f.anime_id=a.id WHERE f.user_id=? "
        "ORDER BY a.id DESC LIMIT ? OFFSET ?",
        (uid, limit, offset),
    )


async def count_favs(uid: int) -> int:
    return await scalar("SELECT COUNT(*) FROM favs WHERE user_id=?", (uid,))


# --------------------------------------------------------------- episodes
async def episodes_of(aid: int) -> list:
    return await all_("SELECT * FROM episodes WHERE anime_id=? ORDER BY num ASC", (aid,))


async def get_episode(aid: int, num: int):
    return await one("SELECT * FROM episodes WHERE anime_id=? AND num=?", (aid, num))


async def max_ep_num(aid: int) -> int:
    return await scalar("SELECT MAX(num) FROM episodes WHERE anime_id=?", (aid,))


async def add_episode(aid: int, num: int, kind: str, file_id: str, storage_msg_id: Optional[int]) -> None:
    await run(
        "INSERT OR REPLACE INTO episodes(anime_id,num,kind,file_id,storage_msg_id) VALUES(?,?,?,?,?)",
        (aid, num, kind, file_id, storage_msg_id),
    )


async def delete_episode(aid: int, num: int) -> None:
    await run("DELETE FROM episodes WHERE anime_id=? AND num=?", (aid, num))


# ------------------------------------------------------- favorites/ratings
async def is_fav(uid: int, aid: int) -> bool:
    return await one("SELECT 1 FROM favs WHERE user_id=? AND anime_id=?", (uid, aid)) is not None


async def toggle_fav(uid: int, aid: int) -> bool:
    """Yangi holatni qaytaradi: True = rejada."""
    if await is_fav(uid, aid):
        await run("DELETE FROM favs WHERE user_id=? AND anime_id=?", (uid, aid))
        return False
    await run("INSERT OR IGNORE INTO favs(user_id,anime_id) VALUES(?,?)", (uid, aid))
    return True


async def set_rating(uid: int, aid: int, stars: int) -> None:
    await run(
        "INSERT INTO ratings(user_id,anime_id,stars) VALUES(?,?,?) "
        "ON CONFLICT(user_id,anime_id) DO UPDATE SET stars=excluded.stars",
        (uid, aid, stars),
    )


async def rating_info(aid: int) -> tuple:
    row = await one("SELECT AVG(stars), COUNT(*) FROM ratings WHERE anime_id=?", (aid,))
    avg = row[0] or 0
    return round(avg, 1), row[1] or 0


async def user_rating(uid: int, aid: int) -> int:
    return await scalar("SELECT stars FROM ratings WHERE user_id=? AND anime_id=?", (uid, aid))


# --------------------------------------------------------------- settings
async def get_setting(key: str, default: str = "") -> str:
    row = await one("SELECT value FROM settings WHERE key=?", (key,))
    return row[0] if row else default


async def set_setting(key: str, value: str) -> None:
    await run(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


async def del_setting(key: str) -> None:
    await run("DELETE FROM settings WHERE key=?", (key,))


# --------------------------------------------------------------- channels
async def channels() -> list:
    return await all_("SELECT * FROM channels ORDER BY id")


async def add_channel(chat_id: str, title: str, link: str) -> None:
    await run("DELETE FROM channels WHERE chat_id=?", (chat_id,))
    await run("INSERT INTO channels(chat_id,title,link) VALUES(?,?,?)", (chat_id, title, link))


async def del_channel(cid: int) -> None:
    await run("DELETE FROM channels WHERE id=?", (cid,))


# ----------------------------------------------------------------- admins
async def admin_ids() -> list:
    rows = await all_("SELECT user_id FROM admins")
    return [r[0] for r in rows]


async def add_admin(uid: int) -> None:
    await run("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (uid,))


async def del_admin(uid: int) -> None:
    await run("DELETE FROM admins WHERE user_id=?", (uid,))


# ------------------------------------------------------------------ stats
async def stats() -> dict:
    now = int(time.time())
    day = now - 86400
    week = now - 7 * 86400
    return {
        "users": await scalar("SELECT COUNT(*) FROM users"),
        "today": await scalar("SELECT COUNT(*) FROM users WHERE joined>=?", (day,)),
        "week": await scalar("SELECT COUNT(*) FROM users WHERE joined>=?", (week,)),
        "active_today": await scalar("SELECT COUNT(*) FROM users WHERE last_seen>=?", (day,)),
        "blocked": await scalar("SELECT COUNT(*) FROM users WHERE active=0"),
        "banned": await scalar("SELECT COUNT(*) FROM users WHERE banned=1"),
        "animes": await scalar("SELECT COUNT(*) FROM animes"),
        "episodes": await scalar("SELECT COUNT(*) FROM episodes"),
        "views": await scalar("SELECT SUM(views) FROM animes"),
        "favs": await scalar("SELECT COUNT(*) FROM favs"),
        "ratings": await scalar("SELECT COUNT(*) FROM ratings"),
        "top": await all_("SELECT name, views FROM animes ORDER BY views DESC, id DESC LIMIT 5"),
    }
