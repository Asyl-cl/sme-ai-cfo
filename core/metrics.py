import pandas as pd


def _empty_ok(df) -> bool:
    return df is None or len(df) == 0


def product_margin(sales: pd.DataFrame) -> pd.DataFrame:
    """Маржа по товарам: выручка, прибыль, маржинальность в %."""
    s = sales.copy()
    s["revenue"] = s["qty"] * s["price"]
    s["profit"] = s["qty"] * (s["price"] - s["cost"])
    g = s.groupby(["sku", "name"], as_index=False)[["qty", "revenue", "profit"]].sum()
    g["margin_pct"] = (g["profit"] / g["revenue"].replace(0, float("nan")) * 100).round(1)
    return g.sort_values("profit", ascending=False)


def abc_analysis(m: pd.DataFrame) -> pd.DataFrame:
    """ABC по доле в накопленной выручке: A до 80%, B до 95%, C остальное."""
    m = m.sort_values("revenue", ascending=False).copy()
    total = m["revenue"].sum()
    if total == 0:
        m["abc"] = "C"
        return m
    share = m["revenue"].cumsum() / total
    m["abc"] = share.apply(lambda x: "A" if x <= 0.8 else ("B" if x <= 0.95 else "C"))
    return m


def loss_makers(m: pd.DataFrame) -> pd.DataFrame:
    """Позиции с отрицательной прибылью."""
    return m[m["profit"] < 0].sort_values("profit")


def dead_stock(sales, stock, cost_map, days=45):
    """Остатки, которые не продавались `days` дней, и сумма, замороженная в них."""
    s_dates = pd.to_datetime(sales["date"])
    last = s_dates.groupby(sales["sku"]).max()
    cutoff = s_dates.max() - pd.Timedelta(days=days)
    out = stock.copy()
    out["last_sale"] = pd.to_datetime(out["sku"].map(last))
    out = out[(out["last_sale"].isna()) | (out["last_sale"] < cutoff)].copy()
    out["frozen_tenge"] = out["qty"] * out["sku"].map(cost_map).fillna(0)
    return out.sort_values("frozen_tenge", ascending=False)


def summary(sales, stock) -> dict:
    """Сводка для отчёта. Все значения — обычные float/str, пригодны для JSON."""
    if _empty_ok(sales):
        return {"revenue": 0.0, "profit": 0.0, "loss_makers": [], "loss_total": 0.0,
                "dead_stock_total": 0.0, "dead_stock_top": []}
    m = product_margin(sales)
    cost_map = sales.groupby("sku")["cost"].mean().to_dict()
    d = dead_stock(sales, stock, cost_map) if not _empty_ok(stock) else stock
    lm = loss_makers(m)
    return {
        "revenue": float(m["revenue"].sum()),
        "profit": float(m["profit"].sum()),
        "loss_makers": [{"name": str(r["name"]), "profit": float(r["profit"])}
                        for _, r in lm.head(5).iterrows()],
        "loss_total": float(lm["profit"].sum()),
        "dead_stock_total": float(d["frozen_tenge"].sum()) if not _empty_ok(d) else 0.0,
        "dead_stock_top": [{"sku": str(r["sku"]), "qty": float(r["qty"]),
                            "frozen_tenge": float(r["frozen_tenge"])}
                           for _, r in d.head(5).iterrows()] if not _empty_ok(d) else [],
    }
