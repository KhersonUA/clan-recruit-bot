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

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

WEBHOOK_PATH = "/tg/webhook"
WEBHOOK_URL = f"{PUBLIC_URL}{WEBHOOK_PATH}"
COOLDOWN_HOURS = 12

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

# ================= Anti-spam =================
last_submit: dict[int, datetime] = {}

LINK_RE = re.compile(r"(https?://|t\.me/|telegram\.me/|www\.)", re.IGNORECASE)
AT_RE = re.compile(r"@", re.IGNORECASE)

def bad_text_general(s: str) -> bool:
    s = (s or "").strip()
    return (not s) or bool(LINK_RE.search(s)) or bool(AT_RE.search(s))

def normalize_contact(raw: str) -> str:
    s = (raw or "").strip()
    s = s.replace("https://", "").replace("http://", "")
    s = s.replace("t.me/", "").replace("telegram.me/", "")
    s = s.strip().lstrip("@").strip()
    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", s):
        return f"@{s}"
    return s[:64]

def guard_private(chat_type: str) -> bool:
    return chat_type == "private"

# ================= Keyboards =================
def k_start():
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Заполнить анкету", callback_data="start_form")
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

def k_yesno(prefix: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data=f"{prefix}:yes")
    kb.button(text="❌ Нет", callback_data=f"{prefix}:no")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(2, 1)
    return kb.as_markup()

def k_contact(username: str | None):
    kb = InlineKeyboardBuilder()
    if username:
        kb.button(
            text=f"✅ Использовать мой Telegram (@{username})",
            callback_data="contact:use_username",
        )
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()

def k_admin_contact(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Связаться с игроком", url=f"tg://user?id={user_id}")
    kb.adjust(1)
    return kb.as_markup()

# ================= Text =================
WELCOME = (
    "🛡 <b>SOBRANIEGOLD — официальный набор</b>\n"
    "Анкеты рассматриваются нашей командой.\n"
    "Заполнение анкеты — обязательное условие."
)

# ================= FSM =================
class Form(StatesGroup):
    nick = State()
    contact = State()
    prof = State()
    lvl = State()
    country = State()
    noble = State()
    prime = State()
    mic = State()
    ready = State()
    discipline = State()
    reason = State()
    confirm = State()

# ================= Preview =================
def fmt_preview(data: dict) -> str:
    return (
        "🧾 <b>Проверь анкету</b>\n\n"
        f"Ник: <b>{data['nick']}</b>\n"
        f"Контакт TG: <b>{data['contact']}</b>\n"
        f"Профа: <b>{data['prof']}</b>\n"
        f"Уровень: <b>{data['lvl']}</b>\n"
        f"Страна / регион: <b>{data['country']}</b>\n"
        f"Нобл: <b>{data['noble']}</b>\n"
        f"Прайм: <b>{data['prime']}</b>\n"
        f"Микрофон: <b>{data['mic']}</b>\n"
        f"Готовность к явке: <b>{data['ready']}</b>\n"
        f"Дисциплина: <b>{data['discipline']}</b>\n\n"
        f"<b>Почему SOBRANIEGOLD:</b>\n{data['reason']}\n\n"
        "Если всё верно — нажми «Отправить»."
    )

# ================= Start =================
@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return
    await state.clear()
    await m.answer(WELCOME, reply_markup=k_start(), parse_mode="HTML")

@dp.callback_query(F.data == "start_form")
async def start_form(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text("Укажи <b>ник в игре</b>:", reply_markup=k_cancel(), parse_mode="HTML")
    await state.set_state(Form.nick)
    await cq.answer()

@dp.callback_query(F.data == "cancel")
async def cancel(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(WELCOME, reply_markup=k_start(), parse_mode="HTML")
    await cq.answer()

@dp.callback_query(F.data == "restart")
async def restart(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text("Укажи <b>ник в игре</b>:", reply_markup=k_cancel(), parse_mode="HTML")
    await state.set_state(Form.nick)
    await cq.answer()

# ================= Steps =================
@dp.message(Form.nick)
async def step_nick(m: Message, state: FSMContext):
    if bad_text_general(m.text):
        return await m.answer("⚠️ Ник без ссылок и @.", reply_markup=k_cancel())
    await state.update_data(nick=m.text.strip())
    await m.answer(
        "Укажи <b>контакт в Telegram</b>:",
        reply_markup=k_contact(m.from_user.username),
        parse_mode="HTML",
    )
    await state.set_state(Form.contact)

@dp.callback_query(F.data == "contact:use_username")
async def use_username(cq: CallbackQuery, state: FSMContext):
    await state.update_data(contact=f"@{cq.from_user.username}")
    await cq.message.edit_text("Укажи <b>профу / саб</b>:", reply_markup=k_cancel(), parse_mode="HTML")
    await state.set_state(Form.prof)
    await cq.answer()

@dp.message(Form.contact)
async def step_contact(m: Message, state: FSMContext):
    await state.update_data(contact=normalize_contact(m.text))
    await m.answer("Укажи <b>профу / саб</b>:", reply_markup=k_cancel(), parse_mode="HTML")
    await state.set_state(Form.prof)

@dp.message(Form.prof)
async def step_prof(m: Message, state: FSMContext):
    await state.update_data(prof=m.text.strip())
    await m.answer("Укажи <b>уровень</b>:", reply_markup=k_cancel(), parse_mode="HTML")
    await state.set_state(Form.lvl)

@dp.message(Form.lvl)
async def step_lvl(m: Message, state: FSMContext):
    await state.update_data(lvl=m.text.strip())
    await m.answer(
        "Укажи <b>страну / регион проживания</b>:\n<i>Например: Польша, Украина</i>",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.country)

@dp.message(Form.country)
async def step_country(m: Message, state: FSMContext):
    await state.update_data(country=m.text.strip())
    await m.answer("Нобл есть?", reply_markup=k_yesno("noble"), parse_mode="HTML")
    await state.set_state(Form.noble)

@dp.callback_query(F.data.startswith("noble:"))
async def step_noble(cq: CallbackQuery, state: FSMContext):
    noble = "да" if cq.data.endswith("yes") else "нет"
    await state.update_data(noble=noble)
    await cq.message.edit_text("Укажи <b>прайм</b>:", reply_markup=k_cancel(), parse_mode="HTML")
    await state.set_state(Form.prime)
    await cq.answer()

@dp.message(Form.prime)
async def step_prime(m: Message, state: FSMContext):
    await state.update_data(prime=m.text.strip())
    await m.answer("Есть <b>микрофон</b>?", reply_markup=k_yesno("mic"), parse_mode="HTML")
    await state.set_state(Form.mic)

@dp.callback_query(F.data.startswith("mic:"))
async def step_mic(cq: CallbackQuery, state: FSMContext):
    mic = "да" if cq.data.endswith("yes") else "нет"
    await state.update_data(mic=mic)
    await cq.message.edit_text(
        "Готовность к <b>прайму / явке</b>:",
        reply_markup=k_yesno("ready"),
        parse_mode="HTML",
    )
    await state.set_state(Form.ready)
    await cq.answer()

@dp.callback_query(F.data.startswith("ready:"))
async def step_ready(cq: CallbackQuery, state: FSMContext):
    ready = "готов" if cq.data.endswith("yes") else "не всегда"
    await state.update_data(ready=ready)
    await cq.message.edit_text(
        "Готов соблюдать правила клана и решения <b>КЛа / ПЛа</b>?",
        reply_markup=k_yesno("disc"),
        parse_mode="HTML",
    )
    await state.set_state(Form.discipline)
    await cq.answer()

@dp.callback_query(F.data.startswith("disc:"))
async def step_disc(cq: CallbackQuery, state: FSMContext):
    discipline = "подтверждена" if cq.data.endswith("yes") else "НЕ подтверждена"
    await state.update_data(discipline=discipline)
    await cq.message.edit_text(
        "Почему ты хочешь вступить именно в <b>SOBRANIEGOLD</b>?\n<i>1–2 предложения</i>",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.reason)
    await cq.answer()

@dp.message(Form.reason)
async def step_reason(m: Message, state: FSMContext):
    await state.update_data(reason=m.text.strip())
    data = await state.get_data()
    await m.answer(fmt_preview(data), reply_markup=k_confirm(), parse_mode="HTML")
    await state.set_state(Form.confirm)

# ================= Confirm =================
@dp.callback_query(F.data == "confirm_send")
async def confirm(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user = cq.from_user

    now = datetime.now(timezone.utc)
    last_submit[user.id] = now

    msg = (
        "🧾 <b>Новая заявка — SOBRANIEGOLD</b>\n\n"
        f"👤 {user.full_name} (<code>{user.id}</code>)\n"
        f"📩 Контакт: <b>{data['contact']}</b>\n\n"
        f"Ник: <b>{data['nick']}</b>\n"
        f"Профа: <b>{data['prof']}</b>\n"
        f"Уровень: <b>{data['lvl']}</b>\n"
        f"Страна: <b>{data['country']}</b>\n"
        f"Нобл: <b>{data['noble']}</b>\n"
        f"Прайм: <b>{data['prime']}</b>\n"
        f"Микрофон: <b>{data['mic']}</b>\n"
        f"Готовность: <b>{data['ready']}</b>\n\n"
        f"⚠️ Дисциплина: <b>{data['discipline']}</b>\n\n"
        f"<b>Почему SOBRANIEGOLD:</b>\n{data['reason']}"
    )

    await bot.send_message(
        ADMIN_CHAT_ID,
        msg,
        parse_mode="HTML",
        reply_markup=k_admin_contact(user.id),
        disable_web_page_preview=True,
    )

    await state.clear()
    await cq.message.edit_text(
        "✅ <b>Анкета принята.</b>\n"
        "Рассмотрение занимает до <b>24 часов</b>.\n"
        "Ответ поступит в Telegram при положительном решении.",
        reply_markup=k_start(),
        parse_mode="HTML",
    )
    await cq.answer("Отправлено")

# ================= Webhook =================
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
