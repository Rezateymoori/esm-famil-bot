# bot.py
"""
ربات اسم‌فامیل — حالت گروهی (Model A)
ویژگی‌ها:
- کاملاً فارسی
- مخصوص گروه (Group-friendly)
- کاربر باید ابتدا در چت خصوصی /start زده باشد تا در گروه بتواند شرکت کند
- دیتابیس از فایل‌های JSON در پوشه data/ بارگذاری می‌شود
- داوری خودکار (JSON + fuzzy) و ارسال پاسخ‌های ناشناخته برای تأیید سازنده
- در صورت تأیید، پاسخ به JSON اضافه می‌شود
- استفاده از ForceReply در گروه برای باز شدن فیلد پاسخ
"""

import os
import json
import random
import logging
import time
from collections import Counter, defaultdict
from difflib import get_close_matches
from typing import Dict, Any, List, Set

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

# ---------- پیکربندی ----------
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

# ---------- لاگ ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- وضعیت‌های درونی ----------
# games[chat_id] = {
#   "owner": user_id,
#   "players": [(uid,name),...],
#   "total_scores": {uid:score,...},
#   "active": bool,
#   "letter": "س",
#   "state_index": int,  # index در CATEGORIES
#   "answers_by_user": { uid: { category: {"text":str, "valid": bool/None} } },
#   "job": job_handle (optional)
#   ...
# }
games: Dict[int, Dict[str, Any]] = defaultdict(dict)

# کسانی که در PV /start زده‌اند نگهداری می‌کنیم (فقط در حافظه)
activated_users: Set[int] = set()

# ---------- بارگذاری و ذخیره JSON ----------
def load_json_set(path: str) -> Set[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(s.strip() for s in data if isinstance(s, str) and s.strip())
            else:
                return set()
    except FileNotFoundError:
        logger.warning("فایل پیدا نشد: %s", path)
        return set()
    except Exception as e:
        logger.exception("خطا در خواندن JSON: %s", e)
        return set()

def save_json_list(path: str, items: Set[str]):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(list(items)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("خطا در نوشتن JSON: %s", e)

# بارگذاری همه‌ی مجموعه‌ها
VALID_MAP: Dict[str, Set[str]] = {}
for cat, fname in CATEGORY_FILES.items():
    VALID_MAP[cat] = load_json_set(os.path.join(DATA_PATH, fname))

# ---------- ابزار fuzzy ----------
def fuzzy_check(ans: str, valid_set: Set[str]):
    if not ans or not valid_set:
        return False, ""
    matches = get_close_matches(ans, list(valid_set), n=1, cutoff=0.75)
    if matches:
        return True, matches[0]
    return False, ""

# ---------- متن‌ها و فایل‌های UI فارسی ----------
def build_lobby_text(chat_id: int) -> str:
    g = games.get(chat_id, {})
    players = g.get("players", [])
    text = "🎲 *ربات اسم‌فامیل — حالت گروهی*\n\n"
    text += "👥 *بازیکنان:*\n"
    if not players:
        text += "— هنوز کسی وارد نشده —\n"
    else:
        for i, (_, name) in enumerate(players, start=1):
            text += f"{i}. {name}\n"
    text += "\n━━━━━━━━━━━━\n"
    text += "➕ برای ورود به بازی روی «ورود به بازی» کلیک کنید.\n"
    text += "🚀 فقط سازنده می‌تواند بازی را شروع کند.\n"
    return text

def build_lobby_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ورود به بازی", callback_data="join")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help")],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data="startgame")],
    ])

# ---------- فرمان /start (PV) ----------
async def start_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کاربر در PV با ربات /start زده است - او را فعال می‌کنیم"""
    user = update.effective_user
    if not user:
        return
    activated_users.add(user.id)
    await update.message.reply_text(
        "👋 سلام! شما اکنون فعال شدید. می‌توانید در بازی‌های گروهی شرکت کنید.\n"
        "توجه: برای شرکت در بازی‌ها لازم است این پیام را یک‌بار ارسال کرده باشید."
    )

# ---------- فرمان /efstart در گروه: ارسال لابی ----------
async def efstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور فقط در گروه اجرا می‌شود.")
        return
    chat_id = chat.id
    user = update.effective_user
    g = games.setdefault(chat_id, {})
    g.setdefault("players", [])
    g.setdefault("total_scores", {})
    g["owner"] = user.id
    # ارسال یا ویرایش پیام لابی
    text = build_lobby_text(chat_id)
    try:
        msg = await update.message.reply_text(text, reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
        g["lobby_message_id"] = msg.message_id
    except Exception:
        # فالوآپ: ارسال پیام ساده
        await update.message.reply_text(text)

    await update.message.reply_text("لطفاً دیگران را دعوت کنید؛ وقتی آماده بودید سازنده «شروع بازی» را بزند.")

# ---------- هندل دکمه‌های لابی ----------
async def lobby_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat = query.message.chat
    if chat.type not in ("group", "supergroup"):
        await query.edit_message_text("این دکمه فقط در گروه کار می‌کند.")
        return
    chat_id = chat.id
    user = query.from_user

    g = games.setdefault(chat_id, {})
    g.setdefault("players", [])
    g.setdefault("total_scores", {})

    if data == "join":
        # کاربر باید قبلاً در PV /start زده باشد
        if user.id not in activated_users:
            await context.bot.send_message(chat_id=chat_id,
                text=f"⚠️ @{user.username if user.username else user.full_name}، برای شرکت در بازی ابتدا در پیام خصوصی با ربات /start را بزنید و سپس دوباره «ورود به بازی» را بزنید.")
            return
        if any(uid == user.id for uid, _ in g["players"]):
            await context.bot.send_message(chat_id=chat_id, text=f"✅ {user.full_name}، شما قبلاً وارد شده‌اید.")
            return
        g["players"].append((user.id, user.full_name))
        g["total_scores"].setdefault(user.id, 0)
        # ویرایش پیام لابی
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
                await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard(), parse_mode="Markdown")

    elif data == "help":
        await context.bot.send_message(chat_id=chat_id, text=(
            "📖 *راهنما:* \n"
            "۱) سازنده /efstart را اجرا کرده و سپس «شروع بازی» را می‌زند.\n"
            "۲) بازیکنان با زدن «ورود به بازی» وارد می‌شوند (قبلش باید در PV /start زده باشند).\n"
            "۳) بعد از شروع، حرف اعلام می‌شود و پیام «جواب را همین‌جا بنویسید» ارسال می‌شود.\n"
            "۴) ربات جواب‌هایی که در JSON نیست را برای سازنده می‌فرستد تا دستی تأیید کند.\n"
            "۵) در صورت تأیید، جواب به فایل JSON اضافه می‌شود."
        ), parse_mode="Markdown")

    elif data == "startgame":
        # فقط سازنده می‌تواند شروع کند
        owner = g.get("owner")
        if owner != user.id:
            await context.bot.send_message(chat_id=chat_id, text="⛔ فقط سازنده‌ی بازی می‌تواند شروع کند.")
            return
        if not g.get("players"):
            await context.bot.send_message(chat_id=chat_id, text="⛔ هیچ بازیکنی وجود ندارد. حداقل یک نفر لازم است.")
            return

        # بررسی اینکه همه بازیکنان فعال شده‌اند (PV /start)
        not_active = [name for (uid, name) in g["players"] if uid not in activated_users]
        if not_active:
            await context.bot.send_message(chat_id=chat_id, text=(
                "⚠️ برخی بازیکنان هنوز در خصوصی /start را نزدند. لیست:\n" + "\n".join(f"- {n}" for n in not_active) +
                "\n\nلطفاً از بازیکنان بخواهید ابتدا در خصوصی با ربات /start را بزنند."
            ))
            return

        # مقداردهی راند
        g["active"] = True
        g["letter"] = random.choice(LETTERS)
        g["state_index"] = 0
        g["answers_by_user"] = {}
        g["finish_order"] = []
        # اعلام شروع بازی و ارسال ForceReply برای ترغیب به ارسال پاسخ در گروه
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🚀 *دور جدید شروع شد!* \n🔤 *حرف این دور:* «{g['letter']}»\n\n✍️ لطفاً جواب‌های خود را در همین گروه و به‌صورت پیام متنی ارسال کنید.",
                reply_markup=ForceReply(selective=False),
                parse_mode="Markdown"
            )
        except Exception:
            # اگر ForceReply شکست خورد، پیام ساده بده
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🚀 دور جدید شروع شد! حرف: «{g['letter']}»\n✍️ لطفاً جواب‌ها را در همین گروه ارسال کنید."
            )

        # زمان پایان کلی راند
        job = context.application.job_queue.run_once(end_round_timeout, ROUND_TIME, chat_id=str(chat_id))
        g["job"] = job

# ---------- هندل پیام‌های متنی در گروه (ثبت پاسخ‌ها) ----------
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
    user_name = user.full_name
    text = (update.message.text or "").strip()
    if not text:
        return

    # بررسی اینکه کاربر عضو بازی است
    if not any(uid == user_id for uid, _ in g.get("players", [])):
        # کاربر عضو نیست؛ راهنمایی کن
        await update.message.reply_text("⚠️ شما عضو بازی نیستید. برای شرکت ابتدا روی «ورود به بازی» بزنید.")
        return

    # دستهٔ جاری
    idx = g.get("state_index", 0)
    if idx is None or idx >= len(CATEGORIES):
        await update.message.reply_text("⛔ بازی در وضعیت مناسبی نیست یا دور تمام شده.")
        return
    cat = CATEGORIES[idx]

    # بررسی اینکه کاربر قبلاً برای این دسته پاسخ نداده باشد
    user_map = g.setdefault("answers_by_user", {}).setdefault(user_id, {})
    if cat in user_map:
        await update.message.reply_text("⛔ شما قبلاً برای این دسته پاسخ داده‌اید.")
        return

    # ذخیره پاسخ با وضعیت pending
    user_map[cat] = {"text": text, "valid": None}
    await update.message.reply_text(f"✅ جواب شما برای «{cat}» ثبت شد: «{text}» — در حال بررسی...")

    # بررسی خودکار با JSON
    valid_set = VALID_MAP.get(cat, set())
    if text in valid_set:
        user_map[cat]["valid"] = True
        await update.message.reply_text(f"✅ پاسخ «{text}» معتبر است (پیشاپیش در دیتابیس موجود).")
        await check_category_completion(context, chat_id)
    else:
        # ارسال پیام به سازنده برای تأیید دستی (در PV)
        owner = g.get("owner")
        if owner and owner in activated_users:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ درست", callback_data=f"valid_manual:{chat_id}:{user_id}:{cat}:yes")],
                [InlineKeyboardButton("❌ غلط", callback_data=f"valid_manual:{chat_id}:{user_id}:{cat}:no")]
            ])
            try:
                await context.bot.send_message(
                    chat_id=owner,
                    text=(f"📩 پاسخ جدید از *{user_name}* در گروه «{chat.title or chat_id}»\n\n"
                          f"دسته: {cat}\nجواب: «{text}»\n\n"
                          "این جواب در فایل JSON وجود ندارد. آیا آن را تایید می‌کنید؟"),
                    reply_markup=kb,
                    parse_mode="Markdown"
                )
                await update.message.reply_text("🕵️ پاسخ شما برای سازنده ارسال شد؛ منتظر تصمیم سازنده باشید.")
            except Exception:
                # اگر ارسال PV به سازنده مقدور نبود
                user_map[cat]["valid"] = False
                await update.message.reply_text("⚠️ نتوانستم پاسخ را به سازنده ارسال کنم؛ بعداً دوباره امتحان کنید.")
        else:
            # سازنده فعال نیست یا در PV استارت نزد — به کاربر بگو سازنده باید PV را فعال کند
            user_map[cat]["valid"] = False
            await update.message.reply_text("⚠️ سازنده بازی در خصوصی فعال نیست؛ نمی‌توان پاسخ شما را ارسال کرد. سازنده /start را در خصوصی بزند.")

# ---------- هندل تأیید دستی سازنده ----------
async def handle_manual_validation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # valid_manual:chat_id:user_id:cat:yes/no
    parts = data.split(":")
    if len(parts) < 5:
        await query.edit_message_text("داده نامعتبر.")
        return
    _, chat_id_s, user_id_s, cat, decision = parts
    chat_id = int(chat_id_s)
    user_id = int(user_id_s)
    g = games.get(chat_id)
    if not g:
        await query.edit_message_text("بازی مربوطه پیدا نشد یا خاتمه یافته است.")
        return
    user_map = g.setdefault("answers_by_user", {}).get(user_id, {})
    ans_text = user_map.get(cat, {}).get("text", "")

    if decision == "yes":
        user_map[cat]["valid"] = True
        # اضافه کردن به JSON و ذخیره
        path = os.path.join(DATA_PATH, CATEGORY_FILES[cat])
        VALID_MAP.setdefault(cat, set()).add(ans_text)
        save_json_list(path, VALID_MAP[cat])
        await query.edit_message_text(f"✅ پاسخ «{ans_text}» تأیید و به دیتابیس افزوده شد.")
        # اطلاع به گروه/بازیکن
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"✅ پاسخ «{ans_text}» برای دسته {cat} توسط سازنده تأیید شد.")
        except Exception:
            pass
    else:
        user_map[cat]["valid"] = False
        await query.edit_message_text(f"❌ پاسخ «{ans_text}» توسط سازنده رد شد.")
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ پاسخ «{ans_text}» برای دسته {cat} رد شد.")
        except Exception:
            pass

    # بررسی اتمام دسته بعد از تصمیم سازنده
    await check_category_completion(context, chat_id)

# ---------- بررسی اتمام دسته و حرکت به دسته بعدی ----------
async def check_category_completion(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    g = games.get(chat_id)
    if not g:
        return
    idx = g.get("state_index", 0)
    if idx is None or idx >= len(CATEGORIES):
        return
    cat_name = CATEGORIES[idx]
    all_checked = True
    for uid, _ in g.get("players", []):
        status = g.get("answers_by_user", {}).get(uid, {}).get(cat_name, {}).get("valid")
        if status is None:
            all_checked = False
            break

    if all_checked:
        # پیشرفت به دسته بعدی
        g["state_index"] = idx + 1
        if g["state_index"] < len(CATEGORIES):
            next_cat = CATEGORIES[g["state_index"]]
            # اطلاع‌رسانی و ارسال ForceReply برای مرحله بعد
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✍️ دستهٔ بعدی: {next_cat}\nلطفاً جواب‌های خود را در همین گروه ارسال کنید.",
                    reply_markup=ForceReply(selective=False)
                )
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=f"✍️ دستهٔ بعدی: {next_cat}\nلطفاً جواب‌های خود را در همین گروه ارسال کنید.")
        else:
            await finish_game(context, chat_id)

# ---------- پایان بازی و محاسبه امتیاز ----------
async def finish_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    g = games.get(chat_id)
    if not g:
        return
    round_scores: Dict[int, int] = {}
    for cat in CATEGORIES:
        # همه پاسخ‌ها برای آن دسته
        all_answers = []
        for uid, _ in g.get("players", []):
            ans = g.get("answers_by_user", {}).get(uid, {}).get(cat, {}).get("text", "").strip()
            all_answers.append(ans)

        for uid, uname in g.get("players", []):
            ans_obj = g.get("answers_by_user", {}).get(uid, {}).get(cat, {"text": "", "valid": False})
            text = ans_obj.get("text", "").strip()
            valid = ans_obj.get("valid", False)
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

    # افزودن به total_scores
    for uid, pts in round_scores.items():
        g["total_scores"][uid] = g["total_scores"].get(uid, 0) + pts

    # ساخت پیام نتیجه
    res = "🏆 نتایج این دور:\n\n"
    for uid, name in g.get("players", []):
        sc = round_scores.get(uid, 0)
        res += f"- {name}: {sc}\n"
    res += "\n📊 جدول کلی:\n"
    for uid, name in g.get("players", []):
        sc = g.get("total_scores", {}).get(uid, 0)
        res += f"- {name}: {sc}\n"

    try:
        await context.bot.send_message(chat_id=chat_id, text=res)
    except Exception:
        logger.exception("ارسال نتیجه ناموفق بود")

    # پاکسازی وضعیت راند (حفظ بازیکنان و total_scores)
    preserved_players = g.get("players", [])
    preserved_scores = g.get("total_scores", {})
    games[chat_id] = {
        "owner": g.get("owner"),
        "players": preserved_players,
        "total_scores": preserved_scores
    }

# ---------- Timeout handler ----------
async def end_round_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = int(job.chat_id)
    g = games.get(chat_id)
    if not g or not g.get("active"):
        return
    # برای همه کاربرانی که در دسته جاری پاسخی نداده‌اند، نال بگذار
    idx = g.get("state_index", 0)
    if idx < len(CATEGORIES):
        cat = CATEGORIES[idx]
        for uid, _ in g.get("players", []):
            user_map = g.setdefault("answers_by_user", {}).setdefault(uid, {})
            if cat not in user_map:
                user_map[cat] = {"text": "", "valid": False}
    g["locked"] = True
    await finish_game(context, chat_id)

# ---------- دستورهای کمکی ----------
async def show_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def leave_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور فقط در گروه کاربرد دارد.")
        return
    chat_id = chat.id
    user = update.effective_user
    g = games.get(chat_id)
    if not g or not g.get("players"):
        await update.message.reply_text("هیچ بازی‌ای در این گپ فعال نیست.")
        return
    before = len(g["players"])
    g["players"] = [(uid, name) for uid, name in g["players"] if uid != user.id]
    g.get("total_scores", {}).pop(user.id, None)
    if before == len(g["players"]):
        await update.message.reply_text("شما در بازی نبودید.")
    else:
        await update.message.reply_text("از بازی خارج شدید.")
        # آپدیت لابی
        try:
            if "lobby_message_id" in g:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=g["lobby_message_id"],
                    text=build_lobby_text(chat_id),
                    reply_markup=build_lobby_keyboard(),
                    parse_mode="Markdown"
                )
        except Exception:
            pass

# ---------- main ----------
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    app = Application.builder().token(token).build()

    # PV handler for /start activation
    app.add_handler(CommandHandler("start", start_private, filters=filters.ChatType.PRIVATE))

    # group handlers
    app.add_handler(CommandHandler("efstart", efstart, filters=filters.ChatType.GROUPS))
    app.add_handler(CallbackQueryHandler(lobby_button_handler, pattern="^(join|help|startgame)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, handle_group_message))
    app.add_handler(CallbackQueryHandler(handle_manual_validation, pattern="^valid_manual:"))

    # utilities
    app.add_handler(CommandHandler("score", show_score, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("leave", leave_game, filters=filters.ChatType.GROUPS))

    logger.info("ربات شروع به کار کرد")
    app.run_polling()

if __name__ == "__main__":
    main()