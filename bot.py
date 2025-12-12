# bot.py
# نسخهٔ پیشرفته — حالت B با پایان خودکار و خلاصه نهایی
import os
import json
import random
import logging
import time
from collections import Counter, defaultdict
from difflib import get_close_matches
from typing import Dict, Any, Set
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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
    text = "🎲 *ربات اسم‌فامیل — نسخه پیشرفته (حالت حذف پیام‌ها)*\n\n"
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

# ---------- هندل پیام‌های گروه (ذخیره و حذف بدون شلوغی) ----------
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
        try:
            await update.message.delete()
        except:
            pass
        return

    try:
        await update.message.delete()
    except:
        pass

    g.setdefault("answers_by_user", {})
    user_map = g["answers_by_user"].setdefault(user.id, {})
    if active_cat in user_map:
        return
    user_map[active_cat] = {"text": text, "valid": None, "ts": time.time()}
    user_active_category[chat_id].pop(user.id, None)

    # داوری خودکار بدون اطلاع در گروه
    valid_set = VALID_MAP.get(active_cat, set())
    if text in valid_set:
        user_map[active_cat]["valid"] = True
    else:
        ok, matched = fuzzy_check(text, valid_set)
        if ok:
            user_map[active_cat]["valid"] = "fuzzy"
        else:
            user_map[active_cat]["valid"] = None
            owner = g.get("owner")
            if owner:
                try:
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ درست", callback_data=f"manualok:{chat_id}:{user.id}:{active_cat}")],
                        [InlineKeyboardButton("❌ غلط", callback_data=f"manualno:{chat_id}:{user.id}:{active_cat}")]
                    ])
                    await context.bot.send_message(
                        chat_id=owner,
                        text=(f"📩 *درخواست تأیید پاسخ*\n\n"
                              f"گروه: {chat.title or chat_id}\n"
                              f"بازیکن: {user.full_name}\n"
                              f"دسته: {active_cat}\n"
                              f"پاسخ: «{text}»"),
                        reply_markup=kb,
                        parse_mode="Markdown"
                    )
                except:
                    pass

# ---------- پایان راند و خلاصه نهایی ----------
async def finish_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    g = games.get(chat_id)
    if not g:
        return

    round_scores = {}
    summary_text = "🏆 *خلاصه راند*\n\n"
    for cat in CATEGORIES:
        summary_text += f"*دسته: {cat}*\n"
        all_answers = []
        for uid, _ in g.get("players", []):
            ans = g.get("answers_by_user", {}).get(uid, {}).get(cat, {}).get("text", "").strip()
            all_answers.append(ans)
        for uid, name in g.get("players", []):
            obj = g.get("answers_by_user", {}).get(uid, {}).get(cat, {"text": "", "valid": False})
            text = obj.get("text", "").strip()
            valid = obj.get("valid", False)
            pts = 0
            if valid:
                if text in VALID_MAP.get(cat, set()):
                    cnt = Counter(all_answers)[text]
                    pts = 5 if cnt > 1 else 10
                else:
                    ok, matched = fuzzy_check(text, VALID_MAP.get(cat, set()))
                    if ok:
                        cnt = Counter(all_answers)[matched]
                        pts = 5 if cnt > 1 else 7
            round_scores[uid] = round_scores.get(uid, 0) + pts
            summary_text += f"- {name}: {text} → {pts} امتیاز\n"
        summary_text += "\n"

    for uid, pts in round_scores.items():
        g["total_scores"][uid] = g.get("total_scores", {}).get(uid, 0) + pts

    summary_text += "📊 *جدول کلی امتیازات*\n"
    for uid, name in g.get("players", []):
        summary_text += f"- {name}: {g.get('total_scores', {}).get(uid, 0)}\n"

    try:
        await context.bot.send_message(chat_id=chat_id, text=summary_text, parse_mode="Markdown")
    except:
        pass

    preserved_players = g.get("players", [])
    preserved_scores = g.get("total_scores", {})
    games[chat_id] = {"owner": g.get("owner"), "players": preserved_players, "total_scores": preserved_scores}
    user_active_category.pop(chat_id, None)

# ---------- تایم اوت راند ----------
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
    g["locked"] = True
    await finish_game(context, chat_id)

# ---------- سایر هندلرها (لابی، دسته، تایید دستی و ...) همان نسخه اصلی ----------
# دستورات /start, /efstart, CallbackQueryHandlerها و غیره را اضافه کنید

# ---------- اجرای بات ----------
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    app = Application.builder().token(token).build()

    # handlers اصلی
    app.add_handler(CommandHandler("start", start_private, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("efstart", efstart, filters=filters.ChatType.GROUPS))
    app.add_handler(CallbackQueryHandler(lobby_button_handler, pattern="^(join|help|startgame|show_scores|open_catkbd:)"))
    app.add_handler(CallbackQueryHandler(pick_category_handler, pattern="^pickcat:"))
    app.add_handler(CallbackQueryHandler(manual_ok_handler, pattern="^manualok:"))
    app.add_handler(CallbackQueryHandler(manual_no_handler, pattern="^manualno:"))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, handle_group_message))
    app.add_handler(CommandHandler("score", cmd_score, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("leave", cmd_leave, filters=filters.ChatType.GROUPS))

    logger.info("ربات شروع به کار کرد")
    app.run_polling()

if __name__ == "__main__":
    main()