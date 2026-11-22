"""
Anime Uzbek bot - sozlamalar.
Railway'da FAQAT BOT_TOKEN o'zgaruvchisi kerak. Qolgani shu faylning ichida.
"""
import os

# ---- Railway Variables'dan oladigan yagona narsa ----
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# ---- Kod ichida yozilgan sozlamalar ----
BRAND = "Anime Uzbek"                  # bot va sayt nomi
BOT_USERNAME = "ANIME_TV1_bot"         # @ belgisiz
ADMIN_ID = 8278356193                  # asosiy admin (@Alfa_gaming98)
ADMIN_USERNAME = "@Alfa_gaming98"
STORAGE_CHANNEL_ID = -1004306638417    # ombor kanal (videolar shu yerga saqlanadi)
PUBLIC_CHANNEL = "@ANIME_uzTV1"        # ommaviy kanal (postlar shu yerga chiqadi)

# Bir marta (bir "Tugatish" bosguncha) qabul qilinadigan maksimal qism soni
MAX_EPISODES_PER_BATCH = 24

# ---- Sayt ----
PORT = int(os.getenv("PORT", "8080"))


def _site_url() -> str:
    url = os.getenv("SITE_URL", "").strip().rstrip("/")
    if url:
        return url
    dom = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if dom:
        return "https://" + dom
    return ""


SITE_URL = _site_url()

# ---- Baza fayli ----
# Railway'da Volume ulasangiz (mount path: /data) baza avtomatik shu yerda saqlanadi
# va qayta deploy qilinganda o'chib ketmaydi.
def _db_path() -> str:
    env = os.getenv("DB_PATH", "").strip()
    if env:
        return env
    if os.path.isdir("/data"):
        return "/data/anime.db"
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "anime.db")


DB_PATH = _db_path()
