import logging
import os
import random
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from questions_data import QUESTIONS
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

DB_PATH = os.path.join(os.path.dirname(__file__), "quiz_bot.db")


# ─── DATABASE ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            wrong1 TEXT NOT NULL,
            wrong2 TEXT NOT NULL,
            wrong3 TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            part INTEGER NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            percent INTEGER NOT NULL,
            finished_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    count = c.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    if count == 0:
        c.executemany("""
            INSERT INTO questions (question, correct_answer, wrong1, wrong2, wrong3)
            VALUES (:question, :correct_answer, :wrong1, :wrong2, :wrong3)
        """, QUESTIONS)
        conn.commit()
        logger.info(f"{len(QUESTIONS)} ta savol avtomatik yuklandi.")
    conn.close()


def register_user(user: types.User):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO users (id, username, full_name)
        VALUES (?, ?, ?)
    """, (user.id, user.username, user.full_name))
    conn.commit()
    conn.close()


def save_result(user_id: int, part: int, score: int, total: int, percent: int):
    conn = get_db()
    conn.execute("""
        INSERT INTO results (user_id, part, score, total, percent)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, part, score, total, percent))
    conn.commit()
    conn.close()


def get_user_results(user_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT part, score, total, percent, finished_at
        FROM results
        WHERE user_id = ?
        ORDER BY finished_at DESC
        LIMIT 10
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_total_questions():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM questions")
    count = c.fetchone()[0]
    conn.close()
    return count


def get_questions_by_part(part: int):
    conn = get_db()
    c = conn.cursor()
    total = get_total_questions()
    half = total // 2
    if part == 1:
        c.execute("SELECT * FROM questions ORDER BY id LIMIT ?", (half,))
    else:
        c.execute("SELECT * FROM questions ORDER BY id LIMIT -1 OFFSET ?", (half,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_total_users():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count


def add_question_to_db(question: str, correct: str, w1: str, w2: str, w3: str):
    conn = get_db()
    conn.execute("""
        INSERT INTO questions (question, correct_answer, wrong1, wrong2, wrong3)
        VALUES (?, ?, ?, ?, ?)
    """, (question, correct, w1, w2, w3))
    conn.commit()
    conn.close()


def parse_bulk_text(text: str) -> list:
    """
    Quyidagi formatdagi matnni parse qiladi:

    1. Savol matni?
    A) To'g'ri javob
    B) Noto'g'ri 1
    C) Noto'g'ri 2
    D) Noto'g'ri 3
    To'g'ri javob: A

    2. Keyingi savol...
    """
    import re

    # Bo'sh satrlarni o'tkazib yuborish, faqat mazmunli satrlar
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    questions = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Savol satri: raqam + nuqta/qavs bilan boshlanadi
        q_match = re.match(r'^\d+\s*[.)]\s*(.+)', line)
        if not q_match:
            i += 1
            continue

        q_text = q_match.group(1).strip()
        options = {}
        correct_letter = None
        i += 1

        while i < len(lines):
            cur = lines[i]

            # Variant satri: A) yoki A. yoki A -
            opt = re.match(r'^([A-Da-d])\s*[).:\-]\s*(.+)', cur)
            if opt:
                options[opt.group(1).upper()] = opt.group(2).strip()
                i += 1
                continue

            # To'g'ri javob satri — istalgan apostraf va har xil yozuv
            # "To'g'ri javob: A", "Javob: B", "Answer: C", "* D"
            ans = re.search(r'(?:javob|answer)\s*[:\-]?\s*([A-Da-d])\b', cur, re.IGNORECASE)
            if ans:
                correct_letter = ans.group(1).upper()
                i += 1
                continue

            # * A  yoki  *A formatida
            star = re.match(r'^\*\s*([A-Da-d])\b', cur)
            if star:
                correct_letter = star.group(1).upper()
                i += 1
                continue

            # Keyingi savol boshlanishi — to'xtash
            if re.match(r'^\d+\s*[.)]\s*', cur):
                break

            i += 1

        if len(options) >= 4 and correct_letter and correct_letter in options:
            wrongs = [v for k, v in options.items() if k != correct_letter]
            questions.append({
                "question": q_text,
                "correct_answer": options[correct_letter],
                "wrong1": wrongs[0],
                "wrong2": wrongs[1],
                "wrong3": wrongs[2],
            })

    return questions


def bulk_save_to_db(questions: list):
    conn = get_db()
    conn.executemany("""
        INSERT INTO questions (question, correct_answer, wrong1, wrong2, wrong3)
        VALUES (:question, :correct_answer, :wrong1, :wrong2, :wrong3)
    """, questions)
    conn.commit()
    conn.close()


# ─── STATES ──────────────────────────────────────────────────────────────────

class QuizState(StatesGroup):
    in_quiz = State()


class AddQuestion(StatesGroup):
    waiting_question = State()
    waiting_correct  = State()
    waiting_wrong1   = State()
    waiting_wrong2   = State()
    waiting_wrong3   = State()


class BulkAdd(StatesGroup):
    waiting_text = State()


# ─── KEYBOARDS ───────────────────────────────────────────────────────────────

def build_main_menu(is_admin: bool = False):
    total = get_total_questions()
    half = total // 2
    part2_count = total - half
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if total > 0:
        kb.add(
            types.KeyboardButton(f"📝 1-Qism ({half} savol)"),
            types.KeyboardButton(f"📝 2-Qism ({part2_count} savol)")
        )
    kb.add(
        types.KeyboardButton("🏆 Natijalarim"),
        types.KeyboardButton("📊 Statistika")
    )
    if is_admin:
        kb.add(types.KeyboardButton("🔧 Admin Panel"))
    return kb


def build_admin_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("📋 Ko'p savol yuborish"),
        types.KeyboardButton("✏️ Bitta savol qo'shish")
    )
    kb.add(
        types.KeyboardButton("🗑 Savollarni tozalash"),
        types.KeyboardButton("📚 Savollar soni")
    )
    kb.add(
        types.KeyboardButton("👥 Foydalanuvchilar"),
        types.KeyboardButton("🏠 Asosiy menyu")
    )
    return kb


def build_question_markup(options: list):
    labels = ["A", "B", "C", "D"]
    keyboard = []
    for i, opt in enumerate(options):
        keyboard.append([types.InlineKeyboardButton(
            text=f"{labels[i]}) {opt}",
            callback_data=f"ans_{i}"
        )])
    keyboard.append([types.InlineKeyboardButton(
        text="❌ Testni to'xtatish",
        callback_data="stop_quiz"
    )])
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_cancel_markup():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Bekor qilish"))
    return kb


# ─── /start ──────────────────────────────────────────────────────────────────

@dp.message_handler(commands=["start", "bekor"], state="*")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.finish()
    register_user(message.from_user)
    is_admin = message.from_user.id == ADMIN_ID
    total = get_total_questions()
    if total == 0:
        await message.answer(
            "👋 Salom! Hozircha savollar bazasi bo'sh.\n"
            "Admin savollar qo'shishi kerak.",
            parse_mode="HTML",
            reply_markup=build_main_menu(is_admin=is_admin)
        )
        return
    await message.answer(
        f"👋 Salom, <b>{message.from_user.full_name}</b>!\n\n"
        f"📚 Bazada jami <b>{total}</b> ta savol mavjud.\n"
        f"Qaysi qismdan boshlashni tanlang:",
        parse_mode="HTML",
        reply_markup=build_main_menu(is_admin=is_admin)
    )


# ─── QUIZ ────────────────────────────────────────────────────────────────────

@dp.message_handler(lambda m: m.text and "1-Qism" in m.text)
async def start_part1(message: types.Message, state: FSMContext):
    await start_quiz(message, state, part=1)


@dp.message_handler(lambda m: m.text and "2-Qism" in m.text)
async def start_part2(message: types.Message, state: FSMContext):
    await start_quiz(message, state, part=2)


async def start_quiz(message: types.Message, state: FSMContext, part: int):
    register_user(message.from_user)
    questions = get_questions_by_part(part)
    if not questions:
        await message.answer("❌ Bu qism uchun savollar topilmadi.")
        return
    await state.set_state(QuizState.in_quiz)
    await state.update_data(
        questions=questions,
        current=0,
        score=0,
        part=part,
        wrong_answers=[]
    )
    await message.answer(
        f"🚀 <b>{part}-Qism Test boshlanmoqda!</b>\n"
        f"Jami: <b>{len(questions)}</b> ta savol\n\n"
        f"Har bir savol uchun to'g'ri variantni tanlang.",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await send_question(message.chat.id, state)


async def send_question(chat_id: int, state: FSMContext):
    data = await state.get_data()
    questions = data["questions"]
    current = data["current"]

    if current >= len(questions):
        await finish_quiz(chat_id, state)
        return

    q = questions[current]
    options = [q["correct_answer"], q["wrong1"], q["wrong2"], q["wrong3"]]
    random.shuffle(options)
    correct_index = options.index(q["correct_answer"])

    await state.update_data(options=options, correct_index=correct_index)

    total = len(questions)
    text = f"📌 <b>Savol {current + 1}/{total}</b>\n\n{q['question']}"
    await bot.send_message(chat_id, text, parse_mode="HTML",
                           reply_markup=build_question_markup(options))


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("ans_"), state=QuizState.in_quiz)
async def process_answer(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    chosen = int(callback.data.split("_")[1])
    correct_index = data["correct_index"]
    options = data["options"]
    current = data["current"]
    score = data["score"]
    questions = data["questions"]
    wrong_answers = data.get("wrong_answers", [])
    labels = ["A", "B", "C", "D"]

    if chosen == correct_index:
        score += 1
        result_text = f"✅ To'g'ri! <b>{labels[correct_index]}) {options[correct_index]}</b>"
    else:
        wrong_answers.append({
            "question": questions[current]["question"],
            "your_answer": options[chosen],
            "correct_answer": options[correct_index]
        })
        result_text = (
            f"❌ Noto'g'ri!\n"
            f"Sizniki: {labels[chosen]}) {options[chosen]}\n"
            f"To'g'ri: <b>{labels[correct_index]}) {options[correct_index]}</b>"
        )

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await bot.send_message(callback.from_user.id, result_text, parse_mode="HTML")
    current += 1
    await state.update_data(current=current, score=score, wrong_answers=wrong_answers)
    await send_question(callback.from_user.id, state)


@dp.callback_query_handler(lambda c: c.data == "stop_quiz", state=QuizState.in_quiz)
async def stop_quiz(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Test to'xtatildi")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await finish_quiz(callback.from_user.id, state, stopped=True)


async def finish_quiz(chat_id: int, state: FSMContext, stopped: bool = False):
    data = await state.get_data()
    score = data.get("score", 0)
    questions = data.get("questions", [])
    current = data.get("current", 0)
    wrong_answers = data.get("wrong_answers", [])
    part = data.get("part", 1)

    answered = current
    total = len(questions)
    percent = round((score / answered * 100) if answered > 0 else 0)

    save_result(chat_id, part, score, answered, percent)

    if percent >= 90:
        grade = "🥇 A'lo"
    elif percent >= 70:
        grade = "🥈 Yaxshi"
    elif percent >= 50:
        grade = "🥉 Qoniqarli"
    else:
        grade = "📉 Qoniqarsiz"

    header = f"⛔ Test to'xtatildi ({part}-Qism)" if stopped else f"🏁 {part}-Qism Test yakunlandi!"
    text = (
        f"<b>{header}</b>\n\n"
        f"📊 Natija: <b>{score}/{answered}</b> ({percent}%)\n"
        f"Baho: {grade}\n"
    )

    if wrong_answers:
        show_count = min(5, len(wrong_answers))
        text += f"\n❌ Xato javoblar: {len(wrong_answers)} ta\n"
        text += "\n<b>Xato javoblaringiz (birinchi 5 ta):</b>\n"
        for i, wa in enumerate(wrong_answers[:show_count]):
            text += (
                f"\n{i+1}. {wa['question']}\n"
                f"   Sizniki: ❌ {wa['your_answer']}\n"
                f"   To'g'ri: ✅ {wa['correct_answer']}\n"
            )

    is_admin = chat_id == ADMIN_ID
    await state.finish()
    await bot.send_message(chat_id, text, parse_mode="HTML",
                           reply_markup=build_main_menu(is_admin=is_admin))


# ─── NATIJALAR ───────────────────────────────────────────────────────────────

@dp.message_handler(lambda m: m.text == "🏆 Natijalarim")
async def show_my_results(message: types.Message):
    register_user(message.from_user)
    results = get_user_results(message.from_user.id)
    is_admin = message.from_user.id == ADMIN_ID
    if not results:
        await message.answer(
            "📭 Siz hali hech qanday test yechmagansiz.\n"
            "Testni boshlash uchun quyidagi tugmalardan birini tanlang.",
            reply_markup=build_main_menu(is_admin=is_admin)
        )
        return

    text = "🏆 <b>Sizning so'nggi natijalatingiz:</b>\n\n"
    for i, r in enumerate(results, 1):
        if r["percent"] >= 90:
            icon = "🥇"
        elif r["percent"] >= 70:
            icon = "🥈"
        elif r["percent"] >= 50:
            icon = "🥉"
        else:
            icon = "📉"
        date = r["finished_at"][:10] if r["finished_at"] else ""
        text += (
            f"{i}. {icon} <b>{r['part']}-Qism</b> — "
            f"{r['score']}/{r['total']} ({r['percent']}%) — {date}\n"
        )

    total_attempts = len(results)
    best = max(results, key=lambda x: x["percent"])
    text += (
        f"\n📈 Jami urinish: <b>{total_attempts}</b> ta\n"
        f"🏅 Eng yaxshi natija: <b>{best['percent']}%</b> ({best['part']}-Qism)"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=build_main_menu(is_admin=is_admin))


# ─── STATISTIKA ──────────────────────────────────────────────────────────────

@dp.message_handler(lambda m: m.text == "📊 Statistika")
async def show_stats(message: types.Message):
    register_user(message.from_user)
    total = get_total_questions()
    half = total // 2
    text = (
        f"📊 <b>Umumiy statistika</b>\n\n"
        f"📚 Bazadagi savollar: <b>{total}</b> ta\n"
        f"  — 1-Qism: <b>{half}</b> ta\n"
        f"  — 2-Qism: <b>{total - half}</b> ta"
    )
    await message.answer(text, parse_mode="HTML")


# ─── ADMIN PANEL ─────────────────────────────────────────────────────────────

@dp.message_handler(commands=["admin"])
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Sizda admin huquqi yo'q.")
        return
    await message.answer(
        "🔧 <b>Admin Panel</b>\n\nQuyidagi tugmalardan foydalaning:",
        parse_mode="HTML",
        reply_markup=build_admin_menu()
    )


@dp.message_handler(lambda m: m.text == "🔧 Admin Panel")
async def admin_panel_button(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "🔧 <b>Admin Panel</b>\n\nQuyidagi tugmalardan foydalaning:",
        parse_mode="HTML",
        reply_markup=build_admin_menu()
    )


@dp.message_handler(lambda m: m.text == "🏠 Asosiy menyu")
async def back_to_main(message: types.Message):
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer("Asosiy menyuga qaytildi.", reply_markup=build_main_menu(is_admin=is_admin))


@dp.message_handler(lambda m: m.text == "👥 Foydalanuvchilar")
async def admin_users(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    total_u = get_total_users()
    await message.answer(
        f"👥 Jami foydalanuvchilar: <b>{total_u}</b> ta",
        parse_mode="HTML"
    )


@dp.message_handler(lambda m: m.text == "📚 Savollar soni")
async def admin_questions_count(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    total_q = get_total_questions()
    half = total_q // 2
    await message.answer(
        f"📚 Jami savollar: <b>{total_q}</b> ta\n"
        f"  — 1-Qism: <b>{half}</b> ta\n"
        f"  — 2-Qism: <b>{total_q - half}</b> ta",
        parse_mode="HTML"
    )


@dp.message_handler(lambda m: m.text == "🗑 Savollarni tozalash")
async def admin_clear(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Ha, o'chirish", callback_data="confirm_clear"),
        types.InlineKeyboardButton("❌ Yo'q", callback_data="cancel_clear")
    )
    await message.answer(
        "⚠️ Haqiqatan ham <b>barcha savollarni</b> o'chirmoqchimisiz?",
        parse_mode="HTML", reply_markup=kb
    )


@dp.callback_query_handler(lambda c: c.data == "confirm_clear")
async def do_clear(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    conn = get_db()
    conn.execute("DELETE FROM questions")
    conn.commit()
    conn.close()
    await callback.message.edit_text("✅ Barcha savollar o'chirildi.")


@dp.callback_query_handler(lambda c: c.data == "cancel_clear")
async def cancel_clear(callback: types.CallbackQuery):
    await callback.message.edit_text("❌ Bekor qilindi.")


# ─── SAVOL QO'SHISH (MATN ORQALI) ────────────────────────────────────────────

@dp.message_handler(lambda m: m.text == "📋 Ko'p savol yuborish")
async def start_bulk_add(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(BulkAdd.waiting_text)
    await message.answer(
        "📋 <b>Ko'p savol yuborish</b>\n\n"
        "Quyidagi formatda barcha savollarni <b>bitta xabarda</b> yuboring:\n\n"
        "<code>1. Savol matni?\n"
        "A) To'g'ri javob\n"
        "B) Noto'g'ri variant\n"
        "C) Noto'g'ri variant\n"
        "D) Noto'g'ri variant\n"
        "To'g'ri javob: A\n\n"
        "2. Keyingi savol?\n"
        "A) ...\n"
        "...</code>\n\n"
        "✅ To'g'ri javob <b>A, B, C yoki D</b> harfi bilan belgilanadi.\n"
        "❌ Bekor qilish uchun tugmani bosing.",
        parse_mode="HTML",
        reply_markup=build_cancel_markup()
    )


@dp.message_handler(state=BulkAdd.waiting_text)
async def process_bulk_text(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.strip()
    await message.answer("⏳ Savollar tahlil qilinmoqda...")
    try:
        questions = parse_bulk_text(text)
        if not questions:
            await message.answer(
                "❌ Hech qanday savol topilmadi!\n\n"
                "<b>Quyidagi formatlardan birida yuboring:</b>\n\n"
                "📌 <b>1-format (standart):</b>\n"
                "<code>1. Savol matni?\n"
                "A) To'g'ri javob\n"
                "B) Noto'g'ri\n"
                "C) Noto'g'ri\n"
                "D) Noto'g'ri\n"
                "Javob: A</code>\n\n"
                "📌 <b>2-format (yulduzcha):</b>\n"
                "<code>1. Savol matni?\n"
                "A) To'g'ri javob\n"
                "B) Noto'g'ri\n"
                "C) Noto'g'ri\n"
                "D) Noto'g'ri\n"
                "* A</code>\n\n"
                "⚠️ <b>Muhim:</b>\n"
                "— Har bir savol raqam va nuqta bilan boshlansin: <code>1.</code>\n"
                "— Variantlar: <code>A)</code> yoki <code>A.</code>\n"
                "— To'g'ri javob: <code>Javob: A</code> yoki <code>* A</code>",
                parse_mode="HTML",
                reply_markup=build_cancel_markup()
            )
            return
        bulk_save_to_db(questions)
        total = get_total_questions()
        await state.finish()
        await message.answer(
            f"✅ <b>{len(questions)} ta savol muvaffaqiyatli qo'shildi!</b>\n\n"
            f"📚 Bazada jami: <b>{total}</b> ta savol\n"
            f"📌 1-Qism: <b>{total // 2}</b> ta\n"
            f"📌 2-Qism: <b>{total - total // 2}</b> ta",
            parse_mode="HTML",
            reply_markup=build_admin_menu()
        )
    except Exception as e:
        logger.error(f"Bulk parse xatosi: {e}")
        await state.finish()
        await message.answer(f"❌ Xatolik: {e}", reply_markup=build_admin_menu())


@dp.message_handler(lambda m: m.text == "✏️ Bitta savol qo'shish")
async def start_add_question(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(AddQuestion.waiting_question)
    await message.answer(
        "✏️ <b>Yangi savol qo'shish</b>\n\n"
        "1️⃣ Savol matnini yozing:\n"
        "<i>(Bekor qilish uchun ❌ Bekor qilish tugmasini bosing)</i>",
        parse_mode="HTML",
        reply_markup=build_cancel_markup()
    )


@dp.message_handler(lambda m: m.text == "❌ Bekor qilish", state="*")
async def cancel_add(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("❌ Bekor qilindi.", reply_markup=build_admin_menu())


@dp.message_handler(state=AddQuestion.waiting_question)
async def got_question(message: types.Message, state: FSMContext):
    await state.update_data(question=message.text.strip())
    await state.set_state(AddQuestion.waiting_correct)
    await message.answer(
        "2️⃣ <b>To'g'ri javobni</b> yozing:",
        parse_mode="HTML"
    )


@dp.message_handler(state=AddQuestion.waiting_correct)
async def got_correct(message: types.Message, state: FSMContext):
    await state.update_data(correct=message.text.strip())
    await state.set_state(AddQuestion.waiting_wrong1)
    await message.answer("3️⃣ <b>1-noto'g'ri variant</b>ni yozing:", parse_mode="HTML")


@dp.message_handler(state=AddQuestion.waiting_wrong1)
async def got_wrong1(message: types.Message, state: FSMContext):
    await state.update_data(wrong1=message.text.strip())
    await state.set_state(AddQuestion.waiting_wrong2)
    await message.answer("4️⃣ <b>2-noto'g'ri variant</b>ni yozing:", parse_mode="HTML")


@dp.message_handler(state=AddQuestion.waiting_wrong2)
async def got_wrong2(message: types.Message, state: FSMContext):
    await state.update_data(wrong2=message.text.strip())
    await state.set_state(AddQuestion.waiting_wrong3)
    await message.answer("5️⃣ <b>3-noto'g'ri variant</b>ni yozing:", parse_mode="HTML")


@dp.message_handler(state=AddQuestion.waiting_wrong3)
async def got_wrong3(message: types.Message, state: FSMContext):
    await state.update_data(wrong3=message.text.strip())
    data = await state.get_data()

    add_question_to_db(
        data["question"],
        data["correct"],
        data["wrong1"],
        data["wrong2"],
        data["wrong3"]
    )

    total = get_total_questions()
    await state.finish()
    await message.answer(
        f"✅ <b>Savol muvaffaqiyatli qo'shildi!</b>\n\n"
        f"📝 Savol: {data['question']}\n"
        f"✅ To'g'ri: {data['correct']}\n"
        f"❌ Noto'g'ri: {data['wrong1']}, {data['wrong2']}, {data['wrong3']}\n\n"
        f"📚 Bazada jami: <b>{total}</b> ta savol",
        parse_mode="HTML",
        reply_markup=build_admin_menu()
    )


# ─── DOCX YUBORISH ───────────────────────────────────────────────────────────

@dp.message_handler(commands=["parse_docx"])
async def cmd_parse_docx(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Sizda admin huquqi yo'q.")
        return
    docx_path = os.path.join(os.path.dirname(__file__), "savollar.docx")
    if not os.path.exists(docx_path):
        await message.answer("❌ <code>savollar.docx</code> fayl topilmadi!", parse_mode="HTML")
        return
    await message.answer("⏳ o'qilmoqda...")
    try:
        from parse_docx import parse_and_save
        count = parse_and_save(docx_path, DB_PATH)
        await message.answer(
            f"✅ <b>{count}</b> ta savol bazaga yozildi.",
            parse_mode="HTML", reply_markup=build_main_menu(is_admin=True)
        )
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")


@dp.message_handler(content_types=types.ContentType.DOCUMENT)
async def receive_docx(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Faqat admin fayl yuborishi mumkin.")
        return
    doc = message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".docx"):
        await message.answer("❌ Faqat <b>.docx</b> formatidagi fayl qabul qilinadi.", parse_mode="HTML")
        return
    await message.answer("⏳ Fayl qabul qilindi, o'qilmoqda...")
    docx_path = os.path.join(os.path.dirname(__file__), "savollar.docx")
    try:
        file = await bot.get_file(doc.file_id)
        await bot.download_file(file.file_path, destination=docx_path)
        from parse_docx import parse_and_save
        count = parse_and_save(docx_path, DB_PATH)
        await message.answer(
            f"✅ <b>{count}</b> ta savol bazaga yozildi.\n\n"
            f"📌 1-Qism: <b>{count // 2}</b> ta\n"
            f"📌 2-Qism: <b>{count - count // 2}</b> ta",
            parse_mode="HTML", reply_markup=build_main_menu(is_admin=True)
        )
    except Exception as e:
        logger.error(f"Fayl yuklashda xatolik: {e}")
        await message.answer(f"❌ Xatolik: {e}")


# ─── FALLBACKS ───────────────────────────────────────────────────────────────

@dp.message_handler(state=QuizState.in_quiz)
async def ignore_text_in_quiz(message: types.Message):
    await message.answer("⚠️ Test davom etmoqda. Iltimos, variantni tanlang.")


@dp.message_handler()
async def unknown_message(message: types.Message):
    register_user(message.from_user)
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer("ℹ️ /start bosing.", reply_markup=build_main_menu(is_admin=is_admin))


# ─── MAIN ────────────────────────────────────────────────────────────────────

def run_web_server():
    port = int(os.environ.get("PORT", 8000))

    class PingHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot ishlayapti!")

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()


if __name__ == "__main__":
    init_db()
    t = threading.Thread(target=run_web_server, daemon=True)
    t.start()
    logger.info("Bot ishga tushmoqda...")
    executor.start_polling(dp, skip_updates=True)
