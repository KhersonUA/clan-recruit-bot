import os
import re
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from fastapi import FastAPI, Request
from fastapi.responses import Response

# ===== ENV =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WEBHOOK_PATH = "/tg/webhook"
COOLDOWN_HOURS = 12

WEBHOOK_URL = f"{PUBLIC_URL}{WEBHOOK_PATH}" if PUBLIC_URL else ""

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

# ===== Validation / Anti-spam =====
last_submit: dict[int, datetime] = {}

LINK_RE = re.compile(r"(https?://|t\.me/|telegram\.me/|www\.)", re.IGNORECASE)
AT_RE = re.compile(r"@", re.IGNORECASE)


def bad_text_general(s: str) -> bool:
    s = (s or "").strip()
    return (not s) or bool(LINK_RE.search(s)) or bool(AT_RE.search(s))


def normalize_contact(raw: str) -> str:
    """
    Accept:
      @username
      username
      t.me/username
      https://t.me/username
    Return:
      @username (if looks like username), else trimmed raw
    """
    s = (raw or "").strip()
    s = s.replace("https://", "").replace("http://", "")
    s = s.replace("t.me/", "").replace("telegram.me/", "")
    s = s.strip().lstrip("@").strip()

    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", s):
        return f"@{s}"
    return (raw or "").strip()[:64]


# ===== i18n =====
SUPPORTED_LANGS = ("ru", "uk", "en")

LANG_LABEL = {
    "ru": "RU Русский",
    "uk": "UA Українська",
    "en": "EN English",
}

FLAG = {
    "ru": "🇷🇺",
    "uk": "🇺🇦",
    "en": "🇺🇸",
}

# You can tweak wording here later without touching logic
T = {
    "ru": {
        "welcome_title": "🏰 <b>SOBRANIEGOLD — официальный набор</b>",
        "welcome_body": (
            "Анкеты рассматриваются нашей командой.\n"
            "Заполнение анкеты — обязательное условие.\n\n"
            "Нажми <b>«Подать заявку»</b> и заполни анкету.\n"
            "⚠️ В анкете <b>без ссылок</b> и <b>@</b> (кроме поля «Контакт TG»)."
        ),
        "menu_apply": "📝 Подать заявку",
        "menu_info": "ℹ️ Инфо/Требования",
        "cancel": "❌ Отмена",
        "restart": "🔄 Заполнить заново",
        "send": "✅ Отправить",

        "info_text": (
            "ℹ️ <b>Информация</b>\n\n"
            "Анкета обязательна.\n"
            "Рассмотрение занимает до 24 часов.\n"
            "Ответ придёт в Telegram при положительном решении.\n\n"
            "Нажми <b>«Подать заявку»</b>, чтобы начать."
        ),

        "lang_pick": "🌍 Выбери язык / Choose language / Оберіть мову:",
        "form_title": "🧾 <b>Анкета</b>",
        "q_nick": "⚔️ (1/12)\n\nВведи <b>ник в игре</b>:",
        "q_contact": (
            "📩 (2/12)\n\nУкажи <b>контакт в Telegram</b>:\n"
            "• @username\n\n"
            "Если нет username — напиши <b>нет</b> или контакт для связи."
        ),
        "use_my_tg": "✅ Использовать мой Telegram",
        "q_country": "🌍 (3/12)\n\nУкажи <b>страна / город</b> (кратко):",
        "q_prof": "🧙‍♂️ (4/12)\n\nУкажи <b>профу / саб</b> (коротко):\n<i>Пример: Necromancer / Bishop</i>",
        "q_lvl": "🧠 (5/12)\n\nУкажи <b>уровень</b> (числом):",
        "q_noble": "🪽 (6/12)\n\nНобл есть?",
        "q_prime": "⏰ (7/12)\n\nУкажи <b>прайм</b> (дни + время):\n<i>Пример: Пн–Пт 20:00–00:00, сб/вс больше</i>",
        "q_mic": "🎙 (8/12)\n\nЕсть <b>микрофон</b> и готов слушать колл (TS/Discord)?",
        "q_goal": "⚔️ (9/12)\n\nНа какую активность ты ориентирован в первую очередь?",
        "q_ready": "🛡 (10/12)\n\nГотовность к <b>прайму/явке</b>:",
        "q_why": "⭐ (11/12)\n\nПочему ты хочешь вступить именно в <b>SOBRANIEGOLD</b>?\n<i>1–2 предложения</i>",
        "q_discipline": "📜 (12/12)\n\nГотов соблюдать правила клана и решения КЛа/ПЛа?",
        "preview_title": "🧾 <b>Проверь заявку</b>",
        "sent_ok": "✅ <b>Анкета принята</b>\n\nРассмотрение занимает до 24 часов.\nОтвет поступит в Telegram при положительном решении.",
        "only_private": "Подача заявки доступна только в личных сообщениях.",
        "invalid_nick": "⚠️ Ник без ссылок и @. Повтори:",
        "invalid_no_links": "⚠️ Без ссылок и @. Повтори:",
        "lvl_number": "⚠️ Уровень должен быть числом. Например: <b>78</b>",
        "lvl_range": "⚠️ Укажи уровень от 1 до 99.",
        "need_contact": "⚠️ Введи контакт или напиши <b>нет</b>.",
        "cooldown": "Повторная заявка доступна через 12 часов.",
        "choose_buttons": "Выбери действие кнопками ниже:",
        "cancelled": "Ок, отменил. Если захочешь — подай заявку заново.",
        "discipline_no": "❌ Заявка отклонена: дисциплина не подтверждена.",
    },
    "uk": {
        "welcome_title": "🏰 <b>SOBRANIEGOLD — офіційний набір</b>",
        "welcome_body": (
            "Анкети розглядає наша команда.\n"
            "Заповнення анкети — обов’язкова умова.\n\n"
            "Натисни <b>«Подати заявку»</b> і заповни анкету.\n"
            "⚠️ Без <b>посилань</b> і <b>@</b> (окрім поля «Контакт TG»)."
        ),
        "menu_apply": "📝 Подати заявку",
        "menu_info": "ℹ️ Інфо/Вимоги",
        "cancel": "❌ Скасувати",
        "restart": "🔄 Заповнити заново",
        "send": "✅ Надіслати",

        "info_text": (
            "ℹ️ <b>Інформація</b>\n\n"
            "Анкета обов’язкова.\n"
            "Розгляд до 24 годин.\n"
            "Відповідь прийде в Telegram при позитивному рішенні.\n\n"
            "Натисни <b>«Подати заявку»</b>, щоб почати."
        ),

        "lang_pick": "🌍 Обери мову / Choose language / Выбери язык:",
        "form_title": "🧾 <b>Анкета</b>",
        "q_nick": "⚔️ (1/12)\n\nВведи <b>нік у грі</b>:",
        "q_contact": (
            "📩 (2/12)\n\nВкажи <b>контакт у Telegram</b>:\n"
            "• @username\n\n"
            "Якщо немає username — напиши <b>нема</b> або контакт для зв’язку."
        ),
        "use_my_tg": "✅ Використати мій Telegram",
        "q_country": "🌍 (3/12)\n\nВкажи <b>країна / місто</b> (коротко):",
        "q_prof": "🧙‍♂️ (4/12)\n\nВкажи <b>профу / саб</b>:\n<i>Приклад: Necromancer / Bishop</i>",
        "q_lvl": "🧠 (5/12)\n\nВкажи <b>рівень</b> (числом):",
        "q_noble": "🪽 (6/12)\n\nЄ нобл?",
        "q_prime": "⏰ (7/12)\n\nВкажи <b>прайм</b> (дні + час):\n<i>Приклад: Пн–Пт 20:00–00:00, сб/нд більше</i>",
        "q_mic": "🎙 (8/12)\n\nЄ <b>мікрофон</b> і готовий слухати колл (TS/Discord)?",
        "q_goal": "⚔️ (9/12)\n\nНа яку активність ти орієнтований в першу чергу?",
        "q_ready": "🛡 (10/12)\n\nГотовність до <b>прайму/явки</b>:",
        "q_why": "⭐ (11/12)\n\nЧому ти хочеш саме в <b>SOBRANIEGOLD</b>?\n<i>1–2 речення</i>",
        "q_discipline": "📜 (12/12)\n\nГотовий дотримуватись правил клану та рішень КЛ/ПЛ?",
        "preview_title": "🧾 <b>Перевір заявку</b>",
        "sent_ok": "✅ <b>Анкету прийнято</b>\n\nРозгляд до 24 годин.\nВідповідь прийде в Telegram при позитивному рішенні.",
        "only_private": "Заявка доступна лише в приватних повідомленнях.",
        "invalid_nick": "⚠️ Нік без посилань і @. Повтори:",
        "invalid_no_links": "⚠️ Без посилань і @. Повтори:",
        "lvl_number": "⚠️ Рівень має бути числом. Наприклад: <b>78</b>",
        "lvl_range": "⚠️ Вкажи рівень від 1 до 99.",
        "need_contact": "⚠️ Введи контакт або напиши <b>нема</b>.",
        "cooldown": "Повторна заявка доступна через 12 годин.",
        "choose_buttons": "Обери дію кнопками нижче:",
        "cancelled": "Ок, скасовано. Якщо захочеш — подай заявку знову.",
        "discipline_no": "❌ Заявку відхилено: дисципліна не підтверджена.",
    },
    "en": {
        "welcome_title": "🏰 <b>SOBRANIEGOLD — official recruitment</b>",
        "welcome_body": (
            "Applications are reviewed by our staff.\n"
            "Filling the form is mandatory.\n\n"
            "Tap <b>“Apply”</b> to start.\n"
            "⚠️ No <b>links</b> and no <b>@</b> (except Telegram contact field)."
        ),
        "menu_apply": "📝 Apply",
        "menu_info": "ℹ️ Info/Requirements",
        "cancel": "❌ Cancel",
        "restart": "🔄 Restart form",
        "send": "✅ Submit",

        "info_text": (
            "ℹ️ <b>Info</b>\n\n"
            "Application is mandatory.\n"
            "Review takes up to 24 hours.\n"
            "You will get a Telegram reply if approved.\n\n"
            "Tap <b>“Apply”</b> to start."
        ),

        "lang_pick": "🌍 Choose language / Выбери язык / Оберіть мову:",
        "form_title": "🧾 <b>Application</b>",
        "q_nick": "⚔️ (1/12)\n\nEnter your <b>in-game nickname</b>:",
        "q_contact": (
            "📩 (2/12)\n\nEnter your <b>Telegram contact</b>:\n"
            "• @username\n\n"
            "If you don’t have one — type <b>none</b> or another contact."
        ),
        "use_my_tg": "✅ Use my Telegram",
        "q_country": "🌍 (3/12)\n\nCountry / City (short):",
        "q_prof": "🧙‍♂️ (4/12)\n\nClass / Sub (short):\n<i>Example: Necromancer / Bishop</i>",
        "q_lvl": "🧠 (5/12)\n\nLevel (number):",
        "q_noble": "🪽 (6/12)\n\nDo you have Noble?",
        "q_prime": "⏰ (7/12)\n\nPrime time (days + time):\n<i>Example: Mon–Fri 20:00–00:00, weekends more</i>",
        "q_mic": "🎙 (8/12)\n\nDo you have a mic and can follow voice calls (TS/Discord)?",
        "q_goal": "⚔️ (9/12)\n\nYour main focus in the clan:",
        "q_ready": "🛡 (10/12)\n\nAttendance / prime readiness:",
        "q_why": "⭐ (11/12)\n\nWhy do you want to join <b>SOBRANIEGOLD</b>?\n<i>1–2 sentences</i>",
        "q_discipline": "📜 (12/12)\n\nWill you follow clan rules and CL/PL decisions?",
        "preview_title": "🧾 <b>Review your application</b>",
        "sent_ok": "✅ <b>Application received</b>\n\nReview takes up to 24 hours.\nYou will get a reply if approved.",
        "only_private": "Please apply in a private chat with the bot.",
        "invalid_nick": "⚠️ No links and no @. Try again:",
        "invalid_no_links": "⚠️ No links and no @. Try again:",
        "lvl_number": "⚠️ Level must be a number. Example: <b>78</b>",
        "lvl_range": "⚠️ Level must be between 1 and 99.",
        "need_contact": "⚠️ Enter a contact or type <b>none</b>.",
        "cooldown": "You can reapply in 12 hours.",
        "choose_buttons": "Use the buttons below:",
        "cancelled": "Cancelled. You can apply again anytime.",
        "discipline_no": "❌ Rejected: discipline not confirmed.",
    },
}


def get_lang_from_state(data: dict) -> str:
    lang = (data or {}).get("lang", "ru")
    return lang if lang in SUPPORTED_LANGS else "ru"


# ===== Keyboards =====
def k_lang() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code in SUPPORTED_LANGS:
        kb.button(text=f"{FLAG[code]} {LANG_LABEL[code]}", callback_data=f"lang:{code}")
    kb.adjust(1)
    return kb.as_markup()


def k_start(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=T[lang]["menu_apply"], callback_data="start_form")
    kb.button(text=T[lang]["menu_info"], callback_data="info")
    kb.adjust(1)
    return kb.as_markup()


def k_cancel(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=T[lang]["cancel"], callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def k_confirm(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=T[lang]["send"], callback_data="confirm_send")
    kb.button(text=T[lang]["restart"], callback_data="restart")
    kb.button(text=T[lang]["cancel"], callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def k_noble(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🪽 Yes", callback_data="noble:yes")
    kb.button(text="⬛ No", callback_data="noble:no")
    kb.button(text="⏳ In progress", callback_data="noble:progress")
    kb.adjust(2, 1)
    return kb.as_markup()


def k_mic(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎙 Yes", callback_data="mic:yes")
    kb.button(text="🔇 No", callback_data="mic:no")
    kb.adjust(2)
    return kb.as_markup()


def k_goal(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 CP", callback_data="goal:kp")
    kb.button(text="⚔️ Sieges/PvP", callback_data="goal:siege")
    kb.button(text="👥 Mass", callback_data="goal:mass")
    kb.button(text="💰 Farm/PvE", callback_data="goal:farm")
    kb.adjust(2, 2)
    return kb.as_markup()


def k_ready(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ready", callback_data="ready:yes")
    kb.button(text="⚠️ Sometimes", callback_data="ready:sometimes")
    kb.button(text="❌ Not ready", callback_data="ready:no")
    kb.adjust(1)
    return kb.as_markup()


def k_discipline(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Yes", callback_data="disc:yes")
    kb.button(text="❌ No", callback_data="disc:no")
    kb.adjust(2)
    return kb.as_markup()


def k_use_my_tg(lang: str, has_username: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_username:
        kb.button(text=T[lang]["use_my_tg"], callback_data="use_my_tg")
    kb.button(text=T[lang]["cancel"], callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def k_admin_contact(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Связаться с игроком", url=f"tg://user?id={user_id}")
    kb.adjust(1)
    return kb.as_markup()


# ===== Text helpers =====
def build_welcome(lang: str) -> str:
    return f"{T[lang]['welcome_title']}\n\n{T[lang]['welcome_body']}"


def fmt_preview(lang: str, data: dict) -> str:
    return (
        f"{T[lang]['preview_title']}\n\n"
        f"⚔️ Nick: <b>{data.get('nick','-')}</b>\n"
        f"📩 TG contact: <b>{data.get('contact','-')}</b>\n"
        f"🌍 Country/City: <b>{data.get('country','-')}</b>\n"
        f"🧙‍♂️ Class/Sub: <b>{data.get('prof','-')}</b>\n"
        f"🧠 Level: <b>{data.get('lvl','-')}</b>\n"
        f"🪽 Noble: <b>{data.get('noble','-')}</b>\n"
        f"⏰ Prime: <b>{data.get('prime','-')}</b>\n"
        f"🎙 Mic/TS: <b>{data.get('mic','-')}</b>\n"
        f"⚔️ Focus: <b>{data.get('goal','-')}</b>\n"
        f"🛡 Attendance: <b>{data.get('ready','-')}</b>\n"
        f"⭐ Why SOBRANIEGOLD: <b>{data.get('why','-')}</b>\n"
        f"📜 Discipline: <b>{data.get('discipline','-')}</b>\n\n"
        "Если всё верно — нажми кнопку отправки."
    )


async def guard_private_message(m: Message, lang: str) -> bool:
    if m.chat.type != "private":
        await m.answer(T[lang]["only_private"])
        return False
    return True


# ===== States =====
class Form(StatesGroup):
    lang = State()
    nick = State()
    contact = State()
    country = State()
    prof = State()
    lvl = State()
    noble = State()
    prime = State()
    mic = State()
    goal = State()
    ready = State()
    why = State()
    discipline = State()
    confirm = State()


# ===== Start / Language =====
@dp.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    # Always ask language first
    await m.answer(T["ru"]["lang_pick"], reply_markup=k_lang(), parse_mode="HTML")


@dp.callback_query(F.data.startswith("lang:"))
async def cb_lang(cq: CallbackQuery, state: FSMContext):
    code = cq.data.split(":", 1)[1]
    if code not in SUPPORTED_LANGS:
        code = "ru"
    await state.update_data(lang=code)
    await cq.message.edit_text(build_welcome(code), reply_markup=k_start(code), parse_mode="HTML")
    await cq.answer()


@dp.callback_query(F.data == "info")
async def cb_info(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    await cq.message.edit_text(T[lang]["info_text"], reply_markup=k_start(lang), parse_mode="HTML")
    await cq.answer()


@dp.callback_query(F.data == "cancel")
async def cb_cancel(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    await state.clear()
    # After cancel -> ask language again (requirement: always ask language)
    await cq.message.edit_text(T["ru"]["lang_pick"], reply_markup=k_lang(), parse_mode="HTML")
    await cq.answer()


@dp.callback_query(F.data == "restart")
async def cb_restart(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    # Keep language, clear other fields
    await state.set_data({"lang": lang})
    await cq.message.edit_text(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_nick']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await cq.answer()


@dp.callback_query(F.data == "start_form")
async def cb_start_form(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    # Keep language, reset form data
    await state.set_data({"lang": lang})
    await cq.message.edit_text(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_nick']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await cq.answer()


# ===== Step 1: Nick =====
@dp.message(Form.nick)
async def step_nick(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if not await guard_private_message(m, lang):
        return

    if bad_text_general(m.text):
        return await m.answer(T[lang]["invalid_nick"], reply_markup=k_cancel(lang), parse_mode="HTML")

    await state.update_data(nick=m.text.strip())

    has_username = bool(m.from_user.username)
    await m.answer(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_contact']}",
        reply_markup=k_use_my_tg(lang, has_username),
        parse_mode="HTML",
    )
    await state.set_state(Form.contact)


@dp.callback_query(F.data == "use_my_tg")
async def cb_use_my_tg(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if await state.get_state() != Form.contact.state:
        await cq.answer()
        return

    username = cq.from_user.username
    if username:
        await state.update_data(contact=f"@{username}")
        await cq.message.edit_text(
            f"{T[lang]['form_title']}\n\n{T[lang]['q_country']}",
            reply_markup=k_cancel(lang),
            parse_mode="HTML",
        )
        await state.set_state(Form.country)
        await cq.answer("OK")
    else:
        await cq.answer("No username", show_alert=True)


# ===== Step 2: Contact =====
@dp.message(Form.contact)
async def step_contact(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if not await guard_private_message(m, lang):
        return

    t = (m.text or "").strip()
    if not t:
        return await m.answer(T[lang]["need_contact"], reply_markup=k_cancel(lang), parse_mode="HTML")

    lower = t.lower()
    if lower in {"нет", "нема", "no", "none"}:
        contact = "нет" if lang == "ru" else ("нема" if lang == "uk" else "none")
    else:
        contact = normalize_contact(t)

    await state.update_data(contact=contact)

    await m.answer(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_country']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.country)


# ===== Step 3: Country/City =====
@dp.message(Form.country)
async def step_country(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if not await guard_private_message(m, lang):
        return

    if bad_text_general(m.text):
        return await m.answer(T[lang]["invalid_no_links"], reply_markup=k_cancel(lang), parse_mode="HTML")

    await state.update_data(country=m.text.strip()[:64])

    await m.answer(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_prof']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.prof)


# ===== Step 4: Class/Sub =====
@dp.message(Form.prof)
async def step_prof(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if not await guard_private_message(m, lang):
        return

    if bad_text_general(m.text):
        return await m.answer(T[lang]["invalid_no_links"], reply_markup=k_cancel(lang), parse_mode="HTML")

    await state.update_data(prof=m.text.strip()[:64])

    await m.answer(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_lvl']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.lvl)


# ===== Step 5: Level =====
@dp.message(Form.lvl)
async def step_lvl(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if not await guard_private_message(m, lang):
        return

    t = (m.text or "").strip()
    if not t.isdigit():
        return await m.answer(T[lang]["lvl_number"], reply_markup=k_cancel(lang), parse_mode="HTML")

    lvl_int = int(t)
    if lvl_int < 1 or lvl_int > 99:
        return await m.answer(T[lang]["lvl_range"], reply_markup=k_cancel(lang), parse_mode="HTML")

    await state.update_data(lvl=lvl_int)

    await m.answer(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_noble']}",
        reply_markup=k_noble(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.noble)


# ===== Step 6: Noble (buttons) =====
@dp.callback_query(F.data.startswith("noble:"))
async def cb_noble(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if await state.get_state() != Form.noble.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    noble_map = {"yes": "yes", "no": "no", "progress": "in progress"}
    noble = noble_map.get(val, "-")
    await state.update_data(noble=noble)

    await cq.message.edit_text(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_prime']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.prime)
    await cq.answer()


# ===== Step 7: Prime =====
@dp.message(Form.prime)
async def step_prime(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if not await guard_private_message(m, lang):
        return

    if bad_text_general(m.text):
        return await m.answer(T[lang]["invalid_no_links"], reply_markup=k_cancel(lang), parse_mode="HTML")

    await state.update_data(prime=m.text.strip()[:80])

    await m.answer(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_mic']}",
        reply_markup=k_mic(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.mic)


# ===== Step 8: Mic (buttons) =====
@dp.callback_query(F.data.startswith("mic:"))
async def cb_mic(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if await state.get_state() != Form.mic.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    mic = "yes" if val == "yes" else "no"
    await state.update_data(mic=mic)

    await cq.message.edit_text(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_goal']}\n\n"
        "🎯 CP (discipline, prime)\n⚔️ Sieges/PvP\n👥 Mass events\n💰 Farm/PvE",
        reply_markup=k_goal(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.goal)
    await cq.answer()


# ===== Step 9: Goal (buttons) =====
@dp.callback_query(F.data.startswith("goal:"))
async def cb_goal(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if await state.get_state() != Form.goal.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    goal_map = {"kp": "CP", "siege": "Sieges/PvP", "mass": "Mass", "farm": "Farm/PvE"}
    await state.update_data(goal=goal_map.get(val, "-"))

    await cq.message.edit_text(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_ready']}",
        reply_markup=k_ready(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.ready)
    await cq.answer()


# ===== Step 10: Ready (buttons) =====
@dp.callback_query(F.data.startswith("ready:"))
async def cb_ready(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if await state.get_state() != Form.ready.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    ready_map = {"yes": "ready", "sometimes": "sometimes", "no": "not ready"}
    await state.update_data(ready=ready_map.get(val, "-"))

    await cq.message.edit_text(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_why']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.why)
    await cq.answer()


# ===== Step 11: Why =====
@dp.message(Form.why)
async def step_why(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if not await guard_private_message(m, lang):
        return

    if bad_text_general(m.text):
        return await m.answer(T[lang]["invalid_no_links"], reply_markup=k_cancel(lang), parse_mode="HTML")

    why = (m.text or "").strip()[:200]
    await state.update_data(why=why)

    await m.answer(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_discipline']}",
        reply_markup=k_discipline(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.discipline)


# ===== Step 12: Discipline (buttons) =====
@dp.callback_query(F.data.startswith("disc:"))
async def cb_disc(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if await state.get_state() != Form.discipline.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    if val == "yes":
        # confirmed -> "all good" icon
        await state.update_data(discipline="✅ confirmed")
        data = await state.get_data()
        await cq.message.edit_text(fmt_preview(lang, data), reply_markup=k_confirm(lang), parse_mode="HTML")
        await state.set_state(Form.confirm)
        await cq.answer("OK")
    else:
        # not confirmed -> send to admin with warning and stop
        await state.update_data(discipline="⚠️ NOT confirmed")
        data2 = await state.get_data()
        user = cq.from_user

        admin_msg = (
            "🧾 <b>Новая заявка (дисциплина НЕ подтверждена)</b>\n"
            f"🌍 Lang: <b>{get_lang_from_state(data2).upper()}</b>\n"
            f"👤 TG: {user.full_name} (id: <code>{user.id}</code>)\n"
            f"📩 Contact: <b>{data2.get('contact','-')}</b>\n\n"
            f"⚔️ Nick: <b>{data2.get('nick','-')}</b>\n"
            f"🌍 Country/City: <b>{data2.get('country','-')}</b>\n"
            f"🧙‍♂️ Class/Sub: <b>{data2.get('prof','-')}</b>\n"
            f"🧠 Level: <b>{data2.get('lvl','-')}</b>\n"
            f"🪽 Noble: <b>{data2.get('noble','-')}</b>\n"
            f"⏰ Prime: <b>{data2.get('prime','-')}</b>\n"
            f"🎙 Mic: <b>{data2.get('mic','-')}</b>\n"
            f"⚔️ Focus: <b>{data2.get('goal','-')}</b>\n"
            f"🛡 Ready: <b>{data2.get('ready','-')}</b>\n"
            f"⭐ Why: <b>{data2.get('why','-')}</b>\n"
            f"📜 Discipline: <b>{data2.get('discipline','-')}</b>\n"
        )

        await bot.send_message(ADMIN_CHAT_ID, admin_msg, parse_mode="HTML", reply_markup=k_admin_contact(user.id))
        await state.clear()
        await cq.message.edit_text(T[lang]["discipline_no"], parse_mode="HTML")
        await cq.answer()


# ===== Confirm send =====
@dp.callback_query(F.data == "confirm_send")
async def cb_confirm_send(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if await state.get_state() != Form.confirm.state:
        await cq.answer()
        return

    # cooldown
    now = datetime.now(timezone.utc)
    prev = last_submit.get(cq.from_user.id)
    if prev and now - prev < timedelta(hours=COOLDOWN_HOURS):
        await cq.answer(T[lang]["cooldown"], show_alert=True)
        return

    user = cq.from_user

    admin_msg = (
        "🧾 <b>Новая заявка</b>\n"
        f"🌍 Lang: <b>{lang.upper()}</b>\n"
        f"👤 TG: {user.full_name} (id: <code>{user.id}</code>)\n"
        f"📩 Contact: <b>{data.get('contact','-')}</b>\n\n"
        f"⚔️ Nick: <b>{data.get('nick','-')}</b>\n"
        f"🌍 Country/City: <b>{data.get('country','-')}</b>\n"
        f"🧙‍♂️ Class/Sub: <b>{data.get('prof','-')}</b>\n"
        f"🧠 Level: <b>{data.get('lvl','-')}</b>\n"
        f"🪽 Noble: <b>{data.get('noble','-')}</b>\n"
        f"⏰ Prime: <b>{data.get('prime','-')}</b>\n"
        f"🎙 Mic: <b>{data.get('mic','-')}</b>\n"
        f"⚔️ Focus: <b>{data.get('goal','-')}</b>\n"
        f"🛡 Ready: <b>{data.get('ready','-')}</b>\n"
        f"⭐ Why: <b>{data.get('why','-')}</b>\n"
        f"📜 Discipline: <b>{data.get('discipline','-')}</b>\n"
        f"⏱ {now.astimezone(timezone(timedelta(hours=3))).strftime('%Y-%m-%d %H:%M')} (UTC+3)"
    )

    await bot.send_message(ADMIN_CHAT_ID, admin_msg, parse_mode="HTML", reply_markup=k_admin_contact(user.id))

    last_submit[user.id] = now
    await state.clear()

    # After success -> ask language again (requirement: always ask language)
    await cq.message.edit_text(T[lang]["sent_ok"], parse_mode="HTML")
    await cq.answer("OK")


@dp.message(Form.confirm)
async def in_confirm_state(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if not await guard_private_message(m, lang):
        return
    await m.answer(T[lang]["choose_buttons"], reply_markup=k_confirm(lang), parse_mode="HTML")


# ===== Webhook =====
@dp.startup()
async def startup():
    if WEBHOOK_URL:
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


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)
