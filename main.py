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
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WEBHOOK_PATH = "/tg/webhook"
COOLDOWN_HOURS = 12

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if ADMIN_CHAT_ID == 0:
    raise RuntimeError("ADMIN_CHAT_ID is not set or invalid")

WEBHOOK_URL = f"{PUBLIC_URL}{WEBHOOK_PATH}" if PUBLIC_URL else ""

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

# ===== Validation / Anti-spam =====
last_submit: dict[int, datetime] = {}

# Запрещаем ссылки/@ почти везде. Для контакта TG — разрешаем.
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

# ===== i18n =====
# Язык храним как 'ru' | 'ua' | 'en'
TXT = {
    "ru": {
        "welcome": (
            "👑 <b>SOBRANIEGOLD — официальный набор</b>\n\n"
            "Анкеты рассматриваются нашей командой.\n"
            "Заполнение анкеты — обязательное условие.\n\n"
            "Нажми <b>«Подать заявку»</b> и заполни анкету.\n"
            "⚠️ В анкете <b>без ссылок</b> и <b>@</b> (кроме поля «Контакт TG»)."
        ),
        "choose_lang": "🌍 Выбери язык / Choose language:",
        "btn_apply": "📝 Подать заявку",
        "btn_info": "ℹ️ Инфо/Требования",
        "info": (
            "ℹ️ <b>Инфо</b>\n\n"
            "Заполни анкету — офицеры рассмотрят её.\n"
            "При положительном решении с тобой свяжутся в Telegram.\n\n"
            "Нажми <b>«Подать заявку»</b>, чтобы начать."
        ),
        "cancelled": "Ок, отменил. Если захочешь — подай заявку заново.",
        "sent": (
            "✅ <b>Анкета принята</b>\n\n"
            "Рассмотрение занимает до <b>24 часов</b>.\n"
            "Ответ поступит в Telegram при положительном решении."
        ),

        "form_title": "📝 <b>Анкета</b>",
        "step1": "Введи <b>ник в игре</b>:",
        "step1_bad": "⚠️ Ник без ссылок и @. Повтори:",
        "step2": (
            "Укажи <b>контакт в Telegram</b>:\n"
            "• @username\n\n"
            "Если нет username — напиши <b>нет</b> или укажи способ связи."
        ),
        "step2_empty": "⚠️ Введи контакт или напиши <b>нет</b>.",
        "step3": "Укажи <b>страна / город</b> (коротко):",
        "step3_bad": "⚠️ Без ссылок и @. Напиши страна/город:",
        "step4": (
            "Укажи <b>профу / саб</b> (коротко):\n"
            "<i>Пример: Necromancer / Bishop</i>"
        ),
        "step4_bad": "⚠️ Без ссылок и @. Повтори профу/саб:",
        "step5": "Укажи <b>уровень</b> (числом):",
        "step5_nan": "⚠️ Уровень должен быть числом. Например: <b>78</b>",
        "step5_range": "⚠️ Укажи уровень от 1 до 99.",
        "step6": "Нобл есть?",
        "step7": (
            "Укажи <b>прайм</b> (дни + время):\n"
            "<i>Пример: Пн–Пт 20:00–00:00, сб/вс больше</i>"
        ),
        "step7_bad": "⚠️ Без ссылок и @. Укажи прайм текстом:",
        "step8": "Есть <b>микрофон</b> и готов слушать колл (TS/Discord)?",
        "step9": "Готовность к <b>прайму/явке</b>:",
        "step10": "Почему ты хочешь вступить именно в <b>SOBRANIEGOLD</b>? (1–2 предложения)",
        "step10_bad": "⚠️ Без ссылок и @. Ответь 1–2 предложениями:",
        "step11": "Готов соблюдать <b>правила клана</b> и решения КЛа/ПЛа?",
        "preview_title": "🧾 <b>Проверь заявку</b>",
        "preview_submit": "Если всё верно — нажми <b>«Отправить»</b>.",
        "confirm_hint": "Выбери действие кнопками ниже:",
        "cooldown": f"Повторная заявка доступна через {COOLDOWN_HOURS} часов.",
        "disc_decline_user": (
            "❌ <b>Заявка не принята</b>\n\n"
            "Для вступления необходимо подтвердить готовность соблюдать правила клана."
        ),
    },

    "ua": {
        "welcome": (
            "👑 <b>SOBRANIEGOLD — офіційний набір</b>\n\n"
            "Анкети розглядаються нашою командою.\n"
            "Заповнення анкети — обов’язкова умова.\n\n"
            "Натисни <b>«Подати заявку»</b> та заповни анкету.\n"
            "⚠️ В анкеті <b>без посилань</b> і <b>@</b> (крім поля «Контакт TG»)."
        ),
        "choose_lang": "🌍 Обери мову / Choose language:",
        "btn_apply": "📝 Подати заявку",
        "btn_info": "ℹ️ Інфо/Вимоги",
        "info": (
            "ℹ️ <b>Інфо</b>\n\n"
            "Заповни анкету — офіцери її розглянуть.\n"
            "При позитивному рішенні з тобою зв’яжуться в Telegram.\n\n"
            "Натисни <b>«Подати заявку»</b>, щоб почати."
        ),
        "cancelled": "Ок, скасовано. Якщо захочеш — подай заявку знову.",
        "sent": (
            "✅ <b>Анкета прийнята</b>\n\n"
            "Розгляд займає до <b>24 годин</b>.\n"
            "Відповідь прийде в Telegram при позитивному рішенні."
        ),

        "form_title": "📝 <b>Анкета</b>",
        "step1": "Введи <b>нік у грі</b>:",
        "step1_bad": "⚠️ Нік без посилань і @. Повтори:",
        "step2": (
            "Вкажи <b>контакт у Telegram</b>:\n"
            "• @username\n\n"
            "Якщо немає username — напиши <b>ні</b> або спосіб зв’язку."
        ),
        "step2_empty": "⚠️ Введи контакт або напиши <b>ні</b>.",
        "step3": "Вкажи <b>країна / місто</b> (коротко):",
        "step3_bad": "⚠️ Без посилань і @. Напиши країна/місто:",
        "step4": (
            "Вкажи <b>профу / саб</b> (коротко):\n"
            "<i>Приклад: Necromancer / Bishop</i>"
        ),
        "step4_bad": "⚠️ Без посилань і @. Повтори профу/саб:",
        "step5": "Вкажи <b>рівень</b> (числом):",
        "step5_nan": "⚠️ Рівень має бути числом. Наприклад: <b>78</b>",
        "step5_range": "⚠️ Вкажи рівень від 1 до 99.",
        "step6": "Є нобл?",
        "step7": (
            "Вкажи <b>прайм</b> (дні + час):\n"
            "<i>Приклад: Пн–Пт 20:00–00:00, сб/нд більше</i>"
        ),
        "step7_bad": "⚠️ Без посилань і @. Вкажи прайм текстом:",
        "step8": "Є <b>мікрофон</b> і готовий слухати колл (TS/Discord)?",
        "step9": "Готовність до <b>прайму/явки</b>:",
        "step10": "Чому ти хочеш вступити саме в <b>SOBRANIEGOLD</b>? (1–2 речення)",
        "step10_bad": "⚠️ Без посилань і @. Відповідай 1–2 реченнями:",
        "step11": "Готовий дотримуватись <b>правил клану</b> та рішень КЛа/ПЛа?",
        "preview_title": "🧾 <b>Перевір заявку</b>",
        "preview_submit": "Якщо все вірно — натисни <b>«Відправити»</b>.",
        "confirm_hint": "Обери дію кнопками нижче:",
        "cooldown": f"Повторна заявка буде доступна через {COOLDOWN_HOURS} год.",
        "disc_decline_user": (
            "❌ <b>Заявка не прийнята</b>\n\n"
            "Для вступу потрібно підтвердити готовність дотримуватись правил клану."
        ),
    },

    "en": {
        "welcome": (
            "👑 <b>SOBRANIEGOLD — official recruitment</b>\n\n"
            "Applications are reviewed by our team.\n"
            "Filling the form is mandatory.\n\n"
            "Press <b>“Apply”</b> and complete the form.\n"
            "⚠️ No <b>links</b> and no <b>@</b> (except in “TG contact”)."
        ),
        "choose_lang": "🌍 Choose language:",
        "btn_apply": "📝 Apply",
        "btn_info": "ℹ️ Info/Requirements",
        "info": (
            "ℹ️ <b>Info</b>\n\n"
            "Fill the form — officers will review it.\n"
            "If approved, you will be contacted in Telegram.\n\n"
            "Press <b>“Apply”</b> to start."
        ),
        "cancelled": "Ok, cancelled. If you want — apply again.",
        "sent": (
            "✅ <b>Application received</b>\n\n"
            "Review can take up to <b>24 hours</b>.\n"
            "You will be contacted in Telegram if approved."
        ),

        "form_title": "📝 <b>Application</b>",
        "step1": "Enter your <b>in-game nickname</b>:",
        "step1_bad": "⚠️ No links and no @. Try again:",
        "step2": (
            "Enter your <b>Telegram contact</b>:\n"
            "• @username\n\n"
            "If you don't have a username — type <b>no</b> or your contact method."
        ),
        "step2_empty": "⚠️ Enter contact or type <b>no</b>.",
        "step3": "Enter <b>country / city</b> (short):",
        "step3_bad": "⚠️ No links and no @. Enter country/city:",
        "step4": (
            "Enter your <b>class / sub</b> (short):\n"
            "<i>Example: Necromancer / Bishop</i>"
        ),
        "step4_bad": "⚠️ No links and no @. Repeat class/sub:",
        "step5": "Enter your <b>level</b> (number):",
        "step5_nan": "⚠️ Level must be a number. Example: <b>78</b>",
        "step5_range": "⚠️ Enter a level between 1 and 99.",
        "step6": "Do you have Noble?",
        "step7": (
            "Enter your <b>prime time</b> (days + time):\n"
            "<i>Example: Mon–Fri 20:00–00:00, weekends more</i>"
        ),
        "step7_bad": "⚠️ No links and no @. Enter prime time:",
        "step8": "Do you have a <b>microphone</b> and can listen to calls (TS/Discord)?",
        "step9": "Your <b>attendance readiness</b>:",
        "step10": "Why do you want to join <b>SOBRANIEGOLD</b>? (1–2 sentences)",
        "step10_bad": "⚠️ No links and no @. Answer in 1–2 sentences:",
        "step11": "Are you ready to follow <b>clan rules</b> and CL/PL decisions?",
        "preview_title": "🧾 <b>Check your form</b>",
        "preview_submit": "If everything is correct — press <b>“Send”</b>.",
        "confirm_hint": "Use the buttons below:",
        "cooldown": f"You can re-apply after {COOLDOWN_HOURS} hours.",
        "disc_decline_user": (
            "❌ <b>Application declined</b>\n\n"
            "You must confirm readiness to follow clan rules."
        ),
    },
}

def get_lang(data: dict) -> str:
    lang = (data or {}).get("lang") or "ru"
    return lang if lang in TXT else "ru"

# ===== Keyboards =====
def k_lang():
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 RU Русский", callback_data="lang:ru")
    kb.button(text="🇺🇦 UA Українська", callback_data="lang:ua")
    kb.button(text="🇺🇸 EN English", callback_data="lang:en")
    kb.adjust(1)
    return kb.as_markup()

def k_start(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=TXT[lang]["btn_apply"], callback_data="start_form")
    kb.button(text=TXT[lang]["btn_info"], callback_data="info")
    kb.adjust(1)
    return kb.as_markup()

def k_cancel(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена" if lang == "ru" else ("❌ Скасувати" if lang == "ua" else "❌ Cancel"), callback_data="cancel")
    return kb.as_markup()

def k_confirm(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Отправить" if lang == "ru" else ("✅ Відправити" if lang == "ua" else "✅ Send"), callback_data="confirm_send")
    kb.button(text="🔄 Заполнить заново" if lang == "ru" else ("🔄 Заповнити знову" if lang == "ua" else "🔄 Fill again"), callback_data="restart")
    kb.button(text="❌ Отмена" if lang == "ru" else ("❌ Скасувати" if lang == "ua" else "❌ Cancel"), callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()

def k_noble():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Yes", callback_data="noble:yes")
    kb.button(text="❌ No", callback_data="noble:no")
    kb.button(text="⏳ In progress", callback_data="noble:progress")
    kb.adjust(2, 1)
    return kb.as_markup()

def k_mic():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎙 Yes", callback_data="mic:yes")
    kb.button(text="❌ No", callback_data="mic:no")
    kb.adjust(2)
    return kb.as_markup()

def k_ready(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готов стабильно" if lang == "ru" else ("✅ Готовий стабільно" if lang == "ua" else "✅ Stable"), callback_data="ready:yes")
    kb.button(text="⚠️ Не всегда" if lang == "ru" else ("⚠️ Не завжди" if lang == "ua" else "⚠️ Sometimes"), callback_data="ready:sometimes")
    kb.button(text="❌ Не готов" if lang == "ru" else ("❌ Не готовий" if lang == "ua" else "❌ Not ready"), callback_data="ready:no")
    kb.adjust(1)
    return kb.as_markup()

def k_discipline(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да" if lang == "ru" else ("✅ Так" if lang == "ua" else "✅ Yes"), callback_data="disc:yes")
    kb.button(text="❌ Нет" if lang == "ru" else ("❌ Ні" if lang == "ua" else "❌ No"), callback_data="disc:no")
    kb.adjust(2)
    return kb.as_markup()

def k_use_my_tg(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(
        text="👤 Использовать мой Telegram" if lang == "ru" else ("👤 Використати мій Telegram" if lang == "ua" else "👤 Use my Telegram"),
        callback_data="use_my_tg",
    )
    kb.button(text="❌ Отмена" if lang == "ru" else ("❌ Скасувати" if lang == "ua" else "❌ Cancel"), callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()

def k_admin_contact(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Связаться с игроком", url=f"tg://user?id={user_id}")
    return kb.as_markup()

# ===== FSM =====
class Form(StatesGroup):
    lang = State()       # выбор языка всегда сначала
    nick = State()       # 1/11
    contact = State()    # 2/11
    country = State()    # 3/11
    prof = State()       # 4/11
    lvl = State()        # 5/11
    noble = State()      # 6/11
    prime = State()      # 7/11
    mic = State()        # 8/11
    ready = State()      # 9/11
    why = State()        # 10/11
    discipline = State() # 11/11
    confirm = State()

async def guard_private_message(m: Message) -> bool:
    if m.chat.type != "private":
        await m.answer("Подача заявки доступна только в личных сообщениях.")
        return False
    return True

def fmt_preview(lang: str, data: dict) -> str:
    t = TXT[lang]
    return (
        f"{t['preview_title']}\n\n"
        f"1) Ник: <b>{data.get('nick','-')}</b>\n"
        f"2) Контакт TG: <b>{data.get('contact','-')}</b>\n"
        f"3) Страна/город: <b>{data.get('country','-')}</b>\n"
        f"4) Профа/Саб: <b>{data.get('prof','-')}</b>\n"
        f"5) Уровень: <b>{data.get('lvl','-')}</b>\n"
        f"6) Нобл: <b>{data.get('noble','-')}</b>\n"
        f"7) Прайм: <b>{data.get('prime','-')}</b>\n"
        f"8) Микрофон: <b>{data.get('mic','-')}</b>\n"
        f"9) Готовность: <b>{data.get('ready','-')}</b>\n"
        f"10) Почему клан: <b>{data.get('why','-')}</b>\n"
        f"11) Дисциплина: <b>{data.get('discipline','-')}</b>\n\n"
        f"{t['preview_submit']}"
    )

# ===== START =====
@dp.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    if not await guard_private_message(m):
        return
    await state.clear()
    await state.set_state(Form.lang)
    await m.answer(TXT["ru"]["choose_lang"], reply_markup=k_lang(), parse_mode="HTML")

# ===== LANGUAGE =====
@dp.callback_query(F.data.startswith("lang:"))
async def cb_lang(cq: CallbackQuery, state: FSMContext):
    lang = cq.data.split(":", 1)[1]
    if lang not in TXT:
        lang = "ru"
    await state.update_data(lang=lang)
    await cq.message.edit_text(TXT[lang]["welcome"], reply_markup=k_start(lang), parse_mode="HTML")
    await cq.answer()

# ===== MENU =====
@dp.callback_query(F.data == "info")
async def cb_info(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data)
    await state.clear()
    await state.update_data(lang=lang)
    await state.set_state(Form.lang)  # язык всегда хранится, но состояние не критично
    await cq.message.edit_text(TXT[lang]["info"], reply_markup=k_start(lang), parse_mode="HTML")
    await cq.answer()

@dp.callback_query(F.data == "start_form")
async def cb_start_form(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data)
    await state.clear()
    await state.update_data(lang=lang)

    await cq.message.edit_text(
        f"{TXT[lang]['form_title']} (1/11)\n\n{TXT[lang]['step1']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await cq.answer()

@dp.callback_query(F.data == "cancel")
async def cb_cancel(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data)
    await state.clear()
    await state.update_data(lang=lang)
    await cq.message.edit_text(TXT[lang]["cancelled"], reply_markup=k_start(lang), parse_mode="HTML")
    await cq.answer()

@dp.callback_query(F.data == "restart")
async def cb_restart(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data)
    await state.clear()
    await state.update_data(lang=lang)

    await cq.message.edit_text(
        f"{TXT[lang]['form_title']} (1/11)\n\n{TXT[lang]['step1']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await cq.answer()

# ===== 1/11 Nick =====
@dp.message(Form.nick)
async def step_nick(m: Message, state: FSMContext):
    if not await guard_private_message(m):
        return
    data = await state.get_data()
    lang = get_lang(data)

    if bad_text_general(m.text):
        return await m.answer(TXT[lang]["step1_bad"], reply_markup=k_cancel(lang), parse_mode="HTML")

    await state.update_data(nick=m.text.strip())

    # 2/11 contact + (optional) use_my_tg
    kb = k_cancel(lang)
    if m.from_user and m.from_user.username:
        kb = k_use_my_tg(lang)

    await m.answer(
        f"{TXT[lang]['form_title']} (2/11)\n\n{TXT[lang]['step2']}",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await state.set_state(Form.contact)

@dp.callback_query(F.data == "use_my_tg")
async def cb_use_my_tg(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.contact.state:
        await cq.answer()
        return
    data = await state.get_data()
    lang = get_lang(data)

    username = cq.from_user.username
    if username:
        contact = f"@{username}"
        await state.update_data(contact=contact)
        await cq.message.edit_text(
            f"{TXT[lang]['form_title']} (3/11)\n\n{TXT[lang]['step3']}",
            reply_markup=k_cancel(lang),
            parse_mode="HTML",
        )
        await state.set_state(Form.country)
    else:
        # если вдруг нет username — просто оставляем на шаге контакта
        await cq.answer("No username" if lang == "en" else ("Немає username" if lang == "ua" else "Нет username"), show_alert=True)
    await cq.answer()

# ===== 2/11 Contact =====
@dp.message(Form.contact)
async def step_contact(m: Message, state: FSMContext):
    if not await guard_private_message(m):
        return
    data = await state.get_data()
    lang = get_lang(data)

    t = (m.text or "").strip()
    if not t:
        return await m.answer(TXT[lang]["step2_empty"], reply_markup=k_cancel(lang), parse_mode="HTML")

    low = t.lower()
    if low in {"нет", "no", "none", "ні", "нема"}:
        contact = "нет" if lang == "ru" else ("ні" if lang == "ua" else "no")
    else:
        contact = normalize_contact(t)

    await state.update_data(contact=contact)
    await m.answer(
        f"{TXT[lang]['form_title']} (3/11)\n\n{TXT[lang]['step3']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.country)

# ===== 3/11 Country/City =====
@dp.message(Form.country)
async def step_country(m: Message, state: FSMContext):
    if not await guard_private_message(m):
        return
    data = await state.get_data()
    lang = get_lang(data)

    if bad_text_general(m.text):
        return await m.answer(TXT[lang]["step3_bad"], reply_markup=k_cancel(lang), parse_mode="HTML")

    await state.update_data(country=m.text.strip()[:64])
    await m.answer(
        f"{TXT[lang]['form_title']} (4/11)\n\n{TXT[lang]['step4']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.prof)

# ===== 4/11 Prof/Sub =====
@dp.message(Form.prof)
async def step_prof(m: Message, state: FSMContext):
    if not await guard_private_message(m):
        return
    data = await state.get_data()
    lang = get_lang(data)

    if bad_text_general(m.text):
        return await m.answer(TXT[lang]["step4_bad"], reply_markup=k_cancel(lang), parse_mode="HTML")

    await state.update_data(prof=m.text.strip()[:80])
    await m.answer(
        f"{TXT[lang]['form_title']} (5/11)\n\n{TXT[lang]['step5']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.lvl)

# ===== 5/11 Level =====
@dp.message(Form.lvl)
async def step_lvl(m: Message, state: FSMContext):
    if not await guard_private_message(m):
        return
    data = await state.get_data()
    lang = get_lang(data)

    t = (m.text or "").strip()
    if not t.isdigit():
        return await m.answer(TXT[lang]["step5_nan"], reply_markup=k_cancel(lang), parse_mode="HTML")

    lvl_int = int(t)
    if lvl_int < 1 or lvl_int > 99:
        return await m.answer(TXT[lang]["step5_range"], reply_markup=k_cancel(lang), parse_mode="HTML")

    await state.update_data(lvl=lvl_int)
    await m.answer(
        f"{TXT[lang]['form_title']} (6/11)\n\n{TXT[lang]['step6']}",
        reply_markup=k_noble(),
        parse_mode="HTML",
    )
    await state.set_state(Form.noble)

# ===== 6/11 Noble (buttons) =====
@dp.callback_query(F.data.startswith("noble:"))
async def cb_noble(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.noble.state:
        await cq.answer()
        return
    data = await state.get_data()
    lang = get_lang(data)

    val = cq.data.split(":", 1)[1]
    noble_map = {"yes": "да", "no": "нет", "progress": "в процессе"}
    noble = noble_map.get(val, "—")

    # локализация значения для UA/EN (админу всё равно придет по-русски)
    if lang == "ua":
        noble = {"да": "так", "нет": "ні", "в процессе": "в процесі"}.get(noble, noble)
    if lang == "en":
        noble = {"да": "yes", "нет": "no", "в процессе": "in progress"}.get(noble, noble)

    await state.update_data(noble=noble)
    await cq.message.edit_text(
        f"{TXT[lang]['form_title']} (7/11)\n\n{TXT[lang]['step7']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.prime)
    await cq.answer()

# ===== 7/11 Prime =====
@dp.message(Form.prime)
async def step_prime(m: Message, state: FSMContext):
    if not await guard_private_message(m):
        return
    data = await state.get_data()
    lang = get_lang(data)

    if bad_text_general(m.text):
        return await m.answer(TXT[lang]["step7_bad"], reply_markup=k_cancel(lang), parse_mode="HTML")

    await state.update_data(prime=m.text.strip()[:80])
    await m.answer(
        f"{TXT[lang]['form_title']} (8/11)\n\n{TXT[lang]['step8']}",
        reply_markup=k_mic(),
        parse_mode="HTML",
    )
    await state.set_state(Form.mic)

# ===== 8/11 Mic (buttons) =====
@dp.callback_query(F.data.startswith("mic:"))
async def cb_mic(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.mic.state:
        await cq.answer()
        return
    data = await state.get_data()
    lang = get_lang(data)

    val = cq.data.split(":", 1)[1]
    mic = "да" if val == "yes" else "нет"
    if lang == "ua":
        mic = "так" if val == "yes" else "ні"
    if lang == "en":
        mic = "yes" if val == "yes" else "no"

    await state.update_data(mic=mic)
    await cq.message.edit_text(
        f"{TXT[lang]['form_title']} (9/11)\n\n{TXT[lang]['step9']}",
        reply_markup=k_ready(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.ready)
    await cq.answer()

# ===== 9/11 Ready (buttons) =====
@dp.callback_query(F.data.startswith("ready:"))
async def cb_ready(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.ready.state:
        await cq.answer()
        return
    data = await state.get_data()
    lang = get_lang(data)

    val = cq.data.split(":", 1)[1]
    if lang == "ru":
        ready_map = {"yes": "готов стабильно", "sometimes": "не всегда", "no": "не готов"}
    elif lang == "ua":
        ready_map = {"yes": "готовий стабільно", "sometimes": "не завжди", "no": "не готовий"}
    else:
        ready_map = {"yes": "stable", "sometimes": "sometimes", "no": "not ready"}

    ready = ready_map.get(val, "—")
    await state.update_data(ready=ready)

    await cq.message.edit_text(
        f"{TXT[lang]['form_title']} (10/11)\n\n{TXT[lang]['step10']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.why)
    await cq.answer()

# ===== 10/11 Why =====
@dp.message(Form.why)
async def step_why(m: Message, state: FSMContext):
    if not await guard_private_message(m):
        return
    data = await state.get_data()
    lang = get_lang(data)

    t = (m.text or "").strip()
    if not t or bad_text_general(t):
        return await m.answer(TXT[lang]["step10_bad"], reply_markup=k_cancel(lang), parse_mode="HTML")

    await state.update_data(why=t[:180])
    await m.answer(
        f"{TXT[lang]['form_title']} (11/11)\n\n{TXT[lang]['step11']}",
        reply_markup=k_discipline(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.discipline)

# ===== 11/11 Discipline =====
@dp.callback_query(F.data.startswith("disc:"))
async def cb_disc(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.discipline.state:
        await cq.answer()
        return
    data = await state.get_data()
    lang = get_lang(data)

    val = cq.data.split(":", 1)[1]
    confirmed = (val == "yes")

    # сохраняем для превью (на языке игрока)
    if lang == "ru":
        disc_text = "подтверждена" if confirmed else "не подтверждена"
    elif lang == "ua":
        disc_text = "підтверджено" if confirmed else "не підтверджено"
    else:
        disc_text = "confirmed" if confirmed else "not confirmed"

    await state.update_data(discipline=disc_text, discipline_ok=confirmed)

    # если дисциплина НЕ подтверждена — отправляем админу сразу (на русском), игроку — отказ (на его языке)
    if not confirmed:
        await send_admin_application_ru(cq.from_user, await state.get_data(), forced_discipline_ok=False)
        await state.clear()
        await state.update_data(lang=lang)
        await cq.message.edit_text(TXT[lang]["disc_decline_user"], reply_markup=k_start(lang), parse_mode="HTML")
        await cq.answer()
        return

    # иначе — показываем превью
    data2 = await state.get_data()
    await cq.message.edit_text(fmt_preview(lang, data2), reply_markup=k_confirm(lang), parse_mode="HTML")
    await state.set_state(Form.confirm)
    await cq.answer()

# ===== Confirm send =====
@dp.callback_query(F.data == "confirm_send")
async def cb_confirm_send(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.confirm.state:
        await cq.answer()
        return

    data = await state.get_data()
    lang = get_lang(data)

    # cooldown
    now = datetime.now(timezone.utc)
    prev = last_submit.get(cq.from_user.id)
    if prev and now - prev < timedelta(hours=COOLDOWN_HOURS):
        await cq.answer(TXT[lang]["cooldown"], show_alert=True)
        return

    # дисциплина ок — отправляем админу (всегда RU)
    await send_admin_application_ru(cq.from_user, data, forced_discipline_ok=True)

    last_submit[cq.from_user.id] = now
    await state.clear()
    await state.update_data(lang=lang)

    await cq.message.edit_text(TXT[lang]["sent"], reply_markup=k_start(lang), parse_mode="HTML")
    await cq.answer("Отправлено" if lang == "ru" else ("Відправлено" if lang == "ua" else "Sent"))

@dp.message(Form.confirm)
async def in_confirm_state(m: Message, state: FSMContext):
    if not await guard_private_message(m):
        return
    data = await state.get_data()
    lang = get_lang(data)
    await m.answer(TXT[lang]["confirm_hint"], reply_markup=k_confirm(lang), parse_mode="HTML")

# ===== Admin message (ALWAYS RUSSIAN) =====
async def send_admin_application_ru(user, data: dict, forced_discipline_ok: bool):
    """
    ВАЖНО: админское сообщение ВСЕГДА на русском.
    Язык игрока показываем отдельным полем.
    """
    now = datetime.now(timezone.utc)
    tz3 = timezone(timedelta(hours=3))
    ts = now.astimezone(tz3).strftime("%Y-%m-%d %H:%M")

    lang = get_lang(data)
    lang_label = {"ru": "RU (Русский)", "ua": "UA (Українська)", "en": "EN (English)"}.get(lang, "RU (Русский)")

    discipline_ok = bool(forced_discipline_ok)
    disc_icon = "✅" if discipline_ok else "❌"
    disc_text = "подтверждена" if discipline_ok else "НЕ подтверждена"

    tg_username = f"@{user.username}" if getattr(user, "username", None) else "—"

    msg = (
        "🧾 <b>Новая заявка (SOBRANIEGOLD)</b>\n\n"
        f"👤 Игрок: <b>{user.full_name}</b>\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📎 TG username: <b>{tg_username}</b>\n"
        f"🌍 Язык анкеты: <b>{lang_label}</b>\n\n"
        f"{disc_icon} Дисциплина: <b>{disc_text}</b>\n\n"
        f"1) Ник: <b>{data.get('nick','-')}</b>\n"
        f"2) Контакт TG (из анкеты): <b>{data.get('contact','-')}</b>\n"
        f"3) Страна/город: <b>{data.get('country','-')}</b>\n"
        f"4) Профа/Саб: <b>{data.get('prof','-')}</b>\n"
        f"5) Уровень: <b>{data.get('lvl','-')}</b>\n"
        f"6) Нобл: <b>{data.get('noble','-')}</b>\n"
        f"7) Прайм: <b>{data.get('prime','-')}</b>\n"
        f"8) Микрофон: <b>{data.get('mic','-')}</b>\n"
        f"9) Готовность: <b>{data.get('ready','-')}</b>\n"
        f"10) Почему наш клан: <b>{data.get('why','-')}</b>\n\n"
        f"⏱ {ts} (UTC+3)"
    )

    await bot.send_message(
        ADMIN_CHAT_ID,
        msg,
        parse_mode="HTML",
        reply_markup=k_admin_contact(user.id),
    )

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
