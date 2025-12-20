import os
import logging
from collections import defaultdict
from typing import Dict, Any

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- وضعیت بازی -----------------
games: Dict[int, Dict[str, Any]] = defaultdict(dict)

# ----------------- UI -----------------
def build_lobby_text(chat_id: int) -> str:
    g = games.get(chat_id, {})
    players = g.get("players", [])

    text = "🎲 ربات اسم‌فامیل\n\n👥 بازیکنان:\n"
    if not players:
        text += "— هنوز کسی وارد نشده —\n"
    else:
        for i, (_, name) in enumerate(players, start=1):
            text += f"{i}. {name}\n"

    text += "\n➕ ورود به بازی\n🚀 فقط سازنده می‌تواند شروع کند"
    return text

def build_lobby_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ ورود به بازی", callback_data="join")],
            [InlineKeyboardButton("🚀 شروع بازی", callback_data="startgame")],
        ]
    )

# ----------------- Handlers -----------------
async def start_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ ربات روشن است")

async def efstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور فقط در گروه است")
        return

    chat_id = chat.id
    user = update.effective_user

    g = games.setdefault(chat_id, {})
    g["owner"] = user.id
    g.setdefault("players", [])

    msg = await update.message.reply_text(
        build_lobby_text(chat_id),
        reply_markup=build_lobby_keyboard(),
    )
    g["lobby_message_id"] = msg.message_id

async def lobby_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat.id
    user = query.from_user

    g = games.setdefault(chat_id, {})
    g.setdefault("players", [])

    if data == "join":
        if any(uid == user.id for uid, _ in g["players"]):
            await query.message.reply_text("قبلاً وارد شده‌ای")
            return

        g["players"].append((user.id, user.full_name))

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=g["lobby_message_id"],
            text=build_lobby_text(chat_id),
            reply_markup=build_lobby_keyboard(),
        )

    elif data == "startgame":
        if g.get("owner") != user.id:
            await query.message.reply_text("فقط سازنده می‌تواند شروع کند")
            return

        await query.message.reply_text("🚀 بازی شروع شد (نسخه پایه)")

# ----------------- main -----------------
def main():
    print("BOT STARTING...")

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN تنظیم نشده")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start_private, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("efstart", efstart, filters=filters.ChatType.GROUPS))
    app.add_handler(CallbackQueryHandler(lobby_button_handler))

    print("RUNNING POLLING...")
    app.run_polling()

if __name__ == "__main__":
    main()