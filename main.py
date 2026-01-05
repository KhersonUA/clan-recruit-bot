import os
import re
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from fastapi import FastAPI, Request
from fastapi.responses import Response

# ===== ENV =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

WEBHOOK_PATH = "/tg/webhook"
COOLDOWN_HOURS = 12
WEBHOOK_URL = f"{PUBLIC_URL}{WEBHOOK_PATH}"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not ADMIN_CHAT_ID:
    raise RuntimeError("ADMIN_CHAT_ID is not set")

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

# ===== Anti-spam / Validation =====
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
def k_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Заполнить анкету", callback_data="start_form")
    kb.button(text="ℹ️ Инфо/Требования", callback_data="info")
    kb.adjust(1)
    return kb.as_markup()

def k_cancel_only():
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="cancel")
    return kb.as_markup()

def k_confirm():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Отправить", callback_data="confirm_send")
    kb.button(text="🔁 Заполнить заново", callback_data="restart")
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

def k_mic():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎙 Да", callback_data="mic:yes")
    kb.button(text="❌ Нет", callback_data="mic:no")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(2, 1)
    return kb.as_markup()

def k_goal():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 КП", callback_data="goal:kp")
    kb.button(text="⚔️ Осады", callback_data="goal:siege")
    kb.button(text="👥 Массовки", callback_data="goal:mass")
    kb.button(text="💰 Фарм", callback_data="goal:farm")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(2, 2, 1)
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
        kb.button(text=f"✅ Использовать мой Telegram (@{username})", callback_data="contact:use_username")
    kb.button(text="❌ Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()

def k_admin_contact(user_id: int):
    kb = InlineKeyboardBuilder()
    # Открывает чат в Telegram-клиентах (без веб-ссылок, обычно без превью)
    kb.button(text="✉️ Связаться с игроком", url=f"tg://user?id={user_id}")
    kb.adjust(1)
    return kb.as_markup()

# ===== Texts =====
WELCOME = (
    "👋 <b>SOBRANIEGOLD — набор в клан</b>\n\n"
    "Нажми <b>«Заполнить анкету»</b> и ответь на вопросы.\n"
    "Заявка уйдёт офицерам в отдельный чат.\n\n"
    "⚠️ В анкете <b>без ссылок</b> и <b>@</b> (кроме поля контакта)."
)

INFO_TEXT = (
    "ℹ️ <b>Инфо</b>\n\n"
    "Заполни анкету — офицеры рассмотрят заявку и при необходимости свяжутся.\n"
    "Если нет TG username — укажи способ связи.\n\n"
    "Нажми <b>«Заполнить анкету»</b>, чтобы начать."
)

# ===== FSM =====
class Form(StatesGroup):
    nick = State()       # 1/10
    contact = State()    # 2/10
    prof = State()       # 3/10
    lvl = State()        # 4/10
    noble = State()      # 5/10
    prime = State()      # 6/10
    mic = State()        # 7/10
    goal = State()       # 8/10
    ready = State()      # 9/10
    source = State()     # 10/10
    confirm = State()

def fmt_preview(data: dict) -> str:
    return (
        "🧾 <b>Проверь заявку</b>\n\n"
        f"1) Ник: <b>{data.get('nick','-')}</b>\n"
        f"2) Контакт: <b>{data.get('contact','-')}</b>\n"
        f"3) Профа/Саб: <b>{data.get('prof','-')}</b>\n"
        f"4) Уровень: <b>{data.get('lvl','-')}</b>\n"
        f"5) Нобл: <b>{data.get('noble','-')}</b>\n"
        f"6) Прайм: <b>{data.get('prime','-')}</b>\n"
        f"7) Микрофон/TS: <b>{data.get('mic','-')}</b>\n"
        f"8) Что ищет: <b>{data.get('goal','-')}</b>\n"
        f"9) Готовность к явке: <b>{data.get('ready','-')}</b>\n"
        f"10) Откуда узнал: <b>{data.get('source','-')}</b>\n\n"
        "Если всё верно — нажми <b>«Отправить»</b>."
    )

def admin_summary(user: dict, data: dict, now_local: str) -> str:
    # user: {"id":..., "full_name":..., "username":...}
    username = user.get("username")
    tg_line = f"{user.get('full_name','-')} (id: <code>{user.get('id','-')}</code>)"
    if username:
        tg_line += f" • <b>@{username}</b>"

    lines = [
        "🧾 <b>Новая заявка в клан</b>",
        "",
        f"👤 TG: {tg_line}",
        f"📩 Контакт: <b>{data.get('contact','-')}</b>",
        "",
        "📌 <b>Анкета</b>",
        f"1) Ник: <b>{data.get('nick','-')}</b>",
        f"2) Профа/Саб: <b>{data.get('prof','-')}</b>",
        f"3) Уровень: <b>{data.get('lvl','-')}</b>",
        f"4) Нобл: <b>{data.get('noble','-')}</b>",
        f"5) Прайм: <b>{data.get('prime','-')}</b>",
        f"6) Микрофон/TS: <b>{data.get('mic','-')}</b>",
        f"7) Что ищет: <b>{data.get('goal','-')}</b>",
        f"8) Готовность к явке: <b>{data.get('ready','-')}</b>",
        f"9) Откуда узнал: <b>{data.get('source','-')}</b>",
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
    await m.answer(WELCOME, reply_markup=k_menu(), parse_mode="HTML")

@dp.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return
    await state.clear()
    await m.answer("Ок, отменил. Если захочешь — заполни анкету заново.", reply_markup=k_menu(), parse_mode="HTML")

# ===== Callbacks: menu =====
@dp.callback_query(F.data == "info")
async def cb_info(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(INFO_TEXT, reply_markup=k_menu(), parse_mode="HTML")
    await cq.answer()

@dp.callback_query(F.data == "start_form")
async def cb_start_form(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(
        "📝 <b>Анкета</b> (1/10)\n\n"
        "Введи <b>ник в игре</b>:",
        reply_markup=k_cancel_only(),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await cq.answer()

@dp.callback_query(F.data == "cancel")
async def cb_cancel(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(
        "Ок, отменил. Если захочешь — заполни анкету заново.",
        reply_markup=k_menu(),
        parse_mode="HTML",
    )
    await cq.answer()

@dp.callback_query(F.data == "restart")
async def cb_restart(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text(
        "📝 <b>Анкета</b> (1/10)\n\n"
        "Введи <b>ник в игре</b>:",
        reply_markup=k_cancel_only(),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await cq.answer()

# ===== Step 1/10 =====
@dp.message(Form.nick)
async def step_nick(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return
    if bad_text_general(m.text):
        return await m.answer("⚠️ Ник без ссылок и @. Повтори:", reply_markup=k_cancel_only(), parse_mode="HTML")

    await state.update_data(nick=m.text.strip())

    username = m.from_user.username if m.from_user else None
    await m.answer(
        "📝 <b>Анкета</b> (2/10)\n\n"
        "Укажи <b>контакт в Telegram</b>.\n"
        "Если есть username — можешь нажать кнопку ниже.\n\n"
        "Если username нет — напиши <b>как с тобой связаться</b> (или напиши <b>нет</b>).",
        reply_markup=k_contact(username),
        parse_mode="HTML",
    )
    await state.set_state(Form.contact)

# ===== Step 2/10: button use username =====
@dp.callback_query(F.data == "contact:use_username")
async def cb_contact_use_username(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.contact.state:
        await cq.answer()
        return

    username = cq.from_user.username
    if not username:
        await cq.answer("У тебя нет username в Telegram.", show_alert=True)
        return

    contact = f"@{username}"
    await state.update_data(contact=contact)

    await cq.message.edit_text(
        "📝 <b>Анкета</b> (3/10)\n\n"
        "Укажи <b>профу / саб</b> (коротко):\n"
        "<i>Пример: Necromancer / Bishop</i>",
        reply_markup=k_cancel_only(),
        parse_mode="HTML",
    )
    await state.set_state(Form.prof)
    await cq.answer("Подставил твой Telegram")

# ===== Step 2/10: text =====
@dp.message(Form.contact)
async def step_contact(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return

    t = (m.text or "").strip()
    if not t:
        return await m.answer("⚠️ Введи контакт или напиши <b>нет</b>.", reply_markup=k_cancel_only(), parse_mode="HTML")

    if t.lower() in {"нет", "no", "none"}:
        contact = "нет"
    else:
        contact = normalize_contact(t)

    await state.update_data(contact=contact)
    await m.answer(
        "📝 <b>Анкета</b> (3/10)\n\n"
        "Укажи <b>профу / саб</b> (коротко):\n"
        "<i>Пример: Necromancer / Bishop</i>",
        reply_markup=k_cancel_only(),
        parse_mode="HTML",
    )
    await state.set_state(Form.prof)

# ===== Step 3/10 =====
@dp.message(Form.prof)
async def step_prof(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return
    if bad_text_general(m.text):
        return await m.answer("⚠️ Без ссылок и @. Повтори профу/саб:", reply_markup=k_cancel_only(), parse_mode="HTML")

    await state.update_data(prof=m.text.strip())
    await m.answer(
        "📝 <b>Анкета</b> (4/10)\n\n"
        "Укажи <b>уровень</b> (числом):",
        reply_markup=k_cancel_only(),
        parse_mode="HTML",
    )
    await state.set_state(Form.lvl)

# ===== Step 4/10 =====
@dp.message(Form.lvl)
async def step_lvl(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return

    t = (m.text or "").strip()
    if not t.isdigit():
        return await m.answer("⚠️ Уровень должен быть числом. Например: <b>78</b>", reply_markup=k_cancel_only(), parse_mode="HTML")

    lvl_int = int(t)
    if lvl_int < 1 or lvl_int > 99:
        return await m.answer("⚠️ Укажи уровень от 1 до 99.", reply_markup=k_cancel_only(), parse_mode="HTML")

    await state.update_data(lvl=lvl_int)
    await m.answer(
        "📝 <b>Анкета</b> (5/10)\n\n"
        "Нобл есть?",
        reply_markup=k_yesno("noble"),
        parse_mode="HTML",
    )
    await state.set_state(Form.noble)

# ===== Step 5/10 (buttons) =====
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
        "📝 <b>Анкета</b> (6/10)\n\n"
        "Укажи <b>прайм</b> (дни + время):\n"
        "<i>Пример: Пн–Пт 20:00–00:00, сб/вс больше</i>",
        reply_markup=k_cancel_only(),
        parse_mode="HTML",
    )
    await state.set_state(Form.prime)
    await cq.answer()

# ===== Step 6/10 =====
@dp.message(Form.prime)
async def step_prime(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return
    if bad_text_general(m.text):
        return await m.answer("⚠️ Без ссылок и @. Укажи прайм текстом:", reply_markup=k_cancel_only(), parse_mode="HTML")

    await state.update_data(prime=m.text.strip())
    await m.answer(
        "📝 <b>Анкета</b> (7/10)\n\n"
        "Есть <b>микрофон</b> и готов слушать колл (TS/Discord)?",
        reply_markup=k_mic(),
        parse_mode="HTML",
    )
    await state.set_state(Form.mic)

# ===== Step 7/10 (buttons) =====
@dp.callback_query(F.data.startswith("mic:"))
async def cb_mic_step(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.mic.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    mic = "да" if val == "yes" else "нет"

    await state.update_data(mic=mic)
    await cq.message.edit_text(
        "📝 <b>Анкета</b> (8/10)\n\n"
        "Что ищешь в клане?",
        reply_markup=k_goal(),
        parse_mode="HTML",
    )
    await state.set_state(Form.goal)
    await cq.answer()

# ===== Step 8/10 (buttons) =====
@dp.callback_query(F.data.startswith("goal:"))
async def cb_goal_step(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.goal.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    goal_map = {"kp": "КП", "siege": "осады", "mass": "массовки", "farm": "фарм"}
    goal = goal_map.get(val, "—")

    await state.update_data(goal=goal)
    await cq.message.edit_text(
        "📝 <b>Анкета</b> (9/10)\n\n"
        "Готовность к <b>прайму/явке</b>:",
        reply_markup=k_ready(),
        parse_mode="HTML",
    )
    await state.set_state(Form.ready)
    await cq.answer()

# ===== Step 9/10 (buttons) =====
@dp.callback_query(F.data.startswith("ready:"))
async def cb_ready_step(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.ready.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    ready_map = {"yes": "готов стабильно", "sometimes": "не всегда", "no": "не готов"}
    ready = ready_map.get(val, "—")

    await state.update_data(ready=ready)
    await cq.message.edit_text(
        "📝 <b>Анкета</b> (10/10)\n\n"
        "Кто пригласил / откуда узнал?\n"
        "Если не хочешь отвечать — напиши <b>пропуск</b>.",
        reply_markup=k_cancel_only(),
        parse_mode="HTML",
    )
    await state.set_state(Form.source)
    await cq.answer()

# ===== Step 10/10 =====
@dp.message(Form.source)
async def step_source(m: Message, state: FSMContext):
    if not guard_private(m.chat.type):
        return

    t = (m.text or "").strip()
    if not t:
        return await m.answer("⚠️ Напиши источник или <b>пропуск</b>.", reply_markup=k_cancel_only(), parse_mode="HTML")

    if t.lower() in {"пропуск", "skip"}:
        source = "—"
    else:
        if bad_text_general(t):
            return await m.answer("⚠️ Без ссылок и @. Напиши текстом или <b>пропуск</b>.", reply_markup=k_cancel_only(), parse_mode="HTML")
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

    await cq.message.edit_text(
        "✅ <b>Заявка отправлена</b>\n\n"
        "Офицеры рассмотрят и при необходимости свяжутся.",
        reply_markup=k_menu(),
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
