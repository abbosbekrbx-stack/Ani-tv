"""Foydalanuvchi qismi: /start, menyu, qidiruv, qismlar, rejam, baholash."""
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import db
from common import (B, esc, ep_keyboard, gate, get_text, is_admin, kb,
                    send_card, send_episode, stars_keyboard, missing_subs)

router = Router(name="user")

LIST_PAGE = 8


# ------------------------------------------------------------------ menus
def main_menu(uid: int):
    rows = [
        [B("Anime izlash", cb="m:search")],
        [B("Qo'llanma", cb="m:help"), B("Reklama", cb="m:ads")],
        [B("Statistika", cb="m:stats")],
        [B("Bot haqida", cb="m:about")],
    ]
    if is_admin(uid):
        rows.append([B("👑 Admin panel", cb="adm:home")])
    return kb(rows)


def search_menu():
    return kb([
        [B("📚 Barcha animelar", cb="ls:az:0"), B("🔥 Top animelar", cb="ls:top:0")],
        [B("🆕 Yangi qo'shilganlar", cb="ls:new:0"), B("❤️ Rejam", cb="ls:fav:0")],
        [B("⬅️ Menyu", cb="m:home")],
    ])


async def show(cb: CallbackQuery, text: str, markup) -> None:
    """Xabarni tahrirlaydi, bo'lmasa yangisini yuboradi."""
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=markup)


async def send_main_menu(bot: Bot, chat_id: int, user) -> None:
    await bot.send_message(chat_id, await get_text("start", user.full_name),
                           reply_markup=main_menu(user.id))


async def handle_payload(bot: Bot, chat_id: int, uid: int, payload: str) -> bool:
    """Deep-link: a_<kod> yoki e_<kod>_<qism>. Ishlov berilsa True."""
    if payload.startswith("a_"):
        code = payload[2:]
        a = await db.get_anime_by_code(code)
        if not a:
            await bot.send_message(chat_id, "😔 Bunday anime topilmadi.")
            return True
        await send_card(bot, chat_id, a, uid)
        return True
    if payload.startswith("e_"):
        body = payload[2:]
        if "_" not in body:
            return False
        code, num = body.rsplit("_", 1)
        a = await db.get_anime_by_code(code)
        if not a or not num.isdigit():
            await bot.send_message(chat_id, "😔 Bunday anime yoki qism topilmadi.")
            return True
        ep = await db.get_episode(a["id"], int(num))
        if not ep:
            await bot.send_message(chat_id, "😔 Bu qism hali qo'shilmagan.")
            await send_card(bot, chat_id, a, uid)
            return True
        await db.add_view(a["id"])
        await send_episode(bot, chat_id, a, ep, uid)
        return True
    return False


# ------------------------------------------------------------------ /start
@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject, bot: Bot, state: FSMContext):
    await state.clear()
    payload = (command.args or "").strip()
    if not await gate(bot, m.chat.id, m.from_user.id, payload if payload and len(payload) <= 55 else "0"):
        return
    if payload and await handle_payload(bot, m.chat.id, m.from_user.id, payload):
        return
    await send_main_menu(bot, m.chat.id, m.from_user)


@router.callback_query(F.data.startswith("chk:"))
async def cb_check_sub(c: CallbackQuery, bot: Bot):
    payload = c.data[4:]
    if await missing_subs(bot, c.from_user.id):
        await c.answer("❌ Siz hali hamma kanalga obuna bo'lmadingiz!", show_alert=True)
        return
    await c.answer("✅ Rahmat!")
    try:
        await c.message.delete()
    except Exception:
        pass
    if payload and payload != "0" and await handle_payload(bot, c.message.chat.id, c.from_user.id, payload):
        return
    await send_main_menu(bot, c.message.chat.id, c.from_user)


@router.callback_query(F.data == "noop")
async def cb_noop(c: CallbackQuery):
    await c.answer()


# ------------------------------------------------------------ menu buttons
@router.callback_query(F.data == "m:home")
async def cb_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    await show(c, await get_text("start", c.from_user.full_name), main_menu(c.from_user.id))


@router.callback_query(F.data == "m:search")
async def cb_search(c: CallbackQuery):
    await c.answer()
    await show(c, "🏷 <b>Anime nomini yoki kodini yozing:</b>\n\nYoki quyidagi bo'limlardan birini tanlang 👇",
               search_menu())


@router.callback_query(F.data.in_({"m:help", "m:ads", "m:about"}))
async def cb_texts(c: CallbackQuery):
    await c.answer()
    key = c.data.split(":")[1]
    await show(c, await get_text(key, c.from_user.full_name), kb([[B("⬅️ Menyu", cb="m:home")]]))


@router.callback_query(F.data == "m:stats")
async def cb_stats(c: CallbackQuery):
    await c.answer()
    s = await db.stats()
    text = (
        "📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{s['users']}</b>\n"
        f"🎬 Animelar: <b>{s['animes']}</b>\n"
        f"📺 Jami qismlar: <b>{s['episodes']}</b>\n"
        f"👁 Ko'rishlar: <b>{s['views']}</b>"
    )
    await show(c, text, kb([[B("⬅️ Menyu", cb="m:home")]]))


# ------------------------------------------------------------------- lists
async def render_list(mode: str, page: int, uid: int):
    if mode == "fav":
        total = await db.count_favs(uid)
        rows_db = await db.fav_animes(uid, LIST_PAGE, page * LIST_PAGE)
        title = "❤️ <b>Mening rejam</b>"
        empty = "Rejangiz hozircha bo'sh. Anime ostidagi 🤍 tugmasini bosib qo'shing."
    else:
        total = await db.count_animes()
        rows_db = await db.list_animes(mode, LIST_PAGE, page * LIST_PAGE)
        title = {"az": "📚 <b>Barcha animelar</b>", "top": "🔥 <b>Top animelar</b>",
                 "new": "🆕 <b>Yangi qo'shilganlar</b>"}.get(mode, "📚 <b>Animelar</b>")
        empty = "Hozircha anime qo'shilmagan."
    if not rows_db:
        return f"{title}\n\n{empty}", kb([[B("⬅️ Orqaga", cb="m:search")]])
    pages = max(1, (total + LIST_PAGE - 1) // LIST_PAGE)
    rows = []
    for a in rows_db:
        extra = f" • {a['eps']} qism" if a["eps"] else ""
        rows.append([B(f"🎬 {a['name']}{extra}"[:60], cb=f"an:{a['id']}")])
    nav = []
    if page > 0:
        nav.append(B("⬅️", cb=f"ls:{mode}:{page - 1}"))
    nav.append(B(f"{page + 1}/{pages}", cb="noop"))
    if page < pages - 1:
        nav.append(B("➡️", cb=f"ls:{mode}:{page + 1}"))
    rows.append(nav)
    rows.append([B("⬅️ Orqaga", cb="m:search")])
    return f"{title}\n\nJami: <b>{total}</b> ta", kb(rows)


@router.callback_query(F.data.startswith("ls:"))
async def cb_list(c: CallbackQuery):
    _, mode, page = c.data.split(":")
    await c.answer()
    text, markup = await render_list(mode, int(page), c.from_user.id)
    await show(c, text, markup)


@router.callback_query(F.data.startswith("an:"))
async def cb_open_anime(c: CallbackQuery, bot: Bot):
    await c.answer()
    a = await db.get_anime(int(c.data[3:]))
    if not a:
        await c.message.answer("😔 Bu anime topilmadi (o'chirilgan bo'lishi mumkin).")
        return
    if not await gate(bot, c.message.chat.id, c.from_user.id, f"a_{a['code']}"):
        return
    await send_card(bot, c.message.chat.id, a, c.from_user.id)


# ------------------------------------------------------------------ search
@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def on_text_search(m: Message, bot: Bot):
    if not await gate(bot, m.chat.id, m.from_user.id, "0"):
        return
    q = m.text.strip()
    exact = await db.get_anime_by_code(q)
    if exact:
        await send_card(bot, m.chat.id, exact, m.from_user.id)
        return
    res = await db.search_animes(q, 20)
    if not res:
        await m.answer(f"😔 «{esc(q)}» bo'yicha hech narsa topilmadi.\n\nBoshqa nom yoki kod yozib ko'ring.",
                       reply_markup=search_menu())
        return
    if len(res) == 1:
        await send_card(bot, m.chat.id, res[0], m.from_user.id)
        return
    rows = []
    for a in res:
        extra = f" • {a['eps']} qism" if a["eps"] else ""
        rows.append([B(f"🎬 {a['name']}{extra}"[:60], cb=f"an:{a['id']}")])
    rows.append([B("⬅️ Menyu", cb="m:home")])
    await m.answer(f"🔎 <b>«{esc(q)}»</b> bo'yicha topildi: {len(res)} ta", reply_markup=kb(rows))


# ------------------------------------------- episode buttons / fav / rating
async def _safe_markup(c: CallbackQuery, markup) -> None:
    try:
        await c.message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("ep:"))
async def cb_episode(c: CallbackQuery, bot: Bot):
    _, aid, num, page = c.data.split(":")
    a = await db.get_anime(int(aid))
    ep = await db.get_episode(int(aid), int(num)) if a else None
    if not a or not ep:
        await c.answer("😔 Bu qism topilmadi.", show_alert=True)
        return
    await c.answer()
    payload = f"e_{a['code']}_{num}"
    if not await gate(bot, c.message.chat.id, c.from_user.id, payload if len(payload) <= 55 else "0"):
        return
    await db.add_view(a["id"])
    try:
        await send_episode(bot, c.message.chat.id, a, ep, c.from_user.id, int(page))
    except Exception:
        await c.message.answer("⚠️ Videoni yuborib bo'lmadi. Birozdan so'ng qayta urinib ko'ring.")


@router.callback_query(F.data.startswith("pg:"))
async def cb_page(c: CallbackQuery):
    _, aid, page, cur = c.data.split(":")
    await c.answer()
    await _safe_markup(c, await ep_keyboard(int(aid), int(cur), int(page), c.from_user.id))


@router.callback_query(F.data.startswith("fav:"))
async def cb_fav(c: CallbackQuery):
    _, aid, cur, page = c.data.split(":")
    state = await db.toggle_fav(c.from_user.id, int(aid))
    await c.answer("❤️ Rejangizga qo'shildi" if state else "💔 Rejangizdan olib tashlandi")
    await _safe_markup(c, await ep_keyboard(int(aid), int(cur), int(page), c.from_user.id))


@router.callback_query(F.data.startswith("rate:"))
async def cb_rate(c: CallbackQuery):
    _, aid, cur, page = c.data.split(":")
    mine = await db.user_rating(c.from_user.id, int(aid))
    await c.answer(f"Sizning bahoyingiz: {mine}⭐" if mine else "Animeni baholang: 1 dan 5 gacha")
    await _safe_markup(c, stars_keyboard(int(aid), int(cur), int(page)))


@router.callback_query(F.data.startswith("st:"))
async def cb_stars(c: CallbackQuery):
    _, aid, stars, cur, page = c.data.split(":")
    await db.set_rating(c.from_user.id, int(aid), int(stars))
    avg, cnt = await db.rating_info(int(aid))
    await c.answer(f"Rahmat! Siz {stars}⭐ baho berdingiz.\nO'rtacha reyting: {avg}⭐ ({cnt} ta)", show_alert=True)
    await _safe_markup(c, await ep_keyboard(int(aid), int(cur), int(page), c.from_user.id))


@router.callback_query(F.data.startswith("bk:"))
async def cb_back(c: CallbackQuery):
    _, aid, cur, page = c.data.split(":")
    await c.answer()
    await _safe_markup(c, await ep_keyboard(int(aid), int(cur), int(page), c.from_user.id))
