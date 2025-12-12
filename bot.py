# bot.py
# نسخهٔ پیشرفته — حالت B (ارسال جواب در گروه، حذف فوری و ذخیره)
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
# games[chat_id] = {...} ساختار بازی
games: Dict[int, Dict[str, Any]] = defaultdict(dict)

# user_active_category[chat_id][user_id] = "نام"  (که کاربر انتخاب کرده قبل از ارسال پیام)
user_active_category: Dict[int, Dict[int, str]] = defaultdict(dict)

# کسانی که /start در PV زدن (اختیاری؛ برای ارسال PM به آنها)
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
    # کیبوردی که هر کاربر قبل از ارسال پیام در گروه کلیک می‌کند تا دسته را انتخاب کند
    rows = []
    for cat in CATEGORIES:
        rows.append([InlineKeyboardButton(cat, callback_data=f"pickcat:{chat_id}:{user_id}:{cat}")])
    rows.append([InlineKeyboardButton("❌ لغو انتخاب", callback_data=f"pickcat:{chat_id}:{user_id}:__cancel__")])
    return InlineKeyboardMarkup(rows)

# ========== Handlers ==========

async def start_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کاربر در PV /start زده — او را فعال می‌کنیم تا در صورت نیاز پیام تاییدی برای owner ارسال شود."""
    user = update.effective_user
    if not user:
        return
    activated_users.add(user.id)
    await update.message.reply_text("👋 شما فعال شدید. اکنون ربات می‌تواند برای برخی اعلان‌ها به شما پیام خصوصی ارسال کند.")

async def efstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال لابی در گروه"""
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

    # send or edit lobby message
    text = build_lobby_text(chat_id)
    try:
        msg = await update.message.reply_text(text, reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
        g["lobby_message_id"] = msg.message_id
    except Exception:
        await update.message.reply_text(text)

    await update.message.reply_text("لطفاً دیگران را دعوت کنید؛ سازنده وقتی آماده بود «شروع دور» را بزند.")

async def lobby_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat = query.message.chat
    if chat.type not in ("group", "supergroup"):
        await query.edit_message_text("این دکمه فقط در گروه قابل استفاده است.")
        return
    chat_id = chat.id
    user = query.from_user
    g = games.setdefault(chat_id, {})
    g.setdefault("players", [])
    g.setdefault("total_scores", {})

    if data == "join":
        # کاربر می‌تواند بدون PV هم وارد شود؛ در حالت B نیازی به PV نیست
        if any(uid == user.id for uid, _ in g["players"]):
            await context.bot.send_message(chat_id=chat_id, text=f"✅ {user.full_name}، شما قبلاً وارد شده‌اید.")
            return
        g["players"].append((user.id, user.full_name))
        g["total_scores"].setdefault(user.id, 0)
        try:
            if "lobby_message_id" in g:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=g["lobby_message_id"], text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
            else:
                await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")

    elif data == "help":
        await context.bot.send_message(chat_id=chat_id, text=(
            "📖 *راهنما:*\n"
            "1. سازنده /efstart را اجرا و سپس «شروع دور» را می‌زند.\n"
            "2. بازیکنان با زدن «ورود به بازی» وارد می‌شوند.\n"
            "3. بعد از شروع دور، برای انتخاب دسته از دکمهٔ «انتخاب دسته» استفاده کنید؛ سپس جواب را در گروه ارسال کنید — پیام حذف و پاسخ ذخیره می‌شود.\n"
            "4. جواب‌های ناشناخته توسط ربات به سازنده جهت بررسی ارسال می‌شود.\n"
        ), parse_mode="Markdown")

    elif data == "show_scores":
        # نشان دادن جدول امتیازات
        if not g.get("players"):
            await context.bot.send_message(chat_id=chat_id, text="هیچ امتیازی هنوز ثبت نشده.")
            return
        text = "📊 جدول امتیازات کلی:\n"
        for uid, name in g["players"]:
            text += f"- {name}: {g.get('total_scores', {}).get(uid, 0)}\n"
        await context.bot.send_message(chat_id=chat_id, text=text)

    elif data == "startgame":
        owner = g.get("owner")
        if owner != user.id:
            await context.bot.send_message(chat_id=chat_id, text="⛔ فقط سازنده می‌تواند دور را شروع کند.")
            return
        if not g.get("players"):
            await context.bot.send_message(chat_id=chat_id, text="⛔ هیچ بازیکنی وجود ندارد. حداقل یک بازیکن لازم است.")
            return

        # مقداردهی راند
        g["active"] = True
        g["letter"] = random.choice(LETTERS)
        g["state_index"] = 0
        g["answers_by_user"] = {}
        g["finish_order"] = []
        # اطلاع شروع و نمایش کیبورد انتخاب دسته (همه کاربران از همان پیام می‌توانند pick کنند)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(f"🚀 *دور جدید شروع شد!*\n🔤 *حرف این دور:* «{g['letter']}»\n\n"
                      "برای ارسال پاسخ: ابتدا از دکمهٔ «انتخاب دسته» دستهٔ موردنظر را انتخاب کنید، سپس جواب را در گروه بفرستید (پیام شما حذف خواهد شد)."),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗂 انتخاب دسته", callback_data=f"open_catkbd:{chat_id}")]]),
                parse_mode="Markdown"
            )
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=f"🚀 دور جدید شروع شد! حرف: «{g['letter']}»\nلطفاً دسته را انتخاب و جواب را ارسال کنید.")

        # زمان پایان راند
        job = context.application.job_queue.run_once(end_round_timeout, ROUND_TIME, chat_id=str(chat_id))
        g["job"] = job

    elif data.startswith("open_catkbd:"):
        # وقتی کاربری روی "انتخاب دسته" کلیک کند، برای او کیبورد دسته‌نما ارسال کنیم
        parts = data.split(":")
        if len(parts) < 2:
            await query.answer()
            return
        chat_id = int(parts[1])
        user_id = query.from_user.id
        # send category keyboard as an ephemeral message (editable by user)
        try:
            await query.message.reply_text("✍️ دستهٔ موردنظر را انتخاب کنید:", reply_markup=build_category_keyboard(chat_id, user_id))
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text="خطا در باز کردن کیبورد دسته.")

    else:
        await query.answer()

# ---------- انتخاب دسته توسط کاربر (callback) ----------
async def pick_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # pattern: pickcat:<chat_id>:<user_id>:<cat>
    parts = data.split(":")
    if len(parts) < 4:
        await query.edit_message_text("درخواست نامعتبر.")
        return
    _, chat_id_s, user_id_s, cat = parts
    try:
        chat_id = int(chat_id_s)
        user_id = int(user_id_s)
    except:
        await query.edit_message_text("داده نامعتبر.")
        return

    # verify caller
    if update.effective_user.id != user_id:
        await query.answer("این کیبورد برای شما نیست.", show_alert=True)
        return

    if cat == "__cancel__":
        user_active_category[chat_id].pop(user_id, None)
        await query.edit_message_text("⛔ انتخاب دسته لغو شد.")
        return

    # ثبت دسته فعال برای کاربر
    user_active_category[chat_id][user_id] = cat
    await query.edit_message_text(f"✅ دستهٔ «{cat}» انتخاب شد. اکنون جواب را در گروه ارسال کنید — پیام شما حذف خواهد شد.")

# ---------- هندل پیام‌های متنی در گروه (حذف و ذخیره) ----------
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return
    chat_id = chat.id
    g = games.get(chat_id)
    if not g or not g.get("active"):
        # در حالت غیر فعال، پیام‌ها نادیده گرفته شوند (یا حذف نشوند)
        return

    user = update.effective_user
    user_id = user.id
    text = (update.message.text or "").strip()
    if not text:
        return

    # آیا کاربر دسته‌ای انتخاب کرده؟
    active_cat = user_active_category.get(chat_id, {}).get(user_id)
    if not active_cat:
        # اگر کاربر دسته انتخاب نکرده، حذف پیام و راهنمایی
        try:
            await update.message.delete()
        except:
            pass
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ {user.full_name}، ابتدا باید از دکمهٔ «انتخاب دسته» دسته را انتخاب کنید.")
        return

    # ذخیره پاسخ (قبل از حذف)
    # حذف پیام کاربر تا دیگران نبیند
    try:
        await update.message.delete()
    except Exception:
        pass

    # store answer
    g.setdefault("answers_by_user", {})
    user_map = g["answers_by_user"].setdefault(user_id, {})
    # جلوگیری از دوبار ثبت برای یک دسته
    if active_cat in user_map:
        await context.bot.send_message(chat_id=chat_id, text=f"⛔ {user.full_name}، شما قبلاً برای دسته «{active_cat}» پاسخ داده‌اید.")
        return

    user_map[active_cat] = {"text": text, "valid": None, "ts": time.time()}
    # پاک کردن دسته فعال کاربر (برای ارسال بعدی باید دوباره انتخاب کند)
    user_active_category[chat_id].pop(user_id, None)

    # اطلاع تایید دریافت (محتویات پنهان می‌ماند)
    await context.bot.send_message(chat_id=chat_id, text=f"✅ جواب {user.full_name} دریافت و محفوظ شد (پیام حذف شد).")

    # داوری خودکار:
    valid_set = VALID_MAP.get(active_cat, set())
    if text in valid_set:
        user_map[active_cat]["valid"] = True
        await context.bot.send_message(chat_id=chat_id, text=f"✅ پاسخ {user.full_name} برای «{active_cat}» معتبر است.")
        await check_if_category_complete(context, chat_id, active_cat)
    else:
        ok, matched = fuzzy_check(text, valid_set)
        if ok:
            # fuzzy match found — قبول با امتیاز کمتر
            user_map[active_cat]["valid"] = "fuzzy"
            await context.bot.send_message(chat_id=chat_id, text=f"✅ پاسخ {user.full_name} شبیه «{matched}» است (تطابق تقریبی).")
            await check_if_category_complete(context, chat_id, active_cat)
        else:
            # پاسخی در VALID_MAP نیست — نیاز به تأیید سازنده
            user_map[active_cat]["valid"] = None  # pending
            # تلاش برای ارسال پیغام خصوصی به سازنده
            owner = g.get("owner")
            if owner:
                try:
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ درست", callback_data=f"manualok:{chat_id}:{user_id}:{active_cat}")],
                        [InlineKeyboardButton("❌ غلط", callback_data=f"manualno:{chat_id}:{user_id}:{active_cat}")]
                    ])
                    await context.bot.send_message(
                        chat_id=owner,
                        text=(f"📩 *درخواست تأیید پاسخ*\n\n"
                              f"گروه: {chat.title or chat_id}\n"
                              f"بازیکن: {user.full_name}\n"
                              f"دسته: {active_cat}\n"
                              f"پاسخ: «{text}»\n\n"
                              "آیا این پاسخ را تأیید می‌کنید؟"),
                        reply_markup=kb,
                        parse_mode="Markdown"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=f"🕵️ پاسخ {user.full_name} نیاز به بررسی دارد؛ به سازنده اطلاع داده شد.")
                except Exception:
                    # سازنده PV را فعال نکرده — اطلاع در گروه
                    await context.bot.send_message(chat_id=chat_id, text=f"⚠️ پاسخ {user.full_name} در دیتابیس موجود نیست و نتوانستم آن را برای سازنده ارسال کنم. سازنده لطفاً در پی‌وی با ربات /start را بزند و سپس از دستور /review استفاده کند.")
            else:
                await context.bot.send_message(chat_id=chat_id, text=f"⚠️ مالک بازی (سازنده) تعیین نشده است؛ پاسخ در حالت معلق قرار گرفت.")

# ---------- هندل تأیید دستی از سوی سازنده (در PV یا گروه) ----------
async def manual_ok_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # manualok:chat_id:user_id:cat
    parts = data.split(":")
    if len(parts) < 4:
        await query.edit_message_text("داده نامعتبر.")
        return
    _, chat_id_s, user_id_s, cat = parts
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

    # تأیید؛ اضافه کردن به JSON و مارک به عنوان معتبر
    path = os.path.join(DATA_PATH, CATEGORY_FILES[cat])
    VALID_MAP.setdefault(cat, set()).add(text)
    save_json_list(path, VALID_MAP[cat])
    user_map[cat]["valid"] = True
    await query.edit_message_text(f"✅ پاسخ «{text}» تأیید شد و به دیتابیس اضافه شد.")
    # اطلاع به گروه
    try:
        await context.bot.send_message(chat_id=chat_id, text=f"✅ پاسخ برای دسته «{cat}» توسط سازنده تأیید شد.")
    except Exception:
        pass
    await check_if_category_complete(context, chat_id, cat)

async def manual_no_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # manualno:chat_id:user_id:cat
    parts = data.split(":")
    if len(parts) < 4:
        await query.edit_message_text("داده نامعتبر.")
        return
    _, chat_id_s, user_id_s, cat = parts
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
    try:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ پاسخ برای دسته «{cat}» توسط سازنده رد شد.")
    except Exception:
        pass
    await check_if_category_complete(context, chat_id, cat)

# ---------- بررسی تکمیل یک دسته (در صورت همه‌پر شدن) ----------
async def check_if_category_complete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, cat_name: str):
    g = games.get(chat_id)
    if not g:
        return
    # بررسی اینکه برای همه بازیکنان وضعیت valid این دسته مشخص شده باشد (True/False/'fuzzy')
    all_checked = True
    for uid, _ in g.get("players", []):
        status = g.get("answers_by_user", {}).get(uid, {}).get(cat_name, {}).get("valid")
        if status is None:
            all_checked = False
            break

    if all_checked:
        # اگر همه بررسی شدند، اعلام در گروه و در صورت نیاز پیشروی به دسته بعدی
        await context.bot.send_message(chat_id=chat_id, text=f"✅ دسته «{cat_name}» بررسی و تکمیل شد.")
        # اگر همه دسته‌ها تکمیل شد، پایان بازی
        # check if all categories have at least some status (not necessarily all players answered)
        # simpler: اگر همه بازیکنان برای همه دسته‌ها valid != None یا وجود داشت: این شرط پیچیده است؛ ما از index استفاده می‌کنیم
        # اگر همه دسته‌ها برای همه بازیکنان بررسی شدند:
        done = True
        for c in CATEGORIES:
            for uid, _ in g.get("players", []):
                if g.get("answers_by_user", {}).get(uid, {}).get(c, {}).get("valid") is None:
                    done = False
                    break
            if not done:
                break
        if done:
            await finish_game(context, chat_id)

# ---------- پایان دور و محاسبه امتیاز ----------
async def finish_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    g = games.get(chat_id)
    if not g:
        return
    round_scores = {}
    # محاسبه امتیاز برای هر بازیکن
    for cat in CATEGORIES:
        # جمع پاسخ‌ها برای بررسی تکراری
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
            # امتیازدهی: unique=10, fuzzy=7, duplicate=5
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

    # افزودن به کل امتیازات
    for uid, pts in round_scores.items():
        g["total_scores"][uid] = g.get("total_scores", {}).get(uid, 0) + pts

    # ساخت پیام نتیجه
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
    except Exception:
        logger.exception("ارسال نتیجه به گروه ناموفق بود")

    # پاکسازی حالت راند (حفظ بازیکنان و total_scores)
    preserved_players = g.get("players", [])
    preserved_scores = g.get("total_scores", {})
    games[chat_id] = {"owner": g.get("owner"), "players": preserved_players, "total_scores": preserved_scores}
    # پاکسازی user_active_category برای این چت
    user_active_category.pop(chat_id, None)

# ---------- انتهای راند در صورت تایم اوت ----------
async def end_round_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = int(job.chat_id)
    g = games.get(chat_id)
    if not g or not g.get("active"):
        return
    # برای کاربرانی که پاسخی نداده‌اند، mark invalid
    for uid, _ in g.get("players", []):
        user_map = g.setdefault("answers_by_user", {}).setdefault(uid, {})
        for cat in CATEGORIES:
            if cat not in user_map:
                user_map[cat] = {"text": "", "valid": False}
    g["locked"] = True
    await finish_game(context, chat_id)

# ---------- دستورات کمکی ----------
async def cmd_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور فقط در گروه کار می‌کند.")
        return
    chat_id = chat.id
    g = games.get(chat_id)
    if not g or not g.get("players"):
        await update.message.reply_text("هیچ بازی‌ای در این گپ فعال نیست.")
        return
    text = "📊 جدول امتیازات کلی:\n"
    for uid, name in g.get("players", []):
        text += f"- {name}: {g.get('total_scores', {}).get(uid, 0)}\n"
    await update.message.reply_text(text)

async def cmd_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور فقط در گروه کار می‌کند.")
        return
    chat_id = chat.id
    user = update.effective_user
    g = games.get(chat_id)
    if not g or not g.get("players"):
        await update.message.reply_text("هیچ بازی‌ای فعال نیست.")
        return
    before = len(g["players"])
    g["players"] = [(uid, n) for uid, n in g["players"] if uid != user.id]
    g.get("total_scores", {}).pop(user.id, None)
    if before == len(g["players"]):
        await update.message.reply_text("شما عضو بازی نبودید.")
    else:
        await update.message.reply_text("شما از بازی خارج شدید.")
        try:
            if "lobby_message_id" in g:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=g["lobby_message_id"], text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
        except Exception:
            pass

# ========== ثبت هندلرها و اجرای بات ==========
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    app = Application.builder().token(token).build()

    # handlers
    app.add_handler(CommandHandler("start", start_private, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("efstart", efstart, filters=filters.ChatType.GROUPS))
    app.add_handler(CallbackQueryHandler(lobby_button_handler, pattern="^(join|help|startgame|show_scores|open_catkbd:)"))
    app.add_handler(CallbackQueryHandler(pick_category_handler, pattern="^pickcat:"))
    app.add_handler(CallbackQueryHandler(manual_ok_handler, pattern="^manualok:"))
    app.add_handler(CallbackQueryHandler(manual_no_handler, pattern="^manualno:"))

    # حذف و ذخیره پیام‌های گروه (پاسخ‌ها)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, handle_group_message))

    # utility
    app.add_handler(CommandHandler("score", cmd_score, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("leave", cmd_leave, filters=filters.ChatType.GROUPS))

    logger.info("ربات شروع به کار کرد")
    app.run_polling()

if __name__ == "__main__":
    main()