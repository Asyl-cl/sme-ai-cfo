import pandas as pd

SUPPLIER_WORDS = ("поставщик", "закуп", "supplier")


def _is_supplier(name: str) -> bool:
    n = str(name).lower()
    return any(w in n for w in SUPPLIER_WORDS)


def cash_forecast(sales, obligations, debts, balance, days=21, debt_recovery=0.0):
    """Грубый прогноз остатка денег на `days` дней.

    Приход: средняя дневная выручка за 28 дней.
    Расход: плановые платежи из obligations + закупки товара. Закупки оцениваем по
    себестоимости проданного; платежи поставщикам из obligations считаем их частью
    (чтобы не считать дважды), остаток закупок размазываем равномерно по дням.
    Возврат долгов: debt_recovery (0..1) — доля неоплаченных долгов, которую ждём
    в срок оплаты (по умолчанию 0: долги не учитываем).
    """
    s = sales.copy(); s["date"] = pd.to_datetime(s["date"])
    daily_rev = float((s["qty"] * s["price"]).groupby(s["date"]).sum().tail(28).mean())
    daily_cogs = float((s["qty"] * s["cost"]).groupby(s["date"]).sum().tail(28).mean())
    today = s["date"].max()

    ob = obligations.copy(); ob["date"] = pd.to_datetime(ob["date"])
    end = today + pd.Timedelta(days=days)
    in_h = ob[(ob["date"] > today) & (ob["date"] <= end)]
    supplier_total = float(in_h.loc[in_h["name"].map(_is_supplier), "amount"].sum())
    extra_purchases_daily = max(0.0, daily_cogs * days - supplier_total) / days
    net_daily = daily_rev - extra_purchases_daily

    inflow_debts = {}
    if debt_recovery > 0 and debts is not None and len(debts):
        d = debts[debts["paid"] == 0]
        for _, r in d.iterrows():
            due = max(pd.Timestamp(r["due_date"]), today + pd.Timedelta(days=1))
            inflow_debts[due] = inflow_debts.get(due, 0.0) + float(r["amount"]) * debt_recovery

    rows, bal, first_gap, min_bal = [], float(balance), None, float(balance)
    for i in range(1, days + 1):
        d = today + pd.Timedelta(days=i)
        bal += net_daily - float(ob.loc[ob["date"] == d, "amount"].sum()) + inflow_debts.get(d, 0.0)
        rows.append({"date": str(d.date()), "balance": int(round(bal))})
        min_bal = min(min_bal, bal)
        if bal < 0 and first_gap is None:
            first_gap = {"date": str(d.date()), "shortfall": int(round(-bal))}
    return {"timeline": rows, "first_gap": first_gap, "net_daily": int(round(net_daily)),
            "min_balance": int(round(min_bal))}
