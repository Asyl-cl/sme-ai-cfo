import json
import pandas as pd
from core import metrics, forecast, cashflow, debts as debts_mod, effect as effect_mod, bank as bank_mod

SAMPLE = "data/sample/"


def load_sample() -> dict:
    return {"sales": pd.read_csv(SAMPLE + "sales.csv"), "stock": pd.read_csv(SAMPLE + "stock.csv"),
            "debts": pd.read_csv(SAMPLE + "debts.csv"), "obligations": pd.read_csv(SAMPLE + "obligations.csv"),
            "bank": pd.read_csv(SAMPLE + "bank.csv"),
            "meta": json.load(open(SAMPLE + "meta.json", encoding="utf-8"))}


def build_report(st: dict) -> dict:
    """Все числа считаются здесь (pandas); LLM получает только этот словарь."""
    sales, stock = st["sales"], st["stock"]
    today = pd.to_datetime(sales["date"]).max()
    summ = metrics.summary(sales, stock)
    cf = cashflow.cash_forecast(sales, st["obligations"], st["debts"], st["meta"]["cash_balance"])
    order = forecast.weekly_order(sales, stock).head(10).reset_index()
    dr = debts_mod.debt_ranking(st["debts"], today=today).head(5)
    rep = {"summary": summ,
           "cashflow": {k: v for k, v in cf.items() if k != "timeline"},
           "order_top": order.to_dict("records"),
           "debtors": dr.astype(str).to_dict("records")}
    rep["effect"] = effect_mod.effect(sales, summ, cf)
    if st.get("bank") is not None and len(st["bank"]):
        from ai import qa
        rep["bank"] = bank_mod.bank_summary(st["bank"], qa.categorize_bank)
    return rep


def fmt(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def effect_text(rep: dict) -> str:
    """Готовая сводка эффекта (без LLM): цифры из расчётов, допущения явно."""
    e = rep["effect"]
    lines = ["Эффект на тестовых данных:",
             f"• Можно высвободить оборотных средств: {fmt(e['freed_working_capital'])} ₸ (залежавшийся товар)",
             f"• Потери от убыточных позиций сократятся на {fmt(e['loss_avoided_per_month'])} ₸ в месяц "
             f"({fmt(e['loss_avoided_per_year'])} ₸ в год)"]
    if e["cash_gap"]:
        lines.append(f"• Кассовый разрыв {e['cash_gap']['date']}: не хватает {fmt(e['cash_gap']['shortfall'])} ₸ — "
                     "заранее есть время закрыть его")
    lines.append("\nДопущения:\n" + "\n".join("– " + a for a in e["assumptions"]))
    return "\n".join(lines)


def order_text(rep: dict) -> str:
    rows = rep["order_top"]
    if not rows:
        return "Остатков хватает на неделю — докупать ничего не нужно."
    return "Закупки на неделю (топ-10):\n" + "\n".join(
        f"• {r['name']}: заказать {fmt(r['order_qty'])} шт. (прогноз спроса {fmt(r['forecast'])})" for r in rows)


def debts_text(rep: dict) -> str:
    rows = rep["debtors"]
    if not rows:
        return "Неоплаченных долгов нет."
    return "Должники (по просрочке):\n" + "\n".join(
        f"• {r['client']}: {fmt(float(r['amount']))} ₸, просрочка {int(float(r['overdue_days']))} дн., риск: {r['risk']}"
        for r in rows) + "\n\nТексты напоминаний: /remind или /remind kk"


def bank_text(rep: dict) -> str:
    b = rep.get("bank")
    if not b:
        return "Банковской выписки нет. Пришлите файл с колонками: date, description, amount (расходы со знаком минус)."
    lines = [f"Выписка: {b['operations']} операций. Поступило {fmt(b['income'])} ₸, потрачено {fmt(b['expenses'])} ₸.",
             "Куда уходят деньги:"]
    lines += [f"• {k}: {fmt(v)} ₸ ({v / b['expenses'] * 100:.0f}%)" for k, v in b["by_category"].items()]
    return "\n".join(lines)


def split_text(text: str, limit: int = 4000) -> list[str]:
    """Режет длинный ответ на части ≤ limit символов по границам абзацев/строк."""
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                parts.append(cur); cur = ""
            parts.append(line[:limit]); line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur); cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    return parts or [""]
