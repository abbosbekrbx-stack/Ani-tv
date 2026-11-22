"""Bot va admin uchun umumiy yordamchilar: tugmalar, matnlar, kartochka, qism yuborish, kanal posti."""
import html
from typing import Optional
from urllib.parse import quote

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import db
from config import (ADMIN_ID, BOT_USERNAME, BRAND, PUBLIC_CHANNEL, SITE_URL,
                    STORAGE_CHANNEL_ID)

EP_PAGE = 25  # bir sahifada nechta qism tugmasi

# ------------------------------------------------------------------ admins
ADMINS: set = {ADMIN_ID}


async def load_admins() -> None:
    ADMINS.clear()
    ADMINS.add(ADMIN_ID)
    for uid in await db.admin_ids():
        ADMINS.add(uid)


def is_admin(uid: int) -> bool:
    return uid in ADMINS


# ----------------------------------------------------------------- helpers
def esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def B(text: str, cb: Optional[str] = None, url: Optional[str] = None,
      style: Optional[str] = None) -> InlineKeyboardButton:
    """Inline tugma. style: 'success' (yashil), 'primary' (ko'k), 'danger' (qizil)."""
    kw = {"text": text}
    if cb is not None:
        kw["callback_data"] = cb
    if url is not None:
        kw["url"] = url
    if style:
        kw["style"] = style
    return InlineKeyboardButton(**kw)


def kb(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def link_anime(code: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=a_{code}"


def link_ep(code: str, num: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=e_{code}_{num}"


def share_url(code: str, name: str) -> str:
    return ("https://t.me/share/url?url=" + quote(link_anime(code), safe="")
            + "&text=" + quote(f"🎬 {name}\n\nBotda tomosha qiling 👇", safe=""))


# ------------------------------------------------------------------- texts
DEFAULT_TEXTS = {
    "start": (
        "👋 Assalomu alaykum, {name}!\n\n"
        f"🎌 <b>{BRAND}</b> botiga xush kelibsiz!\n"
        "Bu yerda sevimli animelaringizni o'zbek tilida tomosha qilishingiz mumkin.\n\n"
        "Quyidagi tugmalar orqali botdan foydalaning:"
    ),
    "help": (
        "📖 <b>Qo'llanma</b>\n\n"
        "1️⃣ <b>Anime izlash</b> tugmasini bosing va anime nomini yoki kodini yozing.\n"
        "2️⃣ Anime kartochkasidagi qism raqamini bosing, video yuboriladi.\n"
        "3️⃣ Video tagidagi tugmalar orqali boshqa qismlarga o'ting.\n"
        "4️⃣ ❤️ tugmasi bilan animeni rejangizga qo'shing, ⭐ bilan baholang.\n"
        "5️⃣ Kanal postidagi <b>Ko'rish</b> tugmasi sizni to'g'ridan-to'g'ri botga olib keladi."
    ),
    "ads": (
        "📢 <b>Reklama</b>\n\n"
        "Reklama va hamkorlik masalalari bo'yicha admin bilan bog'laning."
    ),
    "about": (
        f"ℹ️ <b>{BRAND}</b>\n\n"
        "Anime'larni o'zbek tilida qulay tomosha qilish uchun yaratilgan bot.\n"
        "Yangi anime va qismlar muntazam qo'shib boriladi."
    ),
}

TEXT_TITLES = {
    "start": "👋 Start matni",
    "help": "📖 Qo'llanma",
    "ads": "📢 Reklama",
    "about": "ℹ️ Bot haqida",
}


async def get_text(key: str, name: str = "") -> str:
    t = await db.get_setting("txt_" + key, "") or DEFAULT_TEXTS[key]
    return t.replace("{name}", esc(name))


# -------------------------------------------------------------- anime card
async def card_text(a, n_eps: int) -> str:
    avg, cnt = await db.rating_info(a["id"])
    desc = (a["descr"] or "").strip()
    if len(desc) > 550:
        desc = desc[:550].rstrip() + "…"
    t = f"🎬 <b>{esc(a['name'])}</b>\n\n"
    if desc:
        t += f"{esc(desc)}\n\n"
    t += f"📺 Qismlar: <b>{n_eps}</b> ta\n"
    if cnt:
        t += f"⭐ Reyting: <b>{avg}</b> ({cnt} ta baho)\n"
    else:
        t += "⭐ Reyting: hali baholanmagan\n"
    t += f"👁 Ko'rilgan: <b>{a['views']}</b>"
    return t


async def ep_keyboard(aid: int, cur: int, page: int, uid: int) -> InlineKeyboardMarkup:
    eps = await db.episodes_of(aid)
    nums = [e["num"] for e in eps]
    faved = await db.is_fav(uid, aid)
    pages = max(1, (len(nums) + EP_PAGE - 1) // EP_PAGE)
    page = min(max(page, 0), pages - 1)
    chunk = nums[page * EP_PAGE:(page + 1) * EP_PAGE]
    rows, row = [], []
    for n in chunk:
        label = f"▶️ {n}" if n == cur else str(n)
        row.append(B(label, cb=f"ep:{aid}:{n}:{page}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(B("⬅️", cb=f"pg:{aid}:{page - 1}:{cur}"))
        nav.append(B(f"{page + 1}/{pages}", cb="noop"))
        if page < pages - 1:
            nav.append(B("➡️", cb=f"pg:{aid}:{page + 1}:{cur}"))
        rows.append(nav)
    fav_label = "❤️ Rejada" if faved else "🤍 Rejaga qo'shish"
    rows.append([
        B(fav_label, cb=f"fav:{aid}:{cur}:{page}"),
        B("⭐ Baholash", cb=f"rate:{aid}:{cur}:{page}"),
    ])
    return kb(rows)


def stars_keyboard(aid: int, cur: int, page: int) -> InlineKeyboardMarkup:
    return kb([
        [B(f"{i}⭐", cb=f"st:{aid}:{i}:{cur}:{page}") for i in range(1, 6)],
        [B("⬅️ Orqaga", cb=f"bk:{aid}:{cur}:{page}")],
    ])


async def send_card(bot: Bot, chat_id: int, a, uid: int) -> None:
    eps = await db.episodes_of(a["id"])
    await db.add_view(a["id"])
    a = await db.get_anime(a["id"])
    text = await card_text(a, len(eps))
    markup = await ep_keyboard(a["id"], 0, 0, uid)
    await bot.send_photo(chat_id, a["poster"], caption=text, reply_markup=markup)


async def send_episode(bot: Bot, chat_id: int, a, ep, uid: int, page: int = 0) -> None:
    cap = f"🎬 <b>{esc(a['name'])}</b>\n📺 <b>{ep['num']}-qism</b>\n\n🤖 @{BOT_USERNAME}"
    markup = await ep_keyboard(a["id"], ep["num"], page, uid)
    if ep["storage_msg_id"]:
        try:
            await bot.copy_message(chat_id, STORAGE_CHANNEL_ID, ep["storage_msg_id"],
                                   caption=cap, reply_markup=markup)
            return
        except Exception:
            pass  # ombordan olib bo'lmadi, file_id bilan urinib ko'ramiz
    if ep["kind"] == "document":
        await bot.send_document(chat_id, ep["file_id"], caption=cap, reply_markup=markup)
    else:
        await bot.send_video(chat_id, ep["file_id"], caption=cap, reply_markup=markup)


# ------------------------------------------------------- forced subscription
def _chat_ref(chat_id: str):
    s = str(chat_id)
    return int(s) if s.lstrip("-").isdigit() else s


async def missing_subs(bot: Bot, uid: int) -> list:
    if is_admin(uid):
        return []
    if await db.get_setting("sub_on", "1") != "1":
        return []
    missing = []
    for ch in await db.channels():
        try:
            m = await bot.get_chat_member(_chat_ref(ch["chat_id"]), uid)
        except Exception:
            continue  # tekshirib bo'lmadi (bot admin emas) - o'tkazib yuboramiz
        if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
            missing.append(ch)
        elif m.status == ChatMemberStatus.RESTRICTED and not getattr(m, "is_member", True):
            missing.append(ch)
    return missing


async def gate(bot: Bot, chat_id: int, uid: int, payload: str = "0") -> bool:
    """True = davom etish mumkin. False = obuna bo'lish xabari yuborildi."""
    missing = await missing_subs(bot, uid)
    if not missing:
        return True
    rows = [[B(f"📢 {ch['title']}", url=ch["link"])] for ch in missing]
    rows.append([B("✅ Obunani tekshirish", cb=f"chk:{payload}", style="success")])
    await bot.send_message(
        chat_id,
        "🔒 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n"
        "Obuna bo'lgach «✅ Obunani tekshirish» tugmasini bosing.",
        reply_markup=kb(rows),
    )
    return False


# ------------------------------------------------------------ channel post
def channel_caption(a, n_eps: int) -> str:
    desc = (a["descr"] or "").strip()
    if len(desc) > 600:
        desc = desc[:600].rstrip() + "…"
    t = f"🎬 <b>{esc(a['name'])}</b>\n\n"
    if desc:
        t += f"{esc(desc)}\n\n"
    t += f"📺 Qismlar: <b>{n_eps}</b> ta\n🆔 Kod: <code>{esc(a['code'])}</code>\n\n🤖 @{BOT_USERNAME}"
    return t


def channel_markup(a) -> InlineKeyboardMarkup:
    return kb([
        [B("▶️ Ko'rish", url=link_anime(a["code"]), style="success")],
        [B("📤 Do'stlarga ulashish", url=share_url(a["code"], a["name"]), style="primary")],
    ])


async def post_to_channel(bot: Bot, aid: int) -> int:
    """Animeni ommaviy kanalga joylaydi. Yuborilgan xabar ID'sini qaytaradi."""
    a = await db.get_anime(aid)
    eps = await db.episodes_of(aid)
    msg = await bot.send_photo(
        PUBLIC_CHANNEL, a["poster"],
        caption=channel_caption(a, len(eps)),
        reply_markup=channel_markup(a),
    )
    await db.update_anime(aid, "post_msg_id", msg.message_id)
    return msg.message_id
