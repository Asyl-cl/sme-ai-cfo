import pandas as pd


def debt_ranking(debts: pd.DataFrame, today=None):
    """Неоплаченные долги с просрочкой в днях и уровнем риска. today — дата отсчёта."""
    d = debts[debts["paid"] == 0].copy()
    today = pd.Timestamp(today if today is not None else pd.Timestamp.today().normalize())
    d["overdue_days"] = (today - pd.to_datetime(d["due_date"])).dt.days.clip(lower=0)
    d["risk"] = pd.cut(d["overdue_days"], [-1, 0, 14, 30, 10_000],
                       labels=["низкий", "средний", "высокий", "критичный"]).astype(str)
    return d.sort_values(["overdue_days", "amount"], ascending=False)
