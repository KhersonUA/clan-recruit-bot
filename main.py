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
        "🧾 <b>Проверь анкету</b>\n"
        "<i>Если нужно — нажми «Заполнить заново»</i>\n\n"
        f"🧑 Ник: <b>{data['nick']}</b>\n"
        f"📩 Контакт TG: <b>{data['contact']}</b>\n"
        f"🧙 Профа/Саб: <b>{data['prof']}</b>\n"
        f"📈 Уровень: <b>{data['lvl']}</b>\n"
        f"🌍 Страна/регион: <b>{data['country']}</b>\n"
        f"👑 Нобл: <b>{data['noble']}</b>\n"
        f"⏰ Прайм: <b>{data['prime']}</b>\n"
        f"🎙 Микрофон: <b>{data['mic']}</b>\n"
        f"🛡 Явка/прайм: <b>{data['ready']}</b>\n"
        f"📌 Дисциплина: <b>{data['discipline']}</b>\n\n"
        f"💬 <b>Почему SOBRANIEGOLD:</b>\n{data['reason']}\n\n"
        "Нажми <b>«Отправить»</b>, чтобы отправить анкету офицерам."
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
    await cq.message.edit_text(
        "📝 <b>Анкета</b>\n\n"
        "Укажи <b>ник в игре</b>:",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
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
    await cq.message.edit_text(
        "📝 <b>Анкета</b>\n\n"
        "Укажи <b>ник в игре</b>:",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await cq.answer()


# ================= Steps =================
@dp.message(Form.nick)
async def step_nick(m: Message, state: FSMContext):
    if bad_text_general(m.text):
        return await m.answer("⚠️ Ник без ссылок и @.", reply_markup=k_cancel())
    await state.update_data(nick=m.text.strip())
    await m.answer(
        "📩 Укажи <b>контакт в Telegram</b>:",
        reply_markup=k_contact(m.from_user.username),
        parse_mode="HTML",
    )
    await state.set_state(Form.contact)


@dp.callback_query(F.data == "contact:use_username")
async def use_username(cq: CallbackQuery, state: FSMContext):
    await state.update_data(contact=f"@{cq.from_user.username}")
    await cq.message.edit_text(
        "🧙 Укажи <b>профу / саб</b>:",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.prof)
    await cq.answer("Ок")


@dp.message(Form.contact)
async def step_contact(m: Message, state: FSMContext):
    await state.update_data(contact=normalize_contact(m.text))
    await m.answer("🧙 Укажи <b>профу / саб</b>:", reply_markup=k_cancel(), parse_mode="HTML")
    await state.set_state(Form.prof)


@dp.message(Form.prof)
async def step_prof(m: Message, state: FSMContext):
    if bad_text_general(m.text):
        return await m.answer("⚠️ Без ссылок и @.", reply_markup=k_cancel())
    await state.update_data(prof=m.text.strip())
    await m.answer("📈 Укажи <b>уровень</b>:", reply_markup=k_cancel(), parse_mode="HTML")
    await state.set_state(Form.lvl)


@dp.message(Form.lvl)
async def step_lvl(m: Message, state: FSMContext):
    t = (m.text or "").strip()
    if not t.isdigit():
        return await m.answer("⚠️ Уровень должен быть числом.", reply_markup=k_cancel())
    lvl_int = int(t)
    if lvl_int < 1 or lvl_int > 99:
        return await m.answer("⚠️ Укажи уровень от 1 до 99.", reply_markup=k_cancel())
    await state.update_data(lvl=lvl_int)
    await m.answer(
        "🌍 Укажи <b>страну / регион проживания</b>:\n"
        "<i>Например: Польша, Украина, Германия</i>",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.country)


@dp.message(Form.country)
async def step_country(m: Message, state: FSMContext):
    if bad_text_general(m.text):
        return await m.answer("⚠️ Без ссылок и @.", reply_markup=k_cancel())
    await state.update_data(country=m.text.strip()[:64])
    await m.answer("👑 Нобл есть?", reply_markup=k_yesno("noble"), parse_mode="HTML")
    await state.set_state(Form.noble)


@dp.callback_query(F.data.startswith("noble:"))
async def step_noble(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.noble.state:
        await cq.answer()
        return
    noble = "да" if cq.data.endswith("yes") else "нет"
    await state.update_data(noble=noble)
    await cq.message.edit_text(
        "⏰ Укажи <b>прайм</b> (дни + время):\n"
        "<i>Пример: Пн–Пт 20:00–00:00</i>",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.prime)
    await cq.answer()


@dp.message(Form.prime)
async def step_prime(m: Message, state: FSMContext):
    if bad_text_general(m.text):
        return await m.answer("⚠️ Без ссылок и @.", reply_markup=k_cancel())
    await state.update_data(prime=m.text.strip()[:120])
    await m.answer("🎙 Есть <b>микрофон</b>?", reply_markup=k_yesno("mic"), parse_mode="HTML")
    await state.set_state(Form.mic)


@dp.callback_query(F.data.startswith("mic:"))
async def step_mic(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.mic.state:
        await cq.answer()
        return
    mic = "да" if cq.data.endswith("yes") else "нет"
    await state.update_data(mic=mic)
    await cq.message.edit_text(
        "🛡 Готовность к <b>прайму / явке</b>:",
        reply_markup=k_yesno("ready"),
        parse_mode="HTML",
    )
    await state.set_state(Form.ready)
    await cq.answer()


@dp.callback_query(F.data.startswith("ready:"))
async def step_ready(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.ready.state:
        await cq.answer()
        return
    ready = "готов" if cq.data.endswith("yes") else "не всегда"
    await state.update_data(ready=ready)

    await cq.message.edit_text(
        "📌 Готов соблюдать правила клана и решения <b>КЛа / ПЛа</b>?",
        reply_markup=k_yesno("disc"),
        parse_mode="HTML",
    )
    await state.set_state(Form.discipline)
    await cq.answer()


@dp.callback_query(F.data.startswith("disc:"))
async def step_disc(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.discipline.state:
        await cq.answer()
        return
    discipline = "подтверждена" if cq.data.endswith("yes") else "НЕ подтверждена"
    await state.update_data(discipline=discipline)
    await cq.message.edit_text(
        "💬 Почему ты хочешь вступить именно в <b>SOBRANIEGOLD</b>?\n"
        "<i>1–2 предложения</i>",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.reason)
    await cq.answer()


@dp.message(Form.reason)
async def step_reason(m: Message, state: FSMContext):
    t = (m.text or "").strip()
    if bad_text_general(t) or len(t) < 3:
        return await m.answer("⚠️ Коротко, без ссылок и @.", reply_markup=k_cancel())
    await state.update_data(reason=t[:300])
    data = await state.get_data()
    await m.answer(fmt_preview(data), reply_markup=k_confirm(), parse_mode="HTML")
    await state.set_state(Form.confirm)


# ================= Confirm =================
@dp.callback_query(F.data == "confirm_send")
async def confirm(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.confirm.state:
        await cq.answer()
        return

    data = await state.get_data()
    user = cq.from_user

    # cooldown
    now = datetime.now(timezone.utc)
    prev = last_submit.get(user.id)
    if prev and now - prev < timedelta(hours=COOLDOWN_HOURS):
        await cq.answer(f"Повторная заявка доступна через {COOLDOWN_HOURS} часов.", show_alert=True)
        return

    # discipline icon fix
    if str(data.get("discipline", "")).lower().startswith("не"):
        discipline_line = "⚠️ <b>Дисциплина: НЕ подтверждена</b>"
    else:
        discipline_line = "✅ <b>Дисциплина: подтверждена</b>"

    ts = now.astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M")

    msg = (
        "🧾 <b>Новая заявка — SOBRANIEGOLD</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>{user.full_name}</b>  |  <code>{user.id}</code>\n"
        f"📩 Контакт: <b>{data['contact']}</b>\n\n"
        "📌 <b>Данные</b>\n"
        f"🧑 Ник: <b>{data['nick']}</b>\n"
        f"🧙 Профа/Саб: <b>{data['prof']}</b>\n"
        f"📈 Уровень: <b>{data['lvl']}</b>\n"
        f"🌍 Страна/регион: <b>{data['country']}</b>\n"
        f"👑 Нобл: <b>{data['noble']}</b>\n"
        f"⏰ Прайм: <b>{data['prime']}</b>\n"
        f"🎙 Микрофон: <b>{data['mic']}</b>\n"
        f"🛡 Явка/прайм: <b>{data['ready']}</b>\n\n"
        f"{discipline_line}\n\n"
        "💬 <b>Почему SOBRANIEGOLD:</b>\n"
        f"{data['reason']}\n\n"
        f"⏱ <i>{ts} (UTC+3)</i>"
    )

    await bot.send_message(
        ADMIN_CHAT_ID,
        msg,
        parse_mode="HTML",
        reply_markup=k_admin_contact(user.id),
        disable_web_page_preview=True,
    )

    last_submit[user.id] = now
    await state.clear()

    await cq.message.edit_text(
        "✅ <b>Анкета принята.</b>\n\n"
        "Рассмотрение занимает до <b>24 часов</b>.\n"
        "Ответ поступит в Telegram при положительном решении.",
        reply_markup=k_start(),
        parse_mode="HTML",
    )
    await cq.answer("Отправлено")


@dp.message(Form.confirm)
async def in_confirm_state(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return
    await m.answer("Выбери действие кнопками ниже:", reply_markup=k_confirm(), parse_mode="HTML")


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
