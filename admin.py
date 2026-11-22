"""Admin panel: anime qo'shish (1-24 qism avto-taxlash), tahrirlash, xabar yuborish,
kanalga post, majburiy obuna, matnlar, statistika, adminlar, ban."""
import asyncio
import logging
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, KeyboardButton, Message,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove)

import db
from common import (ADMINS, B, DEFAULT_TEXTS, TEXT_TITLES, esc, is_admin, kb,
                    link_anime, load_admins, post_to_channel)
from config import (ADMIN_ID, MAX_EPISODES_PER_BATCH, PUBLIC_CHANNEL, SITE_URL,
                    STORAGE_CHANNEL_ID)
from user import show

log = logging.getLogger("admin")


class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        u = getattr(event, "from_user", None)
        return u is not None and is_admin(u.id)


router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

CANCEL = "❌ Bekor qilish"
FINISH = "✅ Tugatish"
CODE_RE = re.compile(r"^[A-Za-z0-9-]{1,30}$")
LIST_PAGE = 8

cancel_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=CANCEL)]], resize_keyboard=True)
finish_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=FINISH)], [KeyboardButton(text=CANCEL)]],
    resize_keyboard=True,
)


class Add(StatesGroup):
    poster = State()
    code = State()
    name = State()
    descr = State()
    eps = State()


class Edit(StatesGroup):
    value = State()


class Bc(StatesGroup):
    msg = State()
    confirm = State()


class Sub(StatesGroup):
    add = State()


class Txt(StatesGroup):
    val = State()


class AdmAdd(StatesGroup):
    uid = State()


class BanS(StatesGroup):
    uid = State()


# qism yig'ish sessiyalari (xotirada): uid -> {...}
SESS: dict = {}
TASKS: set = set()


def new_sess() -> dict:
    return {"items": [], "seen": set(), "task": None, "status": None, "warned": False}


# ------------------------------------------------------------------ panel
PANEL_TEXT = "👑 <b>Admin panel</b>\n\nKerakli bo'limni tanlang:"


def panel_kb():
    return kb([
        [B("➕ Anime qo'shish", cb="adm:add"), B("✏️ Anime tahrirlash", cb="adm:edit")],
        [B("📢 Xabar yuborish", cb="adm:bc"), B("📝 Kanalga post", cb="adm:post")],
        [B("📡 Majburiy obuna", cb="adm:sub"), B("📄 Matnlar", cb="adm:txt")],
        [B("📊 Statistika", cb="adm:stats")],
        [B("👮 Adminlar", cb="adm:admins"), B("🚫 Ban / Unban", cb="adm:ban")],
        [B("⬅️ Menyu", cb="m:home")],
    ])


@router.message(Command("admin"))
async def cmd_admin(m: Message, state: FSMContext):
    await state.clear()
    SESS.pop(m.from_user.id, None)
    await m.answer(PANEL_TEXT, reply_markup=panel_kb())


@router.callback_query(F.data == "adm:home")
async def cb_home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    await show(c, PANEL_TEXT, panel_kb())


@router.message(F.text == CANCEL)
async def on_cancel(m: Message, state: FSMContext):
    s = SESS.pop(m.from_user.id, None)
    if s and s.get("task"):
        s["task"].cancel()
    await state.clear()
    await m.answer("❌ Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    await m.answer(PANEL_TEXT, reply_markup=panel_kb())


async def ask(c: CallbackQuery, state: FSMContext, st: State, text: str, markup=cancel_kb) -> None:
    await c.answer()
    await state.clear()
    await state.set_state(st)
    await c.message.answer(text, reply_markup=markup)


async def back_to_panel(m: Message, text: str) -> None:
    await m.answer(text, reply_markup=ReplyKeyboardRemove())
    await m.answer(PANEL_TEXT, reply_markup=panel_kb())


# ================================================================ ANIME QO'SHISH
EPS_PROMPT = (
    "🎞 <b>Qismlarni tashlang</b>\n\n"
    f"1 tadan {MAX_EPISODES_PER_BATCH} tagacha video tashlashingiz mumkin (hammasini birdaniga ham bo'ladi).\n"
    "Bot ularni o'zi tartib bilan <b>1, 2, 3...</b> deb taxlab chiqadi.\n\n"
    f"Hammasini tashlab bo'lgach pastdagi <b>{FINISH}</b> tugmasini bosing."
)


@router.callback_query(F.data == "adm:add")
async def cb_add(c: CallbackQuery, state: FSMContext):
    SESS.pop(c.from_user.id, None)
    await ask(c, state, Add.poster, "🖼 <b>1/4</b> — Anime rasmini (poster) yuboring:")


@router.message(Add.poster, F.photo)
async def add_poster(m: Message, state: FSMContext):
    await state.update_data(poster=m.photo[-1].file_id)
    await state.set_state(Add.code)
    await m.answer("🔑 <b>2/4</b> — Anime kodini yozing.\n\nFaqat lotin harf, raqam va «-» (masalan: <code>101</code>).")


@router.message(Add.poster)
async def add_poster_bad(m: Message):
    await m.answer("⚠️ Iltimos, rasm yuboring (rasm sifatida, fayl emas).")


@router.message(Add.code, F.text)
async def add_code(m: Message, state: FSMContext):
    code = m.text.strip()
    if not CODE_RE.match(code):
        await m.answer("⚠️ Kod faqat lotin harf, raqam va «-» dan iborat bo'lishi kerak (30 belgigacha). Qayta yozing:")
        return
    if await db.code_exists(code):
        await m.answer("⚠️ Bu kod band. Boshqa kod yozing:")
        return
    await state.update_data(code=code)
    await state.set_state(Add.name)
    await m.answer("🏷 <b>3/4</b> — Anime nomini yozing:")


@router.message(Add.name, F.text)
async def add_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip()[:150])
    await state.set_state(Add.descr)
    await m.answer("📝 <b>4/4</b> — Anime tavsifini yozing:\n\n(Tavsif kerak bo'lmasa «-» yuboring)")


@router.message(Add.descr, F.text)
async def add_descr(m: Message, state: FSMContext):
    descr = "" if m.text.strip() == "-" else m.text.strip()
    await state.update_data(descr=descr, mode="new")
    await state.set_state(Add.eps)
    SESS[m.from_user.id] = new_sess()
    await m.answer(EPS_PROMPT, reply_markup=finish_kb)


# ---- qismlarni qabul qilish
def _schedule_status(bot: Bot, uid: int, chat_id: int) -> None:
    s = SESS[uid]
    if s.get("task"):
        s["task"].cancel()
    s["task"] = asyncio.create_task(_status(bot, uid, chat_id))


async def _status(bot: Bot, uid: int, chat_id: int) -> None:
    try:
        await asyncio.sleep(1.2)
    except asyncio.CancelledError:
        return
    s = SESS.get(uid)
    if not s:
        return
    n = len(s["items"])
    text = f"📥 Qabul qilindi: <b>{n}</b> ta qism\n\nYana tashlashingiz yoki <b>{FINISH}</b> ni bosishingiz mumkin."
    if n >= MAX_EPISODES_PER_BATCH:
        text += f"\n\n⚠️ Maksimal {MAX_EPISODES_PER_BATCH} ta. Ortiqchasi qabul qilinmaydi."
    try:
        if s["status"]:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=s["status"])
        else:
            msg = await bot.send_message(chat_id, text)
            s["status"] = msg.message_id
    except Exception:
        try:
            msg = await bot.send_message(chat_id, text)
            s["status"] = msg.message_id
        except Exception:
            pass


@router.message(Add.eps, F.text == FINISH)
async def add_finish(m: Message, state: FSMContext, bot: Bot):
    uid = m.from_user.id
    await asyncio.sleep(1.0)  # oxirgi yuborilgan videolar ro'yxatga tushib ulgurishi uchun
    s = SESS.get(uid)
    if not s or not s["items"]:
        await m.answer("⚠️ Hali birorta qism tashlanmadi. Avval video yuboring.")
        return
    if s.get("task"):
        s["task"].cancel()
    data = await state.get_data()
    items = sorted(s["items"], key=lambda x: x["msg_id"])  # yuborilgan tartib bo'yicha
    mode = data.get("mode", "new")
    prog = await m.answer("⏳ Qismlar saqlanmoqda...", reply_markup=ReplyKeyboardRemove())

    if mode == "new":
        try:
            aid = await db.add_anime(data["code"], data["name"], data["descr"], data["poster"])
        except Exception:
            await state.clear()
            SESS.pop(uid, None)
            await back_to_panel(m, "⚠️ Anime saqlanmadi (kod band bo'lib qolgan). Qaytadan urinib ko'ring.")
            return
        start = 1
    else:
        aid = data["aid"]
        start = (await db.max_ep_num(aid)) + 1
    a = await db.get_anime(aid)

    stored = 0
    total = len(items)
    for i, it in enumerate(items):
        num = start + i
        sid = await _copy_to_storage(bot, it, f"{esc(a['name'])} — {num}-qism")
        if sid:
            stored += 1
        await db.add_episode(aid, num, it["kind"], it["file_id"], sid)
        if (i + 1) % 3 == 0 or i + 1 == total:
            try:
                await prog.edit_text(f"⏳ Saqlanmoqda: {i + 1}/{total}")
            except Exception:
                pass

    SESS.pop(uid, None)
    await state.clear()
    last = start + total - 1
    warn = ""
    if stored < total:
        warn = (f"\n⚠️ Omborga {stored}/{total} ta nusxalandi. Bot ombor kanalda admin ekanini tekshiring "
                "(videolar baribir ishlaydi).")

    if mode == "new":
        post_line = ""
        try:
            await post_to_channel(bot, aid)
            post_line = f"📢 Ommaviy kanalga chiqarildi: {PUBLIC_CHANNEL}\n"
        except Exception as e:
            post_line = f"⚠️ Kanalga chiqarib bo'lmadi: {esc(str(e)[:120])}\n(Bot {PUBLIC_CHANNEL} da admin bo'lishi kerak)\n"
        site_line = "🌐 Saytda ham ko'rinadi\n" if SITE_URL else ""
        text = (f"✅ <b>{esc(a['name'])}</b> qo'shildi!\n\n"
                f"🔑 Kod: <code>{esc(a['code'])}</code>\n"
                f"📺 Qismlar: {total} ta (1–{last})\n"
                f"{post_line}{site_line}{warn}")
        await prog.edit_text(text, reply_markup=kb([
            [B("▶️ Botda ko'rish", url=link_anime(a["code"]), style="success")],
            [B("⬅️ Admin panel", cb="adm:home")],
        ]))
    else:
        await prog.edit_text(
            f"✅ <b>{esc(a['name'])}</b> ga {total} ta yangi qism qo'shildi ({start}–{last}).{warn}",
            reply_markup=kb([
                [B("📝 Kanalga qayta post", cb=f"pk:{aid}")],
                [B("⬅️ Anime menyusi", cb=f"ea:{aid}")],
            ]),
        )


async def _copy_to_storage(bot: Bot, it: dict, caption: str):
    for _ in range(3):
        try:
            msg = await bot.copy_message(STORAGE_CHANNEL_ID, it["chat_id"], it["msg_id"], caption=caption)
            return msg.message_id
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except Exception as e:
            log.warning("Omborga nusxalab bo'lmadi: %s", e)
            return None
    return None


@router.message(Add.eps, F.video | F.document)
async def add_episode_msg(m: Message, bot: Bot):
    uid = m.from_user.id
    s = SESS.setdefault(uid, new_sess())
    if m.video:
        kind, fid, uniq = "video", m.video.file_id, m.video.file_unique_id
    else:
        mime = m.document.mime_type or ""
        if not mime.startswith("video/"):
            await m.answer("⚠️ Faqat video fayl yuboring.")
            return
        kind, fid, uniq = "document", m.document.file_id, m.document.file_unique_id
    if uniq in s["seen"]:
        return
    if len(s["items"]) >= MAX_EPISODES_PER_BATCH:
        _schedule_status(bot, uid, m.chat.id)
        return
    s["seen"].add(uniq)
    s["items"].append({"msg_id": m.message_id, "chat_id": m.chat.id, "kind": kind, "file_id": fid})
    _schedule_status(bot, uid, m.chat.id)


@router.message(Add.eps)
async def add_eps_other(m: Message):
    await m.answer(f"⚠️ Video yuboring yoki <b>{FINISH}</b> tugmasini bosing.")


# ============================================================== TAHRIRLASH / POST
async def admin_list(kind: str, page: int):
    total = await db.count_animes()
    items = await db.list_animes("new", LIST_PAGE, page * LIST_PAGE)
    title = "✏️ <b>Qaysi animeni tahrirlaymiz?</b>" if kind == "e" else "📝 <b>Qaysi animeni kanalga joylaymiz?</b>"
    if not items:
        return "Hozircha anime qo'shilmagan.", kb([[B("⬅️ Orqaga", cb="adm:home")]])
    pages = max(1, (total + LIST_PAGE - 1) // LIST_PAGE)
    rows = []
    for a in items:
        cb = f"ea:{a['id']}" if kind == "e" else f"pk:{a['id']}"
        rows.append([B(f"🎬 {a['name']} ({a['eps']} qism)"[:60], cb=cb)])
    nav = []
    if page > 0:
        nav.append(B("⬅️", cb=f"al:{kind}:{page - 1}"))
    nav.append(B(f"{page + 1}/{pages}", cb="noop"))
    if page < pages - 1:
        nav.append(B("➡️", cb=f"al:{kind}:{page + 1}"))
    rows.append(nav)
    rows.append([B("⬅️ Orqaga", cb="adm:home")])
    return f"{title}\n\nJami: <b>{total}</b> ta", kb(rows)


@router.callback_query(F.data.in_({"adm:edit", "adm:post"}))
async def cb_pick_list(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, markup = await admin_list("e" if c.data == "adm:edit" else "p", 0)
    await show(c, text, markup)


@router.callback_query(F.data.startswith("al:"))
async def cb_list_page(c: CallbackQuery):
    _, kind, page = c.data.split(":")
    await c.answer()
    text, markup = await admin_list(kind, int(page))
    await show(c, text, markup)


async def anime_menu(aid: int):
    a = await db.get_anime(aid)
    if not a:
        return "Anime topilmadi.", kb([[B("⬅️ Orqaga", cb="adm:edit")]])
    eps = await db.episodes_of(aid)
    nums = [e["num"] for e in eps]
    rng = f" ({min(nums)}–{max(nums)})" if nums else ""
    posted = "ha ✅" if a["post_msg_id"] else "yo'q"
    text = (f"🎬 <b>{esc(a['name'])}</b>\n\n"
            f"🔑 Kod: <code>{esc(a['code'])}</code>\n"
            f"📺 Qismlar: <b>{len(nums)}</b> ta{rng}\n"
            f"👁 Ko'rilgan: {a['views']}\n"
            f"📢 Kanalga chiqarilgan: {posted}")
    return text, kb([
        [B("✏️ Nomi", cb=f"ef:{aid}:name"), B("📝 Tavsifi", cb=f"ef:{aid}:descr")],
        [B("🖼 Rasmi", cb=f"ef:{aid}:poster"), B("🔑 Kodi", cb=f"ef:{aid}:code")],
        [B("➕ Qism qo'shish", cb=f"eq:{aid}"), B("🗑 Qism o'chirish", cb=f"ed:{aid}")],
        [B("📝 Kanalga post", cb=f"pk:{aid}"), B("🗑 Animeni o'chirish", cb=f"da:{aid}", style="danger")],
        [B("⬅️ Orqaga", cb="adm:edit")],
    ])


@router.callback_query(F.data.startswith("ea:"))
async def cb_anime_menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, markup = await anime_menu(int(c.data[3:]))
    await show(c, text, markup)


FIELD_PROMPT = {
    "name": "✏️ Yangi nomni yozing:",
    "descr": "📝 Yangi tavsifni yozing:",
    "poster": "🖼 Yangi rasmni yuboring:",
    "code": "🔑 Yangi kodni yozing (lotin harf, raqam, «-»).\n\n⚠️ Kod o'zgarsa, kanaldagi eski postlarning «Ko'rish» tugmasi ishlamay qoladi.",
}


@router.callback_query(F.data.startswith("ef:"))
async def cb_edit_field(c: CallbackQuery, state: FSMContext):
    _, aid, field = c.data.split(":")
    await ask(c, state, Edit.value, FIELD_PROMPT[field])
    await state.update_data(aid=int(aid), field=field)


@router.message(Edit.value)
async def on_edit_value(m: Message, state: FSMContext):
    data = await state.get_data()
    aid, field = data["aid"], data["field"]
    if field == "poster":
        if not m.photo:
            await m.answer("⚠️ Iltimos, rasm yuboring.")
            return
        value = m.photo[-1].file_id
    else:
        if not m.text:
            await m.answer("⚠️ Iltimos, matn yozing.")
            return
        value = m.text.strip()
        if field == "code":
            if not CODE_RE.match(value):
                await m.answer("⚠️ Kod faqat lotin harf, raqam va «-» bo'lsin. Qayta yozing:")
                return
            other = await db.get_anime_by_code(value)
            if other and other["id"] != aid:
                await m.answer("⚠️ Bu kod band. Boshqa kod yozing:")
                return
        if field == "name":
            value = value[:150]
    await db.update_anime(aid, field, value)
    await state.clear()
    await m.answer("✅ Yangilandi.", reply_markup=ReplyKeyboardRemove())
    text, markup = await anime_menu(aid)
    await m.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("eq:"))
async def cb_add_eps(c: CallbackQuery, state: FSMContext):
    aid = int(c.data[3:])
    a = await db.get_anime(aid)
    if not a:
        await c.answer("Anime topilmadi", show_alert=True)
        return
    SESS[c.from_user.id] = new_sess()
    await ask(c, state, Add.eps, f"➕ <b>{esc(a['name'])}</b> ga yangi qismlar.\n\n" + EPS_PROMPT, finish_kb)
    await state.update_data(mode="append", aid=aid)


async def _del_eps_view(aid: int):
    eps = await db.episodes_of(aid)
    if not eps:
        return "Bu animeda qism yo'q.", kb([[B("⬅️ Orqaga", cb=f"ea:{aid}")]])
    rows, row = [], []
    for e in eps:
        row.append(B(f"🗑 {e['num']}", cb=f"dl:{aid}:{e['num']}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([B("⬅️ Orqaga", cb=f"ea:{aid}")])
    return "🗑 <b>Qaysi qismni o'chiramiz?</b>\n\nRaqamni bossangiz qism darhol o'chadi.", kb(rows)


@router.callback_query(F.data.startswith("ed:"))
async def cb_del_eps(c: CallbackQuery):
    await c.answer()
    text, markup = await _del_eps_view(int(c.data[3:]))
    await show(c, text, markup)


@router.callback_query(F.data.startswith("dl:"))
async def cb_del_one(c: CallbackQuery):
    _, aid, num = c.data.split(":")
    await db.delete_episode(int(aid), int(num))
    await c.answer(f"{num}-qism o'chirildi")
    text, markup = await _del_eps_view(int(aid))
    await show(c, text, markup)


@router.callback_query(F.data.startswith("da:"))
async def cb_del_anime(c: CallbackQuery):
    aid = int(c.data[3:])
    a = await db.get_anime(aid)
    await c.answer()
    if not a:
        return
    await show(c, f"⚠️ <b>{esc(a['name'])}</b> va uning barcha qismlari o'chiriladi.\n\nIshonchingiz komilmi?",
               kb([[B("🗑 Ha, o'chirish", cb=f"dy:{aid}", style="danger")],
                   [B("⬅️ Yo'q", cb=f"ea:{aid}")]]))


@router.callback_query(F.data.startswith("dy:"))
async def cb_del_anime_yes(c: CallbackQuery, bot: Bot):
    aid = int(c.data[3:])
    a = await db.get_anime(aid)
    if a and a["post_msg_id"]:
        try:
            await bot.delete_message(PUBLIC_CHANNEL, a["post_msg_id"])
        except Exception:
            pass
    await db.delete_anime(aid)
    await c.answer("🗑 O'chirildi")
    text, markup = await admin_list("e", 0)
    await show(c, text, markup)


@router.callback_query(F.data.startswith("pk:"))
async def cb_post(c: CallbackQuery, bot: Bot):
    aid = int(c.data[3:])
    a = await db.get_anime(aid)
    if not a:
        await c.answer("Anime topilmadi", show_alert=True)
        return
    try:
        await post_to_channel(bot, aid)
    except Exception as e:
        await c.answer("Xatolik", show_alert=True)
        await c.message.answer(f"⚠️ Kanalga joylab bo'lmadi: {esc(str(e)[:200])}\n\n"
                               f"Bot {PUBLIC_CHANNEL} kanalida admin ekanini tekshiring.")
        return
    await c.answer("✅ Kanalga joylandi", show_alert=True)


# ================================================================ XABAR YUBORISH
@router.callback_query(F.data == "adm:bc")
async def cb_bc(c: CallbackQuery, state: FSMContext):
    await ask(c, state, Bc.msg,
              "📢 <b>Barcha foydalanuvchilarga yuboriladigan xabarni yuboring.</b>\n\n"
              "Matn, rasm, video, fayl — istalganini yuborishingiz mumkin.")


@router.message(Bc.msg)
async def bc_got(m: Message, state: FSMContext, bot: Bot):
    n = len(await db.broadcast_ids())
    await state.update_data(chat_id=m.chat.id, msg_id=m.message_id)
    await state.set_state(Bc.confirm)
    await m.answer("👆 Xabar shunday ko'rinadi.")
    try:
        await bot.copy_message(m.chat.id, m.chat.id, m.message_id)
    except Exception:
        pass
    await m.answer(f"Xabar <b>{n}</b> ta foydalanuvchiga yuborilsinmi?",
                   reply_markup=kb([[B("✅ Yuborish", cb="bcgo", style="success"),
                                     B("❌ Bekor qilish", cb="bcno", style="danger")]]))


@router.callback_query(Bc.confirm, F.data == "bcno")
async def bc_no(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    await c.message.answer("❌ Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    await c.message.answer(PANEL_TEXT, reply_markup=panel_kb())


@router.callback_query(Bc.confirm, F.data == "bcgo")
async def bc_go(c: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    await c.answer()
    ids = await db.broadcast_ids()
    status = await c.message.answer(f"📤 Yuborish boshlandi: 0/{len(ids)}", reply_markup=ReplyKeyboardRemove())
    task = asyncio.create_task(_run_broadcast(bot, ids, data["chat_id"], data["msg_id"], status))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)


async def _run_broadcast(bot: Bot, ids: list, from_chat: int, msg_id: int, status: Message) -> None:
    ok = fail = 0
    total = len(ids)
    for i, uid in enumerate(ids):
        try:
            await bot.copy_message(uid, from_chat, msg_id)
            ok += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.copy_message(uid, from_chat, msg_id)
                ok += 1
            except Exception:
                fail += 1
        except TelegramForbiddenError:
            await db.mark_inactive(uid)
            fail += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
        if (i + 1) % 100 == 0:
            try:
                await status.edit_text(f"📤 Yuborilmoqda: {i + 1}/{total}")
            except Exception:
                pass
    try:
        await status.edit_text(
            f"✅ <b>Xabar yuborish tugadi</b>\n\n📨 Yetkazildi: <b>{ok}</b>\n🚫 Yetkazilmadi: <b>{fail}</b>",
            reply_markup=kb([[B("⬅️ Admin panel", cb="adm:home")]]))
    except Exception:
        pass


# ================================================================ MAJBURIY OBUNA
async def sub_view():
    on = await db.get_setting("sub_on", "1") == "1"
    chs = await db.channels()
    text = "📡 <b>Majburiy obuna</b>\n\n"
    text += "Holati: " + ("🟢 <b>yoqilgan</b>" if on else "🔴 <b>o'chirilgan</b>") + "\n\n"
    if chs:
        text += "Kanallar:\n" + "\n".join(f"• {esc(ch['title'])}" for ch in chs)
    else:
        text += "Hozircha kanal qo'shilmagan."
    text += "\n\n⚠️ Bot qo'shilgan kanallarda <b>admin</b> bo'lishi shart."
    rows = [[B("🔴 O'chirish" if on else "🟢 Yoqish", cb="sub:tg")]]
    for ch in chs:
        rows.append([B(f"🗑 {ch['title']}"[:60], cb=f"sd:{ch['id']}")])
    rows.append([B("➕ Kanal qo'shish", cb="sub:add", style="success")])
    rows.append([B("⬅️ Orqaga", cb="adm:home")])
    return text, kb(rows)


@router.callback_query(F.data == "adm:sub")
async def cb_sub(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, markup = await sub_view()
    await show(c, text, markup)


@router.callback_query(F.data == "sub:tg")
async def cb_sub_toggle(c: CallbackQuery):
    on = await db.get_setting("sub_on", "1") == "1"
    await db.set_setting("sub_on", "0" if on else "1")
    await c.answer("O'zgartirildi")
    text, markup = await sub_view()
    await show(c, text, markup)


@router.callback_query(F.data.startswith("sd:"))
async def cb_sub_del(c: CallbackQuery):
    await db.del_channel(int(c.data[3:]))
    await c.answer("🗑 O'chirildi")
    text, markup = await sub_view()
    await show(c, text, markup)


@router.callback_query(F.data == "sub:add")
async def cb_sub_add(c: CallbackQuery, state: FSMContext):
    await ask(c, state, Sub.add,
              "📡 Kanalni qo'shish uchun:\n\n"
              "• kanal <b>@username</b> ini yozing, yoki\n"
              "• kanaldan biror xabarni shu yerga <b>forward</b> qiling.\n\n"
              "Bot o'sha kanalda admin bo'lishi shart.")


@router.message(Sub.add)
async def sub_add_got(m: Message, state: FSMContext, bot: Bot):
    chat = None
    fo = getattr(m, "forward_origin", None)
    if fo is not None and getattr(fo, "chat", None) is not None:
        chat = fo.chat
    elif m.text:
        t = m.text.strip()
        try:
            chat = await bot.get_chat(t if t.startswith("@") else int(t))
        except Exception:
            await m.answer("⚠️ Kanal topilmadi. @username ni to'g'ri yozing yoki xabarni forward qiling.")
            return
    if chat is None:
        await m.answer("⚠️ Kanal @username ini yozing yoki kanaldan xabar forward qiling.")
        return
    try:
        me = await bot.me()
        mem = await bot.get_chat_member(chat.id, me.id)
        if mem.status not in ("administrator", "creator"):
            raise ValueError("not admin")
    except Exception:
        await m.answer(f"⚠️ Bot <b>{esc(chat.title)}</b> kanalida admin emas. Avval botni admin qiling, so'ng qayta yuboring.")
        return
    if chat.username:
        link = f"https://t.me/{chat.username}"
    else:
        try:
            link = (await bot.create_chat_invite_link(chat.id)).invite_link
        except Exception:
            await m.answer("⚠️ Kanal uchun havola yaratib bo'lmadi. Botga «Taklif havolalari» huquqini bering.")
            return
    await db.add_channel(str(chat.id), chat.title or chat.username or str(chat.id), link)
    await state.clear()
    await back_to_panel(m, f"✅ <b>{esc(chat.title)}</b> majburiy obunaga qo'shildi.")


# ================================================================ MATNLAR
@router.callback_query(F.data == "adm:txt")
async def cb_txt(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    rows = [[B(title, cb=f"tx:{key}")] for key, title in TEXT_TITLES.items()]
    rows.append([B("⬅️ Orqaga", cb="adm:home")])
    await show(c, "📄 <b>Matnlar</b>\n\nQaysi matnni o'zgartiramiz?", kb(rows))


@router.callback_query(F.data.startswith("tx:"))
async def cb_txt_edit(c: CallbackQuery, state: FSMContext):
    key = c.data[3:]
    if key not in DEFAULT_TEXTS:
        await c.answer()
        return
    cur = await db.get_setting("txt_" + key, "") or DEFAULT_TEXTS[key]
    await ask(c, state, Txt.val,
              f"{TEXT_TITLES[key]}\n\n<b>Hozirgi matn:</b>\n<pre>{esc(cur)}</pre>\n\n"
              "Yangi matnni yuboring (qalin, kursiv kabi formatlash saqlanadi)."
              + ("\n<code>{name}</code> — foydalanuvchi ismi o'rniga qo'yiladi." if key == "start" else ""))
    await state.update_data(key=key)
    await c.message.answer("Standart matnga qaytarish uchun:",
                           reply_markup=kb([[B("♻️ Standart holatga qaytarish", cb=f"tr:{key}")]]))


@router.message(Txt.val, F.text)
async def txt_save(m: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    await db.set_setting("txt_" + key, m.html_text)
    await state.clear()
    await back_to_panel(m, "✅ Matn saqlandi.")


@router.callback_query(F.data.startswith("tr:"))
async def cb_txt_reset(c: CallbackQuery, state: FSMContext):
    await db.del_setting("txt_" + c.data[3:])
    await state.clear()
    await c.answer("♻️ Standart matn tiklandi", show_alert=True)
    await c.message.answer(PANEL_TEXT, reply_markup=panel_kb())


# ================================================================ STATISTIKA
@router.callback_query(F.data == "adm:stats")
async def cb_stats(c: CallbackQuery):
    await c.answer()
    s = await db.stats()
    top = "\n".join(f"  {i}. {esc(r['name'])} — {r['views']}" for i, r in enumerate(s["top"], 1)) or "  —"
    text = (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{s['users']}</b>\n"
        f"   • bugun qo'shilgan: {s['today']}\n"
        f"   • 7 kunda: {s['week']}\n"
        f"   • bugun faol: {s['active_today']}\n"
        f"   • botni bloklagan: {s['blocked']}\n"
        f"   • banlangan: {s['banned']}\n\n"
        f"🎬 Animelar: <b>{s['animes']}</b>\n"
        f"📺 Qismlar: <b>{s['episodes']}</b>\n"
        f"👁 Ko'rishlar: <b>{s['views']}</b>\n"
        f"❤️ Rejadagilar: {s['favs']}\n"
        f"⭐ Baholar: {s['ratings']}\n\n"
        f"🔥 <b>Top 5:</b>\n{top}"
    )
    await show(c, text, kb([[B("🔄 Yangilash", cb="adm:stats"), B("⬅️ Orqaga", cb="adm:home")]]))


# ================================================================ ADMINLAR
async def admins_view():
    ids = await db.admin_ids()
    text = f"👮 <b>Adminlar</b>\n\n👑 Asosiy admin: <code>{ADMIN_ID}</code>\n"
    rows = []
    for uid in ids:
        text += f"• <code>{uid}</code>\n"
        rows.append([B(f"🗑 {uid}", cb=f"ar:{uid}")])
    if not ids:
        text += "Qo'shimcha adminlar yo'q."
    rows.append([B("➕ Admin qo'shish", cb="aa:add", style="success")])
    rows.append([B("⬅️ Orqaga", cb="adm:home")])
    return text, kb(rows)


@router.callback_query(F.data == "adm:admins")
async def cb_admins(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.answer()
    text, markup = await admins_view()
    await show(c, text, markup)


@router.callback_query(F.data == "aa:add")
async def cb_admin_add(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Faqat asosiy admin qo'sha oladi", show_alert=True)
        return
    await ask(c, state, AdmAdd.uid, "👮 Yangi adminning Telegram ID raqamini yuboring (yoki uning xabarini forward qiling):")


def _extract_uid(m: Message):
    fo = getattr(m, "forward_origin", None)
    if fo is not None and getattr(fo, "sender_user", None) is not None:
        return fo.sender_user.id
    if m.text and m.text.strip().lstrip("-").isdigit():
        return int(m.text.strip())
    return None


@router.message(AdmAdd.uid)
async def admin_add_got(m: Message, state: FSMContext):
    uid = _extract_uid(m)
    if uid is None:
        await m.answer("⚠️ ID raqam yuboring yoki foydalanuvchi xabarini forward qiling.")
        return
    await db.add_admin(uid)
    await load_admins()
    await state.clear()
    await back_to_panel(m, f"✅ <code>{uid}</code> admin qilindi.")


@router.callback_query(F.data.startswith("ar:"))
async def cb_admin_remove(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Faqat asosiy admin o'chira oladi", show_alert=True)
        return
    await db.del_admin(int(c.data[3:]))
    await load_admins()
    await c.answer("🗑 O'chirildi")
    text, markup = await admins_view()
    await show(c, text, markup)


# ================================================================ BAN
@router.callback_query(F.data == "adm:ban")
async def cb_ban(c: CallbackQuery, state: FSMContext):
    await ask(c, state, BanS.uid,
              "🚫 Foydalanuvchi ID raqamini yuboring (yoki uning xabarini forward qiling).\n\n"
              "Agar u banlangan bo'lsa — banni olib tashlayman.")


@router.message(BanS.uid)
async def ban_got(m: Message, state: FSMContext):
    uid = _extract_uid(m)
    if uid is None:
        await m.answer("⚠️ ID raqam yuboring yoki foydalanuvchi xabarini forward qiling.")
        return
    if uid in ADMINS:
        await m.answer("⚠️ Adminni ban qilib bo'lmaydi.")
        return
    banned = await db.is_banned(uid)
    await db.set_banned(uid, not banned)
    await state.clear()
    await back_to_panel(m, f"✅ <code>{uid}</code> — " + ("bani olib tashlandi." if banned else "ban qilindi."))
