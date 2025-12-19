import logging
import random
import time

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ================== تنظیمات ==================
TOKEN = "YOUR_BOT_TOKEN"
ROUND_TIME = 60  # ثانیه

CATEGORIES = ["اسم", "فامیل", "شهر", "کشور", "رنگ", "حیوان"]
LETTERS = list("ابپتثجچحخدذرزسشصضطظعغفقکگلمنوهی")

logging.basicConfig(level=logging.INFO)

# ================== حافظه بازی ==================
games = {}
user_active_category = {}

# ================== ابزارها ==================
def build_category_keyboard(chat_id: int):
    rows = []
    for c in CATEGORIES:
        rows.append([
            InlineKeyboardButton(c, callback_data=f"cat:{chat_id}:{c}")
        ])
    return InlineKeyboardMarkup(rows)

def build_next_round_keyboard(chat_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 راند بعدی", callback_data=f"nextround:{chat_id}")]
    ])

def has_completed_all(chat_id, user_id):
    g = games[chat_id]
    return len(g["answers_by_user"].get(user_id, {})) == len(CATEGORIES)

# ================== شروع بازی ==================
async def efstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id in games and games[chat_id]["active"]:
        await update.message.reply_text("❗ بازی در حال اجراست.")
        return

    letter = random.choice(LETTERS)

    games[chat_id] = {
        "active": True,
        "letter": letter,
        "owner": user.id,
        "players": set(),
        "answers_by_user": {},
        "scores": {},
        "job": None
    }

    await update.message.reply_text(
        f"🎮 *اسم‌فامیل شروع شد!*\n"
        f"🔤 حرف: «{letter}»\n"
        f"⏱ {ROUND_TIME} ثانیه فرصت دارید",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗂 انتخاب دسته", callback_data=f"open:{chat_id}")]
        ])
    )

    job = context.application.job_queue.run_once(
        end_round_timeout,
        ROUND_TIME,
        chat_id=str(chat_id)
    )
    games[chat_id]["job"] = job

# ================== دکمه‌ها ==================
async def lobby_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split(":")[1])

    await query.edit_message_reply_markup(
        reply_markup=build_category_keyboard(chat_id)
    )

async def category_select_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, chat_id, cat = query.data.split(":")
    chat_id = int(chat_id)
    user = query.from_user

    user_active_category.setdefault(chat_id, {})[user.id] = cat
    games[chat_id]["players"].add(user.id)

    # پیام اضافه در گروه نفرست
    await query.answer(f"دسته «{cat}» انتخاب شد", show_alert=False)

# ================== دریافت جواب ==================
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat.id
    user = msg.from_user

    if chat_id not in games or not games[chat_id]["active"]:
        return

    cat = user_active_category.get(chat_id, {}).get(user.id)
    if not cat:
        return

    g = games[chat_id]
    g["answers_by_user"].setdefault(user.id, {})

    if cat in g["answers_by_user"][user.id]:
        return

    g["answers_by_user"][user.id][cat] = msg.text
    g["scores"][user.id] = g["scores"].get(user.id, 0) + 10

    del user_active_category[chat_id][user.id]

    try:
        await msg.delete()
    except:
        pass

    if has_completed_all(chat_id, user.id):
        await finish_game(chat_id, context, winner_id=user.id)

# ================== پایان راند ==================
async def end_round_timeout(context: ContextTypes.DEFAULT_TYPE):
    chat_id = int(context.job.chat_id)
    if chat_id in games and games[chat_id]["active"]:
        await finish_game(chat_id, context)

async def finish_game(chat_id, context, winner_id=None):
    g = games[chat_id]
    g["active"] = False

    if g.get("job"):
        g["job"].schedule_removal()

    text = "🏁 *پایان راند*\n\n"
    if winner_id:
        text += f"🥇 برنده: {winner_id}\n\n"

    for uid, score in g["scores"].items():
        text += f"👤 {uid} → {score} امتیاز\n"

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=build_next_round_keyboard(chat_id)
    )

    # پیام خصوصی به جامانده‌ها
    for uid in g["players"]:
        if uid not in g["answers_by_user"] or \
           len(g["answers_by_user"][uid]) < len(CATEGORIES):
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text="⏰ راند تمام شد! این بار کامل نکردی."
                )
            except:
                pass

# ================== راند بعدی ==================
async def next_round_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = int(query.data.split(":")[1])
    user = query.from_user
    g = games.get(chat_id)

    if not g or user.id != g["owner"]:
        await query.answer("فقط سازنده بازی می‌تواند.", show_alert=True)
        return

    g["active"] = True
    g["letter"] = random.choice(LETTERS)
    g["answers_by_user"] = {}
    user_active_category[chat_id] = {}

    await query.message.edit_text(
        f"🚀 *راند جدید شروع شد!*\n"
        f"🔤 حرف: «{g['letter']}»",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗂 انتخاب دسته", callback_data=f"open:{chat_id}")]
        ])
    )

    job = context.application.job_queue.run_once(
        end_round_timeout,
        ROUND_TIME,
        chat_id=str(chat_id)
    )
    g["job"] = job

# ================== main ==================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("efstart", efstart, filters=filters.ChatType.GROUPS))
    app.add_handler(CallbackQueryHandler(lobby_button_handler, pattern="^open:"))
    app.add_handler(CallbackQueryHandler(category_select_handler, pattern="^cat:"))
    app.add_handler(CallbackQueryHandler(next_round_handler, pattern="^nextround:"))
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            handle_group_message
        )
    )

    app.run_polling()

if __name__ == "__main__":
    main()