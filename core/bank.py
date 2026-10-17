import pandas as pd

CATEGORIES = ["закупки", "аренда", "зарплата", "налоги", "коммунальные", "реклама", "прочее"]
_KEYWORDS = {
    "закупки": ("поставщик", "товар", "закуп", "оптов", "тоо алем"),
    "аренда": ("аренд",),
    "зарплата": ("зарплат", "заработн", "оплата труда", "аванс"),
    "налоги": ("налог", "ипн", "соцотчисл", "кпн", "ндс", "осмс", "ипн"),
    "коммунальные": ("коммунал", "кск", "электро", "водоканал", "газ", "интернет"),
    "реклама": ("реклам", "таргет", "instagram", "2гис"),
}


def categorize_rule(description: str) -> str:
    """Категория по ключевым словам; неизвестное — «прочее»."""
    t = str(description).lower()
    for cat, words in _KEYWORDS.items():
        if any(w in t for w in words):
            return cat
    return "прочее"


def bank_summary(bank: pd.DataFrame, ai_categorize=None) -> dict:
    """Расходы по категориям. ai_categorize(list[str]) -> list[str] уточняет «прочее» (необязательно)."""
    b = bank.copy()
    b["category"] = b["description"].map(categorize_rule)
    if ai_categorize is not None:
        mask = b["category"] == "прочее"
        if mask.any():
            try:
                new = ai_categorize(b.loc[mask, "description"].tolist())
                if len(new) == int(mask.sum()):
                    b.loc[mask, "category"] = [c if c in CATEGORIES else "прочее" for c in new]
            except Exception:
                pass
    exp = b[b["amount"] < 0]
    by_cat = (-exp.groupby("category")["amount"].sum()).sort_values(ascending=False)
    return {
        "income": float(b.loc[b["amount"] > 0, "amount"].sum()),
        "expenses": float(-exp["amount"].sum()),
        "by_category": {k: float(v) for k, v in by_cat.items()},
        "operations": int(len(b)),
    }
