# bot.py — نسخهٔ کامل و نهایی
# پیش‌نیاز: python-telegram-bot==20.5 , Python 3.10+
import os
import json
import random
import logging
from collections import defaultdict
from difflib import get_close_matches
from typing import Dict, Any, Set

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

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
ROUND_TIME = 60  # ثانیه
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

def save_json_list(path: str, items: Set[str]):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(list(items)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("خطا در نوشتن JSON %s: %s", path, e)

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
    text += "➕ ورود به بازی\n🚀 هر کسی می‌تواند دور را شروع کند"
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

# ========== هندلرها ==========
async def start_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    activated_users.add(user.id)
    await update.message.reply_text(
        "👋 شما فعال شدید. ربات می‌تواند برای اعلان‌ها به شما پیام بدهد."
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

    text = build_lobby_text(chat_id)
    msg = await update.message.reply_text(text, reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
    g["lobby_message_id"] = msg.message_id
    await update.message.reply_text("لطفاً دیگران را دعوت کنید؛ وقتی آماده بودید «شروع دور» را بزنید.")

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
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=g["lobby_message_id"],
            text=build_lobby_text(chat_id),
            reply_markup=build_lobby_keyboard(),
            parse_mode="Markdown"
        )
    elif data == "help":
        await context.bot.send_message(chat_id=chat_id, text="📖 راهنما: /efstart → ورود → شروع دور → انتخاب دسته → جواب", parse_mode="Markdown")
    elif data == "show_scores":
        text = "📊 جدول امتیازات کلی:\n"
        for uid, name in g["players"]:
            text += f"- {name}: {g.get('total_scores', {}).get(uid, 0)}\n"
        await context.bot.send_message(chat_id=chat_id, text=text)
    elif data == "startgame":
        if not g.get("players"):
            await context.bot.send_message(chat_id=chat_id, text="⛔ هیچ بازیکنی وجود ندارد.")
            return
        g["active"] = True
        g["letter"] = random.choice(LETTERS)
        g["answers_by_user"] = {}
        g["finish_order"] = []

        await context.bot.send_message(
            chat_id=chat_id,
            text=(f"🚀 دور جدید شروع شد!\n🔤 حرف این دور: «{g['letter']}»\n\n"
                  "برای ارسال پاسخ: ابتدا از دکمهٔ «انتخاب دسته» دسته را انتخاب کنید، سپس جواب را ارسال کنید."),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗂 انتخاب دسته", callback_data=f"open_catkbd:{chat_id}")]]),
            parse_mode="Markdown"
        )

async def pick_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 4:
        return
    _, chat_id_str, user_id_str, cat = parts
    chat_id, user_id = int(chat_id_str), int(user_id_str)
    if cat == "__cancel__":
        await query.edit_message_text("❌ انتخاب دسته لغو شد.")
        return
    user_active_category[user_id][chat_id] = cat
    await query.edit_message_text(f"✅ دستهٔ «{cat}» انتخاب شد. اکنون جواب خود را ارسال کنید.")

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    g = games.get(chat_id, {})
    if not g.get("active"):
        return
    cat = user_active_category.get(user_id, {}).get(chat_id)
    if not cat:
        return
    ans = msg.text.strip()
    await msg.delete()
    valid_set = VALID_MAP.get(cat, set())
    is_valid, canonical = fuzzy_check(ans, valid_set)
    if is_valid:
        g.setdefault("answers_by_user", {}).setdefault(user_id, {})[cat] = canonical
    else:
        owner_id = g.get("players", [])[0][0] if g.get("players") else None
        if owner_id and owner_id in activated_users:
            await context.bot.send_message(owner_id, f"⚠️ جواب مشکوک از {msg.from_user.full_name} برای دسته {cat}: {ans}")
    # بررسی اتمام دور برای بازیکن
    player_answers = g["answers_by_user"].get(user_id, {})
    if len(player_answers) == len(CATEGORIES):
        g["finish_order"].append(user_id)
        # دور تمام می‌شود
        g["active"] = False
        text = "🏁 دور تمام شد!\n\nامتیازات:\n"
        for uid, name in g["players"]:
            score = len(g["answers_by_user"].get(uid, {}))
            g["total_scores"][uid] += score
            text += f"- {name}: {g['total_scores'][uid]}\n"
        await context.bot.send_message(chat_id=chat_id, text=text)

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN تعریف نشده است!")
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start_private))
    app.add_handler(CommandHandler("efstart", efstart))
    app.add_handler(CallbackQueryHandler(lobby_button_handler, pattern="^(join|help|startgame|show_scores)$"))
    app.add_handler(CallbackQueryHandler(pick_category_handler, pattern="^pickcat:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_message))

    logger.info("RUNNING POLLING...")
    app.run_polling()

if __name__ == "__main__":
    main()