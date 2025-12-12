# bot.py
import os
import json
import random
import logging
import time
from collections import Counter, defaultdict
from difflib import get_close_matches

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

# ---------- تنظیمات ----------
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
ROUND_TIME = 60  # ثانیه (اگر خواستی تغییر بده)
LETTERS = list("ابتثجچحخدذرزژسشصضطظعغفقکگلمنوهی")

# ---------- وضعیت بازی کلاینتی ----------
# games[chat_id] = {...}  مشابه ساختارهایی که قبلاً بحث شد
games = defaultdict(dict)

# ---------- بارگذاری JSON ----------
def load_json_set(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(x.strip() for x in data if isinstance(x, str) and x.strip())
            else:
                return set()
    except FileNotFoundError:
        logger.warning("فایل JSON پیدا نشد: %s", path)
        return set()
    except Exception as e:
        logger.exception("خطا در خواندن %s: %s", path, e)
        return set()

def save_json_list(path: str, items: set):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(list(items)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("خطا در نوشتن %s: %s", path, e)

def build_valid_map():
    vm = {}
    for cat, fname in CATEGORY_FILES.items():
        path = os.path.join(DATA_PATH, fname)
        vm[cat] = load_json_set(path)
    return vm

VALID_MAP = build_valid_map()

# fuzzy helper
def fuzzy_check(ans: str, valid_set: set):
    if not ans or not valid_set:
        return False, ""
    matches = get_close_matches(ans, valid_set, n=1, cutoff=0.75)
    return (True, matches[0]) if matches else (False, "")

# ---------- رابط کاربری و متن‌ها (فارسی) ----------
def build_lobby_text(chat_id: int) -> str:
    g = games[chat_id]
    players = g.get("players", [])
    text = "🎲 *ربات بازی اسم‌فامیل — حالت گروهی*\n\n"
    text += "👥 *بازیکنان:*\n"
    if not players:
        text += "— هنوز کسی وارد نشده —\n"
    else:
        for i, (_, name) in enumerate(players, start=1):
            text += f"{i}. {name}\n"
    text += "\n━━━━━━━━━━━━\n"
    text += "برای ورود روی «➕ ورود به بازی» بزنید.\n"
    text += "فقط سازنده می‌تواند بازی را شروع کند.\n"
    return text

def build_lobby_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ورود به بازی", callback_data="join")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help")],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data="startgame")],
    ])

# ---------- فرمان /efstart ----------
async def efstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name

    g = games[chat_id]
    g.setdefault("players", [])
    g.setdefault("total_scores", {})
    g["owner"] = user_id

    msg = await update.message.reply_text(
        build_lobby_text(chat_id),
        reply_markup=build_lobby_keyboard(),
        parse_mode="Markdown"
    )
    g["lobby_message_id"] = msg.message_id
    await update.message.reply_text("لطفاً دیگران را دعوت کنید؛ وقتی آماده بودید «شروع بازی» را بزنید.")

# ---------- هندلر دکمه‌های لابی ----------
async def lobby_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    user_name = query.from_user.full_name
    data = query.data

    g = games[chat_id]
    g.setdefault("players", [])
    g.setdefault("total_scores", {})

    if data == "join":
        if any(uid == user_id for uid, _ in g["players"]):
            await context.bot.send_message(chat_id=chat_id, text=f"✅ {user_name}، شما قبلاً وارد شده‌اید.")
            return
        g["players"].append((user_id, user_name))
        g["total_scores"].setdefault(user_id, 0)
        # آپدیت پیام لابی
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
                await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard())
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=build_lobby_text(chat_id), reply_markup=build_lobby_keyboard())

    elif data == "help":
        await context.bot.send_message(chat_id=chat_id, text=(
            "📖 *راهنمای بازی:* \n"
            "1. سازنده /efstart را اجرا و سپس «شروع بازی» را می‌زند.\n"
            "2. بازیکن‌ها با «ورود به بازی» وارد می‌شوند.\n"
            "3. بعد از شروع، ربات حرف را اعلام می‌کند و پیام «جواب را همین‌جا بنویسید» ارسال می‌کند.\n"
            "4. اگر جوابی در فایل JSON نبود، برای سازنده ارسال می‌شود تا تأیید کند.\n"
            "5. پس از تأیید دستی، جواب به JSON اضافه می‌شود."
        ), parse_mode="Markdown")

    elif data == "startgame":
        owner = g.get("owner")
        if owner != user_id:
            await context.bot.send_message(chat_id=chat_id, text="⛔ فقط سازنده‌ی بازی می‌تواند شروع کند.")
            return
        if not g.get("players"):
            await context.bot.send_message(chat_id=chat_id, text="⛔ هیچ بازیکنی وجود ندارد. حداقل یک نفر لازم است.")
            return

        # مقداردهی راند
        g["letter"] = random.choice(LETTERS)
        g["active"] = True
        g["locked"] = False
        g["start_time"] = time.time()
        g["finish_order"] = []
        g["player_data"] = {}
        g["answers"] = {}  # optional
        # آماده‌سازی player_data
        failed_dm = []
        for uid, uname in g["players"]:
            g["player_data"][uid] = {"answers": {}, "finished": False, "finish_time": None}
            try:
                # ارسال پیام ForceReply به گروه برای ترغیب به جواب (همه باید در گروه تایپ کنند)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🚀 بازی شروع شد!\n🔤 حرف این دور: «{g['letter']}»\n\n✍️ لطفاً جواب‌های خود را در همین گروه و به‌صورت پیام متنی ارسال کنید.",
                    reply_markup=ForceReply(selective=False)
                )
            except Exception:
                # نه بحرانی؛ اما اگر کاربر خصوصی لازم است می‌توان DM کرد
                pass

        # زمان پایان راند اگر هیچ‌کس زودتر اتمام نزد
        job = context.application.job_queue.run_once(end_round_timeout, ROUND_TIME, chat_id=str(chat_id))
        g["job"] = job

        await context.bot.send_message(chat_id=chat_id, text=f"⏱ زمان راند: {ROUND_TIME} ثانیه\nبازی در گروه ادامه دارد؛ هرکس پاسخ‌هایش را ارسال کند.")

# ---------- هندلر پیام‌های متنی (پاسخ‌ها) ----------
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    این هندر پیام‌های متنی در گروه را دریافت می‌کند و به عنوان پاسخ دسته فعلی ثبت می‌کند.
    توجه: در این نسخه ما دسته‌ها به‌صورت ترتیبی (یک‌به‌یک) نداریم؛
    هر پیام به عنوان پاسخ برای همهٔ دسته‌ها در نظر گرفته نمی‌شود — برای یک پیاده‌سازی ساده،
    فرض می‌کنیم پیام‌ها به ترتیب دسته‌ها ارسال می‌شوند یا فرمت خاص می‌دهیم.
    """
    chat = update.effective_chat
    if chat.type == "private":
        # این نسخه انتظار دارد پاسخ‌ها در گروه ارسال شوند.
        return

    chat_id = chat.id
    g = games.get(chat_id)
    if not g or not g.get("active"):
        return

    user_id = update.effective_user.id
    user_name = update.effective_user.full_name
    text = (update.message.text or "").strip()
    if not text:
        return

    # تعیین دستهٔ فعلی: استفاده از game_state که index دسته را نگه می‌دارد
    # اگر می‌خواهی پیام‌ها به‌صورت دسته‌ای (یکی یکی) باشند از game_state استفاده کن.
    idx = g.get("state_index", 0)
    if idx is None or idx >= len(CATEGORIES):
        # اگر state_index تعریف نشده، از حالت ساده: هر پیام یک پاسخ برای همه دسته‌ها نیست.
        # برای سازگاری با کد قبلی، ما پیام را به عنوان پاسخِ دسته فعلی (با index) ثبت می‌کنیم.
        idx = g.setdefault("state_index", 0)

    cat = CATEGORIES[idx]
    # ثبت نوبتی: هر کاربر باید برای هر دسته یکبار پاسخ دهد
    g.setdefault("answers_by_user", {})
    user_ans_map = g["answers_by_user"].setdefault(user_id, {})
    if cat in user_ans_map:
        # کاربر قبلا برای این دسته پاسخ داده
        await update.message.reply_text("⛔ شما قبلاً برای این دسته پاسخ داده‌اید.")
        return

    # ذخیره پاسخ اولیه با وضعیت pending
    user_ans_map[cat] = {"text": text, "valid": None}
    await update.message.reply_text(f"✅ جواب شما برای «{cat}» ثبت شد: «{text}»\nمنتظر بررسی...")

    # بررسی خودکار با JSON
    if text in VALID_MAP.get(cat, set()):
        user_ans_map[cat]["valid"] = True
        await update.message.reply_text(f"✅ پاسخ «{text}» برای دسته {cat} در دیتابیس وجود دارد — تایید شد.")
        await check_category_completion(context, chat_id)
    else:
        # ارسال به سازنده برای تایید دستی
        owner = g.get("owner")
        if owner:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ درست", callback_data=f"valid_manual:{chat_id}:{user_id}:{cat}:yes")],
                [InlineKeyboardButton("❌ غلط", callback_data=f"valid_manual:{chat_id}:{user_id}:{cat}:no")]
            ])
            try:
                await context.bot.send_message(
                    chat_id=owner,
                    text=f"📩 پاسخ جدید از *{user_name}* در گپ {chat.title if chat.title else chat_id}:\n\nدسته: {cat}\nجواب: «{text}»\n\nاین جواب در فایل JSON وجود ندارد. آیا تایید می‌کنید؟",
                    reply_markup=kb,
                    parse_mode="Markdown"
                )
                await update.message.reply_text("🕵️ پاسخ شما برای بررسی به سازنده ارسال شد.")
            except Exception:
                # اگر نتواند به سازنده پیغام بفرستد
                user_ans_map[cat]["valid"] = False
                await update.message.reply_text("⚠️ نتوانستم پاسخ شما را برای سازنده ارسال کنم؛ لطفاً بعداً امتحان کنید.")
        else:
            user_ans_map[cat]["valid"] = False
            await update.message.reply_text("⚠️ سازنده بازی تعیین نشده است؛ پاسخ ثبت شد اما قابل تأیید نیست.")

# ---------- هندلر داوری دستی سازنده ----------
async def validation_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    # pattern: valid_manual:chat_id:user_id:cat:yes/no
    if len(parts) < 5:
        await query.edit_message_text("دادهٔ نامعتبر.")
        return
    _, chat_id_s, user_id_s, cat, decision = parts
    chat_id = int(chat_id_s)
    user_id = int(user_id_s)
    g = games.get(chat_id)
    if not g:
        await query.edit_message_text("بازی پیدا نشد یا منقضی شده است.")
        return
    user_ans_map = g.get("answers_by_user", {}).get(user_id, {})
    ans_text = user_ans_map.get(cat, {}).get("text", "")

    if decision == "yes":
        user_ans_map[cat]["valid"] = True
        # اضافه کردن به JSON و ذخیره فایل
        file_path = os.path.join(DATA_PATH, CATEGORY_FILES[cat])
        VALID_MAP.setdefault(cat, set()).add(ans_text)
        save_json_list(file_path, VALID_MAP[cat])
        await query.edit_message_text(f"✅ پاسخ «{ans_text}» تأیید شد و به دیتابیس اضافه شد.")
    else:
        user_ans_map[cat]["valid"] = False
        await query.edit_message_text(f"❌ پاسخ «{ans_text}» رد شد.")

    # سپس بررسی اتمام دسته
    await check_category_completion(context, chat_id)

# ---------- بررسی اتمام دسته ----------
async def check_category_completion(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    g = games.get(chat_id)
    if not g:
        return
    idx = g.get("state_index", 0)
    cat_name = CATEGORIES[idx]
    # بررسی اینکه همه بازیکنان برای این دسته جوابشان بررسی شده (valid != None)
    all_checked = True
    for uid, _ in g.get("players", []):
        user_ans_map = g.get("answers_by_user", {}).get(uid, {})
        status = user_ans_map.get(cat_name, {}).get("valid")
        if status is None:
            all_checked = False
            break

    if all_checked:
        # حرکت به دسته بعدی
        g["state_index"] = idx + 1
        if g["state_index"] < len(CATEGORIES):
            next_cat = CATEGORIES[g["state_index"]]
            # اطلاع‌رسانی و ارسال ForceReply برای مرحله بعد
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✍️ دستهٔ بعدی: {next_cat}\nلطفاً جواب‌های خود را در همین گروه ارسال کنید.",
                reply_markup=ForceReply(selective=False)
            )
        else:
            # پایان بازی
            await finish_game(context, chat_id)

# ---------- پایان بازی و محاسبه امتیاز ----------
async def finish_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    g = games.get(chat_id)
    if not g:
        return
    round_scores = {}
    for cat in CATEGORIES:
        # جمع پاسخها برای آن دسته از همه بازیکنان (برای بررسی تکراری/یکتا)
        all_answers = []
        for uid, _ in g.get("players", []):
            ans = g.get("answers_by_user", {}).get(uid, {}).get(cat, {}).get("text", "").strip()
            all_answers.append(ans)

        for uid, uname in g.get("players", []):
            ans_obj = g.get("answers_by_user", {}).get(uid, {}).get(cat, {"text": "", "valid": False})
            text = ans_obj.get("text", "").strip()
            valid = ans_obj.get("valid", False)
            if valid:
                # تعیین امتیاز: unique=10, fuzzy=7, duplicate=5
                if text and text in VALID_MAP.get(cat, set()):
                    cnt = Counter(all_answers)[text]
                    score = 5 if cnt > 1 else 10
                else:
                    ok, matched = fuzzy_check(text, VALID_MAP.get(cat, set()))
                    if ok:
                        cnt = Counter(all_answers)[matched]
                        score = 5 if cnt > 1 else 7
                    else:
                        score = 0
                round_scores[uid] = round_scores.get(uid, 0) + score

    # افزودن به جدول کلی
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
        logger.exception("ارسال نتیجه به گروه ناموفق بود")

    # پاکسازی حالت بازی (نگهداری بازیکنان و total_scores)
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
    # برای همه کاربرانی که پاسخشان بررسی نشده، mark as finished (valid False)
    for uid, _ in g.get("players", []):
        user_map = g.setdefault("answers_by_user", {}).setdefault(uid, {})
        # برای دسته جاری اگر پاسخی ثبت نشده، ثبت به عنوان خالی و invalid
        idx = g.get("state_index", 0)
        if idx < len(CATEGORIES):
            cat = CATEGORIES[idx]
            if cat not in user_map:
                user_map[cat] = {"text": "", "valid": False}
    g["locked"] = True
    await finish_game(context, chat_id)

# ---------- کمکی‌ها ----------
async def show_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    g = games.get(chat_id)
    if not g or not g.get("players"):
        await update.message.reply_text("هیچ بازی‌ای در این گپ فعال نیست.")
        return
    text = "📊 جدول امتیازات کلی:\n"
    for uid, name in g.get("players", []):
        text += f"- {name}: {g.get('total_scores', {}).get(uid, 0)}\n"
    await update.message.reply_text(text)

async def leave_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    g = games.get(chat_id)
    if not g or not g.get("players"):
        await update.message.reply_text("هیچ بازی‌ای در این گپ فعال نیست.")
        return
    before = len(g["players"])
    g["players"] = [(uid, name) for uid, name in g["players"] if uid != user_id]
    g.get("total_scores", {}).pop(user_id, None)
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

    app.add_handler(CommandHandler("efstart", efstart))
    app.add_handler(CallbackQueryHandler(lobby_button_handler, pattern="^(join|help|startgame)$"))
    app.add_handler(CallbackQueryHandler(validation_manual, pattern="^valid_manual:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer))
    app.add_handler(CommandHandler("score", show_score))
    app.add_handler(CommandHandler("leave", leave_game))

    logger.info("ربات شروع به کار کرد")
    app.run_polling()

if __name__ == "__main__":
    main()