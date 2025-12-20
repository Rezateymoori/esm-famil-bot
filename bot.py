# bot.py — نسخهٔ کامل نهایی
import os
import json
import random
import logging
from collections import defaultdict
from difflib import get_close_matches
from typing import Dict, Any, Set

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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

# ========== وضعیت ==========
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
    text += "➕ ورود به بازی\n🚀 شروع دور برای کسی است که دستور /efstart را زده"
    return text

def build_lobby_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ورود به بازی", callback_data="join")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help")],
        [InlineKeyboardButton("🚀 شروع دور", callback_data="startgame")],
        [InlineKeyboardButton("📋 جدول امتیازات", callback_data="show_scores")]
    ])

def build_category_keyboard(chat_id: int, user_id: int):
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
    await update.message.reply_text("👋 شما فعال شدید. ربات می‌تواند پیام خصوصی ارسال کند.")

async def efstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور فقط در گروه کاربرد دارد.")
        return
    chat_id = chat.id
    user = update.effective_user

    # ریست بازی قبلی
    g = games.setdefault(chat_id, {})
    g["owner"] = user.id
    g.setdefault("players", [])
    g.setdefault("total_scores", {})

    text = build_lobby_text(chat_id)
    try:
        msg = await update.message.reply_text(text, reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
        g["lobby_message_id"] = msg.message_id
    except Exception:
        await update.message.reply_text(text)

    await update.message.reply_text("لطفاً دیگران را دعوت کنید؛ کسی که /efstart را زده «شروع دور» خواهد بود.")

# ========== Callbacks ==========
async def lobby_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat = query.message.chat
    chat_id = chat.id
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
            if "lobby_message_id" in g:
                await context.bot.edit_message_text(chat_id=chat_id,
                    message_id=g["lobby_message_id"],
                    text=build_lobby_text(chat_id),
                    reply_markup=build_lobby_keyboard(),
                    parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")

    elif data == "help":
        await context.bot.send_message(chat_id=chat_id,
            text=("📖 *راهنما:*\n"
                  "1. هر کسی که /efstart را زد، بازی را شروع می‌کند.\n"
                  "2. بازیکنان با زدن «ورود به بازی» وارد می‌شوند.\n"
                  "3. برای ارسال جواب، ابتدا دسته را انتخاب کنید، سپس جواب را در گروه بفرستید — پیام حذف و پاسخ ذخیره می‌شود.\n"
                  "4. جواب‌های مشکوک به داور ارسال می‌شود."),
            parse_mode="Markdown")
    elif data == "show_scores":
        if not g.get("players"):
            await context.bot.send_message(chat_id=chat_id, text="هیچ امتیازی ثبت نشده.")
            return
        text = "📊 جدول امتیازات کلی:\n"
        for uid, name in g["players"]:
            text += f"- {name}: {g.get('total_scores', {}).get(uid, 0)}\n"
        await context.bot.send_message(chat_id=chat_id, text=text)

    elif data == "startgame":
        if user.id != g.get("owner"):
            await context.bot.send_message(chat_id=chat_id, text="⛔ فقط کسی که بازی را شروع کرده می‌تواند دور را آغاز کند.")
            return
        if not g.get("players"):
            await context.bot.send_message(chat_id=chat_id, text="⛔ حداقل یک بازیکن لازم است.")
            return

        g["active"] = True
        g["letter"] = random.choice(LETTERS)
        g["answers_by_user"] = {}
        g["finish_order"] = []

        try:
            await context.bot.send_message(chat_id=chat_id,
                text=(f"🚀 *دور جدید شروع شد!*\n"
                      f"🔤 *حرف این دور:* «{g['letter']}»\n\n"
                      "برای ارسال پاسخ: ابتدا از دکمهٔ «انتخاب دسته» دسته را انتخاب کنید، سپس جواب را در گروه بفرستید (پیام شما حذف خواهد شد)."),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗂 انتخاب دسته", callback_data=f"open_catkbd:{chat_id}")]]),
                parse_mode="Markdown"
            )
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=f"🚀 دور جدید شروع شد! حرف: «{g['letter']}»")

        job = context.application.job_queue.run_once(end_round_timeout, ROUND_TIME, chat_id=str(chat_id))
        g["job"] = job

# ========== مدیریت دسته و پیام‌های گروه ==========
async def pick_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("pickcat:"):
        return
    _, chat_id_str, user_id_str, cat = data.split(":")
    chat_id = int(chat_id_str)
    user_id = int(user_id_str)
    if query.from_user.id != user_id:
        await query.edit_message_text("⛔ شما نمی‌توانید دستهٔ دیگران را انتخاب کنید.")
        return
    if cat == "__cancel__":
        await query.edit_message_text("❌ انتخاب دسته لغو شد.")
        return
    user_active_category[user_id][chat_id] = cat
    await query.edit_message_text(f"✅ دسته '{cat}' انتخاب شد. اکنون جواب خود را در گروه ارسال کنید.")

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    user = msg.from_user
    g = games.get(chat_id)
    if not g or not g.get("active"):
        return
    if user.id not in user_active_category or chat_id not in user_active_category[user.id]:
        return
    cat = user_active_category[user.id][chat_id]
    ans = msg.text.strip()
    # حذف پیام گروه
    try:
        await msg.delete()
    except Exception:
        pass
    valid_set = VALID_MAP.get(cat, set())
    ok, match = fuzzy_check(ans, valid_set)
    if ok:
        g["answers_by_user"][user.id] = g["answers_by_user"].get(user.id, {})
        g["answers_by_user"][user.id][cat] = match
        g["total_scores"][user.id] = g["total_scores"].get(user.id, 0) + 10
        await context.bot.send_message(chat_id=user.id, text=f"✅ جواب '{ans}' پذیرفته شد. امتیاز +10")
    else:
        # ارسال به سازنده جهت تأیید
        owner_id = g.get("owner")
        if owner_id:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ قبول", callback_data=f"manual_ok:{chat_id}:{user.id}:{cat}:{ans}")],
                [InlineKeyboardButton("❌ رد", callback_data=f"manual_no:{chat_id}:{user.id}:{cat}:{ans}")]
            ])
            await context.bot.send_message(chat_id=owner_id,
                text=f"⚠️ جواب '{ans}' از {user.full_name} برای دسته {cat} مشکوک است. قبول/رد کنید.",
                reply_markup=keyboard
            )

async def manual_ok_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chat_id, user_id, cat, ans = query.data.split(":")
    chat_id = int(chat_id)
    user_id = int(user_id)
    g = games.get(chat_id)
    if not g:
        return
    g["answers_by_user"][user_id] = g["answers_by_user"].get(user_id, {})
    g["answers_by_user"][user_id][cat] = ans
    g["total_scores"][user_id] = g["total_scores"].get(user_id, 0) + 10
    await context.bot.send_message(chat_id=user_id, text=f"✅ جواب '{ans}' توسط سازنده پذیرفته شد. امتیاز +10")
    await query.edit_message_text("✅ جواب پذیرفته شد.")

async def manual_no_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chat_id, user_id, cat, ans = query.data.split(":")
    await query.edit_message_text("❌ جواب رد شد.")

async def end_round_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = int(job.chat_id)
    g = games.get(chat_id)
    if not g:
        return
    g["active"] = False
    text = "⏰ زمان دور تمام شد!\nنتایج:\n"
    for uid, name in g.get("players", []):
        score = g.get("total_scores", {}).get(uid, 0)
        text += f"- {name}: {score}\n"
    await context.bot.send_message(chat_id=chat_id, text=text)

# ========== دستور /score ==========
async def show_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_id = chat.id
    g = games.get(chat_id)
    if not g or not g.get("players"):
        await update.message.reply_text("هیچ امتیازی ثبت نشده.")
        return
    text = "📊 جدول امتیازات:\n"
    for uid, name in g["players"]:
        text += f"- {name}: {g.get('total_scores', {}).get(uid,0)}\n"
    await update.message.reply_text(text)

# ========== دستور /leave ==========
async def leave_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_id = chat.id
    user = update.effective_user
    g = games.get(chat_id)
    if not g:
        return
    g["players"] = [(uid, name) for uid, name in g.get("players", []) if uid != user.id]
    g["total_scores"].pop(user.id, None)
    await update.message.reply_text(f"✅ {user.full_name} از بازی خارج شد.")

# ========== main ==========
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("start", start_private, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("efstart", efstart, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("score", show_score, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("leave", leave_game, filters=filters.ChatType.GROUPS))

    # Callbacks
    app.add_handler(CallbackQueryHandler(lobby_button_handler, pattern="^(join|help|startgame|show_scores|open_catkbd:)"))
    app.add_handler(CallbackQueryHandler(pick_category_handler, pattern="^pickcat:"))
    app.add_handler(CallbackQueryHandler(manual_ok_handler, pattern="^manual_ok:"))
    app.add_handler(CallbackQueryHandler(manual_no_handler, pattern="^manual_no:"))

    # پیام گروه
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_group_message))

    logger.info("ربات آماده اجراست. Polling شروع شد...")
    app.run_polling()

if __name__ == "__main__":
    main()