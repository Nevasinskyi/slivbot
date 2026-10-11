import asyncio
import sqlite3
from aiogram import F
from aiogram.types import Message

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# ==========================================
# НАСТРОЙКИ
# ==========================================

BOT_TOKEN = "8981763316:AAHArSdZbVoWqf-F5_utfBkmfmZELpBPjPA"

GROUP_ID = -1004477990369
CHANNEL_ID = -1003860719061

# Telegram ID модераторов
ADMIN_IDS = {
    940460718,
}

# ==========================================
# ИНИЦИАЛИЗАЦИЯ
# ==========================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db = sqlite3.connect("bot.db")
db.execute("""
    CREATE TABLE IF NOT EXISTS banned_users (
        user_id INTEGER PRIMARY KEY
    )
""")
db.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        card_id INTEGER PRIMARY KEY,
        source_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
    )
""")
db.commit()

# ID сообщения-подсказки -> ID пользователя
pending_replies = {}

@dp.message(F.text == ".id")
async def get_chat_id(message: Message):
    await message.answer(
        f"Название: {message.chat.title}\n"
        f"ID чата: {message.chat.id}"

    )

# ==========================================
# БАЗА ДАННЫХ
# ==========================================

def is_banned(user_id: int) -> bool:
    result = db.execute(
        "SELECT 1 FROM banned_users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return result is not None


def ban_user(user_id: int):
    db.execute(
        "INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)",
        (user_id,),
    )
    db.commit()


def save_submission(
    card_id: int,
    source_id: int,
    user_id: int,
):
    db.execute(
        """
        INSERT OR REPLACE INTO submissions
        (card_id, source_id, user_id, status)
        VALUES (?, ?, ?, 'pending')
        """,
        (card_id, source_id, user_id),
    )
    db.commit()


def get_submission(card_id: int):
    return db.execute(
        """
        SELECT source_id, user_id, status
        FROM submissions
        WHERE card_id = ?
        """,
        (card_id,),
    ).fetchone()


def set_status(card_id: int, status: str):
    db.execute(
        "UPDATE submissions SET status = ? WHERE card_id = ?",
        (status, card_id),
    )
    db.commit()


# ==========================================
# КНОПКИ МОДЕРАЦИИ
# ==========================================

def moderation_keyboard(user_id: int, card_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"accept:{card_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject:{card_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✉️ Написать сообщение",
                    callback_data=f"reply:{card_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Забанить пользователя",
                    callback_data=f"ban:{user_id}:{card_id}",
                ),
            ],
        ]
    )


# ==========================================
# ПРОВЕРКА МОДЕРАТОРА
# ==========================================

async def check_moderator(
    callback: CallbackQuery,
) -> bool:
    if (
        callback.from_user.id not in ADMIN_IDS
        or callback.message is None
        or callback.message.chat.id != GROUP_ID
    ):
        await callback.answer(
            "У тебя нет доступа к этому действию.",
            show_alert=True,
        )
        return False

    return True


# ==========================================
# /START
# ==========================================

@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    if message.from_user is None:
        return

    if is_banned(message.from_user.id):
        await message.answer("Вы забанены.")
        return

    await message.answer(
        "Привет!\n\n"
        "Отправь мне свой тейк"
        "Я передам его модераторам."
    )


# ==========================================
# ПРИЁМ ТЕЙКОВ
# ==========================================

@dp.message(F.chat.type == "private")
async def receive_message(message: Message):
    user = message.from_user

    if user is None:
        return

    if is_banned(user.id):
        await message.answer("Вы забанены.")
        return

    # Не принимаем команды как тейки
    if message.text and message.text.startswith("/"):
        return

    username = (
        f"@{user.username}"
        if user.username
        else "не указан"
    )

    caption = (
        "📩 НОВЫЙ ТЕЙК\n\n"
        f"Имя: {user.full_name}\n"
        f"Username: {username}\n"
        f"ID: {user.id}"
    )

    # Создаём карточку модерации
    card = await bot.send_message(
        chat_id=GROUP_ID,
        text=caption,
    )

    try:
        # Копируем исходное сообщение в группу
        copied = await bot.copy_message(
            chat_id=GROUP_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_to_message_id=card.message_id,
        )
    except Exception as error:
        await card.delete()
        print(f"Ошибка копирования сообщения: {error}")
        await message.answer(
            "Не удалось отправить тейк на модерацию. "
            "Попробуй ещё раз позже."
        )
        return

    # Сохраняем связь карточки с сообщением и пользователем
    save_submission(
        card_id=card.message_id,
        source_id=copied.message_id,
        user_id=user.id,
    )

    await card.edit_reply_markup(
        reply_markup=moderation_keyboard(
            user_id=user.id,
            card_id=card.message_id,
        )
    )

    await message.answer(
        "Твой тейк отправлен на модерацию."
    )


# ==========================================
# ПОЛУЧЕНИЕ ТЕЙКА ДЛЯ ДЕЙСТВИЯ
# ==========================================

async def get_pending_submission(
    callback: CallbackQuery,
    card_id: int,
):
    row = get_submission(card_id)

    if row is None:
        await callback.answer(
            "Тейк не найден.",
            show_alert=True,
        )
        return None

    source_id, user_id, status = row

    if status != "pending":
        await callback.answer(
            "С этим тейком уже работали.",
            show_alert=True,
        )
        return None

    return source_id, user_id


# ==========================================
# ПРИНЯТЬ ТЕЙК
# ==========================================

@dp.callback_query(F.data.startswith("accept:"))
async def accept_handler(callback: CallbackQuery):
    if not await check_moderator(callback):
        return

    if callback.message is None:
        return

    card_id = int(callback.data.split(":")[1])

    submission = await get_pending_submission(
        callback,
        card_id,
    )
    if submission is None:
        return

    source_id, user_id = submission

    try:
        # Публикуем копию исходного сообщения в канале
        await bot.copy_message(
            chat_id=CHANNEL_ID,
            from_chat_id=GROUP_ID,
            message_id=source_id,
        )
    except Exception as error:
        print(f"Ошибка публикации: {error}")
        await callback.answer(
            "Не удалось опубликовать. Проверь права бота в канале.",
            show_alert=True,
        )
        return

    set_status(card_id, "accepted")

    await callback.message.edit_reply_markup(
        reply_markup=None,
    )

    try:
        await bot.send_message(
            chat_id=user_id,
            text="тейк приняли и опубликовали!",
        )
    except Exception:
        pass

    await callback.answer("Тейк опубликован!")


# ==========================================
# ОТКЛОНИТЬ ТЕЙК
# ==========================================

@dp.callback_query(F.data.startswith("reject:"))
async def reject_handler(callback: CallbackQuery):
    if not await check_moderator(callback):
        return

    if callback.message is None:
        return

    card_id = int(callback.data.split(":")[1])

    submission = await get_pending_submission(
        callback,
        card_id,
    )
    if submission is None:
        return

    source_id, user_id = submission

    try:
        await bot.send_message(
            chat_id=user_id,
            text="Ваш тейк отклонили.",
        )
    except Exception:
        await callback.answer(
            "Не удалось написать пользователю.",
            show_alert=True,
        )
        return

    set_status(card_id, "rejected")

    await callback.message.edit_reply_markup(
        reply_markup=None,
    )

    await callback.answer("Тейк отклонён.")


# ==========================================
# ЗАБАНИТЬ ПОЛЬЗОВАТЕЛЯ
# ==========================================

@dp.callback_query(F.data.startswith("ban:"))
async def ban_handler(callback: CallbackQuery):
    if not await check_moderator(callback):
        return

    if callback.message is None:
        return

    parts = callback.data.split(":")
    user_id = int(parts[1])
    card_id = int(parts[2])

    ban_user(user_id)

    row = get_submission(card_id)
    if row is not None and row[2] == "pending":
        set_status(card_id, "banned")

    await callback.message.edit_reply_markup(
        reply_markup=None,
    )

    await callback.message.answer(
        f"Пользователь {user_id} забанен в боте."
    )

    try:
        await bot.send_message(
            chat_id=user_id,
            text="Вы забанены.",
        )
    except Exception:
        pass

    await callback.answer("Пользователь забанен.")


# ==========================================
# ЗАПРОС ОТВЕТА ПОЛЬЗОВАТЕЛЮ
# ==========================================

@dp.callback_query(F.data.startswith("reply:"))
async def reply_handler(callback: CallbackQuery):
    if not await check_moderator(callback):
        return

    if callback.message is None:
        return

    card_id = int(callback.data.split(":")[1])

    submission = await get_pending_submission(
        callback,
        card_id,
    )
    if submission is None:
        return

    source_id, user_id = submission

    prompt = await callback.message.answer(
        f"✉️ Введите сообщение для пользователя {user_id}.\n\n"
        "Отправьте ответ именно ответом на это сообщение."
    )

    pending_replies[prompt.message_id] = user_id

    await callback.answer("Ожидаю сообщение.")


# ==========================================
# ОТПРАВИТЬ ОТВЕТ ПОЛЬЗОВАТЕЛЮ
# ==========================================

@dp.message(F.chat.id == GROUP_ID, F.reply_to_message)
async def send_reply_handler(message: Message):
    if message.from_user is None:
        return

    if message.from_user.id not in ADMIN_IDS:
        return

    replied = message.reply_to_message

    user_id = pending_replies.get(replied.message_id)

    if user_id is None:
        return

    if is_banned(user_id):
        await message.reply(
            "Пользователь забанен. Сообщение не отправлено."
        )
        pending_replies.pop(replied.message_id, None)
        return

    if not message.text:
        await message.reply(
            "Отправь текстовый ответ."
        )
        return

    try:
        await bot.send_message(
            chat_id=user_id,
            text=message.text,
        )

        await message.reply(
            "Сообщение отправлено пользователю."
        )

    except Exception as error:
        print(f"Ошибка отправки ответа: {error}")
        await message.reply(
            "Не удалось отправить сообщение пользователю."
        )

    pending_replies.pop(replied.message_id, None)


# ==========================================
# ЗАПУСК БОТА
# ==========================================

async def main():
    print("Бот запущен.")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())