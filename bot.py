# bot.py
import os
import json
import random
import logging
import time
from collections import Counter, defaultdict
from difflib import get_close_matches

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ForceReply,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- تنظیمات ----------
DATA_PATH = "data"
CATEGORY_FILES = {
    "نام": "names.json",
    "فامیل": "families.json",
    "شهر": "cities.json",
    "کشور": "countries.json",
    "حیوان": "animals.json",
    "غذا": "foods.json",
    "رنگ": "colors.json",
}

CATEGORIES = list(CATEGORY_FILES.keys())
ROUND_TIME = 60
LETTERS = list("ابتثجچحخدذرزژسشصضطظعغفقکگلمنوهی")

games = defaultdict(dict)

# ---------- بارگذاری JSON ----------
def load_json_set(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(x.strip() for x in data if isinstance(x, str) and x.strip())
            else:
                return set()
    except FileNotFoundError:
        logger.warning("فایل JSON پیدا نشد: %s", path)
        return set()
    except Exception as e:
        logger.exception("خطا در خواندن %s: %s", path, e)
        return set()

def save_json_list(path: str, items: set):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(list(items)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("خطا در نوشتن %s: %s", path, e)

def build_valid_map():
    vm = {}
    for cat, fname in CATEGORY_FILES.items():
        path = os.path.join(DATA_PATH, fname)
        vm[cat] = load_json_set(path)
    return vm

VALID_MAP = build_valid_map()

def fuzzy_check(ans: str, valid_set: set):
    if not ans or not valid_set:
        return False, ""
    matches = get_close_matches(ans, valid_set, n=1, cutoff=0.75)
    return (True, matches[0]) if matches else (False, "")

# ---------- رابط کاربری ----------
def build_lobby_text(chat_id: int) -> str:
    g = games[chat_id]
    players = g.get("players", [])
    text = "🎲 *ربات بازی اسم‌فامیل — حالت گروهی*\n\n"
    text += "👥 *بازیکنان:*\n"
    if not players:
        text += "— هنوز کسی وارد نشده —\n"
    else:
        for i, (_, name) in enumerate(players, start=1):
            text += f"{i}. {name}\n"
    text += "\n━━━━━━━━━━━━\n"
    text += "برای ورود روی «➕ ورود به بازی» بزنید.\n"
    text += "فقط سازنده می‌تواند بازی را شروع کند.\n"
    return text

def build_lobby_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ورود به بازی", callback_data="join")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help")],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data="startgame")],
    ])

# ---------- فرمان /efstart ----------
async def efstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name

    g = games[chat_id]
    g.setdefault("players", [])
    g.setdefault("total_scores", {})
    g["owner"] = user_id

    msg = await update.message.reply_text(
        build_lobby_text(chat_id),
        reply_markup=build_lobby_keyboard(),
        parse_mode="Markdown"
    )
    g["lobby_message_id"] = msg.message_id
    await update.message.reply_text("لطفاً دیگران را دعوت کنید؛ وقتی آماده بودید «شروع بازی» را بزنید.")

# ---------- هندلر دکمه‌های لابی ----------
async def lobby_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    user_name = query.from_user.full_name
    data = query.data

    g = games[chat_id]
    g.setdefault("players", [])
    g.setdefault("total_scores", {})

    if data == "join":
        if any(uid == user_id for uid, _ in g["players"]):
            await context.bot.send_message(chat_id=chat_id, text=f"✅ {user_name}، شما قبلاً وارد شده‌اید.")
            return
        g["players"].append((user_id, user_name))
        g["total_scores"].setdefault(user_id, 0)
        try:
            if "lobby_message_id" in g:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=g["lobby_message_id"],
                    text=build_lobby_text(chat_id),
                    reply_markup=build_lobby_keyboard(),
                    parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard())
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard())

    elif data == "help":
        await context.bot.send_message(chat_id=chat_id, text=(
            "📖 *راهنمای بازی:* \n"
            "1. سازنده /efstart را اجرا و سپس «شروع بازی» را می‌زند.\n"
            "2. بازیکن‌ها با «ورود به بازی» وارد می‌شوند.\n"
            "3. بعد از شروع، ربات حرف را اعلام می‌کند و دسته‌ها را یکی‌یکی جلو می‌برد.\n"
            "4. اگر جوابی در فایل JSON نبود، برای سازنده ارسال می‌شود تا تأیید کند.\n"
            "5. پس از تأیید دستی، جواب به JSON اضافه می‌شود."
        ), parse_mode="Markdown")

    elif data == "startgame":
        owner = g.get("owner")
        if owner != user_id:
            await context.bot.send_message(chat_id=chat_id, text="⛔ فقط سازنده‌ی بازی می‌تواند شروع کند.")
            return
        if not g.get("players"):
            await context.bot.send_message(chat_id=chat_id, text="⛔ هیچ بازیکنی وجود ندارد.")
            return

        g["letter"] = random.choice(LETTERS)
        g["active"] = True
        g["locked"] = False
        g["start_time"] = time.time()
        g["finish_order"] = []
        g["player_data"] = {}
        g["answers"] = {}
        g["answers_by_user"] = {}
        g["state_index"] = 0   # 👈 مقداردهی اولیه دسته اول

        for uid, uname in g["players"]:
            g["player_data"][uid] = {"answers": {}, "finished": False, "finish_time": None}

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🚀 بازی شروع شد!\n🔤 حرف این دور: «{g['letter']}»\n\n✍️ دستهٔ اول: {CATEGORIES[0]}",
            reply_markup=ForceReply(selective=False)
        )

        job = context.application.job_queue.run_once(end_round_timeout, ROUND_TIME, chat_id=str(chat_id))
        g["job"] = job

        await context.bot.send_message(chat_id=chat_id, text=f"⏱ زمان هر دسته: {ROUND_TIME} ثانیه")

# ---------- بررسی اتمام دسته ----------
async def check_category_completion(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    g = games.get(chat_id)
    if not g:
        return
    idx = g.get("state_index", 0)
    cat_name = CATEGORIES[idx]
    all_checked = True
    for uid, _ in g.get("players", []):
        user_ans_map = g.get("answers_by_user", {}).get(uid, {})
        status = user_ans_map.get(cat_name, {}).get("valid")
        if status is None:
            all_checked = False
            break

    if all_checked:
        g["state_index"] = idx + 1
        if g["state_index"] < len(CATEGORIES):
            next_cat = CATEGORIES[g["state_index"]]
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✍️ دستهٔ بعدی: {next_cat}",
                reply_markup=ForceReply(selective=False)
            )
        else:
            await finish_game(context, chat)