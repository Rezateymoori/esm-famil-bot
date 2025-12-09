import os
import json
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# مسیر فایل‌های JSON
DATA_PATH = "data/"
CATEGORY_FILES = {
    "نام": "names.json",
    "فامیل": "families.json",
    "شهر": "cities.json",
    "کشور": "countries.json",
    "حیوان": "animals.json",
    "غذا": "foods.json",
    "رنگ": "colors.json"
}

# بارگذاری داده‌ها
VALID_MAP = {}
for cat, file in CATEGORY_FILES.items():
    with open(os.path.join(DATA_PATH, file), encoding="utf-8") as f:
        VALID_MAP[cat] = set(json.load(f))

CATEGORIES = list(CATEGORY_FILES.keys())

players = {}         # chat_id -> [(user_id, name)]
game_owner = {}      # chat_id -> owner_id
game_state = {}      # chat_id -> index دسته فعلی
answers = {}         # chat_id -> user_id -> {cat: {"text":..., "valid":...}}
letter = {}          # chat_id -> حرف دور
total_scores = {}    # chat_id -> user_id -> امتیاز کلی

# =======================
# توابع کمکی
# =======================
def build_main_text(chat_id):
    text = "🎲 به بازی اسم‌فامیل خوش آمدید!\n\nبازیکنان:\n"
    if chat_id in players and players[chat_id]:
        for uid, name in players[chat_id]:
            text += f"- {name} (ID:{uid})\n"
    else:
        text += "(هیچ‌کس هنوز وارد نشده)"
    return text

def build_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ورود به بازی", callback_data="join")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help")],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data="startgame")]
    ])

# =======================
# شروع بازی
# =======================
async def efstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    game_owner[chat_id] = user_id
    players[chat_id] = []
    total_scores[chat_id] = {}
    text = build_main_text(chat_id)
    await update.message.reply_text(text, reply_markup=build_main_keyboard())

# =======================
# هندلر دکمه‌ها
# =======================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    user_name = query.from_user.full_name

    if query.data == "join":
        if (user_id, user_name) not in players[chat_id]:
            players[chat_id].append((user_id, user_name))
        text = build_main_text(chat_id)
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=build_main_keyboard())

    elif query.data == "help":
        await context.bot.send_message(
            chat_id=chat_id,
            text="📖 راهنمای بازی:\n"
                 "1. ربات یک حرف انتخاب می‌کند.\n"
                 "2. باید برای هر دسته کلمه‌ای با آن حرف بنویسید.\n"
                 "3. امتیازها بر اساس یکتا بودن و درستی محاسبه می‌شوند."
        )

    elif query.data == "startgame":
        if user_id != game_owner.get(chat_id):
            await context.bot.send_message(chat_id=chat_id, text="فقط سازنده‌ی بازی می‌تواند شروع کند.")
            return
        game_state[chat_id] = 0
        answers[chat_id] = {}
        letter[chat_id] = random.choice("ابتثجچحخدذرزسشصضطظعغفقکگلمنوهی")
        text = f"🚀 دور جدید شروع شد!\nحرف این دور: {letter[chat_id]}\n\nدسته اول: {CATEGORIES[0]}"
        await context.bot.send_message(chat_id=chat_id, text=text)

# =======================
# هندلر پاسخ‌ها
# =======================
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    idx = game_state.get(chat_id, None)
    if idx is None or idx >= len(CATEGORIES):
        return
    cat = CATEGORIES[idx]
    ans = update.message.text.strip()

    # ذخیره پاسخ اولیه
    answers[chat_id].setdefault(user_id, {})[cat] = {"text": ans, "valid": None}

    # بررسی خودکار JSON
    if ans in VALID_MAP[cat]:
        answers[chat_id][user_id][cat]["valid"] = True
        await context.bot.send_message(chat_id=chat_id, text=f"✅ پاسخ '{ans}' درست است و امتیاز داده شد!")
        await check_category_completion(context, chat_id)
    else:
        # ارسال به سازنده برای تایید دستی
        owner_id = game_owner[chat_id]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ درست", callback_data=f"valid_manual:{chat_id}:{user_id}:{cat}:yes")],
            [InlineKeyboardButton("❌ غلط", callback_data=f"valid_manual:{chat_id}:{user_id}:{cat}:no")]
        ])
        await context.bot.send_message(
            chat_id=owner_id,
            text=f"پاسخ {update.effective_user.full_name} برای دسته {cat}: {ans} در JSON وجود ندارد. تایید کنید:",
            reply_markup=keyboard
        )

# =======================
# هندلر داوری دستی
# =======================
async def validation_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chat_id, user_id, cat, decision = query.data.split(":")
    chat_id, user_id = int(chat_id), int(user_id)
    ans_text = answers[chat_id][user_id][cat]["text"]

    if decision == "yes":
        answers[chat_id][user_id][cat]["valid"] = True
        # اضافه کردن به JSON
        file_path = os.path.join(DATA_PATH, CATEGORY_FILES[cat])
        VALID_MAP[cat].add(ans_text)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(list(VALID_MAP[cat]), f, ensure_ascii=False, indent=2)
        await query.edit_message_text(f"✅ پاسخ '{ans_text}' تایید شد و به JSON اضافه شد.")
    else:
        answers[chat_id][user_id][cat]["valid"] = False
        await query.edit_message_text(f"❌ پاسخ '{ans_text}' رد شد.")

    await check_category_completion(context, chat_id)

# =======================
# بررسی اتمام دسته
# =======================
async def check_category_completion(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    idx = game_state.get(chat_id, 0)
    cat_name = CATEGORIES[idx]
    all_checked = all(
        answers[chat_id].get(uid, {}).get(cat_name, {}).get("valid") is not None
        for uid, _ in players[chat_id]
    )
    if all_checked:
        game_state[chat_id] += 1
        if game_state[chat_id] < len(CATEGORIES):
            next_cat = CATEGORIES[game_state[chat_id]]
            await context.bot.send_message(chat_id=chat_id, text=f"✍️ دسته بعدی: {next_cat}")
        else:
            await finish_game(context, chat_id)

# =======================
# اتمام بازی و محاسبه امتیاز
# =======================
async def finish_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    round_scores = {}
    for cat in CATEGORIES:
        for uid, _ in players[chat_id]:
            ans = answers[chat_id].get(uid, {}).get(cat, {"text": "", "valid": False})
            if ans["valid"]:
                round_scores[uid] = round_scores.get(uid, 0) + 10  # امتیاز ثابت، قابل تغییر
    for uid, sc in round_scores.items():
        total_scores[chat_id][uid] = total_scores[chat_id].get(uid, 0) + sc

    result = "🏆 نتایج این دور:\n"
    for uid, name in players[chat_id]:
        sc = round_scores.get(uid, 0)
        result += f"- {name}: {sc}\n"
    result += "\n📊 جدول کلی:\n"
    for uid, name in players[chat_id]:
        sc = total_scores[chat_id].get(uid, 0)
        result += f"- {name}: {sc}\n"

    await context.bot.send_message(chat_id=chat_id, text=result, reply_markup=build_main_keyboard())

# =======================
# اجرای ربات
# =======================
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable not set!")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("efstart", efstart))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(join|help|startgame)$"))
    app.add_handler(CallbackQueryHandler(validation_manual, pattern="^valid_manual:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer))
    app.run_polling()

if __name__ == "__main__":
    main()