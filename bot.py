"""Anime Uzbek bot - asosiy fayl. Ishga tushirish: python bot.py"""
import asyncio
import logging
import sys

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

import admin
import db
import user
import web as site
from common import is_admin, load_admins
from config import BOT_TOKEN, BOT_USERNAME

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")


class Guard(BaseMiddleware):
    """Har bir foydalanuvchini bazaga yozadi, banlanganlarni o'tkazmaydi."""

    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u is not None and not u.is_bot:
            try:
                await db.touch_user(u)
                if not is_admin(u.id) and await db.is_banned(u.id):
                    return None
            except Exception as e:
                log.warning("Guard xatosi: %s", e)
        return await handler(event, data)


async def main() -> None:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN topilmadi! Railway > Variables ga BOT_TOKEN qo'shing.")
        sys.exit(1)

    await db.init()
    await load_admins()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(Guard())
    dp.include_router(admin.router)
    dp.include_router(user.router)

    runner = await site.start_web(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await bot.set_my_commands([BotCommand(command="start", description="Botni ishga tushirish")])
    except Exception:
        pass
    log.info("Bot ishga tushdi: @%s", BOT_USERNAME)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
