import os
import json
import random
import logging
import time
import asyncio
from collections import Counter, defaultdict
from difflib import get_close_matches
from typing import Dict, Any, Set
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

games: Dict[int, Dict[str, Any]] = defaultdict(dict)
user_active_category: Dict[int, Dict[int, str]] = defaultdict(dict)
activated_users: Set[int] = set()

# ----------- JSON Utilities -----------
def load_json_set(path: str) -> Set[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(x.strip() for x in data if isinstance(x, str) and x.strip())
            return set()
    except: return set()

def save_json_list(path: str, items: Set[str]):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(list(items)), f, ensure_ascii=False, indent=2)
    except: pass

VALID_MAP: Dict[str, Set[str]] = {}
for cat, fname in CATEGORY_FILES.items():
    VALID_MAP[cat] = load_json_set(os.path.join(DATA_PATH, fname))

def fuzzy_check(ans: str, valid_set: Set[str]):
    if not ans or not valid_set: return False, ""
    matches = get_close_matches(ans, list(valid_set), n=1, cutoff=0.75)
    if matches: return True, matches[0]
    return False, ""

# ----------- UI -----------
def build_lobby_text(chat_id: int) -> str:
    g = games.get(chat_id, {})
    players = g.get("players", [])
    text = "🎲 *ربات اسم‌فامیل — نسخه پیشرفته*\n\n"
    text += "👥 *بازیکنان:* \n"
    if not players: text += "— هنوز کسی وارد نشده —\n"
    else:
        for i, (_, name) in enumerate(players, start=1):
            text += f"{i}. {name}\n"
    text += "\n━━━━━━━━━━━━\n➕ ورود به بازی\n🚀 فقط سازنده می‌تواند دور را شروع کند"
    return text

def build_lobby_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ورود به بازی", callback_data="join")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help")],
        [InlineKeyboardButton("🚀 شروع دور", callback_data="startgame")],
        [InlineKeyboardButton("📋 جدول امتیازات", callback_data="show_scores")]
    ])

def build_category_keyboard(chat_id: int, user_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(cat, callback_data=f"pickcat:{chat_id}:{user_id}:{cat}")] for cat in CATEGORIES]
    rows.append([InlineKeyboardButton("❌ لغو انتخاب", callback_data=f"pickcat:{chat_id}:{user_id}:__cancel__")])
    return InlineKeyboardMarkup(rows)

# ----------- Handlers -----------
async def start_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    activated_users.add(user.id)
    await update.message.reply_text("👋 شما فعال شدید. اکنون ربات می‌تواند پیام‌های تاییدی ارسال کند.")

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
    msg = await update.message.reply_text(build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
    g["lobby_message_id"] = msg.message_id

# ----------- لابی دکمه‌ها -----------
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
            return await context.bot.send_message(chat_id=chat_id, text=f"✅ {user.full_name}، شما قبلاً وارد شده‌اید.")
        g["players"].append((user.id, user.full_name))
        g["total_scores"].setdefault(user.id, 0)
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=g["lobby_message_id"],
                                                text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
        except: pass

    elif data == "help":
        await context.bot.send_message(chat_id=chat_id, text="📖 راهنما: ...", parse_mode="Markdown")
    elif data == "show_scores":
        if not g.get("players"):
            return await context.bot.send_message(chat_id=chat_id, text="هیچ امتیازی ثبت نشده.")
        text = "📊 جدول امتیازات کلی:\n"
        for uid, name in g.get("players", []):
            text += f"- {name}: {g.get('total_scores', {}).get(uid, 0)}\n"
        await context.bot.send_message(chat_id=chat_id, text=text)
    elif data == "startgame":
        owner = g.get("owner")
        if owner != user.id:
            return await context.bot.send_message(chat_id=chat_id, text="⛔ فقط سازنده می‌تواند دور را شروع کند.")
        if not g.get("players"):
            return await context.bot.send_message(chat_id=chat_id, text="⛔ هیچ بازیکنی وجود ندارد.")
        g["active"] = True
        g["letter"] = random.choice(LETTERS)
        g["answers_by_user"] = {}
        msg = await context.bot.send_message(chat_id=chat_id, text=f"🚀 دور جدید شروع شد! حرف: «{g['letter']}»\nبرای ارسال پاسخ ابتدا دسته را انتخاب کنید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗂 انتخاب دسته", callback_data=f"open_catkbd:{chat_id}")]]))
        g["job"] = context.application.job_queue.run_once(end_round_timeout, ROUND_TIME, chat_id=str(chat_id))

    elif data.startswith("open_catkbd:"):
        user_id = query.from_user.id
        try:
            await query.message.reply_text("✍️ دسته موردنظر را انتخاب کنید:", reply_markup=build_category_keyboard(chat_id, user_id))
        except: pass

# ----------- انتخاب دسته -----------
async def pick_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    _, chat_id_s, user_id_s, cat = data.split(":")
    chat_id, user_id = int(chat_id_s), int(user_id_s)
    if query.from_user.id != user_id:
        return await query.answer("این کیبورد برای شما نیست.", show_alert=True)
    if cat == "__cancel__":
        user_active_category[chat_id].pop(user_id, None)
        return await query.edit_message_text("⛔ انتخاب دسته لغو شد.")
    user_active_category[chat_id][user_id] = cat
    msg = await query.edit_message_text(f"✅ دسته «{cat}» انتخاب شد. اکنون جواب را در گروه ارسال کنید.")
    # حذف خودکار بعد ۳ ثانیه
    await asyncio.sleep(3)
    try: await msg.delete()
    except: pass

# ----------- هندل پیام‌های گروه (حذف و ذخیره) -----------
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
        return
    try: await update.message.delete()
    except: pass
    user_map = g.setdefault("answers_by_user", {}).setdefault(user_id, {})
    if cat in user_map: return
    user_map[cat] = {"text": text, "valid": True}

    msg = await context.bot.send_message(chat_id=chat_id, text=f"✅ جواب {update.effective_user.full_name} دریافت شد.")
    await asyncio.sleep(3)
    try: await msg.delete()
    except: pass

# ----------- پایان راند خودکار -----------
async def end_round_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = int(job.chat_id)
    g = games.get(chat_id)
    if not g or not g.get("active"): return
    for uid, _ in g.get("players", []):
        user_map = g.setdefault("answers_by_user", {}).setdefault(uid, {})
        for cat in CATEGORIES:
            if cat not in user_map: user_map[cat] = {"text": "", "valid": False}
    g["locked"] = True
    await finish_game(context, chat_id)

async def finish_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    g = games.get(chat_id)
    if not g: return
    round_scores = {}
    for cat in CATEGORIES:
        all_answers = [g.get("answers_by_user", {}).get(uid, {}).get(cat, {}).get("text", "") for uid, _ in g.get("players", [])]
        for uid, name in g.get("players", []):
            obj = g.get("answers_by_user", {}).get(uid, {}).get(cat, {"text": "", "valid": False})
            text, valid = obj.get("text", ""), obj.get("valid", False)
            if not valid: continue
            cnt = Counter(all_answers)[text]
            pts = 5 if cnt > 1 else 10
            round_scores[uid] = round_scores.get(uid, 0) + pts
    for uid, pts in round_scores.items():
        g["total_scores"][uid] = g.get("total_scores", {}).get(uid, 0) + pts
    res = "🏆 *نتایج این دور*\n\n"
    for uid, name in g.get("players", []):
        res += f"- {name}: {round_scores.get(uid, 0)}\n"
    res += "\n📊 *جدول کلی*\n"
    for uid, name in g.get("players", []):
        res += f"- {name}: {g.get('total_scores', {}).get(uid, 0)}\n"
    await context.bot.send_message(chat_id=chat_id, text=res, parse_mode="Markdown")
    preserved_players = g.get("players", [])
    preserved_scores = g.get("total_scores", {})
    games[chat_id] = {"owner": g.get("owner"), "players": preserved_players, "total_scores": preserved_scores}
    user_active_category.pop(chat_id, None)

# ----------- اجرای بات -----------
def main():
    token = os.getenv("BOT_TOKEN")
    if not token: raise ValueError("BOT_TOKEN تنظیم نشده است")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_private, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("efstart", efstart, filters=filters.ChatType.GROUPS))
    app.add_handler(CallbackQueryHandler(lobby_button_handler, pattern="^(join|help|startgame|show_scores|open_catkbd:)"))
    app.add_handler(CallbackQueryHandler(pick_category_handler, pattern="^pickcat:"))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, handle_group_message))
    logger.info("ربات شروع شد")
    app.run_polling()

if __name__ == "__main__":
    main()