import pandas as pd


def weekly_order(sales: pd.DataFrame, stock: pd.DataFrame, horizon_days=7, lookback=28):
    """Что и сколько закупить: прогноз спроса на горизонт с учётом дней недели минус остаток."""
    cols = ["name", "forecast", "order_qty"]
    if sales is None or len(sales) == 0:
        return pd.DataFrame(columns=cols)
    s = sales.copy(); s["date"] = pd.to_datetime(s["date"])
    recent = s[s["date"] > s["date"].max() - pd.Timedelta(days=lookback)]
    daily = recent.groupby("sku")["qty"].sum() / lookback
    wk = s.groupby(s["date"].dt.weekday)["qty"].sum()
    season = (wk / wk.mean()).to_dict()
    start = s["date"].max() + pd.Timedelta(days=1)
    factor = sum(season.get((start + pd.Timedelta(days=i)).weekday(), 1) for i in range(horizon_days))
    need = (daily * factor).round()
    st = stock.set_index("sku")["qty"]
    order = (need - st.reindex(need.index).fillna(0)).clip(lower=0)
    names = s.drop_duplicates("sku").set_index("sku")["name"]
    out = pd.DataFrame({"name": names.reindex(order.index), "forecast": need, "order_qty": order})
    return out[out["order_qty"] > 0].sort_values("order_qty", ascending=False)
