# ============================================================
#  main.py — Telegram-бот поиска свободных юзернеймов
# ============================================================

import asyncio
import json
import logging
import os
import random
import string
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from telethon import TelegramClient, errors, functions
from telethon.sessions import StringSession

# ============================================================
#                   ДАННЫЕ АККАУНТА
# ============================================================
API_ID         = int(os.getenv("TELEGRAM_API_ID", "34714558"))
API_HASH       = os.getenv("TELEGRAM_API_HASH", "335d8883ab3c4b1c8fd7662ea5219bfc")
BOT_TOKEN      = os.getenv("BOT_TOKEN", "8850699128:AAF9nd8EM3sKeJA-kfbRv2YQ75Zha3i0crs")
ADMIN_IDS      = [int(x) for x in os.getenv("ADMIN_IDS", "8754872846").split(",") if x.strip().isdigit()]

# Строка сессии Telethon. Пока пусто — сработает режим логина через бота.
SESSION_STRING = os.getenv("SESSION_STRING", "").strip()
# ============================================================

LOGIN_MODE = not SESSION_STRING

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

SETTINGS_FILE = Path("settings.json")
DEFAULT_SETTINGS = {
    "length": 6,
    "count": 10,
    "prefix": "",
    "suffix": "",
    "check_delay": 0.6,
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for k, v in DEFAULT_SETTINGS.items():
                data.setdefault(k, v)
            return data
        except Exception:
            log.exception("settings read error")
    return DEFAULT_SETTINGS.copy()


def save_settings(s: dict) -> None:
    try:
        SETTINGS_FILE.write_text(
            json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        log.exception("settings write error")


settings = load_settings()

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
client = TelegramClient(
    StringSession(SESSION_STRING if SESSION_STRING else ""),
    API_ID,
    API_HASH,
)

CHARS = string.ascii_lowercase + string.digits + "_"
SEARCH_RUNNING = False


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def valid_format(u: str) -> bool:
    if not (5 <= len(u) <= 32):
        return False
    if u[0] not in string.ascii_lowercase:
        return False
    if "__" in u or u.endswith("_"):
        return False
    return all(c in CHARS for c in u)


def generate_username(length: int, prefix: str = "", suffix: str = "") -> str:
    body_len = length - len(prefix) - len(suffix)
    if body_len < 1:
        return ""
    body = "".join(random.choice(CHARS) for _ in range(body_len))
    return f"{prefix}{body}{suffix}"


async def check_username(username: str):
    u = username.lstrip("@").lower()
    if not valid_format(u):
        return None
    while True:
        try:
            await client(functions.contacts.ResolveUsernameRequest(username=u))
            return False
        except errors.UsernameNotOccupiedError:
            return True
        except errors.UsernameInvalidError:
            return None
        except errors.FloodWaitError as e:
            log.warning("FloodWait %s сек", e.seconds)
            await asyncio.sleep(e.seconds)
        except Exception as e:
            log.exception("check error: %s", e)
            return None


class SettingsState(StatesGroup):
    waiting_length = State()
    waiting_count  = State()
    waiting_prefix = State()
    waiting_suffix = State()
    waiting_delay  = State()


class LoginState(StatesGroup):
    waiting_phone    = State()
    waiting_code     = State()
    waiting_password = State()


def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Начать поиск", callback_data="start_search")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton(text="📊 Текущие настройки", callback_data="show_settings")],
    ])


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📏 Длина: {settings['length']}", callback_data="set_length")],
        [InlineKeyboardButton(text=f"🔢 Сколько найти: {settings['count']}", callback_data="set_count")],
        [InlineKeyboardButton(text=f"🅰️ Префикс: '{settings['prefix'] or '—'}'", callback_data="set_prefix")],
        [InlineKeyboardButton(text=f"🅱️ Суффикс: '{settings['suffix'] or '—'}'", callback_data="set_suffix")],
        [InlineKeyboardButton(text=f"⏱ Задержка: {settings['check_delay']}с", callback_data="set_delay")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")],
    ])


def login_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Войти в аккаунт Telethon", callback_data="do_login")],
    ])


# ============================================================
#                        ХЭНДЛЕРЫ
# ============================================================
@dp.message(Command("id"))
async def cmd_id(m: Message):
    await m.answer(f"Твой ID: <code>{m.from_user.id}</code>")


@dp.message(Command("start", "menu"))
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    if not is_admin(m.from_user.id):
        await m.answer("❌ Доступ только для админа.")
        return
    if LOGIN_MODE:
        await m.answer(
            "⚠️ <b>Бот ещё не авторизован в Telegram-аккаунте юзербота.</b>\n\n"
            "Нажми кнопку ниже. После получения строки сессии вставь её в "
            "переменную <code>SESSION_STRING</code> и перезапусти бота.",
            reply_markup=login_kb(),
        )
        return
    await m.answer(
        "👋 <b>Бот-искатель свободных юзернеймов</b>\n\n"
        "1. Зайди в ⚙️ Настройки\n"
        "2. Укажи длину и количество\n"
        "3. Нажми 🔍 Начать поиск",
        reply_markup=main_kb(),
    )


# ============================================================
#                    ЛОГИН В TELETHON
# ============================================================
@dp.callback_query(F.data == "do_login")
async def cb_do_login(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id):
        await c.answer("Нет доступа", show_alert=True)
        return
    await c.message.edit_text(
        "📱 Отправь номер телефона юзербота в формате <code>+79991234567</code>"
    )
    await state.set_state(LoginState.waiting_phone)
    await c.answer()


@dp.message(LoginState.waiting_phone)
async def msg_phone(m: Message, state: FSMContext):
    phone = m.text.strip().replace(" ", "")
    if not phone.startswith("+") or not phone[1:].isdigit():
        await m.answer("❌ Формат: <code>+79991234567</code>")
        return
    try:
        await client.connect()
        sent = await client.send_code_request(phone)
        await state.update_data(phone=phone, phone_code_hash=sent.phone_code_hash)
        await m.answer(
            "📨 Код отправлен в Telegram.\n\n"
            "Отправь код сюда. Формат: <code>1 2 3 4 5</code> или <code>12345</code>"
        )
        await state.set_state(LoginState.waiting_code)
    except Exception as e:
        log.exception("send_code error")
        await m.answer(f"❌ Ошибка отправки кода: <code>{e}</code>")


@dp.message(LoginState.waiting_code)
async def msg_code(m: Message, state: FSMContext):
    code = m.text.strip().replace(" ", "")
    data = await state.get_data()
    phone = data.get("phone")
    phone_code_hash = data.get("phone_code_hash")
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
    except errors.SessionPasswordNeededError:
        await m.answer("🔐 Включена 2FA. Отправь пароль:")
        await state.set_state(LoginState.waiting_password)
        return
    except errors.PhoneCodeInvalidError:
        await m.answer("❌ Неверный код. Попробуй ещё раз.")
        return
    except errors.PhoneCodeExpiredError:
        await m.answer("❌ Код истёк. Начни заново — /start → 🔑 Войти.")
        await state.clear()
        return
    except Exception as e:
        log.exception("sign_in error")
        await m.answer(f"❌ Ошибка входа: <code>{e}</code>")
        await state.clear()
        return
    await send_session_string(m, state)


@dp.message(LoginState.waiting_password)
async def msg_password(m: Message, state: FSMContext):
    try:
        await client.sign_in(password=m.text.strip())
    except Exception as e:
        log.exception("password error")
        await m.answer(f"❌ Неверный пароль или ошибка: <code>{e}</code>")
        return
    await send_session_string(m, state)


async def send_session_string(m: Message, state: FSMContext):
    try:
        me = await client.get_me()
        session_str = client.session.save()
        await m.answer(
            f"✅ <b>Успешный вход!</b>\n"
            f"Аккаунт: {me.first_name} (@{me.username or '—'}, id={me.id})\n\n"
            f"<b>Скопируй строку ниже и вставь её в переменную окружения "
            f"<code>SESSION_STRING</code> (или прямо в код в блок "
            f"<code>SESSION_STRING = ...</code>), затем перезапусти бота:</b>"
        )
        await m.answer(f"<code>{session_str}</code>")
    except Exception as e:
        log.exception("save session error")
        await m.answer(f"❌ Ошибка сохранения сессии: <code>{e}</code>")
    finally:
        await state.clear()


# ============================================================
#                    ОСНОВНЫЕ ХЭНДЛЕРЫ
# ============================================================
@dp.callback_query(F.data == "back_main")
async def cb_back_main(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text("🏠 Главное меню", reply_markup=main_kb())
    await c.answer()


@dp.callback_query(F.data == "settings")
async def cb_settings(c: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_admin(c.from_user.id):
        await c.answer("Нет доступа", show_alert=True)
        return
    if LOGIN_MODE:
        await c.answer("Сначала авторизуйся через /start", show_alert=True)
        return
    await c.message.edit_text("⚙️ <b>Настройки</b>", reply_markup=settings_kb())
    await c.answer()


@dp.callback_query(F.data == "show_settings")
async def cb_show_settings(c: CallbackQuery, state: FSMContext):
    await state.clear()
    s = settings
    txt = (
        f"📊 <b>Текущие настройки</b>\n\n"
        f"📏 Длина: <code>{s['length']}</code>\n"
        f"🔢 Найти: <code>{s['count']}</code>\n"
        f"🅰️ Префикс: <code>{s['prefix'] or '—'}</code>\n"
        f"🅱️ Суффикс: <code>{s['suffix'] or '—'}</code>\n"
        f"⏱ Задержка: <code>{s['check_delay']}</code> сек\n"
    )
    await c.message.edit_text(txt, reply_markup=back_kb())
    await c.answer()


@dp.callback_query(F.data == "set_length")
async def cb_set_length(c: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsState.waiting_length)
    await c.message.edit_text(
        "📏 Введи длину юзернейма (5–32).\nНапример: <code>6</code>",
        reply_markup=back_kb(),
    )
    await c.answer()


@dp.message(SettingsState.waiting_length, ~F.text.startswith("/"))
async def msg_length(m: Message, state: FSMContext):
    try:
        v = int(m.text.strip())
        if not (5 <= v <= 32):
            raise ValueError
    except Exception:
        await m.answer("❌ Нужно число от 5 до 32.")
        return
    settings["length"] = v
    save_settings(settings)
    await state.clear()
    await m.answer(f"✅ Длина = <b>{v}</b>", reply_markup=main_kb())


@dp.callback_query(F.data == "set_count")
async def cb_set_count(c: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsState.waiting_count)
    await c.message.edit_text(
        "🔢 Сколько свободных найти? (1–50)", reply_markup=back_kb()
    )
    await c.answer()


@dp.message(SettingsState.waiting_count, ~F.text.startswith("/"))
async def msg_count(m: Message, state: FSMContext):
    try:
        v = int(m.text.strip())
        if not (1 <= v <= 50):
            raise ValueError
    except Exception:
        await m.answer("❌ Нужно число от 1 до 50.")
        return
    settings["count"] = v
    save_settings(settings)
    await state.clear()
    await m.answer(f"✅ Найти: <b>{v}</b>", reply_markup=main_kb())


@dp.callback_query(F.data == "set_prefix")
async def cb_set_prefix(c: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsState.waiting_prefix)
    await c.message.edit_text(
        "🅰️ Введи префикс (или <code>-</code> чтобы убрать).\nНапример: <code>neo_</code>",
        reply_markup=back_kb(),
    )
    await c.answer()


@dp.message(SettingsState.waiting_prefix, ~F.text.startswith("/"))
async def msg_prefix(m: Message, state: FSMContext):
    t = m.text.strip().lower()
    if t == "-":
        t = ""
    if t and not all(ch in CHARS for ch in t):
        await m.answer("❌ Только a-z, 0-9 и _")
        return
    settings["prefix"] = t
    save_settings(settings)
    await state.clear()
    await m.answer(f"✅ Префикс: '<b>{t or '—'}</b>'", reply_markup=main_kb())


@dp.callback_query(F.data == "set_suffix")
async def cb_set_suffix(c: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsState.waiting_suffix)
    await c.message.edit_text(
        "🅱️ Введи суффикс (или <code>-</code> чтобы убрать).\nНапример: <code>_bot</code>",
        reply_markup=back_kb(),
    )
    await c.answer()


@dp.message(SettingsState.waiting_suffix, ~F.text.startswith("/"))
async def msg_suffix(m: Message, state: FSMContext):
    t = m.text.strip().lower()
    if t == "-":
        t = ""
    if t and not all(ch in CHARS for ch in t):
        await m.answer("❌ Только a-z, 0-9 и _")
        return
    settings["suffix"] = t
    save_settings(settings)
    await state.clear()
    await m.answer(f"✅ Суффикс: '<b>{t or '—'}</b>'", reply_markup=main_kb())


@dp.callback_query(F.data == "set_delay")
async def cb_set_delay(c: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsState.waiting_delay)
    await c.message.edit_text(
        "⏱ Введи задержку в секундах (0.4–5).\nМеньше 0.4 — риск бана юзербота!",
        reply_markup=back_kb(),
    )
    await c.answer()


@dp.message(SettingsState.waiting_delay, ~F.text.startswith("/"))
async def msg_delay(m: Message, state: FSMContext):
    try:
        v = float(m.text.strip().replace(",", "."))
        if not (0.4 <= v <= 5):
            raise ValueError
    except Exception:
        await m.answer("❌ Нужно число от 0.4 до 5.")
        return
    settings["check_delay"] = v
    save_settings(settings)
    await state.clear()
    await m.answer(f"✅ Задержка: <b>{v}</b> сек", reply_markup=main_kb())


@dp.callback_query(F.data == "start_search")
async def cb_start_search(c: CallbackQuery):
    global SEARCH_RUNNING
    if not is_admin(c.from_user.id):
        await c.answer("Нет доступа", show_alert=True)
        return
    if LOGIN_MODE:
        await c.answer("Сначала авторизуйся через /start", show_alert=True)
        return
    if SEARCH_RUNNING:
        await c.answer("⏳ Поиск уже идёт, подожди.", show_alert=True)
        return
    await c.answer()

    length = settings["length"]
    count  = settings["count"]
    prefix = settings["prefix"]
    suffix = settings["suffix"]
    delay  = settings["check_delay"]

    if length < len(prefix) + len(suffix) + 1:
        await c.message.answer("❌ Длина меньше суммы префикса и суффикса + 1.")
        return

    status = await c.message.answer(
        f"🔍 Ищу <b>{count}</b> свободных длиной <b>{length}</b>...\nПрогресс: 0/{count}"
    )
    SEARCH_RUNNING = True
    asyncio.create_task(run_search(status, length, count, prefix, suffix, delay))


async def run_search(status_msg, length, count, prefix, suffix, delay):
    global SEARCH_RUNNING
    found: list[str] = []
    checked = 0
    max_attempts = count * 300

    try:
        while len(found) < count and checked < max_attempts:
            checked += 1
            u = generate_username(length, prefix, suffix)
            if not u or not valid_format(u):
                continue
            r = await check_username(u)
            await asyncio.sleep(delay)

            if r is True:
                found.append(u)
                try:
                    await status_msg.edit_text(
                        f"🔍 Ищу <b>{count}</b> свободных...\n"
                        f"Найдено: <b>{len(found)}</b>/{count}\n"
                        f"Проверено: {checked}"
                    )
                except Exception:
                    pass

        if not found:
            await status_msg.edit_text(
                "😔 Ничего не нашлось. Попробуй длину побольше."
            )
            return

        header = f"✅ <b>Найдено {len(found)} свободных:</b>\n\n"
        lines = "\n".join(f"@{u}" for u in found)
        full = header + f"<code>{lines}</code>"

        if len(full) <= 4000:
            await status_msg.edit_text(full)
        else:
            chunks, cur = [], ""
            for u in found:
                if len(cur) + len(u) + 2 > 3500:
                    chunks.append(cur)
                    cur = ""
                cur += f"@{u}\n"
            if cur:
                chunks.append(cur)
            await status_msg.edit_text(header)
            for ch in chunks:
                await status_msg.answer(f"<code>{ch}</code>")
    except Exception:
        log.exception("search error")
        try:
            await status_msg.edit_text("❌ Ошибка во время поиска. Смотри логи.")
        except Exception:
            pass
    finally:
        SEARCH_RUNNING = False


# ============================================================
#                        ЗАПУСК
# ============================================================
async def main():
    if LOGIN_MODE:
        log.warning("⚠️ SESSION_STRING не задан — режим логина.")
        log.warning("Напиши боту /start и авторизуйся.")
    else:
        await client.start()
        me = await client.get_me()
        log.info("Telethon запущен: %s (@%s)", me.first_name, me.username)
    log.info("Админы: %s", ADMIN_IDS)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
