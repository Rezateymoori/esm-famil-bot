# bot.py — نسخه پیشرفته چندراندی با کلیدهای عملیاتی
# پیش‌نیاز: python-telegram-bot==20.5, Python 3.10+
import os
import json
import random
import logging
import time
from collections import Counter, defaultdict
from difflib import get_close_matches
from typing import Dict, Any, Set

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
LETTERS = list("ابتثجچحخدذرزژسشصضطظعغفقکگلمنوهی")
ROUND_TIME = 60       # ثانیه برای هر راند
TOTAL_ROUNDS = 3      # تعداد راندهای بازی پیش‌فرض

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

# ========== UI ==========
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
    text += "➕ ورود به بازی\n🚀 فقط سازنده می‌تواند دور را شروع کند\n"
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
    await update.message.reply_text("👋 شما فعال شدید. ربات می‌تواند پیام خصوصی ارسال کند.")

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
    try:
        msg = await update.message.reply_text(text, reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
        g["lobby_message_id"] = msg.message_id
    except Exception:
        await update.message.reply_text(text)
    await update.message.reply_text("لطفاً دیگران را دعوت کنید؛ سازنده وقتی آماده بود «شروع دور» را بزند.")

# ---------- Callback لابی ----------
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
        if "lobby_message_id" in g:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=g["lobby_message_id"],
                text=build_lobby_text(chat_id),
                reply_markup=build_lobby_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
    elif data == "help":
        await context.bot.send_message(chat_id=chat_id,
            text=("📖 *راهنما:*\n"
                  "1. سازنده /efstart را اجرا و سپس «شروع دور» را می‌زند.\n"
                  "2. بازیکنان با زدن «ورود به بازی» وارد می‌شوند.\n"
                  "3. بعد از شروع راند، برای ارسال پاسخ ابتدا دسته را انتخاب کنید.\n"
                  "4. جواب‌ها حذف و ذخیره می‌شوند.\n"),
            parse_mode="Markdown")
    elif data == "show_scores":
        if not g.get("players"):
            await context.bot.send_message(chat_id=chat_id, text="هیچ امتیازی هنوز ثبت نشده.")
            return
        text = "📊 جدول امتیازات کلی:\n"
        for uid, name in g.get("players", []):
            text += f"- {name}: {g.get('total_scores', {}).get(uid, 0)}\n"
        await context.bot.send_message(chat_id=chat_id, text=text)
    elif data == "startgame":
        owner = g.get("owner")
        if owner != user.id:
            await context.bot.send_message(chat_id=chat_id, text="⛔ فقط سازنده می‌تواند دور را شروع کند.")
            return
        if not g.get("players"):
            await context.bot.send_message(chat_id=chat_id, text="⛔ هیچ بازیکنی وجود ندارد.")
            return
        g["round_index"] = 0
        await start_new_round(context, chat_id)
    elif data.startswith("open_catkbd:"):
        user_id = query.from_user.id
        await query.message.reply_text("✍️ دستهٔ موردنظر را انتخاب کنید:", reply_markup=build_category_keyboard(chat_id, user_id))
    else:
        await query.answer()

# ---------- انتخاب دسته ----------
async def pick_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    if len(parts) < 4:
        await query.edit_message_text("درخواست نامعتبر.")
        return
    _, chat_id_s, user_id_s, cat = parts
    chat_id = int(chat_id_s)
    user_id = int(user_id_s)
    if update.effective_user.id != user_id:
        await query.answer("این کیبورد برای شما نیست.", show_alert=True)
        return
    if cat == "__cancel__":
        user_active_category[chat_id].pop(user_id, None)
        await query.edit_message_text("⛔ انتخاب دسته لغو شد.")
        return
    user_active_category[chat_id][user_id] = cat
    await query.edit_message_text(f"✅ دستهٔ «{cat}» انتخاب شد. اکنون جواب را در گروه ارسال کنید — پیام شما حذف خواهد شد.")

# ---------- پیام گروه ----------
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return
    chat_id = chat.id
    g = games.get(chat_id)
    if not g or not g.get("active"):
        return
    user = update.effective_user
    text = (update.message.text or "").strip()
    if not text:
        return
    active_cat = user_active_category.get(chat_id, {}).get(user.id)
    if not active_cat:
        await update.message.delete()
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ {user.full_name}، ابتدا دسته را انتخاب کنید.")
        return
    try:
        await update.message.delete()
    except:
        pass
    g.setdefault("answers_by_user", {})
    user_map = g["answers_by_user"].setdefault(user.id, {})
    if active_cat in user_map:
        await context.bot.send_message(chat_id=chat_id, text=f"⛔ {user.full_name}، قبلاً پاسخ داده‌اید.")
        return
    user_map[active_cat] = {"text": text, "valid": None, "ts": time.time()}
    user_active_category[chat_id].pop(user.id, None)
    await context.bot.send_message(chat_id=chat_id, text=f"✅ جواب {user.full_name} دریافت شد (پیام حذف شد).")

# ---------- شروع راند و پایان ----------
async def start_new_round(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    g = games.get(chat_id)
    g["active"] = True
    g["letter"] = random.choice(LETTERS)
    g["answers_by_user"] = {}
    g["round_index"] = g.get("round_index", 0) + 1
    await context.bot.send_message(chat_id=chat_id,
        text=(f"🚀 *راند {g['round_index']} شروع شد!*\n"
              f"🔤 حرف این راند: «{g['letter']}»\n"
              "دسته را انتخاب و پاسخ دهید."),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗂 انتخاب دسته", callback_data=f"open_catkbd:{chat_id}")]]),
        parse_mode="Markdown")
    job = context.application.job_queue.run_once(end_round_timeout, ROUND_TIME, chat_id=str(chat_id))
    g["job"] = job

async def end_round_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = int(job.chat_id)
    g = games.get(chat_id)
    if not g or not g.get("active"):
        return
    for uid, _ in g.get("players", []):
        user_map = g.setdefault("answers_by_user", {}).setdefault(uid, {})
        for cat in CATEGORIES:
            if cat not in user_map:
                user_map[cat] = {"text": "", "valid": False}
    g["active"] = False
    await finish_round(context, chat_id)

async def finish_round(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    # مشابه finish_game: محاسبه امتیاز، نمایش جدول و شروع راند بعدی یا پایان
    g = games.get(chat_id)
    if not g:
        return
    round_scores = {}
    for cat in CATEGORIES:
        all_answers = [g.get("answers_by_user", {}).get(uid, {}).get(cat, {}).get("text", "") for uid, _ in g.get("players", [])]
        for uid, name in g.get("players", []):
            obj = g.get("answers_by_user", {}).get(uid, {}).get(cat, {"text": "", "valid": False})
            text = obj.get("text", "").strip()
            valid = obj.get("valid", False)
            if not valid:
                continue
            if text in VALID_MAP.get(cat, set()):
                cnt = Counter(all_answers)[text]
                pts = 5 if cnt > 1 else 10
            else:
                ok, matched = fuzzy_check(text, VALID_MAP.get(cat, set()))
                if ok:
                    cnt = Counter(all_answers)[matched]
                    pts = 5 if cnt > 1 else 7
                else:
                    pts = 0
            round_scores[uid] = round_scores.get(uid, 0) + pts
    for uid, pts in round_scores.items():
        g["total_scores"][uid] = g.get("total_scores", {}).get(uid, 0) + pts
    res = f"🏆 *نتایج راند {g['round_index']}*\n\n"
    for uid, name in g.get("players", []):
        sc = round_scores.get(uid, 0)
        res += f"- {name}: {sc}\n"
    res += "\n📊 *جدول کلی*\n"
    for uid, name in g.get("players", []):
        sc = g.get("total_scores", {}).get(uid, 0)
        res += f"- {name}: {sc}\n"
    await context.bot.send_message(chat_id=chat_id, text=res, parse_mode="Markdown")

    if g["round_index"] < TOTAL_ROUNDS:
        await start_new_round(context, chat_id)
    else:
        await context.bot.send_message(chat_id=chat_id, text="🏁 تمام راندها به پایان رسید.")

# ========== اجرای ربات ==========
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    app = Application.builder().token(token).build()

    # دستورات و هندلرها
    app.add_handler(CommandHandler("start", start_private, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("efstart", efstart, filters=filters.ChatType.GROUPS))
    app.add_handler(CallbackQueryHandler(lobby_button_handler, pattern="^(join|help|startgame|show_scores|open_catkbd:)"))
    app.add_handler(CallbackQueryHandler(pick_category_handler, pattern="^pickcat:"))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, handle_group_message))

    logger.info("ربات شروع به کار کرد")
    app.run_polling()

if __name__ == "__main__":
    main()