"""Прогон сценария бота без Telegram: поддельные сообщения, LLM недоступен (работают шаблоны)."""
import asyncio
from types import SimpleNamespace
import pytest
import bot.main as bm


class FakeMsg:
    def __init__(self, text="", doc=None, data=b"", chat=1):
        self.text, self.chat, self.out = text, SimpleNamespace(id=chat), []
        self.document = doc
        async def download(obj, destination):
            destination.write(data)
        self.bot = SimpleNamespace(download=download)

    async def answer(self, text, **kw):
        self.out.append(text)


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setattr("ai.llm._get_client", lambda: (_ for _ in ()).throw(RuntimeError("no key")))
    monkeypatch.setattr("ai.llm.CACHE_FILE", "/tmp/none_cache.json")
    bm.STATE.clear()


def run(c):
    return asyncio.run(c)


def test_demo_then_sections():
    m = FakeMsg()
    run(bm.demo(m))
    assert any("ИИ сейчас недоступен" in t and "Выручка" in t for t in m.out)  # расчёты без ИИ, бот жив
    for kind in ("order", "debts", "effect", "bank"):
        m2 = FakeMsg(); run(bm._section(m2, kind)); assert m2.out and "Сначала" not in m2.out[0]
    m3 = FakeMsg(); run(bm._send_reminders(m3, ["kk"]))
    assert m3.out and "Сәлеметсіз" in m3.out[0]


def test_upload_sales_csv_uses_sample_for_rest():
    data = open("data/sample2/sales.csv", "rb").read()
    m = FakeMsg(doc=SimpleNamespace(file_name="sales.csv", file_size=len(data)), data=data)
    run(bm.upload(m))
    joined = "\n".join(m.out)
    assert "продажи" in joined and "Не хватает" in joined
    assert "report" in bm.STATE[1]


def test_upload_bank_only():
    data = open("data/sample/bank.csv", "rb").read()
    m = FakeMsg(doc=SimpleNamespace(file_name="bank.csv", file_size=len(data)), data=data)
    run(bm.upload(m))
    assert any("Куда уходят деньги" in t for t in m.out)


def test_bad_file_gives_message():
    m = FakeMsg(doc=SimpleNamespace(file_name="x.csv", file_size=5), data=b"a,b\n1,2\n")
    run(bm.upload(m))
    assert any("Не узнал таблицу" in t for t in m.out)


@pytest.mark.parametrize("d", ["sample", "sample2", "sample3"])
def test_three_datasets_end_to_end(d):
    from bot.report import build_report
    import pandas as pd, json
    st = {k: pd.read_csv(f"data/{d}/{f}.csv") for k, f in
          [("sales", "sales"), ("stock", "stock"), ("debts", "debts"), ("obligations", "obligations"), ("bank", "bank")]}
    st["meta"] = json.load(open(f"data/{d}/meta.json", encoding="utf-8"))
    r = build_report(st)
    assert r["effect"]["freed_working_capital"] > 0 and r["summary"]["revenue"] > 0


def test_image_sent_as_document_goes_to_invoice(monkeypatch):
    called = {}
    monkeypatch.setattr(bm, "parse_invoice", lambda img, media="image/jpeg":
                        called.update(media=media) or {"supplier": "ТОО", "date": "2026-10-01", "total": 10,
                                                       "items": [{"name": "Товар 1", "qty": 2, "unit_price": 5, "total": 10}],
                                                       "confidence": "high", "notes": ""})
    m = FakeMsg(doc=SimpleNamespace(file_name="nakl.png", file_size=10, mime_type="image/png"), data=b"x")
    run(bm.upload(m))
    assert called["media"] == "image/png" and any("Распознал" in t or "Поставщик" in t for t in m.out)
    assert bm.STATE[1]["pending_invoice"]["supplier"] == "ТОО"
