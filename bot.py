import re
import time
import os
import json
import asyncio
import nest_asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler,
    CommandHandler, CallbackQueryHandler, ChatMemberHandler, filters
)

nest_asyncio.apply()
TOKEN = "8080826250:AAHY4wpmF46mcLSkZVTxr8paB8IHh5VNbPM"  # 🔐 ВСТАВЬ СЮДА СВОЙ ТОКЕН

GROUPS_DIR = "groups"
os.makedirs(GROUPS_DIR, exist_ok=True)

# 🔁 Генерация паттернов с обходами
def generate_patterns(word):
    clean = word.lower()
    base = ''.join([f"[{re.escape(c)}]+[ .\\-_@*]?" for c in clean])
    return [
        fr"(?i){word}",
        fr"(?i){base[:-9]}",  # убираем последний необязательный символ
    ]

# 📂 Загрузка badwords.txt
def load_badwords():
    path = "badwords.txt"
    with open(path, "r", encoding="utf-8") as f:
        patterns = [line.strip() for line in f if line.strip()]
    
    compiled = []
    for i, p in enumerate(patterns, start=1):
        try:
            compiled.append(re.compile(p))
        except re.error as e:
            print(f"[!] Ошибка в строке {i}: {p} → {e}")
    return compiled

# 🧠 Пользовательские группы
def user_group_file(user_id):
    return os.path.join(GROUPS_DIR, f"{user_id}.json")

def save_user_group(user_id, group_id, title, is_admin):
    path = user_group_file(user_id)
    data = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    data[str(group_id)] = {"title": title, "is_admin": is_admin}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

def load_user_groups(user_id):
    path = user_group_file(user_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# /start — Главное меню
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    keyboard = [
        [
            InlineKeyboardButton("➕ Добавить в группу", url=f"https://t.me/{context.bot.username}?startgroup=true"),
            InlineKeyboardButton("📋 Мои группы", callback_data="my_groups")
        ],
        [
            InlineKeyboardButton("ℹ️ Информация", callback_data="info"),
            InlineKeyboardButton("💬 Поддержка", url="https://t.me/Azimchik_tg")
        ]
    ]
    await update.message.reply_text(
        "👋 Привет! Я — *модератор-бот*, который:\n"
        "- удаляет запрещённые сообщения\n"
        "- блокирует нарушителей\n"
        "- помогает поддерживать порядок\n\n"
        "➤ Добавь меня в свою группу, и я начну работу!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# 🔘 Инлайн-кнопки
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "info":
        await query.edit_message_text(
            "📘 *О боте:*\n"
            "Удаляет рекламу, маты, ссылки и спам.\n"
            "После 5 нарушений — блокировка сообщений.\n"
            "👨‍💻 Управляется кнопками и работает как админ.",
            parse_mode="Markdown"
        )
    elif query.data == "my_groups":
        groups = load_user_groups(user_id)
        if not groups:
            await query.edit_message_text("ℹ️ Я пока не добавлен ни в одну группу.")
            return

        buttons = []
        for gid, info in groups.items():
            label = f"{info['title']} ({'✅ Админ' if info['is_admin'] else '❌ Не админ'})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"settings_{gid}")])

        await query.edit_message_text(
            "*📋 Мои группы:*",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown"
        )
    elif query.data.startswith("settings_"):
        chat_id = query.data.split("_")[1]
        groups = load_user_groups(user_id)
        info = groups.get(chat_id)
        if not info:
            await query.edit_message_text("⚠️ Группа не найдена.")
            return

        muted = context.chat_data.get("muted_users", {})
        await query.edit_message_text(
            f"*Группа:* {info['title']}\n"
            f"*ID:* `{chat_id}`\n"
            f"*Админ:* {'✅' if info['is_admin'] else '❌'}\n"
            f"*Замучено:* {len(muted)} пользователей",
            parse_mode="Markdown"
        )

# 👥 Учёт групп
async def track_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.my_chat_member.chat
    user = update.my_chat_member.from_user
    new_status = update.my_chat_member.new_chat_member.status

    if new_status in ["member", "administrator"]:
        save_user_group(
            user.id,
            chat.id,
            chat.title or str(chat.id),
            is_admin=new_status == "administrator"
        )

# 🧹 Модерация сообщений
badword_patterns = load_badwords()

async def clean_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user = update.effective_user
    chat = update.effective_chat
    text = update.message.text or update.message.caption or ""

    if user.username == "GroupAnonymousBot" or user.id == 1087968824:
        return

    for pattern in badword_patterns:
        if pattern.search(text):
            try:
                await update.message.delete()
            except:
                pass

            uid = user.id
            violations = context.chat_data.setdefault("violations", {})
            violations[uid] = violations.get(uid, 0) + 1
            count = violations[uid]

            if count < 5:
                await context.bot.send_message(
                    chat.id,
                    f"⚠️ @{user.username or user.first_name}, предупреждение {count}/5. Не нарушай!"
                )
            else:
                await context.bot.restrict_chat_member(
                    chat.id, uid, ChatPermissions(can_send_messages=False)
                )
                context.chat_data.setdefault("muted_users", {})[uid] = {
                    "username": user.username,
                    "name": user.first_name,
                    "muted_at": time.time()
                }
                await context.bot.send_message(
                    chat.id,
                    f"🚫 @{user.username or user.first_name}, ты получил 5 нарушений и теперь замучен. Обратись к админам."
                )
            return

# 🔕 Удаление приветствий
async def handle_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        try:
            await update.message.delete()
        except:
            pass

# 🚀 Запуск
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(ChatMemberHandler(track_group, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_member))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, handle_member))
    app.add_handler(MessageHandler(filters.TEXT | filters.Caption, clean_messages))

    print("🤖 Бот запущен и слушает...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
