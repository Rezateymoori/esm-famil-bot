# bot_advanced.py
import os
import json
import random
import logging
import asyncio
from collections import defaultdict, Counter
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
ROUND_TIME = 60  # ثانیه برای کل راند
LETTERS = list("ابتثجچحخدذرزژسشصضطظعغفقکگلمنوهی")

# ========== وضعیت‌ها ==========
games = defaultdict(dict)  # اطلاعات بازی‌ها
user_active_category = defaultdict(dict)  # دستهٔ فعال هر کاربر

# ========== بارگذاری JSON ==========
def load_json_set(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(x.strip() for x in data if isinstance(x, str) and x.strip())
    except:
        return set()

def save_json_list(path, items):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(list(items)), f, ensure_ascii=False, indent=2)

VALID_MAP = {cat: load_json_set(os.path.join(DATA_PATH, fname)) for cat, fname in CATEGORY_FILES.items()}

# ========== UI ==========
def build_lobby_text(chat_id):
    g = games.get(chat_id, {})
    players = g.get("players", [])
    text = "🎲 *ربات اسم‌فامیل — نسخه پیشرفته*\n\n👥 *بازیکنان:* \n"
    if not players:
        text += "— هنوز کسی وارد نشده —\n"
    else:
        for i, (_, name) in enumerate(players, start=1):
            text += f"{i}. {name}\n"
    text += "\n━━━━━━━━━━━━\n"
    text += "➕ ورود به بازی\n🚀 فقط سازنده می‌تواند دور را شروع کند"
    return text

def build_lobby_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ورود به بازی", callback_data="join")],
        [InlineKeyboardButton("🚀 شروع دور", callback_data="startgame")],
        [InlineKeyboardButton("📋 جدول امتیازات", callback_data="show_scores")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help")]
    ])

def build_category_keyboard(chat_id, user_id):
    rows = [[InlineKeyboardButton(cat, callback_data=f"pickcat:{chat_id}:{user_id}:{cat}")] for cat in CATEGORIES]
    rows.append([InlineKeyboardButton("❌ لغو انتخاب", callback_data=f"pickcat:{chat_id}:{user_id}:__cancel__")])
    return InlineKeyboardMarkup(rows)

# ========== هندلرها ==========
async def efstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"): return
    user = update.effective_user
    g = games.setdefault(chat.id, {})
    g.setdefault("players", [])
    g.setdefault("total_scores", {})
    g["owner"] = user.id
    msg = await update.message.reply_text(build_lobby_text(chat.id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
    g["lobby_message_id"] = msg.message_id

async def lobby_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    data = query.data
    g = games.setdefault(chat_id, {})
    g.setdefault("players", [])
    g.setdefault("total_scores", {})

    if data == "join":
        if any(uid == user_id for uid, _ in g["players"]):
            return await query.message.reply_text("✅ شما قبلاً وارد شده‌اید.")
        g["players"].append((user_id, query.from_user.full_name))
        await query.message.edit_text(build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")

    elif data == "startgame":
        if g.get("owner") != user_id: return await query.message.reply_text("⛔ فقط سازنده می‌تواند دور را شروع کند.")
        if not g.get("players"): return await query.message.reply_text("⛔ هیچ بازیکنی وجود ندارد.")
        g["active"] = True
        g["letter"] = random.choice(LETTERS)
        g["answers_by_user"] = {}
        g["finish_order"] = []

        await query.message.reply_text(
            f"🚀 *دور جدید شروع شد!*\n🔤 حرف: «{g['letter']}»\nبرای ارسال پاسخ ابتدا دسته را انتخاب کنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗂 انتخاب دسته", callback_data=f"open_catkbd:{chat_id}")]]),
            parse_mode="Markdown"
        )

        # شروع شمارش معکوس داخلی
        context.application.create_task(end_round_timeout(chat_id, ROUND_TIME))

    elif data.startswith("open_catkbd:"):
        user_id = query.from_user.id
        await query.message.reply_text("✍️ دسته را انتخاب کنید:", reply_markup=build_category_keyboard(chat_id, user_id))

    elif data == "help":
        await query.message.reply_text("راهنما: ورود، شروع دور، انتخاب دسته و ارسال پاسخ.")
    elif data == "show_scores":
        text = "📊 جدول کلی:\n"
        for uid, name in g.get("players", []):
            text += f"- {name}: {g.get('total_scores', {}).get(uid, 0)}\n"
        await query.message.reply_text(text)

async def pick_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chat_id_s, user_id_s, cat = query.data.split(":")
    chat_id, user_id = int(chat_id_s), int(user_id_s)
    if update.effective_user.id != user_id:
        return await query.answer("این کیبورد برای شما نیست.", show_alert=True)
    if cat == "__cancel__":
        user_active_category[chat_id].pop(user_id, None)
        return await query.edit_message_text("⛔ انتخاب لغو شد.")
    user_active_category[chat_id][user_id] = cat
    await query.edit_message_text(f"✅ دسته «{cat}» انتخاب شد. اکنون جواب را در گروه ارسال کنید — پیام حذف خواهد شد.")

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    g = games.get(chat_id)
    if not g or not g.get("active"): return
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()
    if not text: return
    cat = user_active_category.get(chat_id, {}).pop(user_id, None)
    if not cat:
        try: await update.message.delete()
        except: pass
        return await context.bot.send_message(chat_id=chat_id, text=f"⚠️ {update.effective_user.full_name}، ابتدا دسته را انتخاب کنید.")
    try: await update.message.delete()
    except: pass
    user_map = g.setdefault("answers_by_user", {}).setdefault(user_id, {})
    if cat in user_map: return
    user_map[cat] = {"text": text, "valid": True}
    await context.bot.send_message(chat_id=chat_id, text=f"✅ جواب {update.effective_user.full_name} دریافت شد.")

# ---------- پایان راند ----------
async def end_round_timeout(chat_id, delay):
    await asyncio.sleep(delay)
    g = games.get(chat_id)
    if not g or not g.get("active"): return
    g["active"] = False
    res = "⏱ زمان راند تمام شد!\n"
    for uid, name in g.get("players", []):
        pts = len(g.get("answers_by_user", {}).get(uid, {})) * 10
        g["total_scores"][uid] = g.get("total_scores", {}).get(uid, 0) + pts
        res += f"- {name}: {pts} امتیاز\n"
    await g.get("players")[0][1].__class__.__bases__[0].__init__  # فقط برای جلوگیری از lint (ignore)
    await context.bot.send_message(chat_id=chat_id, text=res)

# ========== اجرای بات ==========
def main():
    token = os.getenv("BOT_TOKEN")
    if not token: raise ValueError("BOT_TOKEN تنظیم نشده است.")
    app = Application.builder().token(token).build()

    # CommandHandler
    app.add_handler(CommandHandler("efstart", efstart, filters=filters.ChatType.GROUPS))

    # CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(lobby_button_handler, pattern="^(join|startgame|show_scores|help|open_catkbd:)"))
    app.add_handler(CallbackQueryHandler(pick_category_handler, pattern="^pickcat:"))

    # MessageHandler
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, handle_group_message))

    logger.info("ربات شروع به کار کرد")
    app.run_polling()

if __name__ == "__main__":
    main()