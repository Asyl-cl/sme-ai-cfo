import json
from ai import llm, prompts


def answer(report: dict, question: str) -> str:
    """Ответ на вопрос по готовому отчёту (LLM видит только JSON с числами)."""
    ctx = json.dumps(report, ensure_ascii=False, default=str)
    return llm.ask(prompts.QA_SYSTEM, f"ДАННЫЕ:\n{ctx}\n\nВОПРОС: {question}")


def _fmt(n) -> str:
    return f"{float(n):,.0f}".replace(",", " ")


def _plain_summary(report: dict) -> str:
    """Отчёт без ИИ: только посчитанные числа. Показываем, если API недоступен и кэша нет."""
    s, e = report.get("summary", {}), report.get("effect", {})
    lines = ["ИИ сейчас недоступен, вот расчёты без пояснений:"]
    try:
        lines.append(f"• Выручка: {_fmt(s['revenue'])} ₸, прибыль: {_fmt(s['profit'])} ₸")
        lines.append(f"• Убыточные позиции: {_fmt(s['loss_total'])} ₸ потерь")
        lines.append(f"• Замороженные остатки: {_fmt(s['dead_stock_total'])} ₸")
        gap = e.get("cash_gap")
        if gap:
            lines.append(f"• Кассовый разрыв {gap['date']}: не хватает {_fmt(gap['shortfall'])} ₸")
    except Exception:
        pass
    lines.append("Подробнее: /order, /debts, /effect, /bank.")
    return "\n".join(lines)


def explain(report: dict) -> str:
    return llm.ask(prompts.EXPLAIN_SYSTEM, json.dumps(report, ensure_ascii=False, default=str),
                   fallback=_plain_summary(report))


_TEMPLATES = {
    "ru": "Здравствуйте, {client}! Напоминаем о задолженности {amount} ₸ (просрочка {days} дн.). "
          "Пожалуйста, оплатите до {deadline}. Спасибо!",
    "kk": "Сәлеметсіз бе, {client}! {amount} ₸ қарызыңыз туралы еске саламыз (мерзімі {days} күнге өтті). "
          "Өтінеміз, {deadline} дейін төлеңіз. Рахмет!",
}


def reminder(client: str, amount: float, overdue_days: int, deadline: str,
             lang: str = "ru", tone: str = "мягкий") -> str:
    """Текст напоминания должнику; при сбое LLM отдаём шаблон."""
    amt = f"{amount:,.0f}".replace(",", " ")
    lang = lang if lang in _TEMPLATES else "ru"
    fallback = _TEMPLATES[lang].format(client=client, amount=amt, days=overdue_days, deadline=deadline)
    user = (f"Клиент: {client}. Сумма: {amt} ₸. Просрочка: {overdue_days} дн. "
            f"Срок оплаты: {deadline}. Язык: {lang}. Тон: {tone}.")
    return llm.ask(prompts.REMINDER_SYSTEM, user, max_tokens=300, fallback=fallback)


def categorize_bank(descriptions: list[str]) -> list[str]:
    """Уточняет категории операций, которые правила не распознали. При сбое — «прочее»."""
    import json as _json
    from core.bank import CATEGORIES
    items = [{"index": i, "description": d} for i, d in enumerate(descriptions)]
    raw = llm.ask(prompts.CATEGORIZE_SYSTEM, _json.dumps(items, ensure_ascii=False), max_tokens=800, fallback="")
    try:
        data = _json.loads(raw[raw.find("["): raw.rfind("]") + 1])
        by_idx = {int(x["index"]): x["category"] for x in data if x.get("confidence") == "high"}
    except Exception:
        by_idx = {}
    return [by_idx.get(i, "прочее") if by_idx.get(i) in CATEGORIES else "прочее" for i in range(len(descriptions))]
