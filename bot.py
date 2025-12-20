# bot.py — نسخهٔ کامل نهایی با داوری خودکار و حذف پیام‌ها
# پیش‌نیاز: python-telegram-bot==20.5 , Python 3.10+

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
    InlineKeyboardMarkup
)
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
    text = "🎲 *ربات اسم‌فامیل — نسخه کامل*\n\n"
    text += "👥 *بازیکنان:* \n"
    if not players:
        text += "— هنوز کسی وارد نشده —\n"
    else:
        for i, (_, name) in enumerate(players, start=1):
            text += f"{i}. {name}\n"
    text += "\n━━━━━━━━━━━━\n"
    text += "➕ ورود به بازی\n🚀 شروع بازی با کسی که ربات را صدا می‌کند\n"
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
    await update.message.reply_text("👋 شما فعال شدید. ربات می‌تواند اعلان‌های خصوصی برای شما ارسال کند.")

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

    await update.message.reply_text("لطفاً دیگران را دعوت کنید؛ کسی که ربات را صدا می‌کند، دور را شروع می‌کند.")

# ---------- Callback ----------
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
                await context.bot.edit_message_text(chat_id=chat_id, message_id=g["lobby_message_id"],
                    text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
            else:
                await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id),
                    reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id),
                reply_markup=build_lobby_keyboard(), parse_mode="Markdown")

    elif data == "help":
        await context.bot.send_message(chat_id=chat_id,
            text=("📖 *راهنما:*\n"
                  "1. با زدن «شروع دور»، دور جدید شروع می‌شود.\n"
                  "2. بازیکنان «ورود به بازی» می‌کنند.\n"
                  "3. برای ارسال جواب: ابتدا «انتخاب دسته» و سپس جواب در گروه.\n"
                  "پیام شما حذف و جواب ذخیره می‌شود.\n"
                  "4. جواب‌های مشکوک برای صاحب بازی ارسال می‌شوند."),
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
            await context.bot.send_message(chat_id=chat_id, text="⛔ هیچ بازیکنی وجود ندارد.")
            return

        g["active"] = True
        g["letter"] = random.choice(LETTERS)
        g["answers_by_user"] = {}
        g["finish_order"] = []

        await context.bot.send_message(chat_id=chat_id,
            text=(f"🚀 *دور جدید شروع شد!*\n"
                  f"🔤 *حرف این دور:* «{g['letter']}»\n\n"
                  "برای ارسال جواب: ابتدا از دکمهٔ «انتخاب دسته» دستهٔ موردنظر را انتخاب کنید، سپس جواب را در گروه بفرستید (پیام شما حذف خواهد شد)."),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗂 انتخاب دسته", callback_data=f"open_catkbd:{chat_id}")]]),
            parse_mode="Markdown"
        )

        job = context.application.job_queue.run_once(end_round_timeout, ROUND_TIME, chat_id=str(chat_id))
        g["job"] = job

    elif data.startswith("open_catkbd:"):
        user_id = query.from_user.id
        await query.message.reply_text("✍️ دستهٔ موردنظر را انتخاب کنید:", reply_markup=build_category_keyboard(chat_id, user_id))

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

# ---------- هندل پیام‌های گروه ----------
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return
    chat_id = chat.id
    g = games.get(chat_id)
    if not g or not g.get("active"):
        return
    user = update.effective_user
    user_id = user.id
    text = (update.message.text or "").strip()
    if not text:
        return

    active_cat = user_active_category.get(chat_id, {}).get(user_id)
    if not active_cat:
        try:
            await update.message.delete()
        except: pass
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ {user.full_name}، ابتدا باید دسته را انتخاب کنید.")
        return

    try:
        await update.message.delete()
    except: pass

    g.setdefault("answers_by_user", {})
    user_map = g["answers_by_user"].setdefault(user_id, {})
    if active_cat in user_map:
        await context.bot.send_message(chat_id=chat_id, text=f"⛔ {user.full_name}، شما قبلاً برای دسته «{active_cat}» پاسخ داده‌اید.")
        return

    user_map[active_cat] = {"text": text, "valid": None, "ts": time.time()}
    user_active_category[chat_id].pop(user_id, None)

    # داوری خودکار
    valid_set = VALID_MAP.get(active_cat, set())
    if text in valid_set:
        user_map[active_cat]["valid"] = True
        await context.bot.send_message(chat_id=chat_id, text=f"✅ پاسخ {user.full_name} برای «{active_cat}» معتبر است.")
    else:
        ok, matched = fuzzy_check(text, valid_set)
        if ok:
            user_map[active_cat]["valid"] = "fuzzy"
            await context.bot.send_message(chat_id=chat_id, text=f"✅ پاسخ {user.full_name} شبیه «{matched}» است (تطابق تقریبی).")
        else:
            # پاسخی نیاز به تایید صاحب بازی دارد
            user_map[active_cat]["valid"] = None
            owner = g.get("owner")
            if owner:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ درست", callback_data=f"manualok:{chat_id}:{user_id}:{active_cat}")],
                    [InlineKeyboardButton("❌ غلط", callback_data=f"manualno:{chat_id}:{user_id}:{active_cat}")]
                ])
                try:
                    await context.bot.send_message(chat_id=owner,
                        text=(f"📩 *درخواست تأیید پاسخ*\n\n"
                              f"گروه: {chat.title or chat_id}\n"
                              f"بازیکن: {user.full_name}\n"
                              f"دسته: {active_cat}\n"
                              f"پاسخ: «{text}»\n\n"
                              "آیا این پاسخ را تأیید می‌کنید؟"),
                        reply_markup=kb,
                        parse_mode="Markdown")
                    await context.bot.send_message(chat_id=chat_id, text=f"🕵️ پاسخ {user.full_name} نیاز به بررسی دارد؛ به صاحب بازی اطلاع داده شد.")
                except:
                    await context.bot.send_message(chat_id=chat_id, text=f"⚠️ پاسخ {user.full_name} نیاز به بررسی دارد و پیام به صاحب بازی ارسال نشد.")

# ---------- هندل تأیید دستی ----------
async def manual_ok_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chat_id_s, user_id_s, cat = query.data.split(":")
    chat_id = int(chat_id_s)
    user_id = int(user_id_s)
    g = games.get(chat_id)
    if not g:
        await query.edit_message_text("بازی پیدا نشد یا خاتمه یافته است.")
        return
    user_map = g.setdefault("answers_by_user", {}).get(user_id, {})
    text = user_map.get(cat, {}).get("text", "")
    if not text:
        await query.edit_message_text("هیچ پاسخی برای بررسی یافت نشد.")
        return
    user_map[cat]["valid"] = True
    path = os.path.join(DATA_PATH, CATEGORY_FILES[cat])
    VALID_MAP.setdefault(cat, set()).add(text)
    save_json_list(path, VALID_MAP[cat])
    await query.edit_message_text(f"✅ پاسخ «{text}» تأیید شد و به دیتابیس اضافه شد.")

async def manual_no_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chat_id_s, user_id_s, cat = query.data.split(":")
    chat_id = int(chat_id_s)
    user_id = int(user_id_s)
    g = games.get(chat_id)
    if not g:
        await query.edit_message_text("بازی پیدا نشد یا خاتمه یافته است.")
        return
    user_map = g.setdefault("answers_by_user", {}).get(user_id, {})
    text = user_map.get(cat, {}).get("text", "")
    if not text:
        await query.edit_message_text("هیچ پاسخی برای بررسی یافت نشد.")
        return
    user_map[cat]["valid"] = False
    await query.edit_message_text(f"❌ پاسخ «{text}» رد شد.")

# ---------- پایان راند ----------
async def finish_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    g = games.get(chat_id)
    if not g:
        return
    round_scores = {}
    for cat in CATEGORIES:
        all_answers = []
        for uid, _ in g.get("players", []):
            ans = g.get("answers_by_user", {}).get(uid, {}).get(cat, {}).get("text", "").strip()
            all_answers.append(ans)
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

    res = "🏆 *نتایج این دور*\n\n"
    for uid, name in g.get("players", []):
        sc = round_scores.get(uid, 0)
        res += f"- {name}: {sc}\n"
    res += "\n📊 *جدول کلی*\n"
    for uid, name in g.get("players", []):
        sc = g.get("total_scores", {}).get(uid, 0)
        res += f"- {name}: {sc}\n"

    try:
        await context.bot.send_message(chat_id=chat_id, text=res, parse_mode="Markdown")
    except:
        pass

    preserved_players = g.get("players", [])
    preserved_scores = g.get("total_scores", {})
    games[chat_id] = {"owner": g.get("owner"), "players