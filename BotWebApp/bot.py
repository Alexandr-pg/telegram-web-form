import os
import json
import hashlib
import hmac
from datetime import datetime
from urllib.parse import parse_qsl
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    Message
)
from aiogram.filters import Command, CommandStart
import logging

load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://your-domain.com/webapp")  # HTTPS URL вашей формы
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "").lstrip("@")
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in the environment")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def verify_telegram_init_data(init_data: str, bot_token: str) -> bool:
    """
    Проверка подлинности данных из Telegram Web App
    """
    try:
        # Telegram присылает query string с URL-encoded значениями
        params = dict(parse_qsl(init_data, keep_blank_values=True))

        # Получаем hash и удаляем его из параметров
        received_hash = params.pop('hash', None)

        if not received_hash:
            return False

        # Сортируем параметры и создаем строку для проверки
        sorted_params = sorted(params.items())
        data_check_string = '\n'.join([f"{k}={v}" for k, v in sorted_params])

        # Создаем секретный ключ
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256
        ).digest()

        # Вычисляем hash
        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        return computed_hash == received_hash

    except Exception as e:
        logger.error(f"Error verifying init data: {e}")
        return False


def format_form_response(data: dict) -> str:
    """
    Форматирует ответ из формы в красивый шаблон
    """
    # Получаем информацию о пользователе
    user_info = data.get('user', {})
    username = user_info.get('username', 'Не указан')
    first_name = user_info.get('first_name', '')
    last_name = user_info.get('last_name', '')

    user_display = f"{first_name} {last_name}".strip()
    if user_display:
        user_display += f" (@{username})" if username else ""
    else:
        user_display = f"@{username}" if username else "Пользователь"

    # Поля формы
    fields = {
        "📋 Назначение платежа": data.get('purpose', 'Не указано'),
        "🔢 Количество": data.get('quantity', 'Не указано'),
        "🏢 Подотдел": data.get('subdivision', 'Не указано'),
        "📑 Подстатья": data.get('subarticle', 'Не указано'),
        "💳 Метод оплаты": data.get('payment_method', 'Не указано'),
        "💳 Банковская карта": data.get('card_number', 'Не указано'),
        "📝 Реквизиты": data.get('requisites', 'Не указано'),
        "💰 Сумма и валюта": data.get('amount', 'Не указано')
    }

    # Формируем красивое сообщение
    result = f"✅ <b>Новая заявка</b>\n\n"
    result += f"👤 <b>Отправитель:</b> {user_display}\n"
    result += f"🕐 <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
    result += "─" * 30 + "\n\n"

    for label, value in fields.items():
        result += f"<b>{label}:</b>\n{value}\n\n"

    result += "─" * 30 + "\n"
    result += "<i>Заявка сформирована через Web App</i>"

    return result


@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    if message.chat.type == "private":
        await show_form_button(message)
    else:
        await show_private_chat_button(message)


async def show_form_button(message: Message):
    """Показывает кнопку для открытия Web App"""
    web_app_button = KeyboardButton(
        text="📝 Заполнить анкету",
        web_app=WebAppInfo(url=WEB_APP_URL)
    )

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[web_app_button]],
        resize_keyboard=True,
        one_time_keyboard=False
    )

    await message.answer(
        "📋 Нажмите кнопку ниже, чтобы заполнить анкету:",
        reply_markup=keyboard
    )


@dp.message(Command("form"))
async def cmd_form(message: Message):
    """Повторно показывает кнопку формы в личном чате"""
    if message.chat.type != "private":
        await show_private_chat_button(message)
        return

    await show_form_button(message)


async def show_private_chat_button(message: Message):
    """Показывает ссылку на личный чат с ботом, где доступен Web App"""
    if not BOT_USERNAME:
        await message.answer(
            "⚠️ У бота не настроен BOT_USERNAME. Откройте бота в личных сообщениях и отправьте /start."
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Открыть бота",
                url=f"https://t.me/{BOT_USERNAME}?start=webapp"
            )
        ]]
    )

    await message.answer(
        "📋 Telegram разрешает Web App только в личном чате с ботом.\n"
        "Откройте бота по кнопке ниже, затем нажмите \"📝 Заполнить анкету\".\n"
        "Если кнопка не появилась, отправьте команду /form в личном чате.",
        reply_markup=keyboard
    )


@dp.message(F.web_app_data)
async def handle_web_app_data(message: Message):
    """
    Обработка данных из Web App
    """
    try:
        # Получаем данные из Web App
        web_app_data = message.web_app_data
        data = json.loads(web_app_data.data)

        # Проверяем initData для безопасности
        init_data = data.get('initData', '')
        if init_data and not verify_telegram_init_data(init_data, BOT_TOKEN):
            logger.warning(f"Invalid initData from user {message.from_user.id}")
            await message.answer("⚠️ Ошибка безопасности. Попробуйте снова.")
            return

        # Форматируем ответ
        form_data = data.get('formData', {})
        response_text = format_form_response(form_data)
        destination_chat_id = int(TARGET_CHAT_ID) if TARGET_CHAT_ID else message.chat.id

        # Подтверждаем отправку пользователю и убираем клавиатуру
        await message.answer(
            "✅ Анкета успешно отправлена!",
            reply_markup=types.ReplyKeyboardRemove()
        )

        # Отправляем результат в целевой чат или в текущий чат по умолчанию
        await bot.send_message(
            chat_id=destination_chat_id,
            text=response_text,
            parse_mode="HTML"
        )

        logger.info(
            f"Form submitted by user {message.from_user.id}; source chat={message.chat.id}, target chat={destination_chat_id}"
        )

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        await message.answer("❌ Ошибка обработки данных. Попробуйте снова.")
    except Exception as e:
        logger.error(f"Error processing web app data: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Команда помощи"""
    help_text = """
🤖 <b>Помощь по боту</b>

Бот предназначен для сбора анкет с отправкой результата в чат.

<b>Как использовать:</b>
1. В группе отправьте /start
2. Откройте бота по кнопке из сообщения
3. В личном чате нажмите "📝 Заполнить анкету"
4. Заполните форму и нажмите "Отправить"

Если настроен TARGET_CHAT_ID, анкета появится в указанном чате.

<b>Команды:</b>
/start - Показать инструкцию или кнопку формы
/form - Повторно показать кнопку формы в личном чате
/help - Показать это сообщение
    """
    await message.answer(help_text, parse_mode="HTML")


async def main():
    """Запуск бота"""
    logger.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
