"""Прогон через настоящий диспетчер aiogram (как в Telegram), а не прямой вызов функций.
Ловит ошибки сигнатур обработчиков, которые обычные тесты не видят."""
import asyncio, datetime as dt
import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, Update, User, CallbackQuery
import bot.main as bm


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr("ai.llm._get_client", lambda: (_ for _ in ()).throw(RuntimeError("no key")))
    monkeypatch.setattr("ai.llm.CACHE_FILE", "/tmp/none_cache.json")
    bm.STATE.clear()


class Sent(list):
    pass


def make_bot(sent):
    bot = Bot("123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN")

    async def fake_call(self, method, request_timeout=None):
        sent.append(getattr(method, "text", None))
        return Message(message_id=len(sent), date=dt.datetime.now(),
                       chat=Chat(id=1, type="private"), text=getattr(method, "text", "") or "")
    Bot.__call__ = fake_call
    return bot


def send(text):
    sent = Sent()
    bot = make_bot(sent)
    msg = Message(message_id=1, date=dt.datetime.now(), chat=Chat(id=1, type="private"),
                  from_user=User(id=1, is_bot=False, first_name="t"), text=text)
    entities = None
    if text.startswith("/"):
        from aiogram.types import MessageEntity
        entities = [MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))]
        msg = msg.model_copy(update={"entities": entities})
    asyncio.run(bm.dp.feed_update(bot, Update(update_id=1, message=msg)))
    return [t for t in sent if t]


@pytest.mark.parametrize("cmd", ["/start", "/help", "/demo", "/report", "/order", "/debts",
                                 "/effect", "/bank", "/remind kk", "/balance 5000000"])
def test_command_goes_through_dispatcher(cmd):
    send("/demo")
    out = send(cmd)
    assert out, f"{cmd}: нет ответа"
    assert not any("Что-то пошло не так" in t for t in out), f"{cmd}: упал обработчик → {out}"


def test_question_through_dispatcher():
    send("/demo")
    out = send("Почему упала прибыль?")
    assert out and not any("Что-то пошло не так" in t for t in out)
