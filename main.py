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

# ================= i18n =================
T = {
    "ru": {
        "LANG_PICK": "🌍 <b>Выберите язык</b>",
        "WELCOME": (
            "🛡 <b>SOBRANIEGOLD — официальный набор</b>\n"
            "Анкеты рассматриваются офицерским составом.\n"
            "Заполнение анкеты — обязательное условие."
        ),
        "BTN_START": "⚔️ Заполнить анкету",
        "BTN_CANCEL": "❌ Отмена",
        "BTN_RESTART": "🔄 Заполнить заново",
        "BTN_SEND": "✅ Отправить",
        "BTN_USE_TG": "✅ Использовать мой Telegram",
        "ASK_NICK": "⚔️ Укажи <b>ник в игре</b>:",
        "ASK_CONTACT": "📩 Укажи <b>контакт в Telegram</b>:",
        "ASK_PROF": "🔮 Укажи <b>класс / саб</b>:",
        "ASK_LEVEL": "📈 Укажи <b>уровень</b> (1–99):",
        "ASK_COUNTRY": "🌍 Укажи <b>страну / регион проживания</b>:",
        "ASK_NOBLE": "🕊 Есть <b>Noblesse</b>?",
        "ASK_PRIME": "🏰 Укажи <b>прайм</b> (дни + время):",
        "ASK_MIC": "🎧 Есть <b>микрофон</b>?",
        "ASK_READY": "🛡 Готовность к <b>прайму / явке</b>:",
        "ASK_DISC": "🛡 Готов соблюдать правила клана и решения <b>КЛ / ПЛ</b>?",
        "ASK_REASON": "✍️ Почему ты хочешь вступить в <b>SOBRANIEGOLD</b>?",
        "ERR": "⚠️ Без ссылок и @.",
        "ERR_LVL": "⚠️ Уровень должен быть числом от 1 до 99.",
        "DONE": (
            "✅ <b>Анкета принята.</b>\n\n"
            "Рассмотрение занимает до <b>24 часов</b>.\n"
            "Ответ поступит в Telegram при положительном решении."
        ),
        "COOLDOWN": "Повторная заявка доступна через 12 часов.",
    },
    "ua": {
        "LANG_PICK": "🌍 <b>Оберіть мову</b>",
        "WELCOME": (
            "🛡 <b>SOBRANIEGOLD — офіційний набір</b>\n"
            "Анкети розглядає офіцерський склад.\n"
            "Заповнення анкети — обов’язкова умова."
        ),
        "BTN_START": "⚔️ Заповнити анкету",
        "BTN_CANCEL": "❌ Скасувати",
        "BTN_RESTART": "🔄 Заповнити заново",
        "BTN_SEND": "✅ Відправити",
        "BTN_USE_TG": "✅ Використати мій Telegram",
        "ASK_NICK": "⚔️ Вкажи <b>нік у грі</b>:",
        "ASK_CONTACT": "📩 Вкажи <b>контакт у Telegram</b>:",
        "ASK_PROF": "🔮 Вкажи <b>клас / саб</b>:",
        "ASK_LEVEL": "📈 Вкажи <b>рівень</b> (1–99):",
        "ASK_COUNTRY": "🌍 Вкажи <b>країну / регіон</b>:",
        "ASK_NOBLE": "🕊 Є <b>Noblesse</b>?",
        "ASK_PRIME": "🏰 Вкажи <b>прайм</b> (дні + час):",
        "ASK_MIC": "🎧 Є <b>мікрофон</b>?",
        "ASK_READY": "🛡 Готовність до <b>прайму / явки</b>:",
        "ASK_DISC": "🛡 Готовий дотримуватись правил клану та рішень <b>КЛ / ПЛ</b>?",
        "ASK_REASON": "✍️ Чому хочеш вступити в <b>SOBRANIEGOLD</b>?",
        "ERR": "⚠️ Без посилань і @.",
        "ERR_LVL": "⚠️ Рівень має бути від 1 до 99.",
        "DONE": (
            "✅ <b>Анкету прийнято.</b>\n\n"
            "Розгляд займає до <b>24 годин</b>."
        ),
        "COOLDOWN": "Повторна заявка через 12 годин.",
    },
    "en": {
        "LANG_PICK": "🌍 <b>Choose language</b>",
        "WELCOME": (
            "🛡 <b>SOBRANIEGOLD — official recruitment</b>\n"
            "Applications are reviewed by officers.\n"
            "Filling the form is mandatory."
        ),
        "BTN_START": "⚔️ Fill application",
        "BTN_CANCEL": "❌ Cancel",
        "BTN_RESTART": "🔄 Refill",
        "BTN_SEND": "✅ Submit",
        "BTN_USE_TG": "✅ Use my Telegram",
        "ASK_NICK": "⚔️ Enter <b>in-game nickname</b>:",
        "ASK_CONTACT": "📩 Enter <b>Telegram contact</b>:",
        "ASK_PROF": "🔮 Enter <b>class / sub</b>:",
        "ASK_LEVEL": "📈 Enter <b>level</b> (1–99):",
        "ASK_COUNTRY": "🌍 Enter <b>country / region</b>:",
        "ASK_NOBLE": "🕊 Do you have <b>Noblesse</b>?",
        "ASK_PRIME": "🏰 Enter <b>prime time</b>:",
        "ASK_MIC": "🎧 Do you have a <b>microphone</b>?",
        "ASK_READY": "🛡 Ready for <b>prime / attendance</b>?",
        "ASK_DISC": "🛡 Will you follow clan rules and <b>CL / PL</b> decisions?",
        "ASK_REASON": "✍️ Why do you want to join <b>SOBRANIEGOLD</b>?",
        "ERR": "⚠️ No links or @.",
        "ERR_LVL": "⚠️ Level must be 1–99.",
        "DONE": (
            "✅ <b>Application received.</b>\n\n"
            "Review takes up to <b>24 hours</b>."
        ),
        "COOLDOWN": "You can re-apply in 12 hours.",
    },
}

async def get_lang(state: FSMContext) -> str:
    d = await state.get_data()
    return d.get("lang", "ru")

async def tr(state: FSMContext, key: str) -> str:
    return T[await get_lang(state)][key]

# ================= Keyboards =================
def k_lang():
    kb = InlineKeyboardBuilder()
    kb.button(text="🇺🇦 UA Українська", callback_data="lang:ua")
    kb.button(text="🇷🇺 RU Русский", callback_data="lang:ru")
    kb.button(text="🇺🇸 EN English", callback_data="lang:en")
    kb.adjust(1)
    return kb.as_markup()

async def k_start(state): 
    kb = InlineKeyboardBuilder()
    kb.button(text=await tr(state,"BTN_START"), callback_data="start_form")
    return kb.as_markup()

async def k_cancel(state):
    kb = InlineKeyboardBuilder()
    kb.button(text=await tr(state,"BTN_CANCEL"), callback_data="cancel")
    return kb.as_markup()

async def k_yesno(state,p):
    kb=InlineKeyboardBuilder()
    kb.button(text="✅", callback_data=f"{p}:yes")
    kb.button(text="❌", callback_data=f"{p}:no")
    kb.button(text=await tr(state,"BTN_CANCEL"), callback_data="cancel")
    kb.adjust(2,1)
    return kb.as_markup()

def k_admin_contact(uid):
    kb=InlineKeyboardBuilder()
    kb.button(text="✉️ Связаться", url=f"tg://user?id={uid}")
    return kb.as_markup()

# ================= FSM =================
class Form(StatesGroup):
    nick=State(); contact=State(); prof=State(); lvl=State()
    country=State(); noble=State(); prime=State()
    mic=State(); ready=State(); disc=State(); reason=State(); confirm=State()

# ================= START =================
@dp.message(CommandStart())
async def start(m:Message,state:FSMContext):
    if not guard_private(m.chat.type): return
    await state.clear()
    await m.answer(T["ru"]["LANG_PICK"], reply_markup=k_lang(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("lang:"))
async def pick_lang(cq:CallbackQuery,state:FSMContext):
    await state.update_data(lang=cq.data.split(":")[1])
    await cq.message.edit_text(await tr(state,"WELCOME"), reply_markup=await k_start(state), parse_mode="HTML")
    await cq.answer()

# ================= FLOW =================
@dp.callback_query(F.data=="start_form")
async def start_form(cq,state):
    await cq.message.edit_text(await tr(state,"ASK_NICK"), reply_markup=await k_cancel(state), parse_mode="HTML")
    await state.set_state(Form.nick); await cq.answer()

@dp.message(Form.nick)
async def step(m,state):
    await state.update_data(nick=m.text.strip())
    await m.answer(await tr(state,"ASK_CONTACT"), reply_markup=await k_cancel(state), parse_mode="HTML")
    await state.set_state(Form.contact)

@dp.message(Form.contact)
async def step(m,state):
    await state.update_data(contact=normalize_contact(m.text))
    await m.answer(await tr(state,"ASK_PROF"), reply_markup=await k_cancel(state), parse_mode="HTML")
    await state.set_state(Form.prof)

@dp.message(Form.prof)
async def step(m,state):
    await state.update_data(prof=m.text.strip())
    await m.answer(await tr(state,"ASK_LEVEL"), reply_markup=await k_cancel(state), parse_mode="HTML")
    await state.set_state(Form.lvl)

@dp.message(Form.lvl)
async def step(m,state):
    if not m.text.isdigit(): return await m.answer(await tr(state,"ERR_LVL"))
    await state.update_data(lvl=int(m.text))
    await m.answer(await tr(state,"ASK_COUNTRY"), reply_markup=await k_cancel(state), parse_mode="HTML")
    await state.set_state(Form.country)

@dp.message(Form.country)
async def step(m,state):
    await state.update_data(country=m.text.strip())
    await m.answer(await tr(state,"ASK_NOBLE"), reply_markup=await k_yesno(state,"noble"), parse_mode="HTML")
    await state.set_state(Form.noble)

@dp.callback_query(F.data.startswith("noble:"))
async def step(cq,state):
    await state.update_data(noble="да" if cq.data.endswith("yes") else "нет")
    await cq.message.edit_text(await tr(state,"ASK_PRIME"), reply_markup=await k_cancel(state), parse_mode="HTML")
    await state.set_state(Form.prime); await cq.answer()

@dp.message(Form.prime)
async def step(m,state):
    await state.update_data(prime=m.text.strip())
    await m.answer(await tr(state,"ASK_MIC"), reply_markup=await k_yesno(state,"mic"), parse_mode="HTML")
    await state.set_state(Form.mic)

@dp.callback_query(F.data.startswith("mic:"))
async def step(cq,state):
    await state.update_data(mic="да" if cq.data.endswith("yes") else "нет")
    await cq.message.edit_text(await tr(state,"ASK_READY"), reply_markup=await k_yesno(state,"ready"), parse_mode="HTML")
    await state.set_state(Form.ready); await cq.answer()

@dp.callback_query(F.data.startswith("ready:"))
async def step(cq,state):
    await state.update_data(ready="готов" if cq.data.endswith("yes") else "не всегда")
    await cq.message.edit_text(await tr(state,"ASK_DISC"), reply_markup=await k_yesno(state,"disc"), parse_mode="HTML")
    await state.set_state(Form.disc); await cq.answer()

@dp.callback_query(F.data.startswith("disc:"))
async def step(cq,state):
    await state.update_data(disc="подтверждена" if cq.data.endswith("yes") else "НЕ подтверждена")
    await cq.message.edit_text(await tr(state,"ASK_REASON"), reply_markup=await k_cancel(state), parse_mode="HTML")
    await state.set_state(Form.reason); await cq.answer()

@dp.message(Form.reason)
async def step(m,state):
    await state.update_data(reason=m.text.strip())
    await state.set_state(Form.confirm)
    data=await state.get_data()
    disc_icon="✅" if data["disc"].startswith("под") else "⚠️"
    msg=(
        f"⚔️ Ник: <b>{data['nick']}</b>\n"
        f"🔮 Класс: <b>{data['prof']}</b>\n"
        f"📈 Уровень: <b>{data['lvl']}</b>\n"
        f"🕊 Noblesse: <b>{data['noble']}</b>\n"
        f"🏰 Прайм: <b>{data['prime']}</b>\n"
        f"🛡 Дисциплина: {disc_icon} <b>{data['disc']}</b>\n\n"
        f"✍️ Причина:\n{data['reason']}"
    )
    await m.answer(msg, parse_mode="HTML")

# ================= CONFIRM =================
@dp.message(Form.confirm)
async def confirm(m,state):
    data=await state.get_data()
    disc_icon="✅" if data["disc"].startswith("под") else "⚠️"
    admin=(
        "🧾 <b>Новая заявка — SOBRANIEGOLD</b>\n\n"
        f"🌍 Язык: <b>{(await get_lang(state)).upper()}</b>\n"
        f"⚔️ Ник: <b>{data['nick']}</b>\n"
        f"🔮 Класс: <b>{data['prof']}</b>\n"
        f"📈 Уровень: <b>{data['lvl']}</b>\n"
        f"🕊 Noblesse: <b>{data['noble']}</b>\n"
        f"🏰 Прайм: <b>{data['prime']}</b>\n"
        f"🛡 Дисциплина: {disc_icon} <b>{data['disc']}</b>\n\n"
        f"✍️ {data['reason']}"
    )
    await bot.send_message(ADMIN_CHAT_ID, admin, parse_mode="HTML", reply_markup=k_admin_contact(m.from_user.id))
    await state.clear()
    await m.answer(await tr(state,"DONE"), reply_markup=await k_start(state), parse_mode="HTML")

# ================= WEBHOOK =================
@dp.startup()
async def startup():
    if PUBLIC_URL:
        await bot.set_webhook(WEBHOOK_URL)

@app.post(WEBHOOK_PATH)
async def webhook(req:Request):
    await dp.feed_webhook_update(bot, await req.json())
    return Response(status_code=200)

@app.get("/")
async def ok(): return {"ok":True}
@app.head("/")
async def okh(): return Response(status_code=200)
