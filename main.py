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

# ===== Validation / Anti-spam =====
last_submit: dict[int, datetime] = {}

# Запрещаем ссылки/@ почти везде. Для контакта TG — разрешим.
LINK_RE = re.compile(r"(https?://|t\.me/|telegram\.me/|www\.)", re.IGNORECASE)
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
    Возвращаем:
      @username (если похоже на username),
      иначе исходное (обрезанное).
    """
    s = (raw or "").strip()
    s = s.replace("https://", "").replace("http://", "")
    s = s.replace("t.me/", "").replace("telegram.me/", "")
    s = s.strip().lstrip("@").strip()

    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", s):
        return f"@{s}"
    return (raw or "").strip()[:64]


def guard_private(chat_type: str) -> bool:
    return chat_type == "private"


# ===== Keyboards =====
def k_start():
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Заполнить анкету", callback_data="start_form")
    kb.button(text="ℹ️ Инфо", callback_data="info")
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
    kb.button(text="⏳ В процессе", callback_data=f"{prefix}:progress")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(2, 2)
    return kb.as_markup()


def k_yesno_strict(prefix: str):
    # строго Да/Нет (для дисциплины)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data=f"{prefix}:yes")
    kb.button(text="❌ Нет", callback_data=f"{prefix}:no")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(2, 1)
    return kb.as_markup()


def k_mic():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎙 Да", callback_data="mic:yes")
    kb.button(text="❌ Нет", callback_data="mic:no")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(2, 1)
    return kb.as_markup()


def k_ready():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готов стабильно", callback_data="ready:yes")
    kb.button(text="⚠️ Не всегда", callback_data="ready:sometimes")
    kb.button(text="❌ Не готов", callback_data="ready:no")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(1, 1, 1, 1)
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


# ===== Texts (обновлено под “официальный набор”) =====
WELCOME = (
    "🛡 <b>SOBRANIEGOLD — официальный набор</b>\n"
    "Анкеты рассматриваются нашей командой.\n"
    "Заполнение анкеты — обязательное условие."
)

INFO_TEXT = (
    "ℹ️ <b>Инфо</b>\n\n"
    "Анкеты рассматриваются нашей командой.\n"
    "При положительном решении с вами свяжутся в Telegram."
)


# ===== FSM =====
class Form(StatesGroup):
    nick = State()         # 1
    contact = State()      # 2
    prof = State()         # 3
    lvl = State()          # 4
    noble = State()        # 5
    prime = State()        # 6
    mic = State()          # 7
    ready = State()        # 8
    discipline = State()   # 9
    reason = State()       # 10
    source = State()       # 11 (необязательное)
    confirm = State()


def fmt_preview(data: dict) -> str:
    return (
        "🧾 <b>Проверь анкету</b>\n\n"
        f"1) Ник: <b>{data.get('nick','-')}</b>\n"
        f"2) Контакт: <b>{data.get('contact','-')}</b>\n"
        f"3) Профа/Саб: <b>{data.get('prof','-')}</b>\n"
        f"4) Уровень: <b>{data.get('lvl','-')}</b>\n"
        f"5) Нобл: <b>{data.get('noble','-')}</b>\n"
        f"6) Прайм: <b>{data.get('prime','-')}</b>\n"
        f"7) Микрофон/TS: <b>{data.get('mic','-')}</b>\n"
        f"8) Готовность к явке: <b>{data.get('ready','-')}</b>\n"
        f"9) Дисциплина: <b>{data.get('discipline','-')}</b>\n\n"
        f"10) <b>Почему SOBRANIEGOLD:</b>\n{data.get('reason','-')}\n\n"
        f"11) Откуда узнал: <b>{data.get('source','-')}</b>\n\n"
        "Если всё верно — нажми <b>«Отправить»</b>."
    )


def admin_summary(user: dict, data: dict, now_local: str) -> str:
    username = user.get("username")
    tg_line = f"{user.get('full_name','-')} (id: <code>{user.get('id','-')}</code>)"
    if username:
        tg_line += f" • <b>@{username}</b>"

    discipline = data.get("discipline", "—")
    discipline_mark = (
        "⚠️ <b>ДИСЦИПЛИНА НЕ ПОДТВЕРЖДЕНА</b>"
        if discipline.lower().startswith("не")
        else "✅ Дисциплина подтверждена"
    )

    lines = [
        "🧾 <b>Новая заявка — SOBRANIEGOLD</b>",
        "",
        f"👤 TG: {tg_line}",
        f"📩 Контакт: <b>{data.get('contact','-')}</b>",
        "",
        "📌 <b>Анкета</b>",
        f"Ник: <b>{data.get('nick','-')}</b>",
        f"Профа/Саб: <b>{data.get('prof','-')}</b>",
        f"Уровень: <b>{data.get('lvl','-')}</b>",
        f"Нобл: <b>{data.get('noble','-')}</b>",
        f"Прайм: <b>{data.get('prime','-')}</b>",
        f"Микрофон/TS: <b>{data.get('mic','-')}</b>",
        f"Готовность к явке: <b>{data.get('ready','-')}</b>",
        "",
        discipline_mark,
        "",
        "<b>Почему SOBRANIEGOLD:</b>",
        f"{data.get('reason','-')}",
        "",
        f"Откуда узнал: <b>{data.get('source','-')}</b>",
        "",
        f"⏱ <i>{now_local} (UTC+3)</i>",
    ]
    return "\n".join(lines)


# ===== Commands =====
@dp.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return await m.answer("Подача заявки доступна только в личных сообщениях боту.")
    await state.clear()
    await m.answer(WELCOME, reply_markup=k_start(), parse_mode="HTML")


# ===== Callbacks: menu =====
@dp.callback_query(F.data == "info")
async def cb_info(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(INFO_TEXT, reply_markup=k_start(), parse_mode="HTML")
    await cq.answer()


@dp.callback_query(F.data == "start_form")
async def cb_start_form(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(
        "📝 <b>Анкета</b> (1/11)\n\n"
        "Укажи <b>ник в игре</b>:",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await cq.answer()


@dp.callback_query(F.data == "cancel")
async def cb_cancel(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(WELCOME, reply_markup=k_start(), parse_mode="HTML")
    await cq.answer()


@dp.callback_query(F.data == "restart")
async def cb_restart(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(
        "📝 <b>Анкета</b> (1/11)\n\n"
        "Укажи <b>ник в игре</b>:",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await cq.answer()


# ===== Step 1/11 =====
@dp.message(Form.nick)
async def step_nick(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return
    if bad_text_general(m.text):
        return await m.answer("⚠️ Ник без ссылок и @. Повтори:", reply_markup=k_cancel(), parse_mode="HTML")

    await state.update_data(nick=m.text.strip())

    username = m.from_user.username if m.from_user else None
    await m.answer(
        "📝 <b>Анкета</b> (2/11)\n\n"
        "Укажи <b>контакт в Telegram</b>.\n"
        "Если есть username — нажми кнопку ниже.\n"
        "Если username нет — напиши способ связи (или <b>нет</b>).",
        reply_markup=k_contact(username),
        parse_mode="HTML",
    )
    await state.set_state(Form.contact)


# ===== Step 2/11: use username button =====
@dp.callback_query(F.data == "contact:use_username")
async def cb_contact_use_username(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.contact.state:
        await cq.answer()
        return

    username = cq.from_user.username
    if not username:
        await cq.answer("У тебя не указан username в Telegram.", show_alert=True)
        return

    await state.update_data(contact=f"@{username}")

    await cq.message.edit_text(
        "📝 <b>Анкета</b> (3/11)\n\n"
        "Укажи <b>профу / саб</b> (коротко):\n"
        "<i>Пример: Necromancer / Bishop</i>",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.prof)
    await cq.answer("Контакт подставлен")


# ===== Step 2/11: text =====
@dp.message(Form.contact)
async def step_contact(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return

    t = (m.text or "").strip()
    if not t:
        return await m.answer("⚠️ Укажи контакт или напиши <b>нет</b>.", reply_markup=k_cancel(), parse_mode="HTML")

    if t.lower() in {"нет", "no", "none"}:
        contact = "нет"
    else:
        contact = normalize_contact(t)

    await state.update_data(contact=contact)

    await m.answer(
        "📝 <b>Анкета</b> (3/11)\n\n"
        "Укажи <b>профу / саб</b> (коротко):\n"
        "<i>Пример: Necromancer / Bishop</i>",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.prof)


# ===== Step 3/11 =====
@dp.message(Form.prof)
async def step_prof(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return
    if bad_text_general(m.text):
        return await m.answer("⚠️ Без ссылок и @. Повтори:", reply_markup=k_cancel(), parse_mode="HTML")

    await state.update_data(prof=m.text.strip())

    await m.answer(
        "📝 <b>Анкета</b> (4/11)\n\n"
        "Укажи <b>уровень</b> (числом):",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.lvl)


# ===== Step 4/11 =====
@dp.message(Form.lvl)
async def step_lvl(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return

    t = (m.text or "").strip()
    if not t.isdigit():
        return await m.answer("⚠️ Уровень должен быть числом.", reply_markup=k_cancel(), parse_mode="HTML")

    lvl_int = int(t)
    if lvl_int < 1 or lvl_int > 99:
        return await m.answer("⚠️ Укажи уровень от 1 до 99.", reply_markup=k_cancel(), parse_mode="HTML")

    await state.update_data(lvl=lvl_int)

    await m.answer(
        "📝 <b>Анкета</b> (5/11)\n\n"
        "Нобл есть?",
        reply_markup=k_yesno("noble"),
        parse_mode="HTML",
    )
    await state.set_state(Form.noble)


# ===== Step 5/11 (buttons) =====
@dp.callback_query(F.data.startswith("noble:"))
async def cb_noble(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.noble.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    noble_map = {"yes": "да", "no": "нет", "progress": "в процессе"}
    noble = noble_map.get(val, "—")

    await state.update_data(noble=noble)

    await cq.message.edit_text(
        "📝 <b>Анкета</b> (6/11)\n\n"
        "Укажи <b>прайм</b> (дни + время):\n"
        "<i>Пример: Пн–Пт 20:00–00:00</i>",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.prime)
    await cq.answer()


# ===== Step 6/11 =====
@dp.message(Form.prime)
async def step_prime(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return
    if bad_text_general(m.text):
        return await m.answer("⚠️ Без ссылок и @. Укажи прайм текстом.", reply_markup=k_cancel(), parse_mode="HTML")

    await state.update_data(prime=m.text.strip())

    await m.answer(
        "📝 <b>Анкета</b> (7/11)\n\n"
        "Есть <b>микрофон</b> и готов слушать колл (TS/Discord)?",
        reply_markup=k_mic(),
        parse_mode="HTML",
    )
    await state.set_state(Form.mic)


# ===== Step 7/11 (buttons) =====
@dp.callback_query(F.data.startswith("mic:"))
async def cb_mic(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.mic.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    mic = "да" if val == "yes" else "нет"

    await state.update_data(mic=mic)

    await cq.message.edit_text(
        "📝 <b>Анкета</b> (8/11)\n\n"
        "Готовность к <b>прайму/явке</b>:",
        reply_markup=k_ready(),
        parse_mode="HTML",
    )
    await state.set_state(Form.ready)
    await cq.answer()


# ===== Step 8/11 (buttons) =====
@dp.callback_query(F.data.startswith("ready:"))
async def cb_ready(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.ready.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    ready_map = {"yes": "готов стабильно", "sometimes": "не всегда", "no": "не готов"}
    ready = ready_map.get(val, "—")

    await state.update_data(ready=ready)

    await cq.message.edit_text(
        "📝 <b>Анкета</b> (9/11)\n\n"
        "Готов соблюдать правила клана и решения <b>КЛа, ПЛа</b>?",
        reply_markup=k_yesno_strict("disc"),
        parse_mode="HTML",
    )
    await state.set_state(Form.discipline)
    await cq.answer()


# ===== Step 9/11 (buttons) Discipline =====
@dp.callback_query(F.data.startswith("disc:"))
async def cb_discipline(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.discipline.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    discipline = "подтверждена" if val == "yes" else "НЕ подтверждена"

    await state.update_data(discipline=discipline)

    await cq.message.edit_text(
        "📝 <b>Анкета</b> (10/11)\n\n"
        "Почему ты хочешь вступить именно в <b>SOBRANIEGOLD</b>?\n"
        "<i>1–2 предложения</i>",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.reason)
    await cq.answer()


# ===== Step 10/11 (text) Reason =====
@dp.message(Form.reason)
async def step_reason(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return

    t = (m.text or "").strip()
    if bad_text_general(t) or len(t) < 3:
        return await m.answer("⚠️ Коротко, без ссылок и @. Повтори:", reply_markup=k_cancel(), parse_mode="HTML")

    await state.update_data(reason=t[:300])

    await m.answer(
        "📝 <b>Анкета</b> (11/11)\n\n"
        "Откуда узнал о наборе?\n"
        "<i>Если не хочешь указывать — напиши</i> <b>нет</b>.",
        reply_markup=k_cancel(),
        parse_mode="HTML",
    )
    await state.set_state(Form.source)


# ===== Step 11/11 (text) Source =====
@dp.message(Form.source)
async def step_source(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return

    t = (m.text or "").strip()
    if not t:
        return await m.answer("⚠️ Укажи источник или напиши <b>нет</b>.", reply_markup=k_cancel(), parse_mode="HTML")

    if t.lower() in {"нет", "no", "none"}:
        source = "—"
    else:
        if bad_text_general(t):
            return await m.answer("⚠️ Без ссылок и @. Укажи текстом или <b>нет</b>.", reply_markup=k_cancel(), parse_mode="HTML")
        source = t[:80]

    await state.update_data(source=source)

    data = await state.get_data()
    await m.answer(fmt_preview(data), reply_markup=k_confirm(), parse_mode="HTML")
    await state.set_state(Form.confirm)


# ===== Confirm send =====
@dp.callback_query(F.data == "confirm_send")
async def cb_confirm_send(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.confirm.state:
        await cq.answer()
        return

    data = await state.get_data()

    # cooldown
    now = datetime.now(timezone.utc)
    prev = last_submit.get(cq.from_user.id)
    if prev and now - prev < timedelta(hours=COOLDOWN_HOURS):
        await cq.answer(f"Повторная заявка доступна через {COOLDOWN_HOURS} часов.", show_alert=True)
        return

    user = cq.from_user
    user_info = {
        "id": user.id,
        "full_name": user.full_name,
        "username": user.username or None,
    }

    now_local = now.astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M")

    msg = admin_summary(user_info, data, now_local)

    await bot.send_message(
        ADMIN_CHAT_ID,
        msg,
        parse_mode="HTML",
        reply_markup=k_admin_contact(user.id),
        disable_web_page_preview=True,
    )

    last_submit[user.id] = now
    await state.clear()

    # Финальный экран (как ты утвердил)
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
