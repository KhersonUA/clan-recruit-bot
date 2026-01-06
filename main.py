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
from aiogram.exceptions import TelegramBadRequest

from fastapi import FastAPI, Request
from fastapi.responses import Response

# ===================== ENV =====================
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

# ===================== Anti-spam =====================
last_submit: dict[int, datetime] = {}
LINK_RE = re.compile(r"(https?://|t\.me/|www\.)", re.IGNORECASE)
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
    return (raw or "").strip()[:64]

async def safe_cq_answer(cq: CallbackQuery, text: str | None = None, **kwargs):
    """
    Telegram может вернуть BadRequest если callback query устарел/уже отвечен.
    Никогда не падаем из-за cq.answer().
    """
    try:
        if text is None:
            await cq.answer(**kwargs)
        else:
            await cq.answer(text, **kwargs)
    except TelegramBadRequest:
        pass

# ===================== i18n =====================
SUPPORTED_LANGS = ("ru", "ua", "en")

TXT = {
    "ru": {
        "choose_lang": "🌍 Выбери язык:",
        "welcome": (
            "👑 <b>SOBRANIEGOLD — официальный набор</b>\n\n"
            "Анкеты рассматриваются нашей командой.\n"
            "Заполнение анкеты — обязательное условие.\n\n"
            "Нажми <b>«Подать заявку»</b> и заполни анкету.\n"
            "⚠️ В анкете <b>без ссылок</b> и <b>@</b> (кроме поля «Контакт TG»)."
        ),
        "btn_apply": "📝 Подать заявку",
        "btn_info": "ℹ️ Инфо/Требования",
        "info": (
            "ℹ️ <b>Инфо</b>\n\n"
            "Заполни анкету — офицеры рассмотрят её.\n"
            "При положительном решении с тобой свяжутся в Telegram.\n\n"
            "Нажми <b>«Подать заявку»</b>, чтобы начать."
        ),
        "cancel": "❌ Отмена",
        "back": "⬅️ Назад",
        "cancelled": "Ок, отменил. Если захочешь — подай заявку заново.",
        "restart": "🔄 Заполнить заново",
        "send": "✅ Отправить",

        "form": "📝 <b>Анкета</b>",

        # 1/12
        "step1": "👤 Введи <b>ник в игре</b>:",
        "step1_bad": "⚠️ Ник без ссылок и @. Повтори:",

        # 2/12
        "step2": "🧾 Укажи <b>настоящее имя</b>:",
        "step2_bad": "⚠️ Имя без ссылок и @. Повтори:",

        # 3/12
        "step3": (
            "📱 Укажи <b>контакт в Telegram</b>:\n"
            "• @username\n\n"
            "Если нет username — напиши <b>нет</b> или укажи способ связи."
        ),
        "use_my_tg": "👤 Использовать мой Telegram",
        "step3_empty": "⚠️ Введи контакт или напиши <b>нет</b>.",
        "no_username_alert": "У тебя нет @username в Telegram.",

        # 4/12
        "step4": "🌍 Укажи <b>страна / город</b> (коротко):",
        "step4_bad": "⚠️ Без ссылок и @. Напиши страна/город:",

        # 5/12
        "step5": (
            "🧙‍♂️ Укажи <b>профу / саб</b> (коротко):\n"
            "<i>Пример: Necromancer / Bishop</i>"
        ),
        "step5_bad": "⚠️ Без ссылок и @. Повтори профу/саб:",

        # 6/12
        "step6": "⭐ Твой <b>LVL</b> в игре? (числом):",
        "step6_nan": "⚠️ LVL должен быть числом. Например: <b>78</b>",
        "step6_range": "⚠️ Укажи LVL от 1 до 99.",

        # 7/12
        "step7": "👑 Нобл есть?",
        "noble_yes": "✅ Да",
        "noble_no": "❌ Нет",
        "noble_progress": "⏳ В процессе",

        # 8/12
        "step8": (
            "⏰ Укажи <b>прайм</b> (дни + время):\n"
            "<i>Пример: Пн–Пт 20:00–00:00, сб/вс больше</i>"
        ),
        "step8_bad": "⚠️ Без ссылок и @. Укажи прайм текстом:",

        # 9/12
        "step9": "🎙 Есть <b>микрофон</b> и готов слушать колл (TS/Discord)?",
        "mic_yes": "🎙 Да",
        "mic_no": "❌ Нет",

        # 10/12
        "step10": "📅 Готовность к <b>прайму/явке</b>:",
        "ready_yes": "✅ Готов стабильно",
        "ready_sometimes": "⚠️ Не всегда",
        "ready_no": "❌ Не готов",

        # 11/12
        "step11": "🏰 Почему ты хочешь вступить именно в <b>SOBRANIEGOLD</b>? (1–2 предложения)",
        "step11_bad": "⚠️ Без ссылок и @. Ответь 1–2 предложениями:",

        # 12/12
        "step12": "⚠️ Готов соблюдать <b>правила клана</b> и решения КЛа/ПЛа?",
        "disc_yes": "✅ Да",
        "disc_no": "❌ Нет",

        "preview_title": "🧾 <b>Проверь заявку</b>",
        "preview_submit": "Если всё верно — нажми <b>«Отправить»</b>.",
        "confirm_hint": "Выбери действие кнопками ниже:",

        "cooldown": f"Повторная заявка доступна через {COOLDOWN_HOURS} часов.",

        "sent": (
            "✅ <b>Анкета принята</b>\n\n"
            "Рассмотрение занимает до <b>24 часов</b>.\n"
            "Ответ поступит в Telegram при положительном решении."
        ),
        "disc_decline_user": (
            "❌ <b>Заявка не принята</b>\n\n"
            "Для вступления необходимо подтвердить готовность соблюдать правила клана."
        ),
        "private_only": "Подача заявки доступна только в личных сообщениях.",
        "lang_already": "Язык уже выбран.",
    },

    "ua": {
        "choose_lang": "🌍 Обери мову:",
        "welcome": (
            "👑 <b>SOBRANIEGOLD — офіційний набір</b>\n\n"
            "Анкети розглядаються нашою командою.\n"
            "Заповнення анкети — обов’язкова умова.\n\n"
            "Натисни <b>«Подати заявку»</b> та заповни анкету.\n"
            "⚠️ В анкеті <b>без посилань</b> і <b>@</b> (крім поля «Контакт TG»)."
        ),
        "btn_apply": "📝 Подати заявку",
        "btn_info": "ℹ️ Інфо/Вимоги",
        "info": (
            "ℹ️ <b>Інфо</b>\n\n"
            "Заповни анкету — офіцери її розглянуть.\n"
            "При позитивному рішенні з тобою зв’яжуться в Telegram.\n\n"
            "Натисни <b>«Подати заявку»</b>, щоб почати."
        ),
        "cancel": "❌ Скасувати",
        "back": "⬅️ Назад",
        "cancelled": "Ок, скасовано. Якщо захочеш — подай заявку знову.",
        "restart": "🔄 Заповнити знову",
        "send": "✅ Відправити",

        "form": "📝 <b>Анкета</b>",

        "step1": "👤 Введи <b>нік у грі</b>:",
        "step1_bad": "⚠️ Нік без посилань і @. Повтори:",

        "step2": "🧾 Вкажи <b>справжнє ім’я</b>:",
        "step2_bad": "⚠️ Ім’я без посилань і @. Повтори:",

        "step3": (
            "📱 Вкажи <b>контакт у Telegram</b>:\n"
            "• @username\n\n"
            "Якщо немає username — напиши <b>ні</b> або спосіб зв’язку."
        ),
        "use_my_tg": "👤 Використати мій Telegram",
        "step3_empty": "⚠️ Введи контакт або напиши <b>ні</b>.",
        "no_username_alert": "У тебе немає @username у Telegram.",

        "step4": "🌍 Вкажи <b>країна / місто</b> (коротко):",
        "step4_bad": "⚠️ Без посилань і @. Напиши країна/місто:",

        "step5": (
            "🧙‍♂️ Вкажи <b>профу / саб</b> (коротко):\n"
            "<i>Приклад: Necromancer / Bishop</i>"
        ),
        "step5_bad": "⚠️ Без посилань і @. Повтори профу/саб:",

        "step6": "⭐ Твій <b>LVL</b> у грі? (числом):",
        "step6_nan": "⚠️ LVL має бути числом. Наприклад: <b>78</b>",
        "step6_range": "⚠️ Вкажи LVL від 1 до 99.",

        "step7": "👑 Є нобл?",
        "noble_yes": "✅ Так",
        "noble_no": "❌ Ні",
        "noble_progress": "⏳ В процесі",

        "step8": (
            "⏰ Вкажи <b>прайм</b> (дні + час):\n"
            "<i>Приклад: Пн–Пт 20:00–00:00, сб/нд більше</i>"
        ),
        "step8_bad": "⚠️ Без посилань і @. Вкажи прайм текстом:",

        "step9": "🎙 Є <b>мікрофон</b> і готовий слухати колл (TS/Discord)?",
        "mic_yes": "🎙 Так",
        "mic_no": "❌ Ні",

        "step10": "📅 Готовність до <b>прайму/явки</b>:",
        "ready_yes": "✅ Готовий стабільно",
        "ready_sometimes": "⚠️ Не завжди",
        "ready_no": "❌ Не готовий",

        "step11": "🏰 Чому ти хочеш вступити саме в <b>SOBRANIEGOLD</b>? (1–2 речення)",
        "step11_bad": "⚠️ Без посилань і @. Відповідай 1–2 реченнями:",

        "step12": "⚠️ Готовий дотримуватись <b>правил клану</b> та рішень КЛа/ПЛа?",
        "disc_yes": "✅ Так",
        "disc_no": "❌ Ні",

        "preview_title": "🧾 <b>Перевір заявку</b>",
        "preview_submit": "Якщо все вірно — натисни <b>«Відправити»</b>.",
        "confirm_hint": "Обери дію кнопками нижче:",

        "cooldown": f"Повторна заявка буде доступна через {COOLDOWN_HOURS} год.",

        "sent": (
            "✅ <b>Анкета прийнята</b>\n\n"
            "Розгляд займає до <b>24 годин</b>.\n"
            "Відповідь прийде в Telegram при позитивному рішенні."
        ),
        "disc_decline_user": (
            "❌ <b>Заявка не прийнята</b>\n\n"
            "Для вступу потрібно підтвердити готовність дотримуватись правил клану."
        ),
        "private_only": "Подання заявки доступне лише в особистих повідомленнях.",
        "lang_already": "Мову вже обрано.",
    },

    "en": {
        "choose_lang": "🌍 Choose language:",
        "welcome": (
            "👑 <b>SOBRANIEGOLD — official recruitment</b>\n\n"
            "Applications are reviewed by our team.\n"
            "Filling the form is mandatory.\n\n"
            "Press <b>“Apply”</b> and complete the form.\n"
            "⚠️ No <b>links</b> and no <b>@</b> (except in “TG contact”)."
        ),
        "btn_apply": "📝 Apply",
        "btn_info": "ℹ️ Info/Requirements",
        "info": (
            "ℹ️ <b>Info</b>\n\n"
            "Fill the form — officers will review it.\n"
            "If approved, you will be contacted in Telegram.\n\n"
            "Press <b>“Apply”</b> to start."
        ),
        "cancel": "❌ Cancel",
        "back": "⬅️ Back",
        "cancelled": "Ok, cancelled. If you want — apply again.",
        "restart": "🔄 Fill again",
        "send": "✅ Send",

        "form": "📝 <b>Application</b>",

        "step1": "👤 Enter your <b>in-game nickname</b>:",
        "step1_bad": "⚠️ No links and no @. Try again:",

        "step2": "🧾 Enter your <b>real name</b>:",
        "step2_bad": "⚠️ No links and no @. Try again:",

        "step3": (
            "📱 Enter your <b>Telegram contact</b>:\n"
            "• @username\n\n"
            "If you don't have a username — type <b>no</b> or your contact method."
        ),
        "use_my_tg": "👤 Use my Telegram",
        "step3_empty": "⚠️ Enter contact or type <b>no</b>.",
        "no_username_alert": "You don't have a Telegram @username.",

        "step4": "🌍 Enter <b>country / city</b> (short):",
        "step4_bad": "⚠️ No links and no @. Enter country/city:",

        "step5": (
            "🧙‍♂️ Enter your <b>class / sub</b> (short):\n"
            "<i>Example: Necromancer / Bishop</i>"
        ),
        "step5_bad": "⚠️ No links and no @. Repeat class/sub:",

        "step6": "⭐ Your <b>LVL</b> in game? (number):",
        "step6_nan": "⚠️ LVL must be a number. Example: <b>78</b>",
        "step6_range": "⚠️ Enter a LVL between 1 and 99.",

        "step7": "👑 Do you have Noble?",
        "noble_yes": "✅ Yes",
        "noble_no": "❌ No",
        "noble_progress": "⏳ In progress",

        "step8": (
            "⏰ Enter your <b>prime time</b> (days + time):\n"
            "<i>Example: Mon–Fri 20:00–00:00, weekends more</i>"
        ),
        "step8_bad": "⚠️ No links and no @. Enter prime time:",

        "step9": "🎙 Do you have a <b>microphone</b> and can listen to calls (TS/Discord)?",
        "mic_yes": "🎙 Yes",
        "mic_no": "❌ No",

        "step10": "📅 Your <b>attendance readiness</b>:",
        "ready_yes": "✅ Stable",
        "ready_sometimes": "⚠️ Sometimes",
        "ready_no": "❌ Not ready",

        "step11": "🏰 Why do you want to join <b>SOBRANIEGOLD</b>? (1–2 sentences)",
        "step11_bad": "⚠️ No links and no @. Answer in 1–2 sentences:",

        "step12": "⚠️ Are you ready to follow <b>clan rules</b> and CL/PL decisions?",
        "disc_yes": "✅ Yes",
        "disc_no": "❌ No",

        "preview_title": "🧾 <b>Check your form</b>",
        "preview_submit": "If everything is correct — press <b>“Send”</b>.",
        "confirm_hint": "Use the buttons below:",

        "cooldown": f"You can re-apply after {COOLDOWN_HOURS} hours.",

        "sent": (
            "✅ <b>Application received</b>\n\n"
            "Review can take up to <b>24 hours</b>.\n"
            "You will be contacted in Telegram if approved."
        ),
        "disc_decline_user": (
            "❌ <b>Application declined</b>\n\n"
            "You must confirm readiness to follow clan rules."
        ),
        "private_only": "Application is available only in private messages.",
        "lang_already": "Language already selected.",
    },
}

def safe_lang(lang: str | None) -> str:
    return lang if lang in SUPPORTED_LANGS else "ru"

def get_selected_lang(data: dict) -> str | None:
    lang = data.get("lang")
    return lang if lang in SUPPORTED_LANGS else None

TOTAL_STEPS = 12

# ===================== Keyboards =====================
def k_lang():
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 RU Русский", callback_data="lang:ru")
    kb.button(text="🇺🇦 UA Українська", callback_data="lang:ua")
    kb.button(text="🇺🇸 EN English", callback_data="lang:en")
    kb.adjust(1)
    return kb.as_markup()

def k_start(lang: str):
    t = TXT[lang]
    kb = InlineKeyboardBuilder()
    kb.button(text=t["btn_apply"], callback_data="start_form")
    kb.button(text=t["btn_info"], callback_data="info")
    kb.adjust(1)
    return kb.as_markup()

def k_info(lang: str):
    t = TXT[lang]
    kb = InlineKeyboardBuilder()
    kb.button(text=t["btn_apply"], callback_data="start_form")
    kb.button(text=t["back"], callback_data="back")
    kb.adjust(1)
    return kb.as_markup()

def k_cancel_back(lang: str, with_back: bool = True):
    t = TXT[lang]
    kb = InlineKeyboardBuilder()
    if with_back:
        kb.button(text=t["back"], callback_data="back")
    kb.button(text=t["cancel"], callback_data="cancel")
    kb.adjust(2)
    return kb.as_markup()

def k_confirm(lang: str):
    t = TXT[lang]
    kb = InlineKeyboardBuilder()
    kb.button(text=t["send"], callback_data="confirm_send")
    kb.button(text=t["restart"], callback_data="restart")
    kb.button(text=t["back"], callback_data="back")
    kb.button(text=t["cancel"], callback_data="cancel")
    kb.adjust(1, 1, 2)
    return kb.as_markup()

def k_use_my_tg(lang: str):
    t = TXT[lang]
    kb = InlineKeyboardBuilder()
    kb.button(text=t["use_my_tg"], callback_data="use_my_tg")
    kb.button(text=t["back"], callback_data="back")
    kb.button(text=t["cancel"], callback_data="cancel")
    kb.adjust(1, 2)
    return kb.as_markup()

def k_noble(lang: str):
    t = TXT[lang]
    kb = InlineKeyboardBuilder()
    kb.button(text=t["noble_yes"], callback_data="noble:yes")
    kb.button(text=t["noble_no"], callback_data="noble:no")
    kb.button(text=t["noble_progress"], callback_data="noble:progress")
    kb.button(text=t["back"], callback_data="back")
    kb.button(text=t["cancel"], callback_data="cancel")
    kb.adjust(2, 1, 2)
    return kb.as_markup()

def k_mic(lang: str):
    t = TXT[lang]
    kb = InlineKeyboardBuilder()
    kb.button(text=t["mic_yes"], callback_data="mic:yes")
    kb.button(text=t["mic_no"], callback_data="mic:no")
    kb.button(text=t["back"], callback_data="back")
    kb.button(text=t["cancel"], callback_data="cancel")
    kb.adjust(2, 2)
    return kb.as_markup()

def k_ready(lang: str):
    t = TXT[lang]
    kb = InlineKeyboardBuilder()
    kb.button(text=t["ready_yes"], callback_data="ready:yes")
    kb.button(text=t["ready_sometimes"], callback_data="ready:sometimes")
    kb.button(text=t["ready_no"], callback_data="ready:no")
    kb.button(text=t["back"], callback_data="back")
    kb.button(text=t["cancel"], callback_data="cancel")
    kb.adjust(1, 2, 2)
    return kb.as_markup()

def k_discipline(lang: str):
    t = TXT[lang]
    kb = InlineKeyboardBuilder()
    kb.button(text=t["disc_yes"], callback_data="disc:yes")
    kb.button(text=t["disc_no"], callback_data="disc:no")
    kb.button(text=t["back"], callback_data="back")
    kb.button(text=t["cancel"], callback_data="cancel")
    kb.adjust(2, 2)
    return kb.as_markup()

def k_admin_contact(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Связаться с игроком", url=f"tg://user?id={user_id}")
    return kb.as_markup()

# ===================== FSM =====================
class Form(StatesGroup):
    lang = State()
    nick = State()
    real_name = State()
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

FORM_ORDER = [
    Form.nick,
    Form.real_name,
    Form.contact,
    Form.country,
    Form.prof,
    Form.lvl,
    Form.noble,
    Form.prime,
    Form.mic,
    Form.ready,
    Form.why,
    Form.discipline,
]
STATE_TO_STEP = {st.state: i + 1 for i, st in enumerate(FORM_ORDER)}

# ===================== Helpers =====================
async def guard_private_message(m: Message, lang: str) -> bool:
    if m.chat.type != "private":
        await m.answer(TXT[lang]["private_only"], parse_mode="HTML")
        return False
    return True

def fmt_preview(lang: str, data: dict) -> str:
    t = TXT[lang]
    label = {
        "ru": (
            "👤 Ник","🧾 Имя","📱 Контакт TG","🌍 Страна/город","🧙‍♂️ Профа/Саб","⭐ LVL",
            "👑 Нобл","⏰ Прайм","🎙 Микрофон","📅 Готовность","🏰 Почему клан","⚠️ Дисциплина",
        ),
        "ua": (
            "👤 Нік","🧾 Ім’я","📱 Контакт TG","🌍 Країна/місто","🧙‍♂️ Профа/Саб","⭐ LVL",
            "👑 Нобл","⏰ Прайм","🎙 Мікрофон","📅 Готовність","🏰 Чому клан","⚠️ Дисципліна",
        ),
        "en": (
            "👤 Nick","🧾 Name","📱 TG contact","🌍 Country/City","🧙‍♂️ Class/Sub","⭐ LVL",
            "👑 Noble","⏰ Prime time","🎙 Mic","📅 Readiness","🏰 Why clan","⚠️ Discipline",
        ),
    }[lang]

    return (
        f"{t['preview_title']}\n\n"
        f"1) {label[0]}: <b>{data.get('nick','-')}</b>\n"
        f"2) {label[1]}: <b>{data.get('real_name','-')}</b>\n"
        f"3) {label[2]}: <b>{data.get('contact','-')}</b>\n"
        f"4) {label[3]}: <b>{data.get('country','-')}</b>\n"
        f"5) {label[4]}: <b>{data.get('prof','-')}</b>\n"
        f"6) {label[5]}: <b>{data.get('lvl','-')}</b>\n"
        f"7) {label[6]}: <b>{data.get('noble','-')}</b>\n"
        f"8) {label[7]}: <b>{data.get('prime','-')}</b>\n"
        f"9) {label[8]}: <b>{data.get('mic','-')}</b>\n"
        f"10) {label[9]}: <b>{data.get('ready','-')}</b>\n"
        f"11) {label[10]}: <b>{data.get('why','-')}</b>\n"
        f"12) {label[11]}: <b>{data.get('discipline','-')}</b>\n\n"
        f"{t['preview_submit']}"
    )

def to_ru_value(field: str, value: str, user_lang: str) -> str:
    v = (value or "").strip().lower()
    ul = user_lang

    if field == "contact":
        if v in {"no", "none", "нет", "ні", "нема"}:
            return "нет"
        return value

    if field == "noble":
        maps = {
            "ru": {"да": "да", "нет": "нет", "в процессе": "в процессе"},
            "ua": {"так": "да", "ні": "нет", "в процесі": "в процессе"},
            "en": {"yes": "да", "no": "нет", "in progress": "в процессе"},
        }
        return maps.get(ul, {}).get(v, value)

    if field == "mic":
        maps = {
            "ru": {"да": "да", "нет": "нет"},
            "ua": {"так": "да", "ні": "нет"},
            "en": {"yes": "да", "no": "нет"},
        }
        return maps.get(ul, {}).get(v, value)

    if field == "ready":
        maps = {
            "ru": {"готов стабильно": "готов стабильно", "не всегда": "не всегда", "не готов": "не готов"},
            "ua": {"готовий стабільно": "готов стабильно", "не завжди": "не всегда", "не готовий": "не готов"},
            "en": {"stable": "готов стабильно", "sometimes": "не всегда", "not ready": "не готов"},
        }
        return maps.get(ul, {}).get(v, value)

    return value

async def send_admin_application_ru(user, data: dict, discipline_ok: bool):
    now = datetime.now(timezone.utc)
    tz3 = timezone(timedelta(hours=3))
    ts = now.astimezone(tz3).strftime("%Y-%m-%d %H:%M")

    user_lang = safe_lang(data.get("lang"))
    lang_label = {"ru": "RU (Русский)", "ua": "UA (Українська)", "en": "EN (English)"}[user_lang]

    disc_icon = "✅" if discipline_ok else "❌"
    disc_text = "подтверждена" if discipline_ok else "НЕ подтверждена"

    tg_username = f"@{user.username}" if getattr(user, "username", None) else "—"

    contact_ru = to_ru_value("contact", str(data.get("contact", "-")), user_lang)
    noble_ru = to_ru_value("noble", str(data.get("noble", "-")), user_lang)
    mic_ru = to_ru_value("mic", str(data.get("mic", "-")), user_lang)
    ready_ru = to_ru_value("ready", str(data.get("ready", "-")), user_lang)

    msg = (
        "🧾 <b>Новая заявка (SOBRANIEGOLD)</b>\n\n"
        f"👤 Игрок: <b>{user.full_name}</b>\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📎 TG username: <b>{tg_username}</b>\n"
        f"🌍 Язык анкеты: <b>{lang_label}</b>\n\n"
        f"{disc_icon} Дисциплина: <b>{disc_text}</b>\n\n"
        f"1) 👤 Ник: <b>{data.get('nick','-')}</b>\n"
        f"2) 🧾 Имя: <b>{data.get('real_name','-')}</b>\n"
        f"3) 📱 Контакт TG (из анкеты): <b>{contact_ru}</b>\n"
        f"4) 🌍 Страна/город: <b>{data.get('country','-')}</b>\n"
        f"5) 🧙‍♂️ Профа/Саб: <b>{data.get('prof','-')}</b>\n"
        f"6) ⭐ LVL: <b>{data.get('lvl','-')}</b>\n"
        f"7) 👑 Нобл: <b>{noble_ru}</b>\n"
        f"8) ⏰ Прайм: <b>{data.get('prime','-')}</b>\n"
        f"9) 🎙 Микрофон: <b>{mic_ru}</b>\n"
        f"10) 📅 Готовность: <b>{ready_ru}</b>\n"
        f"11) 🏰 Почему наш клан: <b>{data.get('why','-')}</b>\n\n"
        f"⏱ {ts} (UTC+3)"
    )

    await bot.send_message(
        ADMIN_CHAT_ID,
        msg,
        parse_mode="HTML",
        reply_markup=k_admin_contact(user.id),
    )

def build_step_text(lang: str, step_no: int, key: str) -> str:
    return f"{TXT[lang]['form']} ({step_no}/{TOTAL_STEPS})\n\n{TXT[lang][key]}"

async def show_step_by_state(cq_or_msg, state: FSMContext, lang: str, target_state: State, edit: bool):
    st = target_state.state
    step_no = STATE_TO_STEP.get(st, 1)

    if st == Form.nick.state:
        text = build_step_text(lang, step_no, "step1")
        kb = k_cancel_back(lang, with_back=True)
    elif st == Form.real_name.state:
        text = build_step_text(lang, step_no, "step2")
        kb = k_cancel_back(lang, with_back=True)
    elif st == Form.contact.state:
        has_username = bool(getattr(getattr(cq_or_msg, "from_user", None), "username", None))
        kb = k_use_my_tg(lang) if has_username else k_cancel_back(lang, with_back=True)
        text = build_step_text(lang, step_no, "step3")
    elif st == Form.country.state:
        text = build_step_text(lang, step_no, "step4")
        kb = k_cancel_back(lang, with_back=True)
    elif st == Form.prof.state:
        text = build_step_text(lang, step_no, "step5")
        kb = k_cancel_back(lang, with_back=True)
    elif st == Form.lvl.state:
        text = build_step_text(lang, step_no, "step6")
        kb = k_cancel_back(lang, with_back=True)
    elif st == Form.noble.state:
        text = build_step_text(lang, step_no, "step7")
        kb = k_noble(lang)
    elif st == Form.prime.state:
        text = build_step_text(lang, step_no, "step8")
        kb = k_cancel_back(lang, with_back=True)
    elif st == Form.mic.state:
        text = build_step_text(lang, step_no, "step9")
        kb = k_mic(lang)
    elif st == Form.ready.state:
        text = build_step_text(lang, step_no, "step10")
        kb = k_ready(lang)
    elif st == Form.why.state:
        text = build_step_text(lang, step_no, "step11")
        kb = k_cancel_back(lang, with_back=True)
    elif st == Form.discipline.state:
        text = build_step_text(lang, step_no, "step12")
        kb = k_discipline(lang)
    else:
        text = TXT[lang]["welcome"]
        kb = k_start(lang)

    await state.set_state(target_state)

    if isinstance(cq_or_msg, CallbackQuery):
        if edit:
            await cq_or_msg.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        else:
            await cq_or_msg.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await cq_or_msg.answer(text, reply_markup=kb, parse_mode="HTML")

# ===================== /start =====================
@dp.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Form.lang)
    await m.answer(TXT["ru"]["choose_lang"], reply_markup=k_lang(), parse_mode="HTML")

# ===================== Language select =====================
@dp.callback_query(F.data.startswith("lang:"))
async def cb_lang(cq: CallbackQuery, state: FSMContext):
    lang = safe_lang(cq.data.split(":", 1)[1])

    data = await state.get_data()
    selected = get_selected_lang(data)

    if selected == lang:
        await safe_cq_answer(cq, TXT[lang]["lang_already"])
        return

    await state.update_data(lang=lang)

    try:
        await cq.message.edit_text(TXT[lang]["welcome"], reply_markup=k_start(lang), parse_mode="HTML")
    except Exception:
        await cq.message.answer(TXT[lang]["welcome"], reply_markup=k_start(lang), parse_mode="HTML")

    await safe_cq_answer(cq)

# ===================== Back button =====================
@dp.callback_query(F.data == "back")
async def cb_back(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))
    cur = await state.get_state()

    if cur == Form.confirm.state:
        await show_step_by_state(cq, state, lang, Form.discipline, edit=True)
        await safe_cq_answer(cq)
        return

    if cur not in STATE_TO_STEP:
        await state.clear()
        await state.update_data(lang=lang)
        await cq.message.edit_text(TXT[lang]["welcome"], reply_markup=k_start(lang), parse_mode="HTML")
        await safe_cq_answer(cq)
        return

    cur_idx = STATE_TO_STEP[cur]
    if cur_idx <= 1:
        await state.clear()
        await state.update_data(lang=lang)
        await cq.message.edit_text(TXT[lang]["welcome"], reply_markup=k_start(lang), parse_mode="HTML")
        await safe_cq_answer(cq)
        return

    prev_state = FORM_ORDER[cur_idx - 2]
    await show_step_by_state(cq, state, lang, prev_state, edit=True)
    await safe_cq_answer(cq)

# ===================== Menu =====================
@dp.callback_query(F.data == "info")
async def cb_info(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))
    await cq.message.edit_text(TXT[lang]["info"], reply_markup=k_info(lang), parse_mode="HTML")
    await safe_cq_answer(cq)

@dp.callback_query(F.data == "start_form")
async def cb_start_form(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    await state.clear()
    await state.update_data(lang=lang)

    await cq.message.edit_text(
        build_step_text(lang, 1, "step1"),
        reply_markup=k_cancel_back(lang, with_back=True),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await safe_cq_answer(cq)

@dp.callback_query(F.data == "cancel")
async def cb_cancel(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    await state.clear()
    await state.update_data(lang=lang)

    await cq.message.edit_text(TXT[lang]["cancelled"], reply_markup=k_start(lang), parse_mode="HTML")
    await safe_cq_answer(cq)

@dp.callback_query(F.data == "restart")
async def cb_restart(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    await state.clear()
    await state.update_data(lang=lang)

    await cq.message.edit_text(
        build_step_text(lang, 1, "step1"),
        reply_markup=k_cancel_back(lang, with_back=True),
        parse_mode="HTML",
    )
    await state.set_state(Form.nick)
    await safe_cq_answer(cq)

# ===================== Step 1 Nick =====================
@dp.message(Form.nick)
async def step_nick(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    if not await guard_private_message(m, lang):
        return

    if bad_text_general(m.text):
        await m.answer(TXT[lang]["step1_bad"], reply_markup=k_cancel_back(lang, with_back=True), parse_mode="HTML")
        return

    await state.update_data(nick=m.text.strip()[:40])

    await m.answer(
        build_step_text(lang, 2, "step2"),
        reply_markup=k_cancel_back(lang, with_back=True),
        parse_mode="HTML",
    )
    await state.set_state(Form.real_name)

# ===================== Step 2 Real name =====================
@dp.message(Form.real_name)
async def step_real_name(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    if not await guard_private_message(m, lang):
        return

    if bad_text_general(m.text):
        await m.answer(TXT[lang]["step2_bad"], reply_markup=k_cancel_back(lang, with_back=True), parse_mode="HTML")
        return

    await state.update_data(real_name=m.text.strip()[:40])

    kb = k_cancel_back(lang, with_back=True)
    if m.from_user and m.from_user.username:
        kb = k_use_my_tg(lang)

    await m.answer(
        build_step_text(lang, 3, "step3"),
        reply_markup=kb,
        parse_mode="HTML",
    )
    await state.set_state(Form.contact)

@dp.callback_query(F.data == "use_my_tg")
async def cb_use_my_tg(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.contact.state:
        await safe_cq_answer(cq)
        return

    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    username = cq.from_user.username
    if not username:
        await safe_cq_answer(cq, TXT[lang]["no_username_alert"], show_alert=True)
        return

    await state.update_data(contact=f"@{username}")

    await cq.message.edit_text(
        build_step_text(lang, 4, "step4"),
        reply_markup=k_cancel_back(lang, with_back=True),
        parse_mode="HTML",
    )
    await state.set_state(Form.country)
    await safe_cq_answer(cq)

# ===================== Step 3 Contact =====================
@dp.message(Form.contact)
async def step_contact(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    if not await guard_private_message(m, lang):
        return

    t = (m.text or "").strip()
    if not t:
        await m.answer(TXT[lang]["step3_empty"], reply_markup=k_cancel_back(lang, with_back=True), parse_mode="HTML")
        return

    low = t.lower()
    if low in {"нет", "no", "none", "ні", "нема"}:
        contact = {"ru": "нет", "ua": "ні", "en": "no"}[lang]
    else:
        contact = normalize_contact(t)

    await state.update_data(contact=contact)

    await m.answer(
        build_step_text(lang, 4, "step4"),
        reply_markup=k_cancel_back(lang, with_back=True),
        parse_mode="HTML",
    )
    await state.set_state(Form.country)

# ===================== Step 4 Country =====================
@dp.message(Form.country)
async def step_country(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    if not await guard_private_message(m, lang):
        return

    if bad_text_general(m.text):
        await m.answer(TXT[lang]["step4_bad"], reply_markup=k_cancel_back(lang, with_back=True), parse_mode="HTML")
        return

    await state.update_data(country=m.text.strip()[:64])

    await m.answer(
        build_step_text(lang, 5, "step5"),
        reply_markup=k_cancel_back(lang, with_back=True),
        parse_mode="HTML",
    )
    await state.set_state(Form.prof)

# ===================== Step 5 Prof =====================
@dp.message(Form.prof)
async def step_prof(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    if not await guard_private_message(m, lang):
        return

    if bad_text_general(m.text):
        await m.answer(TXT[lang]["step5_bad"], reply_markup=k_cancel_back(lang, with_back=True), parse_mode="HTML")
        return

    await state.update_data(prof=m.text.strip()[:80])

    await m.answer(
        build_step_text(lang, 6, "step6"),
        reply_markup=k_cancel_back(lang, with_back=True),
        parse_mode="HTML",
    )
    await state.set_state(Form.lvl)

# ===================== Step 6 Level =====================
@dp.message(Form.lvl)
async def step_lvl(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    if not await guard_private_message(m, lang):
        return

    t = (m.text or "").strip()
    if not t.isdigit():
        await m.answer(TXT[lang]["step6_nan"], reply_markup=k_cancel_back(lang, with_back=True), parse_mode="HTML")
        return

    lvl_int = int(t)
    if lvl_int < 1 or lvl_int > 99:
        await m.answer(TXT[lang]["step6_range"], reply_markup=k_cancel_back(lang, with_back=True), parse_mode="HTML")
        return

    await state.update_data(lvl=lvl_int)

    await m.answer(
        build_step_text(lang, 7, "step7"),
        reply_markup=k_noble(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.noble)

# ===================== Step 7 Noble =====================
@dp.callback_query(F.data.startswith("noble:"))
async def cb_noble(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.noble.state:
        await safe_cq_answer(cq)
        return

    data = await state.get_data()
    lang = safe_lang(data.get("lang"))
    t = TXT[lang]

    val = cq.data.split(":", 1)[1]
    if val == "yes":
        noble = t["noble_yes"].replace("✅ ", "")
    elif val == "no":
        noble = t["noble_no"].replace("❌ ", "")
    else:
        noble = t["noble_progress"].replace("⏳ ", "")

    await state.update_data(noble=noble)

    await cq.message.edit_text(
        build_step_text(lang, 8, "step8"),
        reply_markup=k_cancel_back(lang, with_back=True),
        parse_mode="HTML",
    )
    await state.set_state(Form.prime)
    await safe_cq_answer(cq)

# ===================== Step 8 Prime =====================
@dp.message(Form.prime)
async def step_prime(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    if not await guard_private_message(m, lang):
        return

    if bad_text_general(m.text):
        await m.answer(TXT[lang]["step8_bad"], reply_markup=k_cancel_back(lang, with_back=True), parse_mode="HTML")
        return

    await state.update_data(prime=m.text.strip()[:80])

    await m.answer(
        build_step_text(lang, 9, "step9"),
        reply_markup=k_mic(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.mic)

# ===================== Step 9 Mic =====================
@dp.callback_query(F.data.startswith("mic:"))
async def cb_mic(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.mic.state:
        await safe_cq_answer(cq)
        return

    data = await state.get_data()
    lang = safe_lang(data.get("lang"))
    t = TXT[lang]

    val = cq.data.split(":", 1)[1]
    mic = t["mic_yes"].replace("🎙 ", "") if val == "yes" else t["mic_no"].replace("❌ ", "")

    await state.update_data(mic=mic)

    await cq.message.edit_text(
        build_step_text(lang, 10, "step10"),
        reply_markup=k_ready(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.ready)
    await safe_cq_answer(cq)

# ===================== Step 10 Ready =====================
@dp.callback_query(F.data.startswith("ready:"))
async def cb_ready(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.ready.state:
        await safe_cq_answer(cq)
        return

    data = await state.get_data()
    lang = safe_lang(data.get("lang"))
    t = TXT[lang]

    val = cq.data.split(":", 1)[1]
    if val == "yes":
        ready = t["ready_yes"].replace("✅ ", "")
    elif val == "sometimes":
        ready = t["ready_sometimes"].replace("⚠️ ", "")
    else:
        ready = t["ready_no"].replace("❌ ", "")

    await state.update_data(ready=ready)

    await cq.message.edit_text(
        build_step_text(lang, 11, "step11"),
        reply_markup=k_cancel_back(lang, with_back=True),
        parse_mode="HTML",
    )
    await state.set_state(Form.why)
    await safe_cq_answer(cq)

# ===================== Step 11 Why =====================
@dp.message(Form.why)
async def step_why(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    if not await guard_private_message(m, lang):
        return

    t = (m.text or "").strip()
    if not t or bad_text_general(t):
        await m.answer(TXT[lang]["step11_bad"], reply_markup=k_cancel_back(lang, with_back=True), parse_mode="HTML")
        return

    await state.update_data(why=t[:180])

    await m.answer(
        build_step_text(lang, 12, "step12"),
        reply_markup=k_discipline(lang),
        parse_mode="HTML",
    )
    await state.set_state(Form.discipline)

# ===================== Step 12 Discipline =====================
@dp.callback_query(F.data.startswith("disc:"))
async def cb_disc(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.discipline.state:
        await safe_cq_answer(cq)
        return

    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    val = cq.data.split(":", 1)[1]
    ok = (val == "yes")

    if lang == "ru":
        disc_text = "подтверждена" if ok else "не подтверждена"
    elif lang == "ua":
        disc_text = "підтверджено" if ok else "не підтверджено"
    else:
        disc_text = "confirmed" if ok else "not confirmed"

    await state.update_data(discipline=disc_text, discipline_ok=ok)

    if not ok:
        await send_admin_application_ru(cq.from_user, await state.get_data(), discipline_ok=False)
        await state.clear()
        await state.update_data(lang=lang)
        await cq.message.edit_text(TXT[lang]["disc_decline_user"], reply_markup=k_start(lang), parse_mode="HTML")
        await safe_cq_answer(cq)
        return

    data2 = await state.get_data()
    await cq.message.edit_text(fmt_preview(lang, data2), reply_markup=k_confirm(lang), parse_mode="HTML")
    await state.set_state(Form.confirm)
    await safe_cq_answer(cq)

# ===================== Confirm send =====================
@dp.callback_query(F.data == "confirm_send")
async def cb_confirm_send(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != Form.confirm.state:
        await safe_cq_answer(cq)
        return

    data = await state.get_data()
    lang = safe_lang(data.get("lang"))

    now = datetime.now(timezone.utc)
    prev = last_submit.get(cq.from_user.id)
    if prev and now - prev < timedelta(hours=COOLDOWN_HOURS):
        await safe_cq_answer(cq, TXT[lang]["cooldown"], show_alert=True)
        return

    await send_admin_application_ru(cq.from_user, data, discipline_ok=True)

    last_submit[cq.from_user.id] = now
    await state.clear()
    await state.update_data(lang=lang)

    await cq.message.edit_text(TXT[lang]["sent"], reply_markup=k_start(lang), parse_mode="HTML")
    await safe_cq_answer(cq, "OK")

@dp.message(Form.confirm)
async def in_confirm_state(m: Message, state: FSMContext):
    data = await state.get_data()
    lang = safe_lang(data.get("lang"))
    if not await guard_private_message(m, lang):
        return
    await m.answer(TXT[lang]["confirm_hint"], reply_markup=k_confirm(lang), parse_mode="HTML")

# ===================== Webhook =====================
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
