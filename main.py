import os
import re
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from fastapi import FastAPI, Request
from fastapi.responses import Response

# ===== ENV =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WEBHOOK_PATH = "/tg/webhook"
COOLDOWN_HOURS = 12

WEBHOOK_URL = f"{PUBLIC_URL}{WEBHOOK_PATH}"

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

# ===== Anti-spam / Validation =====
last_submit: dict[int, datetime] = {}

# ссылки запрещаем почти везде, но для поля "контакт" разрешим @ и t.me
LINK_RE = re.compile(r"(https?://|t\.me/|www\.)", re.IGNORECASE)
AT_RE = re.compile(r"@", re.IGNORECASE)

def bad_text_general(s: str) -> bool:
    s = (s or "").strip()
    return (not s) or bool(LINK_RE.search(s)) or bool(AT_RE.search(s))

def normalize_contact(raw: str) -> str:
    """
    Принимаем:
      @username
      username
      t.me/username
      https://t.me/username
    Возвращаем красивый кликабельный формат:
      @username (если возможно)
      или исходное значение, если не удаётся нормализовать.
    """
    s = (raw or "").strip()
    s = s.replace("https://", "").replace("http://", "")
    s = s.replace("t.me/", "")
    s = s.replace("telegram.me/", "")
    s = s.strip()

    # убираем лишние символы
    s = s.lstrip("@").strip()

    # username в Telegram: латиница/цифры/подчёркивание, 5-32
    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", s):
        return f"@{s}"

    # если не похоже на username — вернём как есть, но обрежем длину
    return raw.strip()[:64]

def k_start():
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Подать заявку", callback_data="start_form")
    kb.button(text="ℹ️ Требования", callback_data="info")
    kb.adjust(1)
    return kb.as_markup()

def k_cancel():
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="cancel")
    return kb.as_markup()

def k_confirm():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Отправить", callback_data="confirm_send")
    kb.button(text="🔄 Заполнить заново", callback_data="restart")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()

WELCOME = (
    "👋 <b>Набор в клан</b>\n\n"
    "Нажми <b>«Подать заявку»</b> и заполни анкету.\n"
    "Заявка уйдёт офицерам.\n\n"
    "⚠️ В анкете <b>без ссылок</b> (кроме поля контакта)."
)

INFO_TEXT = (
    "ℹ️ <b>Информация / требования</b>\n\n"
    "• Адекватность, без токсичности\n"
    "• Онлайн в прайм (укажи)\n"
    "• Готовность к командной игре\n\n"
    "Нажми <b>«Подать заявку»</b>, чтобы начать."
)

class Form(StatesGroup):
    nick = State()
    contact = State()
    cls = State()
    lvl = State()
    prime = State()
    note = State()
    confirm = State()

def fmt_preview(data: dict) -> str:
    return (
        "🧾 <b>Проверь заявку</b>\n\n"
        f"🔹 Ник: <b>{data.get('nick','-')}</b>\n"
        f"🔹 Контакт TG: <b>{data.get('contact','-')}</b>\n"
        f"🔹 Класс/профа: <b>{data.get('cls','-')}</b>\n"
        f"🔹 Уровень: <b>{data.get('lvl','-')}</b>\n"
        f"🔹 Прайм: <b>{data.get('prime','-')}</b>\n"
        f"📝 Коммент: {data.get('note','-')}\n\n"
        "Если всё верно — нажми <b>«Отправить»</b>."
    )

async def guard_private(m: Message) -> bool:
    if m.chat.type != "private":
        await m.answer("Подача заявки доступна только в личных сообщениях.")
        return False
    return True

# ===== Commands =====
@dp.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    if not await guard_private(m):
        return
    await state.clear()
    await m.answer(WELCOME, reply_markup=k_start(), parse_mode="HTML")

# ===== Callbacks =====
@dp.callback_query(F.data == "info")
async def cb_info(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(INFO_TEXT, reply_markup=k_start(), parse_mode="HTML")
    await cq.answer()

@dp.callback_query(F.data == "start_form")
async def cb_start_form(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(
        "📝 <b>Анкета</b> (1/6)\n\n"
        "Введи <b>ник в игре</b>:",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await cq.answer()

@dp.callback_query(F.data == "cancel")
async def cb_cancel(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(
        "Ок, отменил. Если захочешь — подай заявку заново.",
        reply_markup=k_start(),
        parse_mode="HTML",
    )
    await cq.answer()

@dp.callback_query(F.data == "restart")
async def cb_restart(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(
        "📝 <b>Анкета</b> (1/6)\n\n"
        "Введи <b>ник в игре</b>:",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await cq.answer()

@dp.callback_query(F.data == "confirm_send")
async def cb_confirm_send(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    now = datetime.now(timezone.utc)
    prev = last_submit.get(cq.from_user.id)
    if prev and now - prev < timedelta(hours=COOLDOWN_HOURS):
        await cq.answer(f"Повторная заявка доступна через {COOLDOWN_HOURS} часов.", show_alert=True)
        return

    user = cq.from_user
    msg = (
        "🧾 <b>Новая заявка</b>\n"
        f"👤 TG: {user.full_name} (id: <code>{user.id}</code>)\n"
        f"📩 Контакт: <b>{data.get('contact','-')}</b>\n"
        f"🔹 Ник: <b>{data.get('nick','-')}</b>\n"
        f"🔹 Класс/профа: <b>{data.get('cls','-')}</b>\n"
        f"🔹 Уровень: <b>{data.get('lvl','-')}</b>\n"
        f"🔹 Прайм: <b>{data.get('prime','-')}</b>\n"
        f"📝 Коммент: {data.get('note','-')}\n"
        f"⏱ {now.astimezone(timezone(timedelta(hours=3))).strftime('%Y-%m-%d %H:%M')} (UTC+3)"
    )
    await bot.send_message(ADMIN_CHAT_ID, msg, parse_mode="HTML")

    last_submit[user.id] = now
    await state.clear()

    await cq.message.edit_text(
        "✅ <b>Заявка отправлена</b>\n\n"
        "Офицеры рассмотрят и при необходимости напишут тебе в Telegram.",
        reply_markup=k_start(),
        parse_mode="HTML",
    )
    await cq.answer("Отправлено")

# ===== Form Steps =====
@dp.message(Form.nick)
async def step_nick(m: Message, state: FSMContext):
    if not await guard_private(m):
        return
    if bad_text_general(m.text):
        return await m.answer("⚠️ Ник без ссылок и @. Повтори:", reply_markup=k_cancel(), parse_mode="HTML")

    await state.update_data(nick=m.text.strip())
    await m.answer(
        "📝 <b>Анкета</b> (2/6)\n\n"
        "Укажи <b>контакт в Telegram</b>:\n"
        "• @username\n"
        "• или t.me/username\n\n"
        "Если у тебя нет username — напиши <b>нет</b>.",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.contact)

@dp.message(Form.contact)
async def step_contact(m: Message, state: FSMContext):
    if not await guard_private(m):
        return
    text = (m.text or "").strip()
    if not text:
        return await m.answer("⚠️ Введи контакт или напиши <b>нет</b>.", reply_markup=k_cancel(), parse_mode="HTML")

    if text.lower() in {"нет", "no", "none"}:
        contact = "нет"
    else:
        contact = normalize_contact(text)

    await state.update_data(contact=contact)

    await m.answer("📝 <b>Анкета</b> (3/6)\n\nВведи <b>класс/профу</b>:", reply_markup=k_cancel(), parse_mode="HTML")
    await state.set_state(Form.cls)

@dp.message(Form.cls)
async def step_cls(m: Message, state: FSMContext):
    if not await guard_private(m):
        return
    if bad_text_general(m.text):
        return await m.answer("⚠️ Без ссылок и @. Введи класс/профу текстом:", reply_markup=k_cancel(), parse_mode="HTML")

    await state.update_data(cls=m.text.strip())
    await m.answer("📝 <b>Анкета</b> (4/6)\n\nВведи <b>уровень</b> (число):", reply_markup=k_cancel(), parse_mode="HTML")
    await state.set_state(Form.lvl)

@dp.message(Form.lvl)
async def step_lvl(m: Message, state: FSMContext):
    if not await guard_private(m):
        return
    t = (m.text or "").strip()
    if not t.isdigit():
        return await m.answer("⚠️ Уровень должен быть числом. Например: <b>78</b>", reply_markup=k_cancel(), parse_mode="HTML")

    lvl_int = int(t)
    if lvl_int < 1 or lvl_int > 99:
        return await m.answer("⚠️ Укажи уровень от 1 до 99.", reply_markup=k_cancel(), parse_mode="HTML")

    await state.update_data(lvl=lvl_int)
    await m.answer("📝 <b>Анкета</b> (5/6)\n\nУкажи <b>прайм</b> (например 19:00–23:00 МСК):", reply_markup=k_cancel(), parse_mode="HTML")
    await state.set_state(Form.prime)

@dp.message(Form.prime)
async def step_prime(m: Message, state: FSMContext):
    if not await guard_private(m):
        return
    if bad_text_general(m.text):
        return await m.answer("⚠️ Без ссылок и @. Укажи прайм текстом:", reply_markup=k_cancel(), parse_mode="HTML")

    await state.update_data(prime=m.text.strip())
    await m.answer("📝 <b>Анкета</b> (6/6)\n\nКоротко о себе (10–300 символов):", reply_markup=k_cancel(), parse_mode="HTML")
    await state.set_state(Form.note)

@dp.message(Form.note)
async def step_note(m: Message, state: FSMContext):
    if not await guard_private(m):
        return
    text = (m.text or "").strip()
    # тут тоже запрещаем ссылки/@
    if bad_text_general(text) or len(text) < 10 or len(text) > 300:
        return await m.answer("⚠️ Текст 10–300 символов, без ссылок/@. Повтори:", reply_markup=k_cancel(), parse_mode="HTML")

    await state.update_data(note=text)
    data = await state.get_data()
    await m.answer(fmt_preview(data), reply_markup=k_confirm(), parse_mode="HTML")
    await state.set_state(Form.confirm)

@dp.message(Form.confirm)
async def in_confirm_state(m: Message, state: FSMContext):
    if not await guard_private(m):
        return
    await m.answer("Выбери действие кнопками ниже:", reply_markup=k_confirm(), parse_mode="HTML")

# ===== Webhook =====
@dp.startup()
async def startup():
    if PUBLIC_URL:
        await bot.set_webhook(WEBHOOK_URL)

@app.post(WEBHOOK_PATH)
async def webhook(req: Request):
    await dp.feed_webhook_update(bot, await req.json())
    return Response(status_code=200)

@app.get("/")
async def ok():
    return {"ok": True}

@app.head("/")
async def ok_head():
    return Response(status_code=200)
