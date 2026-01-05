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

T = {
    "ru": {
        "lang_pick": "🌍 Выбери язык / Choose language / Оберіть мову:",
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

        "form_title": "🧾 <b>Анкета</b>",
        "q_nick": "⚔️ (1/11)\n\nВведи <b>ник в игре</b>:",
        "q_contact": (
            "📩 (2/11)\n\nУкажи <b>контакт в Telegram</b>:\n"
            "• @username\n\n"
            "Если нет username — напиши <b>нет</b> или контакт для связи."
        ),
        "use_my_tg": "✅ Использовать мой Telegram",
        "q_country": "🌍 (3/11)\n\nУкажи <b>страна / город</b> (кратко):",
        "q_prof": "🧙‍♂️ (4/11)\n\nУкажи <b>профу / саб</b> (коротко):\n<i>Пример: Necromancer / Bishop</i>",
        "q_lvl": "🧠 (5/11)\n\nУкажи <b>уровень</b> (числом):",
        "q_noble": "🪽 (6/11)\n\nНобл есть?",
        "q_prime": "⏰ (7/11)\n\nУкажи <b>прайм</b> (дни + время):\n<i>Пример: Пн–Пт 20:00–00:00, сб/вс больше</i>",
        "q_mic": "🎙 (8/11)\n\nЕсть <b>микрофон</b> и готов слушать колл (TS/Discord)?",
        "q_ready": "🛡 (9/11)\n\nГотовность к <b>прайму/явке</b>:",
        "q_why": "⭐ (10/11)\n\nПочему ты хочешь вступить именно в <b>SOBRANIEGOLD</b>?\n<i>1–2 предложения</i>",
        "q_discipline": "📜 (11/11)\n\nГотов соблюдать правила клана и решения КЛа/ПЛа?",

        "btn_yes": "✅ Да",
        "btn_no": "❌ Нет",
        "btn_progress": "⏳ В процессе",

        "btn_mic_yes": "🎙 Да",
        "btn_mic_no": "🔇 Нет",

        "btn_ready_yes": "✅ Готов стабильно",
        "btn_ready_sometimes": "⚠️ Не всегда",
        "btn_ready_no": "❌ Не готов",

        "preview_title": "🧾 <b>Проверь заявку</b>",
        "preview_hint": "Если всё верно — нажми <b>«Отправить»</b>.",
        "sent_ok": "✅ <b>Анкета принята</b>\n\nРассмотрение занимает до 24 часов.\nОтвет поступит в Telegram при положительном решении.",

        "only_private": "Подача заявки доступна только в личных сообщениях.",
        "invalid_nick": "⚠️ Ник без ссылок и @. Повтори:",
        "invalid_no_links": "⚠️ Без ссылок и @. Повтори:",
        "lvl_number": "⚠️ Уровень должен быть числом. Например: <b>78</b>",
        "lvl_range": "⚠️ Укажи уровень от 1 до 99.",
        "need_contact": "⚠️ Введи контакт или напиши <b>нет</b>.",
        "cooldown": "Повторная заявка доступна через 12 часов.",
        "choose_buttons": "Выбери действие кнопками ниже:",
        "discipline_no_user": "❌ Заявка отклонена: дисциплина не подтверждена.",

        "label_nick": "Ник",
        "label_contact": "Контакт TG",
        "label_country": "Страна/город",
        "label_prof": "Профа/саб",
        "label_lvl": "Уровень",
        "label_noble": "Нобл",
        "label_prime": "Прайм",
        "label_mic": "Микрофон/TS",
        "label_ready": "Готовность",
        "label_why": "Почему к нам",
        "label_disc": "Дисциплина",
    },

    "uk": {
        "lang_pick": "🌍 Обери мову / Choose language / Выбери язык:",
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

        "form_title": "🧾 <b>Анкета</b>",
        "q_nick": "⚔️ (1/11)\n\nВведи <b>нік у грі</b>:",
        "q_contact": (
            "📩 (2/11)\n\nВкажи <b>контакт у Telegram</b>:\n"
            "• @username\n\n"
            "Якщо немає username — напиши <b>нема</b> або контакт для зв’язку."
        ),
        "use_my_tg": "✅ Використати мій Telegram",
        "q_country": "🌍 (3/11)\n\nВкажи <b>країна / місто</b> (коротко):",
        "q_prof": "🧙‍♂️ (4/11)\n\nВкажи <b>профу / саб</b>:\n<i>Приклад: Necromancer / Bishop</i>",
        "q_lvl": "🧠 (5/11)\n\nВкажи <b>рівень</b> (числом):",
        "q_noble": "🪽 (6/11)\n\nЄ нобл?",
        "q_prime": "⏰ (7/11)\n\nВкажи <b>прайм</b> (дні + час):\n<i>Приклад: Пн–Пт 20:00–00:00, сб/нд більше</i>",
        "q_mic": "🎙 (8/11)\n\nЄ <b>мікрофон</b> і готовий слухати колл (TS/Discord)?",
        "q_ready": "🛡 (9/11)\n\nГотовність до <b>прайму/явки</b>:",
        "q_why": "⭐ (10/11)\n\nЧому ти хочеш саме в <b>SOBRANIEGOLD</b>?\n<i>1–2 речення</i>",
        "q_discipline": "📜 (11/11)\n\nГотовий дотримуватись правил клану та рішень КЛ/ПЛ?",

        "btn_yes": "✅ Так",
        "btn_no": "❌ Ні",
        "btn_progress": "⏳ В процесі",

        "btn_mic_yes": "🎙 Так",
        "btn_mic_no": "🔇 Ні",

        "btn_ready_yes": "✅ Готовий стабільно",
        "btn_ready_sometimes": "⚠️ Не завжди",
        "btn_ready_no": "❌ Не готовий",

        "preview_title": "🧾 <b>Перевір заявку</b>",
        "preview_hint": "Якщо все вірно — натисни <b>«Надіслати»</b>.",
        "sent_ok": "✅ <b>Анкету прийнято</b>\n\nРозгляд до 24 годин.\nВідповідь прийде в Telegram при позитивному рішенні.",

        "only_private": "Заявка доступна лише в приватних повідомленнях.",
        "invalid_nick": "⚠️ Нік без посилань і @. Повтори:",
        "invalid_no_links": "⚠️ Без посилань і @. Повтори:",
        "lvl_number": "⚠️ Рівень має бути числом. Наприклад: <b>78</b>",
        "lvl_range": "⚠️ Вкажи рівень від 1 до 99.",
        "need_contact": "⚠️ Введи контакт або напиши <b>нема</b>.",
        "cooldown": "Повторна заявка доступна через 12 годин.",
        "choose_buttons": "Обери дію кнопками нижче:",
        "discipline_no_user": "❌ Заявку відхилено: дисципліну не підтверджено.",

        "label_nick": "Нік",
        "label_contact": "Контакт TG",
        "label_country": "Країна/місто",
        "label_prof": "Профа/саб",
        "label_lvl": "Рівень",
        "label_noble": "Нобл",
        "label_prime": "Прайм",
        "label_mic": "Мікрофон/TS",
        "label_ready": "Готовність",
        "label_why": "Чому до нас",
        "label_disc": "Дисципліна",
    },

    "en": {
        "lang_pick": "🌍 Choose language / Выбери язык / Оберіть мову:",
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

        "form_title": "🧾 <b>Application</b>",
        "q_nick": "⚔️ (1/11)\n\nEnter your <b>in-game nickname</b>:",
        "q_contact": (
            "📩 (2/11)\n\nEnter your <b>Telegram contact</b>:\n"
            "• @username\n\n"
            "If you don’t have one — type <b>none</b> or another contact."
        ),
        "use_my_tg": "✅ Use my Telegram",
        "q_country": "🌍 (3/11)\n\nCountry / City (short):",
        "q_prof": "🧙‍♂️ (4/11)\n\nClass / Sub (short):\n<i>Example: Necromancer / Bishop</i>",
        "q_lvl": "🧠 (5/11)\n\nLevel (number):",
        "q_noble": "🪽 (6/11)\n\nDo you have Noble?",
        "q_prime": "⏰ (7/11)\n\nPrime time (days + time):\n<i>Example: Mon–Fri 20:00–00:00, weekends more</i>",
        "q_mic": "🎙 (8/11)\n\nDo you have a mic and can follow voice calls (TS/Discord)?",
        "q_ready": "🛡 (9/11)\n\nAttendance / prime readiness:",
        "q_why": "⭐ (10/11)\n\nWhy do you want to join <b>SOBRANIEGOLD</b>?\n<i>1–2 sentences</i>",
        "q_discipline": "📜 (11/11)\n\nWill you follow clan rules and CL/PL decisions?",

        "btn_yes": "✅ Yes",
        "btn_no": "❌ No",
        "btn_progress": "⏳ In progress",

        "btn_mic_yes": "🎙 Yes",
        "btn_mic_no": "🔇 No",

        "btn_ready_yes": "✅ Ready",
        "btn_ready_sometimes": "⚠️ Sometimes",
        "btn_ready_no": "❌ Not ready",

        "preview_title": "🧾 <b>Review your application</b>",
        "preview_hint": "If everything is correct — tap <b>“Submit”</b>.",
        "sent_ok": "✅ <b>Application received</b>\n\nReview takes up to 24 hours.\nYou will get a reply if approved.",

        "only_private": "Please apply in a private chat with the bot.",
        "invalid_nick": "⚠️ No links and no @. Try again:",
        "invalid_no_links": "⚠️ No links and no @. Try again:",
        "lvl_number": "⚠️ Level must be a number. Example: <b>78</b>",
        "lvl_range": "⚠️ Level must be between 1 and 99.",
        "need_contact": "⚠️ Enter a contact or type <b>none</b>.",
        "cooldown": "You can reapply in 12 hours.",
        "choose_buttons": "Use the buttons below:",
        "discipline_no_user": "❌ Rejected: discipline not confirmed.",

        "label_nick": "Nick",
        "label_contact": "TG contact",
        "label_country": "Country/City",
        "label_prof": "Class/Sub",
        "label_lvl": "Level",
        "label_noble": "Noble",
        "label_prime": "Prime",
        "label_mic": "Mic/TS",
        "label_ready": "Readiness",
        "label_why": "Why us",
        "label_disc": "Discipline",
    },
}


def get_lang_from_state(data: dict) -> str:
    lang = (data or {}).get("lang", "ru")
    return lang if lang in SUPPORTED_LANGS else "ru"


def build_welcome(lang: str) -> str:
    return f"{T[lang]['welcome_title']}\n\n{T[lang]['welcome_body']}"


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
    kb.button(text=T[lang]["btn_yes"], callback_data="noble:yes")
    kb.button(text=T[lang]["btn_no"], callback_data="noble:no")
    kb.button(text=T[lang]["btn_progress"], callback_data="noble:progress")
    kb.adjust(2, 1)
    return kb.as_markup()


def k_mic(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=T[lang]["btn_mic_yes"], callback_data="mic:yes")
    kb.button(text=T[lang]["btn_mic_no"], callback_data="mic:no")
    kb.adjust(2)
    return kb.as_markup()


def k_ready(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=T[lang]["btn_ready_yes"], callback_data="ready:yes")
    kb.button(text=T[lang]["btn_ready_sometimes"], callback_data="ready:sometimes")
    kb.button(text=T[lang]["btn_ready_no"], callback_data="ready:no")
    kb.adjust(1)
    return kb.as_markup()


def k_discipline(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=T[lang]["btn_yes"], callback_data="disc:yes")
    kb.button(text=T[lang]["btn_no"], callback_data="disc:no")
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


def human_noble(lang: str, v: str) -> str:
    if v == "yes":
        return "да" if lang == "ru" else ("так" if lang == "uk" else "yes")
    if v == "no":
        return "нет" if lang == "ru" else ("ні" if lang == "uk" else "no")
    if v == "progress":
        return "в процессе" if lang == "ru" else ("в процесі" if lang == "uk" else "in progress")
    return "-"


def human_yesno(lang: str, v: str) -> str:
    if v == "yes":
        return "да" if lang == "ru" else ("так" if lang == "uk" else "yes")
    if v == "no":
        return "нет" if lang == "ru" else ("ні" if lang == "uk" else "no")
    return "-"


def human_ready(lang: str, v: str) -> str:
    if v == "yes":
        return "готов стабильно" if lang == "ru" else ("готовий стабільно" if lang == "uk" else "ready")
    if v == "sometimes":
        return "не всегда" if lang == "ru" else ("не завжди" if lang == "uk" else "sometimes")
    if v == "no":
        return "не готов" if lang == "ru" else ("не готовий" if lang == "uk" else "not ready")
    return "-"


def fmt_preview(lang: str, data: dict) -> str:
    disc_ok = data.get("disc_raw") == "yes"
    disc_icon = "✅" if disc_ok else "⚠️"

    return (
        f"{T[lang]['preview_title']}\n\n"
        f"⚔️ {T[lang]['label_nick']}: <b>{data.get('nick','-')}</b>\n"
        f"📩 {T[lang]['label_contact']}: <b>{data.get('contact','-')}</b>\n"
        f"🌍 {T[lang]['label_country']}: <b>{data.get('country','-')}</b>\n"
        f"🧙‍♂️ {T[lang]['label_prof']}: <b>{data.get('prof','-')}</b>\n"
        f"🧠 {T[lang]['label_lvl']}: <b>{data.get('lvl','-')}</b>\n"
        f"🪽 {T[lang]['label_noble']}: <b>{human_noble(lang, data.get('noble_raw','-'))}</b>\n"
        f"⏰ {T[lang]['label_prime']}: <b>{data.get('prime','-')}</b>\n"
        f"🎙 {T[lang]['label_mic']}: <b>{human_yesno(lang, data.get('mic_raw','-'))}</b>\n"
        f"🛡 {T[lang]['label_ready']}: <b>{human_ready(lang, data.get('ready_raw','-'))}</b>\n"
        f"⭐ {T[lang]['label_why']}: <b>{data.get('why','-')}</b>\n"
        f"📜 {T[lang]['label_disc']}: <b>{disc_icon}</b>\n\n"
        f"{T[lang]['preview_hint']}"
    )


async def guard_private_message(m: Message, lang: str) -> bool:
    if m.chat.type != "private":
        await m.answer(T[lang]["only_private"])
        return False
    return True


class Form(StatesGroup):
    nick = State()
    contact = State()
    country = State()
    prof = State()
    lvl = State()
    noble = State()
    prime = State()
    mic = State()
    ready = State()
    why = State()
    discipline = State()
    confirm = State()


# ===== START =====
@dp.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(T["ru"]["lang_pick"], reply_markup=k_lang(), parse_mode="HTML")


@dp.callback_query(F.data.startswith("lang:"))
async def cb_lang(cq: CallbackQuery, state: FSMContext):
    code = cq.data.split(":", 1)[1]
    if code not in SUPPORTED_LANGS:
        code = "ru"
    await state.set_data({"lang": code})
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
    await state.clear()
    await cq.message.edit_text(T["ru"]["lang_pick"], reply_markup=k_lang(), parse_mode="HTML")
    await cq.answer()


@dp.callback_query(F.data == "restart")
async def cb_restart(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
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
    await state.set_data({"lang": lang})
    await cq.message.edit_text(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_nick']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await cq.answer()


# ===== 1/11 Nick =====
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


# ===== 2/11 Contact =====
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


# ===== 3/11 Country =====
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


# ===== 4/11 Prof =====
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


# ===== 5/11 Level =====
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


# ===== 6/11 Noble (buttons) =====
@dp.callback_query(F.data.startswith("noble:"))
async def cb_noble(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if await state.get_state() != Form.noble.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    if val not in {"yes", "no", "progress"}:
        val = "no"

    await state.update_data(noble_raw=val)

    await cq.message.edit_text(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_prime']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.prime)
    await cq.answer()


# ===== 7/11 Prime =====
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


# ===== 8/11 Mic (buttons) =====
@dp.callback_query(F.data.startswith("mic:"))
async def cb_mic(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if await state.get_state() != Form.mic.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    if val not in {"yes", "no"}:
        val = "no"
    await state.update_data(mic_raw=val)

    await cq.message.edit_text(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_ready']}",
        reply_markup=k_ready(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.ready)
    await cq.answer()


# ===== 9/11 Ready (buttons) =====
@dp.callback_query(F.data.startswith("ready:"))
async def cb_ready(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if await state.get_state() != Form.ready.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    if val not in {"yes", "sometimes", "no"}:
        val = "no"
    await state.update_data(ready_raw=val)

    await cq.message.edit_text(
        f"{T[lang]['form_title']}\n\n{T[lang]['q_why']}",
        reply_markup=k_cancel(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.why)
    await cq.answer()


# ===== 10/11 Why =====
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


# ===== 11/11 Discipline (buttons) =====
@dp.callback_query(F.data.startswith("disc:"))
async def cb_disc(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if await state.get_state() != Form.discipline.state:
        await cq.answer()
        return

    val = cq.data.split(":", 1)[1]
    if val not in {"yes", "no"}:
        val = "no"

    await state.update_data(disc_raw=val)

    # If discipline YES -> go to confirm
    if val == "yes":
        data2 = await state.get_data()
        await cq.message.edit_text(fmt_preview(lang, data2), reply_markup=k_confirm(lang), parse_mode="HTML")
        await state.set_state(Form.confirm)
        await cq.answer("OK")
        return

    # If discipline NO -> send to admin as warning and stop
    data2 = await state.get_data()
    user = cq.from_user

    admin_msg = (
        "🧾 <b>Новая заявка (дисциплина НЕ подтверждена)</b>\n"
        f"🌍 Lang: <b>{lang.upper()}</b>\n"
        f"👤 TG: {user.full_name} (id: <code>{user.id}</code>)\n"
        f"📩 Contact: <b>{data2.get('contact','-')}</b>\n\n"
        f"⚔️ Nick: <b>{data2.get('nick','-')}</b>\n"
        f"🌍 Country/City: <b>{data2.get('country','-')}</b>\n"
        f"🧙‍♂️ Class/Sub: <b>{data2.get('prof','-')}</b>\n"
        f"🧠 Level: <b>{data2.get('lvl','-')}</b>\n"
        f"🪽 Noble: <b>{human_noble(lang, data2.get('noble_raw','-'))}</b>\n"
        f"⏰ Prime: <b>{data2.get('prime','-')}</b>\n"
        f"🎙 Mic: <b>{human_yesno(lang, data2.get('mic_raw','-'))}</b>\n"
        f"🛡 Ready: <b>{human_ready(lang, data2.get('ready_raw','-'))}</b>\n"
        f"⭐ Why: <b>{data2.get('why','-')}</b>\n"
        f"📜 Discipline: <b>⚠️</b>\n"
    )

    await bot.send_message(ADMIN_CHAT_ID, admin_msg, parse_mode="HTML", reply_markup=k_admin_contact(user.id))
    await state.clear()
    await cq.message.edit_text(T[lang]["discipline_no_user"], parse_mode="HTML")
    await cq.answer()


# ===== Confirm send =====
@dp.callback_query(F.data == "confirm_send")
async def cb_confirm_send(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = get_lang_from_state(data)
    if await state.get_state() != Form.confirm.state:
        await cq.answer()
        return

    now = datetime.now(timezone.utc)
    prev = last_submit.get(cq.from_user.id)
    if prev and now - prev < timedelta(hours=COOLDOWN_HOURS):
        await cq.answer(T[lang]["cooldown"], show_alert=True)
        return

    user = cq.from_user
    data2 = await state.get_data()

    disc_ok = data2.get("disc_raw") == "yes"

    admin_msg = (
        "🧾 <b>Новая заявка</b>\n"
        f"🌍 Lang: <b>{lang.upper()}</b>\n"
        f"👤 TG: {user.full_name} (id: <code>{user.id}</code>)\n"
        f"📩 Contact: <b>{data2.get('contact','-')}</b>\n\n"
        f"⚔️ Nick: <b>{data2.get('nick','-')}</b>\n"
        f"🌍 Country/City: <b>{data2.get('country','-')}</b>\n"
        f"🧙‍♂️ Class/Sub: <b>{data2.get('prof','-')}</b>\n"
        f"🧠 Level: <b>{data2.get('lvl','-')}</b>\n"
        f"🪽 Noble: <b>{human_noble(lang, data2.get('noble_raw','-'))}</b>\n"
        f"⏰ Prime: <b>{data2.get('prime','-')}</b>\n"
        f"🎙 Mic: <b>{human_yesno(lang, data2.get('mic_raw','-'))}</b>\n"
        f"🛡 Ready: <b>{human_ready(lang, data2.get('ready_raw','-'))}</b>\n"
        f"⭐ Why: <b>{data2.get('why','-')}</b>\n"
        f"📜 Discipline: <b>{'✅' if disc_ok else '⚠️'}</b>\n"
        f"⏱ {now.astimezone(timezone(timedelta(hours=3))).strftime('%Y-%m-%d %H:%M')} (UTC+3)"
    )

    await bot.send_message(ADMIN_CHAT_ID, admin_msg, parse_mode="HTML", reply_markup=k_admin_contact(user.id))

    last_submit[user.id] = now
    await state.clear()

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
