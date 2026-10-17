"""Синтетические данные. Примеры:
python data/generate_data.py                       # основной набор (data/sample)
python data/generate_data.py --seed 7 --out data/sample2 --skus 40 --cash 600000
"""
import argparse, json, os
import numpy as np, pandas as pd


def generate(out="data/sample", seed=42, n_skus=60, cash=1_100_000, name="Мини-маркет Тараз", scale=1.0):
    rng = np.random.default_rng(seed)
    os.makedirs(out, exist_ok=True)
    cats = ["Молочные", "Хлеб", "Бакалея", "Напитки", "Овощи", "Снеки", "Бытовая химия"]
    skus = []
    for i in range(n_skus):
        cost = float(rng.integers(100, 1500))
        skus.append({"sku": f"S{i:03d}", "name": f"Товар {i}", "category": cats[i % len(cats)],
                     "cost": cost, "price": round(cost * rng.uniform(1.12, 1.45))})
    for i in range(5):                                   # убыточные позиции
        skus[i]["price"] = round(skus[i]["cost"] * rng.uniform(0.85, 0.97))
    dead = set(range(n_skus - 10, n_skus - 2))           # залежавшийся товар

    days = pd.date_range(end=pd.Timestamp.today().normalize(), periods=180)
    rows = []
    for d in days:
        wk = 1.3 if d.weekday() >= 5 else 1.0
        for i, s in enumerate(skus):
            if i in dead and (days[-1] - d).days < 60:
                continue
            qty = max(0, rng.poisson(rng.uniform(0.5, 6) * wk * scale))
            if qty:
                rows.append({"date": d.date(), **{k: s[k] for k in ["sku", "name", "category", "price", "cost"]}, "qty": qty})
    pd.DataFrame(rows).to_csv(f"{out}/sales.csv", index=False)

    stock = [{"sku": s["sku"], "qty": int(rng.integers(5, 40)) * (6 if i in dead else 1),
              "last_purchase_date": str((days[-1] - pd.Timedelta(days=int(rng.integers(3, 40)))).date())}
             for i, s in enumerate(skus)]
    pd.DataFrame(stock).to_csv(f"{out}/stock.csv", index=False)

    today = days[-1]
    debts = [{"client": f"Клиент {j}", "amount": int(rng.integers(20, 300)) * 1000,
              "issued_date": str((today - pd.Timedelta(days=int(rng.integers(10, 80)))).date()),
              "due_date": str((today + pd.Timedelta(days=int(rng.integers(-30, 20)))).date()), "paid": 0}
             for j in range(6)]
    pd.DataFrame(debts).to_csv(f"{out}/debts.csv", index=False)

    k = scale
    obl = [{"date": str((today + pd.Timedelta(days=n)).date()), "name": nm, "amount": int(a * k)}
           for n, nm, a in [(3, "Поставщик молочки", 450000), (5, "Зарплата", 900000),
                            (9, "Аренда", 600000), (12, "Поставщик бакалеи", 700000)]]
    pd.DataFrame(obl).to_csv(f"{out}/obligations.csv", index=False)

    bank = []   # банковская выписка за 30 дней: расходы отрицательные, поступления положительные
    for n in range(30, 0, -1):
        d = str((today - pd.Timedelta(days=n)).date())
        bank.append({"date": d, "description": "Поступление выручки Kaspi QR", "amount": int(rng.integers(150, 260) * 1000 * k)})
        if n % 7 == 0:
            bank.append({"date": d, "description": "Оплата поставщику ТОО Алем за товар", "amount": -int(rng.integers(300, 500) * 1000 * k)})
    for n, desc, a in [(25, "Аренда помещения за месяц", -600000), (20, "Заработная плата сотрудникам", -900000),
                       (18, "Коммунальные услуги КСК", -45000), (15, "Налог ИПН и соцотчисления", -120000),
                       (10, "Реклама Instagram таргет", -35000), (6, "Ремонт холодильника", -28000)]:
        bank.append({"date": str((today - pd.Timedelta(days=n)).date()), "description": desc, "amount": int(a * k)})
    pd.DataFrame(bank).sort_values("date").to_csv(f"{out}/bank.csv", index=False)

    json.dump({"cash_balance": cash, "business_name": name},
              open(f"{out}/meta.json", "w", encoding="utf-8"), ensure_ascii=False)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/sample"); ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skus", type=int, default=60); ap.add_argument("--cash", type=int, default=1_100_000)
    ap.add_argument("--name", default="Мини-маркет Тараз"); ap.add_argument("--scale", type=float, default=1.0)
    a = ap.parse_args()
    print("Готово:", generate(a.out, a.seed, a.skus, a.cash, a.name, a.scale))
