import io
import pandas as pd
import pytest
from core import metrics, forecast, cashflow, debts
from bot import loader
from bot.report import split_text
from ai.invoice_ocr import _extract_json


def _sales():
    rows = []
    for d in pd.date_range("2026-01-01", periods=60):
        rows.append({"date": str(d.date()), "sku": "A", "name": "Хлеб", "qty": 2, "price": 150, "cost": 100})
        rows.append({"date": str(d.date()), "sku": "B", "name": "Убыток", "qty": 1, "price": 90, "cost": 100})
    return pd.DataFrame(rows)


def test_margin_and_loss():
    m = metrics.product_margin(_sales())
    a = m[m["sku"] == "A"].iloc[0]
    assert a["profit"] == 2 * 50 * 60 and a["margin_pct"] == pytest.approx(33.3)
    assert list(metrics.loss_makers(m)["sku"]) == ["B"]


def test_dead_stock_sum():
    sales = _sales()
    stock = pd.DataFrame({"sku": ["A", "Z"], "qty": [5, 10]})  # Z никогда не продавался, цены нет → 0
    d = metrics.dead_stock(sales, stock, {"A": 100})
    assert list(d["sku"]) == ["Z"] and d["frozen_tenge"].iloc[0] == 0


def test_summary_empty():
    assert metrics.summary(pd.DataFrame(), pd.DataFrame())["revenue"] == 0.0


def test_cashflow_gap_and_no_double_count():
    sales = _sales()  # выручка 390/день, COGS 300/день
    obl = pd.DataFrame({"date": ["2026-03-04"], "name": ["Аренда"], "amount": [100_000]})
    cf = cashflow.cash_forecast(sales, obl, pd.DataFrame(columns=["paid"]), 1000, days=5)
    assert cf["first_gap"]["date"] == "2026-03-04"
    # закупки по себестоимости: нетто = 390 - 300 = 90/день
    assert cf["net_daily"] == 90


def test_debt_ranking():
    d = pd.DataFrame({"client": ["a", "b"], "amount": [10, 20], "due_date": ["2026-01-01", "2026-02-20"],
                      "paid": [0, 0]})
    r = debts.debt_ranking(d, today="2026-02-01")
    assert r.iloc[0]["client"] == "a" and r.iloc[0]["risk"] == "критичный"
    assert r.iloc[1]["risk"] == "низкий"


def test_weekly_order_nonnegative():
    st = pd.DataFrame({"sku": ["A", "B"], "qty": [0, 1000]})
    o = forecast.weekly_order(_sales(), st)
    assert list(o.index) == ["A"] and (o["order_qty"] > 0).all()


def test_loader_csv_semicolon_cp1251():
    data = "date;sku;name;qty;price;cost\n2026-01-01;A;Хлеб;2;150;100\n".encode("cp1251")
    got = loader.read_upload(data, "sales.csv")
    assert "sales" in got and got["sales"].iloc[0]["qty"] == 2


def test_loader_excel_multisheet():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        _sales().to_excel(w, sheet_name="s", index=False)
        pd.DataFrame({"Client": ["x"], "Amount": [5], "Due_Date": ["2026-01-02"]}).to_excel(w, sheet_name="d", index=False)
    got = loader.read_upload(buf.getvalue(), "all.xlsx")
    assert set(got) == {"sales", "debts"} and got["debts"].iloc[0]["paid"] == 0


def test_loader_errors():
    with pytest.raises(loader.FileError):
        loader.read_upload(b"a,b\n1,2\n", "x.csv")
    with pytest.raises(loader.FileError):
        loader.read_upload(b"zzz", "x.pdf")


def test_split_text():
    parts = split_text("a" * 9000 + "\nb\nc", limit=4000)
    assert all(len(p) <= 4000 for p in parts) and "".join(parts).replace("\n", "").count("a") == 9000


def test_extract_json():
    assert _extract_json('Вот:\n```json\n{"total": 5}\n```') == {"total": 5}


def test_loader_russian_headers_and_messy_excel():
    import io
    rows = [["Отчёт о продажах", None, None, None, None, None],
            [None] * 6,
            ["Дата", "Артикул", "Наименование", "Кол-во", "Цена, ₸", "Себестоимость"],
            ["05.10.2026", 101, "Хлеб", "2", "1 200,50", "900"],
            ["06.10.2026", 102, "Молоко", 3, 500, 400]]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, header=False, index=False)
    got = loader.read_upload(buf.getvalue(), "продажи.xlsx")["sales"]
    assert len(got) == 2 and got.iloc[0]["price"] == 1200.5 and got.iloc[0]["date"] == "2026-10-05"
    assert got.iloc[0]["sku"] == "101"


def test_loader_russian_debts_paid_words():
    data = "Клиент;Сумма долга;Срок оплаты;Оплачено\nИП Ахмет;150 000;01.10.2026;нет\nТОО Алем;50000;02.10.2026;да\n"
    got = loader.read_upload(data.encode("utf-8"), "долги.csv")["debts"]
    assert list(got["paid"]) == [0, 1] and got.iloc[0]["amount"] == 150000


def test_apply_invoice():
    from core.invoice import apply_invoice
    stock = pd.DataFrame({"sku": ["A"], "qty": [5], "last_purchase_date": ["2026-01-01"]})
    inv = {"date": "2026-03-01", "items": [{"name": " хлеб ", "qty": 10}, {"name": "Неизвестный", "qty": 1}]}
    new, ok, bad = apply_invoice(stock, _sales(), inv)
    assert new.loc[new["sku"] == "A", "qty"].iloc[0] == 15 and bad == ["Неизвестный"]
    assert new.iloc[0]["last_purchase_date"] == "2026-03-01"
