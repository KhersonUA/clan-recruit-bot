import os
import re
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from fastapi import FastAPI, Request
from fastapi.responses import Response

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WEBHOOK_PATH = "/tg/webhook"
COOLDOWN_HOURS = 12

WEBHOOK_URL = f"{PUBLIC_URL}{WEBHOOK_PATH}"

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

last_submit = {}
LINK_RE = re.compile(r"(https?://|t\.me/|@|www\.)", re.IGNORECASE)

def bad_text(s: str) -> bool:
    s = (s or "").strip()
    return (not s) or bool(LINK_RE.search(s))

class Form(StatesGroup):
    nick = State()
    cls = State()
    lvl = State()
    prime = State()
    note = State()

@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    if m.chat.type != "private":
        return await m.answer("Пиши мне в личку для подачи заявки.")
    await state.clear()
    await m.answer("Заявка в клан.\n\n1/5 Ник в игре?")
    await state.set_state(Form.nick)

@dp.message(Form.nick)
async def nick(m: Message, state: FSMContext):
    if bad_text(m.text):
        return await m.answer("Без ссылок и @. Повтори ник.")
    await state.update_data(nick=m.text.strip())
    await m.answer("2/5 Класс/профа?")
    await state.set_state(Form.cls)

@dp.message(Form.cls)
async def cls(m: Message, state: FSMContext):
    if bad_text(m.text):
        return await m.answer("Без ссылок и @. Повтори.")
    await state.update_data(cls=m.text.strip())
    await m.answer("3/5 Уровень (числом)?")
    await state.set_state(Form.lvl)

@dp.message(Form.lvl)
async def lvl(m: Message, state: FSMContext):
    t = (m.text or "").strip()
    if not t.isdigit():
        return await m.answer("Уровень должен быть числом. Например: 78")
    lvl_int = int(t)
    if lvl_int < 1 or lvl_int > 99:
        return await m.answer("Укажи уровень 1–99.")
    await state.update_data(lvl=lvl_int)
    await m.answer("4/5 Прайм-тайм/онлайн (например 19:00–23:00 МСК)?")
    await state.set_state(Form.prime)

@dp.message(Form.prime)
async def prime(m: Message, state: FSMContext):
    if bad_text(m.text):
        return await m.answer("Без ссылок и @. Укажи прайм текстом.")
    await state.update_data(prime=m.text.strip())
    await m.answer("5/5 Коротко о себе (10–300 символов, без ссылок/@).")
    await state.set_state(Form.note)

@dp.message(Form.note)
async def note(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    if bad_text(text) or len(text) < 10 or len(text) > 300:
        return await m.answer("Текст 10–300 символов, без ссылок/@. Повтори.")
    now = datetime.now(timezone.utc)

    prev = last_submit.get(m.from_user.id)
    if prev and now - prev < timedelta(hours=COOLDOWN_HOURS):
        return await m.answer(f"Повторная заявка доступна через {COOLDOWN_HOURS} часов.")

    last_submit[m.from_user.id] = now

    data = await state.get_data()
    msg = (
        "🧾 <b>Новая заявка</b>\n"
        f"👤 TG: {m.from_user.full_name} (id: <code>{m.from_user.id}</code>)\n"
        f"🔹 Ник: <b>{data['nick']}</b>\n"
        f"🔹 Класс: <b>{data['cls']}</b>\n"
        f"🔹 Уровень: <b>{data['lvl']}</b>\n"
        f"🔹 Прайм: <b>{data['prime']}</b>\n"
        f"📝 Коммент: {text}"
    )

    await bot.send_message(ADMIN_CHAT_ID, msg, parse_mode="HTML")
    await state.clear()
    await m.answer("Заявка отправлена офицерам. Ожидай ответа.")

@dp.startup()
async def startup():
    # PUBLIC_URL добавим на хостинге после деплоя
    if PUBLIC_URL:
        await bot.set_webhook(WEBHOOK_URL)

@app.post(WEBHOOK_PATH)
async def webhook(req: Request):
    await dp.feed_webhook_update(bot, await req.json())
    return Response(status_code=200)

@app.get("/")
async def ok():
    return {"ok": True}
