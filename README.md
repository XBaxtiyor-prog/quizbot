# Telegram Quiz Bot

Aiogram v2 asosida qurilgan to'liq funksional Telegram Quiz Bot.

## Xususiyatlar

- `savollar.docx` faylini avtomatik parse qilish
- SQLite3 ma'lumotlar bazasi
- Savollarni 2 qismga (50/50) bo'lish
- Har safar variantlarni tasodifiy aralashtirish
- Admin panel (foydalanuvchilar va savollar statistikasi)
- Xato javoblarni ko'rsatish

## Fayllar

```
quiz_bot/
├── main.py              — Asosiy bot kodi
├── parse_docx.py        — Word faylni o'qish moduli
├── create_sample_docx.py — Namuna fayl yaratuvchi
├── requirements.txt     — Kutubxonalar
├── quiz_bot.db          — SQLite bazasi (avtomatik yaratiladi)
└── savollar.docx        — Savolingiz bu yerga (siz joylaysiz)
```

## savollar.docx Formati

```
1. Savol matni?
A) To'g'ri javob
B) Noto'g'ri variant 1
C) Noto'g'ri variant 2
D) Noto'g'ri variant 3
To'g'ri javob: A

2. Keyingi savol?
...
```

## Admin Buyruqlar

- `/admin` — Admin panelni ko'rish
- `/parse_docx` — savollar.docx ni qayta o'qish
- `/clear_questions` — Barcha savollarni o'chirish

## Muhit O'zgaruvchilari

- `BOT_TOKEN` — @BotFather dan olingan token
- `ADMIN_ID` — Admin Telegram ID raqami
