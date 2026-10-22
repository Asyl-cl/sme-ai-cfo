import asyncio, functools, io, logging, os
import pandas as pd
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                           MenuButtonCommands, Message, ReplyKeyboardMarkup)
from dotenv import load_dotenv

from ai import qa
from ai.invoice_ocr import parse_invoice, format_invoice
from bot import loader
from bot.report import (bank_text, build_report, debts_text, effect_text, load_sample,
                        order_text, split_text)
from core import bank as bank_mod
from core.invoice import apply_invoice

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")
dp = Dispatcher()
STATE: dict[int, dict] = {}   # chat_id -> данные и отчёт (для хакатона достаточно памяти)
MAX_FILE = 10 * 1024 * 1024
HELP = ("Что я умею:\n"
        "/demo — пример на тестовых данных\n"
        "Отправьте файл .csv или .xlsx: продажи (дата, товар, количество, цена, себестоимость), остатки, "
        "долги (клиент, сумма, срок оплаты), плановые платежи. Заголовки можно писать по-русски. "
        "В Excel можно сложить всё на разные листы.\n"
        "/balance 1100000 — задать остаток денег на счетах\n"
        "/report — повторить отчёт\n"
        "/order — что закупить на неделю\n"
        "/debts — должники\n"
        "/effect — сколько денег можно высвободить и сохранить\n"
        "/bank — куда уходят деньги по банковской выписке (файл date, description, amount)\n"
        "/remind [ru|kk] [мягкий|настойчивый|последнее] — тексты напоминаний должникам\n"
        "Фото накладной — распознаю товары и суммы.\n"
        "Любой вопрос или просьба о совете текстом — отвечу (с вашими данными точнее).")


async def reply(m: Message, text: str):
    for part in split_text(text):
        await m.answer(part)


def _ready(st: dict) -> bool:
    return all(k in st for k in ("sales", "stock", "debts", "obligations", "meta"))


def _guard(handler):
    """Любой сбой в обработчике → понятное сообщение, бот живёт."""
    @functools.wraps(handler)   # aiogram по сигнатуре решает, что передавать
    async def wrapper(m: Message, *a, **kw):
        try:
            return await handler(m, *a, **kw)
        except loader.FileError as e:
            await m.answer(str(e))
        except Exception:
            log.exception("handler failed")
            await m.answer("Что-то пошло не так. Попробуйте ещё раз или напишите /help.")
    return wrapper


MENU = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🛒 Закупки", callback_data="order"),
     InlineKeyboardButton(text="👥 Должники", callback_data="debts")],
    [InlineKeyboardButton(text="💰 Эффект", callback_data="effect"),
     InlineKeyboardButton(text="🏦 Выписка", callback_data="bank")],
    [InlineKeyboardButton(text="✉️ Напоминания", callback_data="remind")]])
KB = ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True, keyboard=[
    [KeyboardButton(text="📊 Демо"), KeyboardButton(text="📈 Отчёт")],
    [KeyboardButton(text="🛒 Закупки"), KeyboardButton(text="👥 Должники")],
    [KeyboardButton(text="💰 Эффект"), KeyboardButton(text="🏦 Выписка")],
    [KeyboardButton(text="✉️ Напоминания"), KeyboardButton(text="❓ Помощь")]])
BUTTON_TEXTS = {"📊 Демо", "📈 Отчёт", "🛒 Закупки", "👥 Должники", "💰 Эффект", "🏦 Выписка",
                "✉️ Напоминания", "❓ Помощь"}
COMMANDS = [BotCommand(command="start", description="Начать работу"),
            BotCommand(command="demo", description="Пример на тестовых данных"),
            BotCommand(command="report", description="Отчёт по вашим данным"),
            BotCommand(command="order", description="Что закупить на неделю"),
            BotCommand(command="debts", description="Должники"),
            BotCommand(command="effect", description="Сколько денег можно высвободить"),
            BotCommand(command="bank", description="Куда уходят деньги (выписка)"),
            BotCommand(command="remind", description="Напоминания должникам"),
            BotCommand(command="balance", description="Указать остаток денег"),
            BotCommand(command="help", description="Что я умею")]
DESCRIPTION = ("ИИ-финдиректор для малого бизнеса Тараза.\n\n"
               "Пришлите Excel или CSV с продажами, фото накладной или просто задайте вопрос. "
               "Покажу, где теряются деньги, что закупить, когда не хватит денег и кому напомнить о долге.\n\n"
               "Нажмите «Начать» внизу.")
SHORT_DESCRIPTION = "ИИ-финдиректор: загрузите Excel с продажами и узнайте, где теряются деньги и что делать."
TEXTS = {"order": order_text, "debts": debts_text, "effect": effect_text, "bank": bank_text}


async def _make_report(m: Message, st: dict):
    st["report"] = await asyncio.to_thread(build_report, st)   # pandas и LLM не блокируют бота
    await reply(m, await asyncio.to_thread(qa.explain, st["report"]))
    await m.answer("Что показать дальше? Или задайте вопрос текстом, например: «Почему упала прибыль?»",
                   reply_markup=MENU)


async def _section(m: Message, kind: str):
    st = STATE.get(m.chat.id)
    if not st or "report" not in st:
        return await m.answer("Сначала отправьте файл с продажами или напишите /demo.")
    await reply(m, TEXTS[kind](st["report"]))


for _k in TEXTS:
    def _mk(kind):
        @dp.message(Command(kind))
        @_guard
        async def _cmd(m: Message):
            await _section(m, kind)
        return _cmd
    _mk(_k)


@dp.callback_query(F.data.in_(set(TEXTS) | {"remind"}))
async def menu_click(c: CallbackQuery):
    await c.answer()
    try:
        msg = c.message
        if c.data == "remind":
            await _send_reminders(msg, [])
        else:
            await _section(msg, c.data)
    except Exception:
        log.exception("callback failed")
        await c.message.answer("Что-то пошло не так. Напишите /help.")


TOPICS_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="💸 Как закрыть долг", callback_data="t_debt")],
    [InlineKeyboardButton(text="📈 Как заработать больше", callback_data="t_profit")],
    [InlineKeyboardButton(text="📊 Попробовать на примере", callback_data="t_demo"),
     InlineKeyboardButton(text="📎 Загрузить свои данные", callback_data="t_upload")],
    [InlineKeyboardButton(text="🤖 Что умеет бот", callback_data="t_about")]])
UPLOAD_HINT = ("Пришлите файл .xlsx или .csv: продажи (дата, товар, количество, цена, себестоимость), остатки, "
               "долги (клиент, сумма, срок оплаты) или банковскую выписку. Заголовки можно писать по-русски. "
               "Можно также прислать фото накладной.")


@dp.message(CommandStart())
@_guard
async def start(m: Message):
    await m.answer("Привет! Я ИИ-финдиректор для малого бизнеса. Помогаю понять, где теряются деньги, "
                   "что закупить и как не уйти в кассовый разрыв.", reply_markup=KB)
    await m.answer("Какой у вас вопрос? Выберите тему или напишите свой вопрос своими словами, например: "
                   "«У меня долг 1 800 000 ₸, как его закрыть?»", reply_markup=TOPICS_KB)


@dp.message(Command("help"))
@_guard
async def help_cmd(m: Message):
    await m.answer(HELP, reply_markup=KB)


@dp.callback_query(F.data.in_({"t_debt", "t_profit", "t_demo", "t_upload", "t_about"}))
async def topic_click(c: CallbackQuery):
    await c.answer()
    try:
        m = c.message                      # chat_id берём из сообщения с кнопками
        if c.data == "t_debt":
            await m.answer("Расскажите одним сообщением: сколько вы должны, кому (поставщику, банку, другому) "
                           "и к какому сроку. Дам план, как закрыть долг.")
        elif c.data == "t_profit":
            report = (STATE.get(m.chat.id) or {}).get("report")
            await reply(m, await asyncio.to_thread(qa.answer, report, "Как мне заработать больше?"))
        elif c.data == "t_demo":
            await demo(m)
        elif c.data == "t_upload":
            await m.answer(UPLOAD_HINT)
        else:
            await m.answer(HELP)
    except Exception:
        log.exception("topic callback failed")
        await c.message.answer("Что-то пошло не так. Напишите /help.")


@dp.message(Command("demo"))
@_guard
async def demo(m: Message):
    st = load_sample(); STATE[m.chat.id] = st
    await m.answer("Загружаю тестовые данные мини-маркета (синтетика)…")
    await _make_report(m, st)


@dp.message(Command("report"))
@_guard
async def report_cmd(m: Message):
    st = STATE.get(m.chat.id)
    if not st or not _ready(st):
        return await m.answer("Сначала отправьте файл с продажами или напишите /demo.")
    await _make_report(m, st)


@dp.message(Command("balance"))
@_guard
async def balance(m: Message):
    raw = " ".join((m.text or "").split()[1:])            # «5 000 000» приходит несколькими словами
    cleaned = raw.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return await m.answer("Напишите так: /balance 1100000")
    st = STATE.setdefault(m.chat.id, {})
    st.setdefault("meta", {"business_name": "Ваш бизнес"})["cash_balance"] = value
    await m.answer(f"Остаток денег: {value:,.0f} ₸.".replace(",", " ") + " Напишите /report, чтобы пересчитать.")


@dp.message(Command("remind"))
@_guard
async def remind(m: Message):
    await _send_reminders(m, [a.lower() for a in (m.text or "").split()[1:]])


async def _send_reminders(m: Message, args: list[str]):
    st = STATE.get(m.chat.id)
    if not st or "report" not in st:
        return await m.answer("Сначала получите отчёт: отправьте файл или напишите /demo.")
    lang = "kk" if "kk" in args else "ru"
    tone = next((t for t in ("настойчивый", "последнее") if t in args), "мягкий")
    tone = "последнее предупреждение" if tone == "последнее" else tone
    debtors = [d for d in st["report"]["debtors"] if int(float(d["overdue_days"])) > 0][:3]
    if not debtors:
        return await m.answer("Просроченных долгов нет — напоминать некому.")
    deadline = (pd.Timestamp.today().normalize() + pd.Timedelta(days=3)).strftime("%d.%m.%Y")
    for d in debtors:
        text = await asyncio.to_thread(qa.reminder, d["client"], float(d["amount"]),
                                       int(float(d["overdue_days"])), deadline, lang, tone)
        await m.answer(f"{d['client']} (просрочка {int(float(d['overdue_days']))} дн.):\n\n{text}")


@dp.message(F.document)
@_guard
async def upload(m: Message):
    doc = m.document
    if doc.file_size and doc.file_size > MAX_FILE:
        return await m.answer("Файл больше 10 МБ. Пришлите выгрузку за меньший период.")
    buf = io.BytesIO()
    await m.bot.download(doc, destination=buf)
    fname = (doc.file_name or "").lower()
    mime = getattr(doc, "mime_type", None) or ""
    if mime.startswith("image/") or fname.endswith((".jpg", ".jpeg", ".png", ".webp")):
        media = mime if mime in ("image/jpeg", "image/png", "image/webp") else (
            "image/png" if fname.endswith(".png") else "image/webp" if fname.endswith(".webp") else "image/jpeg")
        return await _process_invoice(m, buf.getvalue(), media)
    found = await asyncio.to_thread(loader.read_upload, buf.getvalue(), doc.file_name or "")

    st = STATE.setdefault(m.chat.id, {})
    st.pop("report", None)
    got = []
    for kind, df in found.items():
        st[kind] = df
        note = f", пропущено строк с ошибками: {df.attrs['dropped']}" if df.attrs.get("dropped") else ""
        got.append(f"• {loader.TITLES[kind]}: {len(df)} строк{note}")
    await m.answer("Принял:\n" + "\n".join(got))

    if "sales" not in st:
        if "bank" in st:
            summ = await asyncio.to_thread(bank_mod.bank_summary, st["bank"], qa.categorize_bank)
            await reply(m, bank_text({"bank": summ}))
        return await m.answer("Для полного отчёта пришлите файл с продажами.")

    # недостающие таблицы берём из примера и честно говорим об этом
    sample, filled = load_sample(), []
    for key in ("stock", "debts", "obligations", "meta"):
        if key not in st:
            st[key] = sample[key]
            filled.append({"stock": "остатки", "debts": "долги", "obligations": "плановые платежи",
                           "meta": "остаток денег (1 100 000 ₸)"}[key])
    if filled:
        await m.answer("Не хватает: " + ", ".join(filled) + ". Пока использую тестовые значения — "
                       "они не про ваш бизнес. Пришлите свои файлы или /balance, и я пересчитаю.")
    await _make_report(m, st)


INVOICE_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="✅ Внести в остатки", callback_data="invoice_apply"),
    InlineKeyboardButton(text="✖ Отмена", callback_data="invoice_cancel")]])


async def _process_invoice(m: Message, image: bytes, media_type: str):
    await m.answer("Распознаю накладную…")
    data = await asyncio.to_thread(parse_invoice, image, media_type)
    await reply(m, format_invoice(data))
    if "error" not in data and data.get("items"):
        STATE.setdefault(m.chat.id, {})["pending_invoice"] = data
        await m.answer("Внести эти товары в остатки?", reply_markup=INVOICE_KB)


@dp.message(F.photo)
@_guard
async def invoice(m: Message):
    buf = io.BytesIO()
    await m.bot.download(m.photo[-1], destination=buf)
    await _process_invoice(m, buf.getvalue(), "image/jpeg")


@dp.callback_query(F.data.in_({"invoice_apply", "invoice_cancel"}))
async def invoice_click(c: CallbackQuery):
    await c.answer()
    try:
        await _invoice_click(c)
    except Exception:
        log.exception("invoice callback failed")
        await c.message.answer("Что-то пошло не так. Попробуйте ещё раз.")


async def _invoice_click(c: CallbackQuery):
    st = STATE.get(c.message.chat.id, {})
    inv = st.pop("pending_invoice", None)
    if c.data == "invoice_cancel" or not inv:
        return await c.message.answer("Хорошо, остатки не менял." if inv else "Накладная уже обработана или устарела.")
    if "stock" not in st or "sales" not in st:
        return await c.message.answer("Сначала загрузите продажи и остатки (или /demo): "
                                      "я ищу товары накладной по названиям из продаж.")
    st["stock"], matched, unmatched = apply_invoice(st["stock"], st["sales"], inv)
    st["report"] = await asyncio.to_thread(build_report, st)
    text = f"Внёс в остатки: {len(matched)} поз." + (f"\nНе нашёл в ваших товарах: {', '.join(map(str, unmatched))}" if unmatched else "")
    await c.message.answer(text + "\nОтчёт пересчитан: /order, /effect.")


@dp.message(F.text.in_(BUTTON_TEXTS))
@_guard
async def keyboard_button(m: Message):
    """Кнопки нижней клавиатуры: те же действия, что и у команд (не уходят в ИИ как вопрос)."""
    t = m.text
    if t == "📊 Демо":
        return await demo(m)
    if t == "📈 Отчёт":
        return await report_cmd(m)
    if t == "✉️ Напоминания":
        return await _send_reminders(m, [])
    if t == "❓ Помощь":
        return await help_cmd(m)
    kind = {"🛒 Закупки": "order", "👥 Должники": "debts", "💰 Эффект": "effect", "🏦 Выписка": "bank"}[t]
    await _section(m, kind)


@dp.message(F.text & ~F.text.startswith("/"))
@_guard
async def question(m: Message):
    st = STATE.get(m.chat.id) or {}
    report = st.get("report")          # None, если данных ещё нет: совет всё равно работает
    await reply(m, await asyncio.to_thread(qa.answer, report, m.text))


async def setup_bot(bot: Bot):
    """Список команд, кнопка «Меню», описание на экране перед запуском. Сбой не мешает работе бота."""
    try:
        await bot.set_my_commands(COMMANDS)
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        await bot.set_my_description(DESCRIPTION)
        await bot.set_my_short_description(SHORT_DESCRIPTION)
    except Exception:
        log.exception("Не удалось настроить меню бота (бот продолжит работать)")


async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Не задан TELEGRAM_BOT_TOKEN в .env")
    bot = Bot(token)
    await setup_bot(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
