# Anime Uzbek bot (@ANIME_TV1_bot)

Bot + admin panel + sayt — hammasi bitta servis.

## Railway'ga o'rnatish
1. Hamma fayllarni GitHub repoga yuklang (papka tuzilishi shu holda qolsin: `static/index.html` ham).
2. Railway → New Project → Deploy from GitHub repo.
3. **Variables** ga faqat bitta narsa qo'shing: `BOT_TOKEN`
   (admin ID, kanallar, bot username — hammasi `config.py` ichida yozilgan).
4. **Volume** qo'shing (Settings → Volumes → Mount path: `/data`).
   Shunda baza (animelar, foydalanuvchilar) qayta deploy qilinganda o'chib ketmaydi.
5. Settings → Networking → **Generate Domain** — shu havola sizning saytingiz.
6. Botni **ommaviy kanal** (@ANIME_uzTV1) va **ombor kanal**da admin qiling
   (post yuborish huquqi bilan). Majburiy obuna kanallarida ham admin bo'lishi shart.

## Ishlatish
- Botda `/start` → «👑 Admin panel» (yoki `/admin`).
- **Anime qo'shish**: rasm → kod → nom → tavsif → videolarni tashlang → pastdagi **✅ Tugatish**.
  Bot qismlarni 1, 2, 3... deb taxlaydi, omborga saqlaydi, ommaviy kanalga chiqaradi,
  saytda ham ko'rinadi.
- Kanal postida yashil «Ko'rish» (botga o'tadi) va ko'k «Do'stlarga ulashish» tugmalari bor.

## Fayllar
| Fayl | Vazifasi |
|---|---|
| `bot.py` | ishga tushirish |
| `config.py` | ID va sozlamalar |
| `db.py` | baza |
| `common.py` | umumiy funksiyalar, kanal posti |
| `user.py` | foydalanuvchi qismi |
| `admin.py` | admin panel |
| `web.py` + `static/index.html` | sayt |
