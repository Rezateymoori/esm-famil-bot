# bot.py — نسخهٔ نهایی کامل
# پیش‌نیاز: python-telegram-bot==20.5 , Python 3.10+
import os
import json
import random
import logging
from collections import defaultdict
from difflib import get_close_matches
from typing import Dict, Any, Set

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== پیکربندی ==========
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

# ========== وضعیت‌ها ==========
games: Dict[int, Dict[str, Any]] = defaultdict(dict)
user_active_category: Dict[int, Dict[int, str]] = defaultdict(dict)
activated_users: Set[int] = set()

# ========== بارگذاری JSON ==========
def load_json_set(path: str) -> Set[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(x.strip() for x in data if isinstance(x, str) and x.strip())
            return set()
    except FileNotFoundError:
        logger.warning("فایل پیدا نشد: %s", path)
        return set()
    except Exception as e:
        logger.exception("خطا در خواندن JSON %s: %s", path, e)
        return set()

VALID_MAP: Dict[str, Set[str]] = {}
for cat, fname in CATEGORY_FILES.items():
    VALID_MAP[cat] = load_json_set(os.path.join(DATA_PATH, fname))

# ========== ابزار fuzzy ==========
def fuzzy_check(ans: str, valid_set: Set[str]):
    if not ans or not valid_set:
        return False, ""
    matches = get_close_matches(ans, list(valid_set), n=1, cutoff=0.75)
    if matches:
        return True, matches[0]
    return False, ""

# ========== UI فارسی ==========
def build_lobby_text(chat_id: int) -> str:
    g = games.get(chat_id, {})
    players = g.get("players", [])
    text = "🎲 *ربات اسم‌فامیل — نسخه پیشرفته*\n\n"
    text += "👥 *بازیکنان:* \n"
    if not players:
        text += "— هنوز کسی وارد نشده —\n"
    else:
        for i, (_, name) in enumerate(players, start=1):
            text += f"{i}. {name}\n"
    text += "\n━━━━━━━━━━━━\n"
    text += "➕ ورود به بازی\n🚀 هر کسی می‌تواند دور را شروع کند\n"
    return text

def build_lobby_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ورود به بازی", callback_data="join")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help")],
        [InlineKeyboardButton("🚀 شروع دور", callback_data="startgame")],
        [InlineKeyboardButton("📋 جدول امتیازات", callback_data="show_scores")]
    ])

def build_category_keyboard(chat_id: int, user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for cat in CATEGORIES:
        rows.append([InlineKeyboardButton(cat, callback_data=f"pickcat:{chat_id}:{user_id}:{cat}")])
    rows.append([InlineKeyboardButton("❌ لغو انتخاب", callback_data=f"pickcat:{chat_id}:{user_id}:__cancel__")])
    return InlineKeyboardMarkup(rows)

# ========== Handlers ==========
async def start_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    activated_users.add(user.id)
    await update.message.reply_text(
        "👋 شما فعال شدید. اکنون ربات می‌تواند برای برخی اعلان‌ها به شما پیام خصوصی ارسال کند."
    )

async def efstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور فقط در گروه کاربرد دارد.")
        return
    chat_id = chat.id
    user = update.effective_user

    g = games.setdefault(chat_id, {})
    g.setdefault("players", [])
    g.setdefault("total_scores", {})
    g["owner"] = user.id

    text = build_lobby_text(chat_id)
    msg = await update.message.reply_text(text, reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
    g["lobby_message_id"] = msg.message_id

async def lobby_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat.id
    user = query.from_user

    g = games.setdefault(chat_id, {})
    g.setdefault("players", [])
    g.setdefault("total_scores", {})

    if data == "join":
        if any(uid == user.id for uid, _ in g["players"]):
            await context.bot.send_message(chat_id=chat_id, text=f"✅ {user.full_name}، شما قبلاً وارد شده‌اید.")
            return
        g["players"].append((user.id, user.full_name))
        g["total_scores"].setdefault(user.id, 0)
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=g.get("lobby_message_id"),
                text=build_lobby_text(chat_id),
                reply_markup=build_lobby_keyboard(),
                parse_mode="Markdown"
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=build_lobby_text(chat_id),
                reply_markup=build_lobby_keyboard(),
                parse_mode="Markdown"
            )
    elif data == "help":
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "📖 *راهنما:*\n"
                "1. هر کسی می‌تواند /efstart را اجرا و دور را شروع کند.\n"
                "2. بازیکنان با زدن «ورود به بازی» وارد می‌شوند.\n"
                "3. بعد از شروع دور، برای انتخاب دسته از دکمهٔ «انتخاب دسته» استفاده کنید؛ سپس جواب را در گروه ارسال کنید — پیام حذف و پاسخ ذخیره می‌شود.\n"
                "4. جواب‌های ناشناخته توسط ربات داوری می‌شوند و در صورت نیاز پی‌وی به شما ارسال می‌شود.\n"
            ),
            parse_mode="Markdown"
        )
    elif data == "show_scores":
        if not g.get("players"):
            await context.bot.send_message(chat_id=chat_id, text="هیچ امتیازی هنوز ثبت نشده.")
            return
        text = "📊 جدول امتیازات کلی:\n"
        for uid, name in g["players"]:
            text += f"- {name}: {g.get('total_scores', {}).get(uid, 0)}\n"
        await context.bot.send_message(chat_id=chat_id, text=text)
    elif data == "startgame":
        if not g.get("players"):
            await context.bot.send_message(chat_id=chat_id, text="⛔ هیچ بازیکنی وجود ندارد. حداقل یک بازیکن لازم است.")
            return

        g["active"] = True
        g["letter"] = random.choice(LETTERS)
        g["state_index"] = 0
        g["answers_by_user"] = defaultdict(dict)
        g["finish_order"] = []

        await context.bot.send_message(
            chat_id=chat_id,
            text=(f"🚀 *دور جدید شروع شد!*\n🔤 *حرف این دور:* «{g['letter']}»\n\n"
                  "برای ارسال پاسخ: ابتدا از دکمهٔ «انتخاب دسته» دستهٔ موردنظر را انتخاب کنید، سپس جواب را در گروه بفرستید (پیام شما حذف خواهد شد)."),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗂 انتخاب دسته", callback_data=f"open_catkbd:{chat_id}")]
            ]),
            parse_mode="Markdown"
        )

        # پایان خودکار دور بعد از ROUND_TIME
        context.application.job_queue.run_once(end_round_timeout, ROUND_TIME, chat_id=str(chat_id))

async def category_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split(":")
    if len(parts) != 4:
        return
    _, chat_id_str, user_id_str, cat = parts
    chat_id = int(chat_id_str)
    user_id = int(user_id_str)
    g = games.get(chat_id, {})
    if cat == "__cancel__":
        await query.message.delete()
        return
    user_active_category[user_id][chat_id] = cat
    await query.message.delete()
    await context.bot.send_message(chat_id=chat_id, text=f"✅ {cat} انتخاب شد. اکنون پاسخ را ارسال کنید.")

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat.id
    user = msg.from_user
    g = games.get(chat_id)
    if not g or not g.get("active"):
        return
    if user.id not in [uid for uid, _ in g["players"]]:
        return
    cat = user_active_category.get(user.id, {}).get(chat_id)
    if not cat:
        return
    answer = msg.text.strip()
    await msg.delete()  # حذف پیام کاربر

    valid_set = VALID_MAP.get(cat, set())
    ok, matched = fuzzy_check(answer, valid_set)
    g["answers_by_user"][user.id][cat] = matched if ok else answer

    # بررسی پایان دور برای یک بازیکن (تمام دسته‌ها جواب داده شده)
    if all(c in g["answers_by_user"][user.id] for c in CATEGORIES):
        g["finish_order"].append(user.id)
        await context.bot.send_message(chat_id=chat_id, text=f"🎯 {user.full_name} همه دسته‌ها را پاسخ داد!")
        # پایان دور برای همه
        g["active"] = False
        text = "🏁 دور پایان یافت!\n📊 امتیازات:\n"
        for uid, name in g["players"]:
            total = len(g["answers_by_user"].get(uid, {}))
            g["total_scores"][uid] += total
            text += f"- {name}: {g['total_scores'].get(uid,0)}\n"
        await context.bot.send_message(chat_id=chat_id, text=text)

async def end_round_timeout(context: ContextTypes.DEFAULT_TYPE):
    chat_id = int(context.job.chat_id)
    g = games.get(chat_id)
    if g and g.get("active"):
        g["active"] = False
        text = "⏰ زمان دور به پایان رسید!\n📊 امتیازات فعلی:\n"
        for uid, name in g["players"]:
            total = len(g["answers_by_user"].get(uid, {}))
            g["total_scores"][uid] += total
            text += f"- {name}: {g['total_scores'].get(uid,0)}\n"
        await context.bot.send_message(chat_id=chat_id, text=text)

async def leave_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    g = games.get(chat_id)
    if not g or "players" not in g:
        return
    g["players"] = [(uid,name) for uid,name in g["players"] if uid != user.id]
    g["total_scores"].pop(user.id, None)
    await update.message.reply_text("✅ شما از بازی خارج شدید.")
    # بروزرسانی لابی
    if "lobby_message_id" in g:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=g["lobby_message_id"],
            text=build_lobby_text(chat_id),
            reply_markup=build_lobby_keyboard(),
            parse_mode="Markdown"
        )

# ========== اجرای ربات ==========
def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("توکن ربات پیدا نشد!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # دستورات
    app.add_handler(CommandHandler("start", start_private))
    app.add_handler(CommandHandler("efstart", efstart))
    app.add_handler(CommandHandler("leave", leave_game))
    # callback buttons
    app.add_handler(CallbackQueryHandler(lobby_button_handler, pattern="^(join|help|startgame|show_scores)$"))
    app.add_handler(CallbackQueryHandler(category_button_handler, pattern="^pickcat:"))

    # پیام‌های گروه
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_group_message))

    logger.info("Running polling...")
    app.run_polling()

if __name__ == "__main__":
    main()