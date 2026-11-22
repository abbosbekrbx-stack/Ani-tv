"""Sayt serveri: bot bilan bir jarayonda ishlaydi (Railway'da bitta servis)."""
import hashlib
import io
import logging
import os
from urllib.parse import quote

from aiohttp import web

import db
from config import BOT_USERNAME, BRAND, PORT, PUBLIC_CHANNEL

log = logging.getLogger("web")
BASE = os.path.dirname(os.path.abspath(__file__))
_poster_cache: dict = {}


def _short(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _poster_url(a) -> str:
    v = hashlib.md5((a["poster"] or "").encode()).hexdigest()[:8]
    return f"/poster/{a['id']}?v={v}"


def _item(a) -> dict:
    return {
        "code": a["code"],
        "name": a["name"],
        "descr": _short(a["descr"], 160),
        "eps": a["eps"] or 0,
        "rating": a["rating"] or 0,
        "views": a["views"] or 0,
        "poster": _poster_url(a),
    }


async def index(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(os.path.join(BASE, "static", "index.html"))


async def api_config(request: web.Request) -> web.Response:
    return web.json_response({
        "brand": BRAND,
        "bot": BOT_USERNAME,
        "channel": "https://t.me/" + PUBLIC_CHANNEL.lstrip("@"),
    })


async def api_animes(request: web.Request) -> web.Response:
    q = request.query.get("q", "").strip()
    sort = request.query.get("sort", "new")
    if q:
        rows = await db.search_animes(q, 60)
    else:
        rows = await db.list_animes(sort if sort in ("new", "top", "az") else "new", 200, 0)
    return web.json_response([_item(a) for a in rows])


async def api_anime(request: web.Request) -> web.Response:
    a = await db.get_anime_by_code(request.match_info["code"])
    if not a:
        raise web.HTTPNotFound()
    eps = await db.episodes_of(a["id"])
    avg, cnt = await db.rating_info(a["id"])
    code = a["code"]
    deep = f"https://t.me/{BOT_USERNAME}?start=a_{code}"
    return web.json_response({
        "code": code,
        "name": a["name"],
        "descr": a["descr"] or "",
        "views": a["views"] or 0,
        "rating": avg,
        "rating_count": cnt,
        "poster": _poster_url(a),
        "episodes": [{"num": e["num"], "link": f"https://t.me/{BOT_USERNAME}?start=e_{code}_{e['num']}"} for e in eps],
        "bot_link": deep,
        "share_link": "https://t.me/share/url?url=" + quote(deep, safe="") + "&text=" + quote(f"🎬 {a['name']}", safe=""),
    })


async def poster(request: web.Request) -> web.Response:
    try:
        a = await db.get_anime(int(request.match_info["id"]))
    except ValueError:
        raise web.HTTPNotFound()
    if not a:
        raise web.HTTPNotFound()
    key = a["poster"]
    data = _poster_cache.get(key)
    if data is None:
        try:
            bot = request.app["bot"]
            f = await bot.get_file(key)
            buf = io.BytesIO()
            await bot.download_file(f.file_path, destination=buf)
            data = buf.getvalue()
        except Exception as e:
            log.warning("Poster olinmadi: %s", e)
            raise web.HTTPNotFound()
        if len(_poster_cache) > 300:
            _poster_cache.pop(next(iter(_poster_cache)))
        _poster_cache[key] = data
    return web.Response(body=data, content_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def make_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/config", api_config)
    app.router.add_get("/api/animes", api_animes)
    app.router.add_get("/api/anime/{code}", api_anime)
    app.router.add_get("/poster/{id}", poster)
    return app


async def start_web(bot) -> web.AppRunner:
    runner = web.AppRunner(make_app(bot))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Sayt ishga tushdi: port %s", PORT)
    return runner
