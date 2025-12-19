# ---------- انتخاب دسته توسط کاربر ----------
async def pick_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # pickcat:<chat_id>:<user_id>:<cat>
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

    if update.effective_user.id != user_id:
        await query.answer("این کیبورد برای شما نیست.", show_alert=True)
        return

    if cat == "__cancel__":
        user_active_category[chat_id].pop(user_id, None)
        await query.edit_message_text("⛔ انتخاب دسته لغو شد.")
        return

    user_active_category[chat_id][user_id] = cat
    await query.edit_message_text(f"✅ دستهٔ «{cat}» انتخاب شد. اکنون جواب را در گروه ارسال کنید — پیام شما حذف خواهد شد.")

# ---------- هندل پیام‌های متنی در گروه ----------
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
        except:
            pass
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ {user.full_name}، ابتدا باید دسته را انتخاب کنید.")
        return

    try:
        await update.message.delete()
    except:
        pass

    g.setdefault("answers_by_user", {})
    user_map = g["answers_by_user"].setdefault(user_id, {})
    if active_cat in user_map:
        await context.bot.send_message(chat_id=chat_id, text=f"⛔ {user.full_name}، شما قبلاً برای دسته «{active_cat}» پاسخ داده‌اید.")
        return

    user_map[active_cat] = {"text": text, "valid": None, "ts": time.time()}
    user_active_category[chat_id].pop(user_id, None)

    await context.bot.send_message(chat_id=chat_id, text=f"✅ جواب {user.full_name} دریافت و محفوظ شد (پیام حذف شد).")

    valid_set = VALID_MAP.get(active_cat, set())
    if text in valid_set:
        user_map[active_cat]["valid"] = True
        await context.bot.send_message(chat_id=chat_id, text=f"✅ پاسخ {user.full_name} برای «{active_cat}» معتبر است.")
        await check_if_category_complete(context, chat_id, active_cat)
    else:
        ok, matched = fuzzy_check(text, valid_set)
        if ok:
            user_map[active_cat]["valid"] = "fuzzy"
            await context.bot.send_message(chat_id=chat_id, text=f"✅ پاسخ {user.full_name} شبیه «{matched}» است (تطابق تقریبی).")
            await check_if_category_complete(context, chat_id, active_cat)
        else:
            user_map[active_cat]["valid"] = None
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
                    await context.bot.send_message(chat_id=chat_id, text=f"⚠️ پاسخ {user.full_name} در دیتابیس موجود نیست و نتوانستم آن را برای سازنده ارسال کنم.")
            else:
                await context.bot.send_message(chat_id=chat_id, text=f"⚠️ مالک بازی تعیین نشده است؛ پاسخ در حالت معلق قرار گرفت.")

# ---------- تایید دستی سازنده ----------
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

    path = os.path.join(DATA_PATH, CATEGORY_FILES[cat])
    VALID_MAP.setdefault(cat, set()).add(text)
    save_json_list(path, VALID_MAP[cat])
    user_map[cat]["valid"] = True
    await query.edit_message_text(f"✅ پاسخ «{text}» تأیید شد و به دیتابیس اضافه شد.")
    try:
        await context.bot.send_message(chat_id=chat_id, text=f"✅ پاسخ برای دسته «{cat}» توسط سازنده تأیید شد.")
    except Exception:
        pass
    await check_if_category_complete(context, chat_id, cat)

async def manual_no_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
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

# ---------- بررسی تکمیل دسته ----------
async def check_if_category_complete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, cat_name: str):
    g = games.get(chat_id)
    if not g:
        return
    all_checked = True
    for uid, _ in g.get("players", []):
        status = g.get("answers_by_user", {}).get(uid, {}).get(cat_name, {}).get("valid")
        if status is None:
            all_checked = False
            break
    if all_checked:
        await context.bot.send_message(chat_id=chat_id, text=f"✅ دسته «{cat_name}» بررسی و تکمیل شد.")
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
    except Exception:
        logger.exception("ارسال نتیجه به گروه ناموفق بود")

    preserved_players = g.get("players", [])
    preserved_scores = g.get("total_scores", {})
    games[chat_id] = {"owner": g.get("owner"), "players": preserved_players, "total_scores": preserved_scores}
    user_active_category.pop(chat_id, None)

# ---------- پایان راند در صورت تایم‌اوت ----------
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