"""Регрессии на найденные баги: даты дд.мм.гггг, русские заголовки, /balance, выбор провайдера ИИ."""
import asyncio
from types import SimpleNamespace
import pytest
from bot import loader
import bot.main as bm


def test_dates_day_first():
    r = loader.read_upload(b"date,sku,name,qty,price,cost\n01.02.2026,1,A,2,100,60\n13.02.2026,1,A,2,100,60\n", "a.csv")
    assert r["sales"]["date"].tolist() == ["2026-02-01", "2026-02-13"]


def test_iso_dates_untouched():
    r = loader.read_upload(b"date,sku,name,qty,price,cost\n2026-02-01,1,A,2,100,60\n", "a.csv")
    assert r["sales"]["date"].tolist() == ["2026-02-01"]


def test_russian_headers_and_decimal_comma():
    csv = "Дата;Артикул;Наименование;Количество;Цена;Себестоимость\n05.03.2026;7;Хлеб;3;\"1 250,5\";900\n".encode("cp1251")
    r = loader.read_upload(csv, "prodazhi.csv")
    row = r["sales"].iloc[0]
    assert row["price"] == 1250.5 and row["qty"] == 3 and row["date"] == "2026-03-05"


class FakeMsg:
    def __init__(self, text):
        self.text, self.chat, self.out = text, SimpleNamespace(id=5), []
    async def answer(self, text, **kw):
        self.out.append(text)


@pytest.mark.parametrize("txt,val", [("/balance 5 000 000", 5000000), ("/balance 1100000", 1100000),
                                     ("/balance 1 500,5", 1500.5)])
def test_balance_parsing(txt, val):
    bm.STATE.clear()
    m = FakeMsg(txt)
    asyncio.run(bm.balance(m))
    assert bm.STATE[5]["meta"]["cash_balance"] == val


def test_balance_garbage():
    bm.STATE.clear()
    m = FakeMsg("/balance abc")
    asyncio.run(bm.balance(m))
    assert "Напишите так" in m.out[0] and "meta" not in bm.STATE.get(5, {})


def test_openai_compatible_provider(monkeypatch):
    from ai import llm
    calls = {}
    class Comp:
        def create(self, **kw):
            calls.update(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ответ"))])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=Comp()))
    monkeypatch.setattr(llm, "PROVIDER", "openai"); monkeypatch.setattr(llm, "MODEL", "m")
    monkeypatch.setattr(llm, "_get_client", lambda: fake)
    monkeypatch.setattr(llm, "CACHE_FILE", "/tmp/c_test.json")
    assert llm.ask("sys", "usr") == "ответ"
    assert calls["messages"][0]["role"] == "system"
    out = llm.ask_image("sys", "usr", b"\x89PNG", "image/png")
    assert out == "ответ" and calls["messages"][1]["content"][0]["type"] == "image_url"
