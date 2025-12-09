from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from collections import Counter

CATEGORIES = ["نام", "فامیل", "شهر", "کشور", "حیوان", "غذا", "رنگ"]
players = {}
game_owner = {}
game_state = {}
answers = {}
letter = {}
total_scores = {}

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

async def efstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    game_owner[chat_id] = user_id
    players[chat_id] = []
    total_scores[chat_id] = {}
    text = build_main_text(chat_id)
    await update.message.reply_text(text, reply_markup=build_main_keyboard())

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
        await query.edit_message_text(text, reply_markup=build_main_keyboard())

    elif query.data == "help":
        await query.message.reply_text(
            "📖 راهنمای بازی:\n"
            "1. ربات یک حرف انتخاب می‌کند.\n"
            "2. باید برای هر دسته کلمه‌ای با آن حرف بنویسید.\n"
            "3. امتیازها بر اساس یکتا بودن و درستی محاسبه می‌شوند."
        )

    elif query.data == "startgame":
        if user_id != game_owner.get(chat_id):
            await query.message.reply_text("فقط سازنده‌ی بازی می‌تواند شروع کند.")
            return
        game_state[chat_id] = 0
        answers[chat_id] = {}
        letter[chat_id] = "س"  # اینجا می‌توانی تصادفی انتخاب کنی
        text = f"🚀 دور جدید شروع شد!\nحرف این دور: {letter[chat_id]}\n\nدسته اول: {CATEGORIES[0]}"
        await query.edit_message_text(text)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    idx = game_state.get(chat_id, None)
    if idx is None or idx >= len(CATEGORIES):
        return

    cat = CATEGORIES[idx]
    ans = update.message.text.strip()
    answers[chat_id].setdefault(user_id, {})[cat] = {"text": ans, "valid": None}

    # ارسال به داور برای تأیید
    owner_id = game_owner[chat_id]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ درست", callback_data=f"valid:{chat_id}:{user_id}:{cat}:yes")],
        [InlineKeyboardButton("❌ غلط", callback_data=f"valid:{chat_id}:{user_id}:{cat}:no")]
    ])
    await context.bot.send_message(
        chat_id=owner_id,
        text=f"پاسخ {update.effective_user.full_name} برای دسته {cat}: {ans}",
        reply_markup=keyboard
    )

async def validation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, chat_id, user_id, cat, decision = query.data.split(":")
    chat_id, user_id = int(chat_id), int(user_id)

    if decision == "yes":
        answers[chat_id][user_id][cat]["valid"] = True
    else:
        answers[chat_id][user_id][cat]["valid"] = False

    await query.edit_message_text(f"✅ تصمیم ثبت شد: {cat} → {'درست' if decision=='yes' else 'غلط'}")

    # بررسی اینکه همه جواب‌های دسته فعلی تأیید شده‌اند
    idx = game_state[chat_id]
    cat_name = CATEGORIES[idx]
    all_checked = all(
        ans.get("valid") is not None
        for ans in [answers[chat_id].get(uid, {}).get(cat_name, {"valid": None}) for uid, _ in players[chat_id]]
    )

    if all_checked:
        game_state[chat_id] += 1
        if game_state[chat_id] < len(CATEGORIES):
            next_cat = CATEGORIES[game_state[chat_id]]
            await context.bot.send_message(chat_id=chat_id, text=f"✍️ دسته بعدی: {next_cat}")
        else:
            await finish_game(update, chat_id)

async def finish_game(update: Update, chat_id: int):
    round_scores = {}
    for cat in CATEGORIES:
        for uid, _ in players[chat_id]:
            ans = answers[chat_id].get(uid, {}).get(cat, {"text": "", "valid": False})
            if ans["valid"]:
                round_scores[uid] = round_scores.get(uid, 0) + 10

    for uid, sc in round_scores.items():
        total_scores[chat_id][uid] = total_scores[chat_id].get(uid, 0) + sc

    result = "🏆 نتایج این دور:\n"
    for uid, name in players[chat_id]:
        sc = round_scores.get(uid, 0)
        result += f"- {name}: {sc}\n"

    result += "\n📊 جدول کلی (لیگ):\n"
    for uid, name in players[chat_id]:
        sc = total_scores[chat_id].get(uid, 0)
        result += f"- {name}: {sc}\n"

    await update.callback_query.message.reply_text(result, reply_markup=build_main_keyboard())

def main():
    app = Application.builder().token("BOT_TOKEN").build()
    app.add_handler(CommandHandler("efstart", efstart))  # تغییر دستور
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(join|help|startgame)$"))
    app.add_handler(CallbackQueryHandler(validation_handler, pattern="^valid:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer))
    app.run_polling()

if __name__ == "__main__":
    main()