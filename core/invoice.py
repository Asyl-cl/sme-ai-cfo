import re
import pandas as pd


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower().replace("ё", "е"))


def apply_invoice(stock: pd.DataFrame, sales: pd.DataFrame, invoice: dict):
    """Добавляет количества из накладной в остатки. Товары ищем по названию среди продаж.
    Возвращает (новые остатки, внесённые позиции, не найденные позиции)."""
    names = sales.drop_duplicates("sku").assign(_n=lambda d: d["name"].map(_norm)).set_index("_n")["sku"]
    st = stock.copy()
    st["sku"] = st["sku"].astype(str)
    matched, unmatched = [], []
    date = invoice.get("date")
    for it in invoice.get("items") or []:
        key = _norm(it.get("name"))
        qty = it.get("qty")
        if key in names.index and isinstance(qty, (int, float)) and qty > 0:
            sku = str(names[key])
            if (st["sku"] == sku).any():
                st.loc[st["sku"] == sku, "qty"] += qty
            else:
                st = pd.concat([st, pd.DataFrame([{"sku": sku, "qty": qty}])], ignore_index=True)
            if date and "last_purchase_date" in st.columns:
                st.loc[st["sku"] == sku, "last_purchase_date"] = date
            matched.append({"name": it.get("name"), "qty": qty})
        else:
            unmatched.append(it.get("name"))
    return st, matched, unmatched
