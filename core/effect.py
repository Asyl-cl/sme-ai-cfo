import pandas as pd


def effect(sales: pd.DataFrame, summary: dict, cashflow_res: dict) -> dict:
    """Денежный эффект для слайда и отчёта. Все допущения перечислены в `assumptions`."""
    d = pd.to_datetime(sales["date"])
    months = max((d.max() - d.min()).days / 30.0, 1.0)
    loss_month = abs(summary["loss_total"]) / months
    gap = cashflow_res.get("first_gap")
    return {
        "freed_working_capital": float(summary["dead_stock_total"]),
        "loss_avoided_per_month": float(round(loss_month)),
        "loss_avoided_per_year": float(round(loss_month * 12)),
        "cash_gap": gap,
        "assumptions": [
            "Замороженные остатки: сумма по себестоимости товаров без продаж 45+ дней; "
            "высвободить можно скидкой или возвратом поставщику, не всё сразу.",
            "Потери от убыточных позиций: средний убыток в месяц за период данных; "
            "эффект наступает, если поднять цену до себестоимости или убрать позицию.",
            "Расчёт на тестовых данных, кассовый прогноз — грубая оценка.",
        ],
    }
